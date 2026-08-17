import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import psycopg
from psycopg.rows import dict_row

from app.config import get_finnhub_api_key, get_news_ttl_seconds, get_quote_ttl_seconds

logger = logging.getLogger(__name__)
FINNHUB_BASE = "https://finnhub.io/api/v1"

RANGE_MAP = {
    "1D": ("5", 1),
    "1W": ("60", 7),
    "1M": ("60", 30),
    "3M": ("D", 90),
    "1Y": ("D", 365),
    "ALL": ("W", 260),
}

YAHOO_RANGE_MAP = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "15m"),
    "1M": ("1mo", "60m"),
    "3M": ("3mo", "1d"),
    "1Y": ("1y", "1d"),
    "ALL": ("5y", "1wk"),
}


class MarketStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self):
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            yield conn

    def ping(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    def search_symbols(self, query: str, limit: int = 20) -> list[dict]:
        q = query.strip()
        if not q:
            return []
        pattern = f"%{q}%"
        prefix = f"{q.upper()}%"
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT symbol, name, exchange
                    FROM symbols
                    WHERE is_active = true
                      AND (symbol ILIKE %s OR name ILIKE %s)
                    ORDER BY
                      CASE WHEN symbol ILIKE %s THEN 0 ELSE 1 END,
                      symbol
                    LIMIT %s
                    """,
                    (pattern, pattern, prefix, limit),
                )
                return list(cur.fetchall())

    def get_symbol(self, symbol: str) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, name, exchange FROM symbols WHERE symbol = %s AND is_active = true",
                    (symbol.upper(),),
                )
                return cur.fetchone()

    def get_cached_quote(self, symbol: str) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM quote_cache WHERE symbol = %s", (symbol.upper(),))
                return cur.fetchone()

    def upsert_quote(self, symbol: str, price, change, change_pct, prev_close) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO quote_cache (symbol, price, change, change_pct, prev_close, fetched_at)
                    VALUES (%s, %s, %s, %s, %s, now())
                    ON CONFLICT (symbol) DO UPDATE SET
                      price = EXCLUDED.price,
                      change = EXCLUDED.change,
                      change_pct = EXCLUDED.change_pct,
                      prev_close = EXCLUDED.prev_close,
                      fetched_at = now()
                    """,
                    (symbol.upper(), price, change, change_pct, prev_close),
                )
            conn.commit()

    def get_suggestions(self) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.symbol, s.name, sg.label,
                           q.price, q.change, q.change_pct
                    FROM suggested_symbols sg
                    JOIN symbols s ON s.symbol = sg.symbol
                    LEFT JOIN quote_cache q ON q.symbol = s.symbol
                    ORDER BY sg.sort_order
                    """
                )
                return list(cur.fetchall())

    def get_discover_candidates(
        self,
        *,
        exclude: list[str] | None = None,
        limit: int = 36,
    ) -> list[dict]:
        """Curated suggestions first, then fill from other symbols so Discover never runs dry."""
        excluded = {s.strip().upper() for s in (exclude or []) if s and s.strip()}
        if limit <= 0:
            return []

        rows: list[dict] = []
        seen: set[str] = set()
        # Common US common-stock tickers (skip warrants, units, single-letter noise).
        equity_filter = r"^[A-Z]{2,5}$"

        def _append(batch: list[dict]) -> None:
            for row in batch:
                sym = (row.get("symbol") or "").upper()
                if not sym or sym in seen or sym in excluded:
                    continue
                seen.add(sym)
                rows.append(row)
                if len(rows) >= limit:
                    return

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.symbol, s.name, sg.label,
                           q.price, q.change, q.change_pct
                    FROM suggested_symbols sg
                    JOIN symbols s ON s.symbol = sg.symbol AND s.is_active = true
                    LEFT JOIN quote_cache q ON q.symbol = s.symbol
                    ORDER BY sg.sort_order
                    """
                )
                _append(list(cur.fetchall()))
                if len(rows) >= limit:
                    return rows

                blocked = list(seen | excluded) or [""]

                # Prefer symbols that already have quotes (fast, no Finnhub round-trip).
                cur.execute(
                    """
                    SELECT s.symbol, s.name, NULL::text AS label,
                           q.price, q.change, q.change_pct
                    FROM symbols s
                    JOIN quote_cache q ON q.symbol = s.symbol
                    WHERE s.is_active = true
                      AND s.symbol ~ %s
                      AND NOT (s.symbol = ANY(%s))
                    ORDER BY ABS(COALESCE(q.change_pct, 0)) DESC, s.symbol
                    LIMIT %s
                    """,
                    (equity_filter, blocked, max((limit - len(rows)) * 2, limit)),
                )
                _append(list(cur.fetchall()))
                if len(rows) >= limit:
                    return rows

                blocked = list(seen | excluded) or [""]

                # Fill from the broader universe with stable pseudo-random order.
                cur.execute(
                    """
                    SELECT s.symbol, s.name, NULL::text AS label,
                           q.price, q.change, q.change_pct
                    FROM symbols s
                    LEFT JOIN quote_cache q ON q.symbol = s.symbol
                    WHERE s.is_active = true
                      AND s.symbol ~ %s
                      AND NOT (s.symbol = ANY(%s))
                    ORDER BY md5(s.symbol), s.symbol
                    LIMIT %s
                    """,
                    (equity_filter, blocked, max((limit - len(rows)) * 3, limit)),
                )
                _append(list(cur.fetchall()))

        return rows

    def get_candles(self, symbol: str, resolution: str, limit: int = 200) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bar_time, close
                    FROM candles
                    WHERE symbol = %s AND resolution = %s
                    ORDER BY bar_time DESC
                    LIMIT %s
                    """,
                    (symbol.upper(), resolution, limit),
                )
                rows = list(cur.fetchall())
        rows.reverse()
        return rows

    def upsert_candles(self, symbol: str, resolution: str, bars: list[dict]) -> None:
        if not bars:
            return
        with self._connection() as conn:
            with conn.cursor() as cur:
                for bar in bars:
                    cur.execute(
                        """
                        INSERT INTO candles (symbol, resolution, bar_time, open, high, low, close, volume)
                        VALUES (%s, %s, to_timestamp(%s), %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol, resolution, bar_time) DO UPDATE SET
                          open = EXCLUDED.open, high = EXCLUDED.high,
                          low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume
                        """,
                        (
                            symbol.upper(),
                            resolution,
                            bar["t"],
                            bar.get("o"),
                            bar.get("h"),
                            bar.get("l"),
                            bar.get("c"),
                            bar.get("v"),
                        ),
                    )
            conn.commit()

    def get_news(self, symbol: str, limit: int = 10) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, headline, source, url, published_at, fetched_at
                    FROM news_articles
                    WHERE symbol = %s
                    ORDER BY published_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    (symbol.upper(), limit),
                )
                return list(cur.fetchall())

    def replace_news(self, symbol: str, articles: list[dict]) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM news_articles WHERE symbol = %s", (symbol.upper(),))
                for article in articles:
                    cur.execute(
                        """
                        INSERT INTO news_articles (id, symbol, headline, source, url, published_at, fetched_at)
                        VALUES (%s, %s, %s, %s, %s, to_timestamp(%s), now())
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            str(article["id"]),
                            symbol.upper(),
                            article.get("headline", ""),
                            article.get("source"),
                            article.get("url"),
                            article.get("datetime"),
                        ),
                    )
            conn.commit()

    def upsert_symbols_batch(self, rows: list[dict]) -> int:
        count = 0
        with self._connection() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    symbol = row.get("symbol", "").strip().upper()
                    if not symbol:
                        continue
                    cur.execute(
                        """
                        INSERT INTO symbols (symbol, name, exchange, currency, is_active, synced_at)
                        VALUES (%s, %s, 'US', %s, true, now())
                        ON CONFLICT (symbol) DO UPDATE SET
                          name = EXCLUDED.name,
                          currency = EXCLUDED.currency,
                          is_active = true,
                          synced_at = now()
                        """,
                        (symbol, row.get("description", symbol), row.get("currency")),
                    )
                    count += 1
            conn.commit()
        return count


class FinnhubClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        if not self._api_key:
            raise RuntimeError("FINNHUB_API_KEY is not set")
        query = dict(params or {})
        query["token"] = self._api_key
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(f"{FINNHUB_BASE}{path}", params=query)
            response.raise_for_status()
            return response.json()

    def stock_symbols(self, exchange: str = "US") -> list:
        return self._get("/stock/symbol", {"exchange": exchange})

    def quote(self, symbol: str) -> dict:
        return self._get("/quote", {"symbol": symbol.upper()})

    def candles(self, symbol: str, resolution: str, start: int, end: int) -> dict:
        if not self._api_key:
            raise RuntimeError("FINNHUB_API_KEY is not set")
        query = {
            "symbol": symbol.upper(),
            "resolution": resolution,
            "from": start,
            "to": end,
            "token": self._api_key,
        }
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(f"{FINNHUB_BASE}/stock/candle", params=query)
            if response.status_code in (401, 403):
                logger.info("finnhub candles not available for %s (status %s)", symbol, response.status_code)
                return {"s": "no_access"}
            response.raise_for_status()
            return response.json()

    def company_news(self, symbol: str, start: str, end: str) -> list:
        return self._get(
            "/company-news",
            {"symbol": symbol.upper(), "from": start, "to": end},
        )


