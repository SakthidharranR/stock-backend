import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import AuthUser, get_current_user, set_user_store
from app.chart_history import reconstruct_portfolio_chart
from app.config import get_cors_origins, get_database_url, get_market_service_url, redact_db_url
from app.models import (
    CashTransferItem,
    CashTransferRequest,
    CashTransferResponse,
    HoldingItem,
    OrderItem,
    OrderRequest,
    OrderResponse,
    PortfolioChartPoint,
    PortfolioSummary,
)
from app.store import MarketClient, PortfolioStore, open_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

_store: PortfolioStore | None = None
_market: MarketClient | None = None

CHART_RANGE_DAYS = {
    "1D": 1,
    "1W": 7,
    "1M": 30,
    "3M": 90,
    "1Y": 365,
    "ALL": 3650,
}


def get_store() -> PortfolioStore:
    if _store is None:
        raise RuntimeError("store not initialized")
    return _store


def get_market() -> MarketClient:
    if _market is None:
        raise RuntimeError("market client not initialized")
    return _market


def _resolve_fill_price(market: MarketClient, symbol: str) -> Decimal:
    try:
        quote = market.get_quote(symbol)
        return Decimal(str(quote["price"]))
    except Exception as exc:
        logger.exception("fill price lookup failed symbol=%s", symbol)
        raise HTTPException(status_code=502, detail="unable to get market price") from exc


def _holding_mark_price(row: dict) -> Decimal:
    if row.get("price") is not None:
        return Decimal(str(row["price"]))
    return Decimal(str(row["avg_cost"]))


def _compute_equity(holdings: list[dict]) -> Decimal:
    equity = Decimal("0")
    for row in holdings:
        shares = Decimal(str(row["shares"]))
        equity += shares * _holding_mark_price(row)
    return equity


def _apply_quotes_to_holdings(holdings: list[dict], quotes: list[dict]) -> list[dict]:
    by_symbol = {str(q.get("symbol", "")).upper(): q for q in quotes}
    merged: list[dict] = []
    for row in holdings:
        quote = by_symbol.get(str(row["symbol"]).upper())
        if not quote:
            merged.append(row)
            continue
        updated = dict(row)
        if quote.get("price") is not None:
            updated["price"] = quote["price"]
        if quote.get("change") is not None:
            updated["change"] = quote["change"]
        # Market API uses change_percent; quote_cache column is change_pct.
        if quote.get("change_percent") is not None:
            updated["change_pct"] = quote["change_percent"]
        elif quote.get("change_pct") is not None:
            updated["change_pct"] = quote["change_pct"]
        merged.append(updated)
    return merged


def _ensure_holding_quotes(
    market: MarketClient,
    holdings: list[dict],
) -> list[dict]:
    symbols = [str(row["symbol"]) for row in holdings if row.get("symbol")]
    if not symbols:
        return holdings
    try:
        quotes = market.get_quotes_batch(symbols)
    except Exception:
        logger.exception("batch quote refresh failed symbols=%s", symbols)
        return holdings
    return _apply_quotes_to_holdings(holdings, quotes)


def _start_of_day_utc(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _range_reference_value(
    store: PortfolioStore,
    account_id: str,
    total: Decimal,
    chart_range: str,
    today: date,
) -> Decimal:
    """1D baseline value. Multi-day change uses the chart's first point instead."""
    if chart_range == "1D":
        return store.get_or_set_daily_baseline(account_id, total, today)
    return total


def _fetch_candles_by_symbol(
    market: MarketClient,
    symbols: list[str],
    chart_range: str,
) -> dict[str, list[dict]]:
    unique = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not unique:
        return {}

    out: dict[str, list[dict]] = {}

    def _one(sym: str) -> tuple[str, list[dict]]:
        try:
            return sym, market.get_candles(sym, chart_range)
        except Exception:
            logger.exception("candle fetch failed for portfolio chart symbol=%s", sym)
            return sym, []

    workers = min(8, len(unique))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, sym) for sym in unique]
        for fut in as_completed(futures):
            sym, points = fut.result()
            out[sym] = points
    return out


