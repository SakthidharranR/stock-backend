import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    get_admin_key,
    get_cors_origins,
    get_database_url,
    get_finnhub_api_key,
    get_news_ttl_seconds,
    get_port,
    get_quote_ttl_seconds,
    redact_db_url,
)
from app.models import (
    CandlePoint,
    CandlesResponse,
    NewsItem,
    QuoteResult,
    SuggestionItem,
    SymbolResult,
)
from app.store import (
    FinnhubClient,
    MarketStore,
    RANGE_MAP,
    YahooChartClient,
    finnhub_quote_to_cache,
    open_store,
    parse_quote_row,
    quote_is_fresh,
    quote_to_candle_points,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

_store: MarketStore | None = None
_finnhub: FinnhubClient | None = None
_yahoo: YahooChartClient | None = None


def get_store() -> MarketStore:
    if _store is None:
        raise RuntimeError("store not initialized")
    return _store


def get_finnhub() -> FinnhubClient:
    if _finnhub is None:
        raise RuntimeError("finnhub not initialized")
    return _finnhub


def _require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = get_admin_key()
    if not expected:
        raise HTTPException(status_code=503, detail="admin sync not configured")
    if x_admin_key != expected:
        raise HTTPException(status_code=401, detail="invalid admin key")


def _fetch_quote(store: MarketStore, finnhub: FinnhubClient, symbol: str) -> dict | None:
    sym = symbol.upper()
    meta = store.get_symbol(sym)
    if not meta:
        return None

    cached = store.get_cached_quote(sym)
    if cached and quote_is_fresh(cached["fetched_at"], get_quote_ttl_seconds()):
        return parse_quote_row(cached, sym, meta["name"])

    try:
        data = finnhub.quote(sym)
        price, change, pct, prev = finnhub_quote_to_cache(sym, data)
        store.upsert_quote(sym, price, change, pct, prev)
        return {
            "symbol": sym,
            "name": meta["name"],
            "price": float(price),
            "change": float(change),
            "change_percent": float(pct),
            "prev_close": float(prev),
        }
    except Exception:
        logger.exception("finnhub quote failed symbol=%s", sym)
        if cached:
            return parse_quote_row(cached, sym, meta["name"])
        raise


def create_app(store: MarketStore | None = None, finnhub: FinnhubClient | None = None) -> FastAPI:
    global _store, _finnhub, _yahoo

    app = FastAPI(title="Stock Market Service", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Admin-Key", "X-Dev-Email"],
    )

    if store is not None:
        _store = store
    else:
        logger.info("using database url=%s", redact_db_url(get_database_url()))
        _store = open_store(get_database_url())

    _finnhub = finnhub if finnhub is not None else FinnhubClient(get_finnhub_api_key())
    _yahoo = YahooChartClient()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/symbols/search", response_model=list[SymbolResult])
    def search_symbols(
        q: str = Query(default=""),
        store: MarketStore = Depends(get_store),
    ) -> list[SymbolResult]:
        rows = store.search_symbols(q)
        return [SymbolResult(symbol=r["symbol"], name=r["name"], exchange=r["exchange"]) for r in rows]

    @app.get("/quotes/{symbol}", response_model=QuoteResult)
    def get_quote(
        symbol: str,
        store: MarketStore = Depends(get_store),
        finnhub: FinnhubClient = Depends(get_finnhub),
    ) -> QuoteResult:
        quote = _fetch_quote(store, finnhub, symbol)
        if not quote:
            raise HTTPException(status_code=404, detail="symbol not found")
        return QuoteResult(**quote)

    @app.get("/quotes", response_model=list[QuoteResult])
    def get_quotes_batch(
        symbols: str = Query(..., description="Comma-separated symbols"),
        store: MarketStore = Depends(get_store),
        finnhub: FinnhubClient = Depends(get_finnhub),
    ) -> list[QuoteResult]:
        results: list[QuoteResult] = []
        for raw in symbols.split(","):
            sym = raw.strip().upper()
            if not sym:
                continue
            try:
                quote = _fetch_quote(store, finnhub, sym)
                if quote:
                    results.append(QuoteResult(**quote))
            except Exception:
                logger.exception("batch quote failed symbol=%s", sym)
        return results

    @app.get("/candles/{symbol}", response_model=CandlesResponse)
    def get_candles(
        symbol: str,
        range: str = Query(default="1M", alias="range"),
        store: MarketStore = Depends(get_store),
        finnhub: FinnhubClient = Depends(get_finnhub),
    ) -> CandlesResponse:
        sym = symbol.upper()
        meta = store.get_symbol(sym)
        if not meta:
            raise HTTPException(status_code=404, detail="symbol not found")

        if range not in RANGE_MAP:
            raise HTTPException(status_code=400, detail="invalid range")

        resolution, days = RANGE_MAP[range]
        cached = store.get_candles(sym, resolution, limit=500)
        if len(cached) >= min(days, 5):
            points = [
                CandlePoint(time=int(row["bar_time"].timestamp()), close=float(row["close"]))
                for row in cached
            ]
            return CandlesResponse(symbol=sym, range=range, resolution=resolution, points=points)

        end = int(datetime.now(timezone.utc).timestamp())
        start = int((datetime.now(timezone.utc) - timedelta(days=days * 2)).timestamp())
        bars: list[dict] = []
        try:
            data = finnhub.candles(sym, resolution, start, end)
            if data.get("s") == "ok":
                bars = [
                    {"t": t, "c": c}
                    for t, c in zip(data["t"], data["c"])
                    if c is not None
                ]
                store.upsert_candles(
                    sym,
                    resolution,
                    [
                        {"t": t, "o": o, "h": h, "l": lo, "c": c, "v": v}
                        for t, o, h, lo, c, v in zip(
                            data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
                        )
                    ],
                )
        except Exception:
            logger.exception("finnhub candles failed symbol=%s", sym)

        if not bars and _yahoo is not None:
            try:
                bars = _yahoo.candles(sym, range)
                logger.info("using yahoo chart fallback symbol=%s range=%s points=%s", sym, range, len(bars))
            except Exception:
                logger.exception("yahoo candles failed symbol=%s", sym)

        if not bars:
            try:
                quote = _fetch_quote(store, finnhub, sym)
                if quote:
                    bars = quote_to_candle_points(quote["price"], quote.get("prev_close"))
            except Exception:
                logger.exception("quote candle fallback failed symbol=%s", sym)

        if not bars and cached:
            points = [
                CandlePoint(time=int(r["bar_time"].timestamp()), close=float(r["close"]))
                for r in cached
            ]
            return CandlesResponse(symbol=sym, range=range, resolution=resolution, points=points)

        if not bars:
            raise HTTPException(status_code=502, detail="no candle data")

        points = [CandlePoint(time=int(b["t"]), close=float(b["c"])) for b in bars]
        return CandlesResponse(symbol=sym, range=range, resolution=resolution, points=points)

    @app.get("/news/{symbol}", response_model=list[NewsItem])
    def get_news(
        symbol: str,
        store: MarketStore = Depends(get_store),
        finnhub: FinnhubClient = Depends(get_finnhub),
    ) -> list[NewsItem]:
        sym = symbol.upper()
        if not store.get_symbol(sym):
            raise HTTPException(status_code=404, detail="symbol not found")

        cached = store.get_news(sym)
        if cached and cached[0].get("fetched_at"):
            if quote_is_fresh(cached[0]["fetched_at"], get_news_ttl_seconds()):
                return [
                    NewsItem(
                        id=r["id"],
                        headline=r["headline"],
                        source=r.get("source"),
                        url=r.get("url"),
                        published_at=r["published_at"].isoformat() if r.get("published_at") else None,
                    )
                    for r in cached
                ]

        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=7)
        try:
            articles = finnhub.company_news(sym, start.isoformat(), end.isoformat())
            store.replace_news(sym, articles[:20])
            return [
                NewsItem(
                    id=str(a.get("id", "")),
                    headline=a.get("headline", ""),
                    source=a.get("source"),
                    url=a.get("url"),
                    published_at=datetime.fromtimestamp(a["datetime"], tz=timezone.utc).isoformat()
                    if a.get("datetime")
                    else None,
                )
                for a in articles[:20]
            ]
        except Exception as exc:
            logger.exception("news failed symbol=%s", sym)
            if cached:
                return [
                    NewsItem(
                        id=r["id"],
                        headline=r["headline"],
                        source=r.get("source"),
                        url=r.get("url"),
                        published_at=r["published_at"].isoformat() if r.get("published_at") else None,
                    )
                    for r in cached
                ]
            raise HTTPException(status_code=502, detail="news fetch failed") from exc

    @app.get("/suggestions", response_model=list[SuggestionItem])
    def get_suggestions(
        exclude: str | None = Query(
            None,
            description="Comma-separated symbols to omit (e.g. already owned)",
        ),
        limit: int = Query(12, ge=1, le=50),
        store: MarketStore = Depends(get_store),
        finnhub: FinnhubClient = Depends(get_finnhub),
    ) -> list[SuggestionItem]:
        exclude_list = [s.strip().upper() for s in (exclude or "").split(",") if s.strip()]
        # Over-fetch candidates so quote misses still leave a full Discover list.
        rows = store.get_discover_candidates(
            exclude=exclude_list,
            limit=max(limit * 3, 24),
        )
        results: list[SuggestionItem] = []
        for row in rows:
            if len(results) >= limit:
                break
            sym = row["symbol"]
            if row.get("price") is None:
                try:
                    quote = _fetch_quote(store, finnhub, sym)
                    if quote:
                        row = {**row, **quote}
                except Exception:
                    continue
            if row.get("price") is None:
                continue
            results.append(
                SuggestionItem(
                    symbol=sym,
                    name=row["name"],
                    label=row.get("label"),
                    price=float(row["price"]),
                    change=float(row.get("change") or 0),
                    change_percent=float(row.get("change_percent") or row.get("change_pct") or 0),
                )
            )
        return results

    @app.post("/admin/sync-symbols")
    def sync_symbols(
        _: None = Depends(_require_admin),
        store: MarketStore = Depends(get_store),
        finnhub: FinnhubClient = Depends(get_finnhub),
    ) -> dict:
        rows = finnhub.stock_symbols("US")
        count = store.upsert_symbols_batch(rows)
        return {"synced": count}

    return app


def create_application() -> FastAPI:
    return create_app()