class YahooChartClient:
    """Fallback chart data when Finnhub candles are not on the current plan."""

    _BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

    def candles(self, symbol: str, chart_range: str) -> list[dict]:
        if chart_range not in YAHOO_RANGE_MAP:
            return []
        yahoo_range, interval = YAHOO_RANGE_MAP[chart_range]
        headers = {"User-Agent": "Mozilla/5.0 (compatible; StockApp/1.0)"}
        with httpx.Client(timeout=30.0, headers=headers) as client:
            response = client.get(
                f"{self._BASE}/{symbol.upper()}",
                params={"range": yahoo_range, "interval": interval},
            )
            response.raise_for_status()
            payload = response.json()

        results = payload.get("chart", {}).get("result") or []
        if not results:
            return []
        result = results[0]
        timestamps = result.get("timestamp") or []
        closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        bars: list[dict] = []
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            bars.append({"t": int(ts), "c": float(close)})
        return bars


def quote_to_candle_points(price: float, prev_close: float | None) -> list[dict]:
    now = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    prev = float(prev_close if prev_close is not None else price)
    return [{"t": start, "c": prev}, {"t": now, "c": float(price)}]


def quote_is_fresh(fetched_at: datetime | None, ttl_seconds: int) -> bool:
    if fetched_at is None:
        return False
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched_at < timedelta(seconds=ttl_seconds)


def parse_quote_row(row: dict, symbol: str, name: str | None = None) -> dict:
    price = float(row["price"] or 0)
    change = float(row["change"] or 0)
    pct = float(row["change_pct"] or 0)
    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "change": change,
        "change_percent": pct,
        "prev_close": float(row["prev_close"]) if row.get("prev_close") is not None else None,
    }


def finnhub_quote_to_cache(symbol: str, data: dict) -> tuple:
    current = Decimal(str(data.get("c") or 0))
    prev = Decimal(str(data.get("pc") or 0))
    change = current - prev
    pct = (change / prev * 100) if prev else Decimal("0")
    return current, change, pct, prev


def open_store(database_url: str) -> MarketStore:
    store = MarketStore(database_url)
    store.ping()
    return store