def _try_reconstruct_chart(
    store: PortfolioStore,
    market: MarketClient,
    account_id: str,
    cash: Decimal,
    current_total: Decimal,
    chart_range: str,
    today: date,
    baseline: Decimal,
) -> list[PortfolioChartPoint] | None:
    orders = store.get_all_orders_asc(account_id)
    transfers = store.get_all_cash_transfers_asc(account_id)
    holdings = store.get_holdings(account_id)
    symbols = {str(o["symbol"]).upper() for o in orders}
    symbols.update(str(h["symbol"]).upper() for h in holdings if h.get("symbol"))
    if not symbols and not transfers:
        return None

    candles = _fetch_candles_by_symbol(market, sorted(symbols), chart_range) if symbols else {}
    if not any(candles.values()) and not orders and not transfers:
        return None

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if chart_range == "1D":
        baseline_row = store.get_daily_baseline_row(account_id, today)
        effective_at = baseline_row.get("effective_at") if baseline_row else None
        if effective_at is not None:
            if effective_at.tzinfo is None:
                effective_at = effective_at.replace(tzinfo=timezone.utc)
            window_start_ts = int(effective_at.timestamp())
        else:
            window_start_ts = int(_start_of_day_utc(today).timestamp())
    else:
        days = CHART_RANGE_DAYS.get(chart_range, 30)
        window_start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

    points = reconstruct_portfolio_chart(
        orders_asc=orders,
        candles_by_symbol=candles,
        current_cash=cash,
        current_total=current_total,
        window_start_ts=window_start_ts,
        now_ts=now_ts,
        transfers_asc=transfers,
    )
    if len(points) < 2:
        return None

    if chart_range == "1D":
        # Keep day P&L trade-neutral: chart starts at the locked baseline.
        start_ts = window_start_ts
        if points[0].time == start_ts:
            points[0] = PortfolioChartPoint(time=start_ts, value=float(baseline))
        else:
            points.insert(0, PortfolioChartPoint(time=start_ts, value=float(baseline)))

    return points


def _build_chart_points_from_marks(
    store: PortfolioStore,
    account_id: str,
    current_total: Decimal,
    baseline: Decimal,
    chart_range: str,
    today: date,
) -> list[PortfolioChartPoint]:
    now_ts = int(datetime.now(timezone.utc).timestamp())

    if chart_range == "1D":
        baseline_row = store.get_daily_baseline_row(account_id, today)
        effective_at = baseline_row.get("effective_at") if baseline_row else None
        if effective_at is not None:
            if effective_at.tzinfo is None:
                effective_at = effective_at.replace(tzinfo=timezone.utc)
            since = effective_at
        else:
            since = _start_of_day_utc(today)

        marks = store.get_marks_since(account_id, since)
        points: list[PortfolioChartPoint] = []
        start_ts = int(since.timestamp())
        points.append(PortfolioChartPoint(time=start_ts, value=float(baseline)))

        # Skip leading quote-catch-up marks below the post-trade baseline so the
        # chart doesn't "rally" while 1D change stays ~0.
        caught_up = effective_at is None
        for mark in marks:
            marked_at = mark["marked_at"]
            if marked_at.tzinfo is None:
                marked_at = marked_at.replace(tzinfo=timezone.utc)
            mark_ts = int(marked_at.timestamp())
            if mark_ts <= start_ts:
                continue
            val = float(mark["total_value"])
            if not caught_up:
                if Decimal(str(val)) + Decimal("0.01") >= Decimal(str(baseline)):
                    caught_up = True
                else:
                    continue
            points.append(PortfolioChartPoint(time=mark_ts, value=val))

        if not points or points[-1].time != now_ts or points[-1].value != float(current_total):
            points.append(PortfolioChartPoint(time=now_ts, value=float(current_total)))
        return points

    # Multi-day: earliest mark *inside* the window (same series the % uses).
    days = CHART_RANGE_DAYS.get(chart_range, 30)
    daily = store.get_daily_last_marks(account_id, days)
    if not daily:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        marks = store.get_marks_since(account_id, since)
        if not marks:
            return [
                PortfolioChartPoint(time=now_ts, value=float(current_total)),
            ]
        points = []
        for mark in marks:
            marked_at = mark["marked_at"]
            if marked_at.tzinfo is None:
                marked_at = marked_at.replace(tzinfo=timezone.utc)
            points.append(
                PortfolioChartPoint(
                    time=int(marked_at.timestamp()),
                    value=float(mark["total_value"]),
                )
            )
        if points[-1].time != now_ts or points[-1].value != float(current_total):
            points.append(PortfolioChartPoint(time=now_ts, value=float(current_total)))
        return points

    points = [
        PortfolioChartPoint(
            time=int(_start_of_day_utc(row["mark_date"]).timestamp()),
            value=float(row["total_value"]),
        )
        for row in daily
    ]
    if points[-1].time != now_ts or points[-1].value != float(current_total):
        points.append(PortfolioChartPoint(time=now_ts, value=float(current_total)))
    return points


def _build_chart_points(
    store: PortfolioStore,
    account_id: str,
    current_total: Decimal,
    baseline: Decimal,
    chart_range: str,
    today: date,
    market: MarketClient | None = None,
    cash: Decimal | None = None,
) -> list[PortfolioChartPoint]:
    if market is not None and cash is not None:
        try:
            reconstructed = _try_reconstruct_chart(
                store,
                market,
                account_id,
                cash,
                current_total,
                chart_range,
                today,
                baseline,
            )
            if reconstructed:
                return reconstructed
        except Exception:
            logger.exception("portfolio chart reconstruction failed; falling back to marks")

    return _build_chart_points_from_marks(
        store, account_id, current_total, baseline, chart_range, today
    )


