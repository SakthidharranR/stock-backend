"""Rebuild portfolio value history from orders, cash transfers, and market candles."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models import PortfolioChartPoint


def infer_starting_cash(
    current_cash: Decimal,
    orders_asc: list[dict],
    transfers_asc: list[dict] | None = None,
) -> Decimal:
    """Walk ledger newest→oldest to recover cash before the first activity."""
    cash = Decimal(str(current_cash))
    for order in reversed(orders_asc):
        total = Decimal(str(order["total"]))
        if order["side"] == "buy":
            cash += total
        else:
            cash -= total
    for transfer in reversed(transfers_asc or []):
        amount = Decimal(str(transfer["amount"]))
        if transfer["side"] == "deposit":
            cash -= amount
        else:
            cash += amount
    return cash


def clamp_window_start(
    range_start_ts: int,
    *,
    account_created_at: datetime | None,
    orders_asc: list[dict],
    transfers_asc: list[dict] | None = None,
) -> int:
    """Do not chart before the account (or first ledger event) existed."""
    starts: list[int] = []
    if account_created_at is not None:
        starts.append(int(_as_utc(account_created_at).timestamp()))
    if orders_asc:
        starts.append(_event_ts(orders_asc[0]))
    transfers = transfers_asc or []
    if transfers:
        starts.append(_event_ts(transfers[0]))
    if not starts:
        return range_start_ts
    return max(range_start_ts, min(starts))


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _event_ts(row: dict) -> int:
    return int(_as_utc(row["created_at"]).timestamp())


class _PriceCursor:
    """Walk candle closes forward; always returns last known close <= t."""

    def __init__(self, points: list[tuple[int, float]]) -> None:
        self._points = points
        self._i = -1
        self._last: float | None = None

    def price_at(self, t: int) -> float | None:
        while self._i + 1 < len(self._points) and self._points[self._i + 1][0] <= t:
            self._i += 1
            self._last = self._points[self._i][1]
        return self._last


def reconstruct_portfolio_chart(
    *,
    orders_asc: list[dict],
    candles_by_symbol: dict[str, list[dict]],
    current_cash: Decimal,
    current_total: Decimal,
    window_start_ts: int,
    now_ts: int,
    transfers_asc: list[dict] | None = None,
) -> list[PortfolioChartPoint]:
    """
    Replay trades and cash transfers across a shared candle timeline.

    Returns [] when there isn't enough market history to build a real series
    (caller should fall back to saved portfolio marks).
    """
    transfers_asc = transfers_asc or []
    if (
        not orders_asc
        and not transfers_asc
        and float(current_total) == float(current_cash)
    ):
        return []

    cursors: dict[str, _PriceCursor] = {}
    for symbol, points in candles_by_symbol.items():
        series: list[tuple[int, float]] = []
        for p in points:
            try:
                t = int(p["time"])
                close = float(p["close"])
            except (KeyError, TypeError, ValueError):
                continue
            if t < window_start_ts or t > now_ts:
                continue
            series.append((t, close))
        series.sort(key=lambda x: x[0])
        if series:
            cursors[symbol.upper()] = _PriceCursor(series)

    if not cursors and not orders_asc and not transfers_asc:
        return []

    events: list[tuple[int, str, dict]] = []
    for order in orders_asc:
        events.append((_event_ts(order), "order", order))
    for transfer in transfers_asc:
        events.append((_event_ts(transfer), "transfer", transfer))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "transfer" else 1))

    times: set[int] = set()
    for cursor in cursors.values():
        for t, _ in cursor._points:
            times.add(t)
    for ts, _, _ in events:
        if window_start_ts <= ts <= now_ts:
            times.add(ts)
    times.add(window_start_ts)
    times.add(now_ts)

    if len(times) < 2 and not events:
        return []

    cash = infer_starting_cash(current_cash, orders_asc, transfers_asc)
    shares: dict[str, Decimal] = {}
    last_fill: dict[str, float] = {}
    event_i = 0
    n_events = len(events)

    def apply_event(kind: str, payload: dict) -> None:
        nonlocal cash
        if kind == "order":
            sym = str(payload["symbol"]).upper()
            qty = Decimal(str(payload["quantity"]))
            total = Decimal(str(payload["total"]))
            fill = float(payload["fill_price"])
            last_fill[sym] = fill
            if payload["side"] == "buy":
                cash -= total
                shares[sym] = shares.get(sym, Decimal("0")) + qty
            else:
                cash += total
                shares[sym] = shares.get(sym, Decimal("0")) - qty
                if shares[sym] <= 0:
                    shares.pop(sym, None)
            return

        amount = Decimal(str(payload["amount"]))
        if payload["side"] == "deposit":
            cash += amount
        else:
            cash -= amount

    while event_i < n_events and events[event_i][0] <= window_start_ts:
        _, kind, payload = events[event_i]
        apply_event(kind, payload)
        event_i += 1

    def equity_at(t: int) -> Decimal:
        total_eq = Decimal("0")
        for sym, qty in shares.items():
            if qty <= 0:
                continue
            px: float | None = None
            cursor = cursors.get(sym)
            if cursor is not None:
                px = cursor.price_at(t)
            if px is None:
                px = last_fill.get(sym)
            if px is None:
                continue
            total_eq += qty * Decimal(str(px))
        return total_eq

    points: list[PortfolioChartPoint] = []
    for t in sorted(times):
        if t < window_start_ts or t > now_ts:
            continue
        while event_i < n_events and events[event_i][0] <= t:
            _, kind, payload = events[event_i]
            apply_event(kind, payload)
            event_i += 1

        value = float(cash + equity_at(t))
        if points and points[-1].time == t:
            points[-1] = PortfolioChartPoint(time=t, value=value)
        else:
            points.append(PortfolioChartPoint(time=t, value=value))

    if not points:
        return []

    if points[-1].time != now_ts:
        points.append(PortfolioChartPoint(time=now_ts, value=float(current_total)))
    else:
        points[-1] = PortfolioChartPoint(time=now_ts, value=float(current_total))

    if len(points) < 2:
        return []

    return points