def _apply_trade_to_daily_baseline(
    store: PortfolioStore,
    account_id: str,
    today: date,
    pre_total: Decimal,
    post_total: Decimal,
    had_holdings_before: bool,
    orders_on_day_after: int,
    order_created_at: datetime,
) -> None:
    """Keep day P&L trade-neutral; anchor 1D to first purchase when exposure starts today."""
    delta = post_total - pre_total
    is_first_order_today = orders_on_day_after == 1
    starts_exposure_today = is_first_order_today and not had_holdings_before

    if starts_exposure_today:
        created = order_created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        store.set_daily_baseline(account_id, post_total, today, effective_at=created)
        return

    store.adjust_daily_baseline(account_id, delta, today, create_from=pre_total)


def _build_portfolio_summary(
    store: PortfolioStore,
    account_id: str,
    holdings: list[dict],
    cash: Decimal,
    chart_range: str = "1D",
    market: MarketClient | None = None,
) -> PortfolioSummary:
    equity = _compute_equity(holdings)
    total = cash + equity
    today = datetime.now(timezone.utc).date()

    baseline_for_chart = _range_reference_value(store, account_id, total, chart_range, today)
    if chart_range != "1D":
        store.get_or_set_daily_baseline(account_id, total, today)

    store.maybe_record_mark(account_id, total, cash, equity)
    chart_points = _build_chart_points(
        store,
        account_id,
        total,
        baseline_for_chart,
        chart_range,
        today,
        market=market,
        cash=cash,
    )

    # Headline change always matches chart start → current.
    if chart_points:
        reference = Decimal(str(chart_points[0].value))
    else:
        reference = total
    day_change = total - reference
    pct = (day_change / reference * 100) if reference else Decimal("0")

    return PortfolioSummary(
        cash_balance=float(cash),
        equity=float(equity),
        total_value=float(total),
        day_change=float(day_change),
        day_change_percent=float(pct),
        chart_points=chart_points,
    )


def _holding_items(rows: list[dict]) -> list[HoldingItem]:
    """Holding change is P&L since your cost basis (avg_cost), not Finnhub's session move."""
    items: list[HoldingItem] = []
    for row in rows:
        shares = float(row["shares"])
        avg_cost = float(row["avg_cost"])
        price = float(_holding_mark_price(row))
        position_change = shares * (price - avg_cost)
        position_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost else 0.0
        items.append(
            HoldingItem(
                symbol=row["symbol"],
                name=row["name"],
                shares=shares,
                avg_cost=avg_cost,
                price=price,
                change=position_change,
                change_percent=position_pct,
                equity=shares * price,
            )
        )
    return items


def create_app(
    store: PortfolioStore | None = None,
    market: MarketClient | None = None,
) -> FastAPI:
    global _store, _market

    app = FastAPI(title="Stock Portfolio Service", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Dev-Email"],
    )

    if store is not None:
        _store = store
    else:
        logger.info("using database url=%s", redact_db_url(get_database_url()))
        _store = open_store(get_database_url())

    _market = market if market is not None else MarketClient(get_market_service_url())
    set_user_store(_store)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/portfolio", response_model=PortfolioSummary)
    def get_portfolio(
        range: str = Query(default="1D", alias="range"),
        user: AuthUser = Depends(get_current_user),
        store: PortfolioStore = Depends(get_store),
        market: MarketClient = Depends(get_market),
    ) -> PortfolioSummary:
        if range not in CHART_RANGE_DAYS:
            raise HTTPException(status_code=400, detail="invalid range")
        account = store.get_or_create_account(user.id)
        holdings = store.get_holdings(str(account["id"]))
        holdings = _ensure_holding_quotes(market, holdings)
        cash = Decimal(str(account["cash_balance"]))
        return _build_portfolio_summary(
            store, str(account["id"]), holdings, cash, range, market=market
        )

    @app.get("/holdings", response_model=list[HoldingItem])
    def get_holdings(
        user: AuthUser = Depends(get_current_user),
        store: PortfolioStore = Depends(get_store),
        market: MarketClient = Depends(get_market),
    ) -> list[HoldingItem]:
        account = store.get_or_create_account(user.id)
        rows = store.get_holdings(str(account["id"]))
        rows = _ensure_holding_quotes(market, rows)
        return _holding_items(rows)

    @app.post("/orders", response_model=OrderResponse, status_code=201)
    def create_order(
        body: OrderRequest,
        user: AuthUser = Depends(get_current_user),
        store: PortfolioStore = Depends(get_store),
        market: MarketClient = Depends(get_market),
    ):
        sym = body.symbol.strip().upper()
        if not store.symbol_exists(sym):
            return JSONResponse(status_code=400, content={"error": "unknown symbol"})

        fill_price = _resolve_fill_price(market, sym)
        quantity = Decimal(str(body.quantity))
        today = datetime.now(timezone.utc).date()

        try:
            account = store.get_or_create_account(user.id)
            account_id = str(account["id"])

            pre_holdings = store.get_holdings(account_id)
            had_holdings_before = len(pre_holdings) > 0
            pre_holdings = _ensure_holding_quotes(market, pre_holdings)
            pre_cash = Decimal(str(account["cash_balance"]))
            pre_total = pre_cash + _compute_equity(pre_holdings)

            result = store.place_order(
                account_id,
                sym,
                body.side,
                quantity,
                fill_price,
            )
            holdings = store.get_holdings(account_id)
            holdings = _ensure_holding_quotes(market, holdings)
            cash = Decimal(str(result["cash_balance"]))
            equity = _compute_equity(holdings)
            total = cash + equity

            orders_today = store.count_orders_on_date(account_id, today)
            order = result["order"]
            _apply_trade_to_daily_baseline(
                store,
                account_id,
                today,
                pre_total,
                total,
                had_holdings_before,
                orders_today,
                order["created_at"],
            )
            store.maybe_record_mark(account_id, total, cash, equity)
        except ValueError as err:
            return JSONResponse(status_code=400, content={"error": str(err)})

        order = result["order"]
        return OrderResponse(
            order=OrderItem(
                id=str(order["id"]),
                symbol=order["symbol"],
                side=order["side"],
                quantity=float(order["quantity"]),
                fill_price=float(order["fill_price"]),
                total=float(order["total"]),
                created_at=order["created_at"].isoformat(),
            ),
            cash_balance=float(result["cash_balance"]),
        )

    @app.get("/orders", response_model=list[OrderItem])
    def list_orders(
        symbol: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        user: AuthUser = Depends(get_current_user),
        store: PortfolioStore = Depends(get_store),
    ) -> list[OrderItem]:
        account = store.get_or_create_account(user.id)
        rows = store.get_orders(
            str(account["id"]),
            limit=limit,
            symbol=symbol.strip().upper() if symbol else None,
        )
        return [
            OrderItem(
                id=str(r["id"]),
                symbol=r["symbol"],
                side=r["side"],
                quantity=float(r["quantity"]),
                fill_price=float(r["fill_price"]),
                total=float(r["total"]),
                created_at=r["created_at"].isoformat(),
            )
            for r in rows
        ]

    @app.post("/cash", response_model=CashTransferResponse, status_code=201)
    def create_cash_transfer(
        body: CashTransferRequest,
        user: AuthUser = Depends(get_current_user),
        store: PortfolioStore = Depends(get_store),
        market: MarketClient = Depends(get_market),
    ):
        today = datetime.now(timezone.utc).date()
        try:
            account = store.get_or_create_account(user.id)
            account_id = str(account["id"])
            holdings = _ensure_holding_quotes(market, store.get_holdings(account_id))
            pre_cash = Decimal(str(account["cash_balance"]))
            pre_total = pre_cash + _compute_equity(holdings)

            result = store.transfer_cash(
                account_id,
                body.side,
                Decimal(str(body.amount)),
            )
            cash = Decimal(str(result["cash_balance"]))
            equity = _compute_equity(holdings)
            total = cash + equity

            # Keep day P&L neutral to deposits/withdrawals (external cash, not market).
            store.adjust_daily_baseline(account_id, total - pre_total, today, create_from=pre_total)
            store.maybe_record_mark(account_id, total, cash, equity)
        except ValueError as err:
            return JSONResponse(status_code=400, content={"error": str(err)})

        transfer = result["transfer"]
        return CashTransferResponse(
            transfer=CashTransferItem(
                id=str(transfer["id"]),
                side=transfer["side"],
                amount=float(transfer["amount"]),
                created_at=transfer["created_at"].isoformat(),
            ),
            cash_balance=float(result["cash_balance"]),
        )

    @app.get("/cash", response_model=list[CashTransferItem])
    def list_cash_transfers(
        user: AuthUser = Depends(get_current_user),
        store: PortfolioStore = Depends(get_store),
    ) -> list[CashTransferItem]:
        account = store.get_or_create_account(user.id)
        rows = store.get_cash_transfers(str(account["id"]))
        return [
            CashTransferItem(
                id=str(r["id"]),
                side=r["side"],
                amount=float(r["amount"]),
                created_at=r["created_at"].isoformat(),
            )
            for r in rows
        ]

    return app


def create_application() -> FastAPI:
    return create_app()
