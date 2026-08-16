import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import httpx
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

MARK_MIN_INTERVAL_SECONDS = 60


class PortfolioStore:
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

    def get_user_by_cognito_sub(self, cognito_sub: str) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, cognito_sub, email, display_name FROM users WHERE cognito_sub = %s",
                    (cognito_sub,),
                )
                return cur.fetchone()

    def get_user_by_email(self, email: str) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, cognito_sub, email, display_name FROM users WHERE lower(email) = lower(%s)",
                    (email.strip(),),
                )
                return cur.fetchone()

    def get_or_create_account(self, user_id: str) -> dict:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, user_id, cash_balance FROM accounts WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                if row:
                    return row
                cur.execute(
                    """
                    INSERT INTO accounts (user_id, cash_balance)
                    VALUES (%s, 10000.00)
                    RETURNING id, user_id, cash_balance
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
            conn.commit()
            return row

    def get_holdings(self, account_id: str) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT h.symbol, h.shares, h.avg_cost, s.name,
                           q.price, q.change, q.change_pct
                    FROM holdings h
                    JOIN symbols s ON s.symbol = h.symbol
                    LEFT JOIN quote_cache q ON q.symbol = h.symbol
                    WHERE h.account_id = %s
                    ORDER BY h.symbol
                    """,
                    (account_id,),
                )
                return list(cur.fetchall())

    def get_orders(self, account_id: str, limit: int = 50, symbol: str | None = None) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                if symbol:
                    cur.execute(
                        """
                        SELECT id, symbol, side, quantity, fill_price, total, created_at
                        FROM orders
                        WHERE account_id = %s AND symbol = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (account_id, symbol.upper(), limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, symbol, side, quantity, fill_price, total, created_at
                        FROM orders
                        WHERE account_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (account_id, limit),
                    )
                return list(cur.fetchall())

    def get_all_orders_asc(self, account_id: str) -> list[dict]:
        """Full trade ledger oldest→newest for portfolio chart reconstruction."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, symbol, side, quantity, fill_price, total, created_at
                    FROM orders
                    WHERE account_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (account_id,),
                )
                return list(cur.fetchall())

    def get_all_cash_transfers_asc(self, account_id: str) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, side, amount, created_at
                    FROM cash_transfers
                    WHERE account_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (account_id,),
                )
                return list(cur.fetchall())

    def get_cash_transfers(self, account_id: str, limit: int = 50) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, side, amount, created_at
                    FROM cash_transfers
                    WHERE account_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (account_id, limit),
                )
                return list(cur.fetchall())

    def transfer_cash(self, account_id: str, side: str, amount: Decimal) -> dict:
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount <= 0:
            raise ValueError("amount must be positive")
        if side not in ("deposit", "withdraw"):
            raise ValueError("invalid transfer side")

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cash_balance FROM accounts WHERE id = %s FOR UPDATE",
                    (account_id,),
                )
                account = cur.fetchone()
                if not account:
                    raise ValueError("account not found")

                cash = Decimal(str(account["cash_balance"]))
                if side == "deposit":
                    cash += amount
                else:
                    if cash < amount:
                        raise ValueError("insufficient cash")
                    cash -= amount

                cur.execute(
                    "UPDATE accounts SET cash_balance = %s WHERE id = %s",
                    (cash, account_id),
                )
                cur.execute(
                    """
                    INSERT INTO cash_transfers (account_id, side, amount)
                    VALUES (%s, %s, %s)
                    RETURNING id, side, amount, created_at
                    """,
                    (account_id, side, amount),
                )
                transfer = cur.fetchone()
            conn.commit()
            return {"transfer": transfer, "cash_balance": cash}

    def get_cached_quote(self, symbol: str) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, price, change, change_pct FROM quote_cache WHERE symbol = %s",
                    (symbol.upper(),),
                )
                return cur.fetchone()

    def symbol_exists(self, symbol: str) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM symbols WHERE symbol = %s AND is_active = true",
                    (symbol.upper(),),
                )
                return cur.fetchone() is not None

    def place_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        fill_price: Decimal,
    ) -> dict:
        sym = symbol.upper()
        total = (quantity * fill_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cash_balance FROM accounts WHERE id = %s FOR UPDATE",
                    (account_id,),
                )
                account = cur.fetchone()
                if not account:
                    raise ValueError("account not found")

                cash = Decimal(str(account["cash_balance"]))

                if side == "buy":
                    if cash < total:
                        raise ValueError("insufficient cash")
                    cur.execute(
                        """
                        SELECT shares, avg_cost FROM holdings
                        WHERE account_id = %s AND symbol = %s
                        FOR UPDATE
                        """,
                        (account_id, sym),
                    )
                    holding = cur.fetchone()
                    if holding:
                        old_shares = Decimal(str(holding["shares"]))
                        old_cost = Decimal(str(holding["avg_cost"]))
                        new_shares = old_shares + quantity
                        new_avg = ((old_shares * old_cost) + (quantity * fill_price)) / new_shares
                        cur.execute(
                            """
                            UPDATE holdings
                            SET shares = %s, avg_cost = %s, updated_at = now()
                            WHERE account_id = %s AND symbol = %s
                            """,
                            (new_shares, new_avg, account_id, sym),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO holdings (account_id, symbol, shares, avg_cost)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (account_id, sym, quantity, fill_price),
                        )
                    cash -= total
                else:
                    cur.execute(
                        """
                        SELECT shares FROM holdings
                        WHERE account_id = %s AND symbol = %s
                        FOR UPDATE
                        """,
                        (account_id, sym),
                    )
                    holding = cur.fetchone()
                    if not holding:
                        raise ValueError("no shares to sell")
                    shares = Decimal(str(holding["shares"]))
                    if shares < quantity:
                        raise ValueError("insufficient shares")
                    remaining = shares - quantity
                    if remaining == 0:
                        cur.execute(
                            "DELETE FROM holdings WHERE account_id = %s AND symbol = %s",
                            (account_id, sym),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE holdings
                            SET shares = %s, updated_at = now()
                            WHERE account_id = %s AND symbol = %s
                            """,
                            (remaining, account_id, sym),
                        )
                    cash += total

                cur.execute(
                    "UPDATE accounts SET cash_balance = %s WHERE id = %s",
                    (cash, account_id),
                )
                cur.execute(
                    """
                    INSERT INTO orders (account_id, symbol, side, quantity, fill_price, total)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, symbol, side, quantity, fill_price, total, created_at
                    """,
                    (account_id, sym, side, quantity, fill_price, total),
                )
                order = cur.fetchone()
            conn.commit()
            return {"order": order, "cash_balance": cash}

    def get_or_set_daily_baseline(self, account_id: str, total_value: Decimal, on_date: date) -> Decimal:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT start_value FROM portfolio_daily_baseline
                    WHERE account_id = %s AND baseline_date = %s
                    """,
                    (account_id, on_date),
                )
                row = cur.fetchone()
                if row:
                    return Decimal(str(row["start_value"]))
                cur.execute(
                    """
                    INSERT INTO portfolio_daily_baseline (account_id, baseline_date, start_value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (account_id, baseline_date) DO NOTHING
                    """,
                    (account_id, on_date, total_value),
                )
            conn.commit()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT start_value FROM portfolio_daily_baseline
                    WHERE account_id = %s AND baseline_date = %s
                    """,
                    (account_id, on_date),
                )
                row = cur.fetchone()
                return Decimal(str(row["start_value"])) if row else total_value

    def get_daily_baseline_row(self, account_id: str, on_date: date) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT start_value, effective_at
                    FROM portfolio_daily_baseline
                    WHERE account_id = %s AND baseline_date = %s
                    """,
                    (account_id, on_date),
                )
                return cur.fetchone()

    def set_daily_baseline(
        self,
        account_id: str,
        total_value: Decimal,
        on_date: date,
        effective_at: datetime | None = None,
    ) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO portfolio_daily_baseline (
                        account_id, baseline_date, start_value, effective_at
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (account_id, baseline_date) DO UPDATE
                    SET start_value = EXCLUDED.start_value,
                        effective_at = COALESCE(EXCLUDED.effective_at, portfolio_daily_baseline.effective_at)
                    """,
                    (account_id, on_date, total_value, effective_at),
                )
            conn.commit()

    def adjust_daily_baseline(
        self,
        account_id: str,
        delta: Decimal,
        on_date: date,
        create_from: Decimal | None = None,
    ) -> Decimal:
        """Add delta to today's baseline. Creates baseline from create_from + delta if missing."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT start_value FROM portfolio_daily_baseline
                    WHERE account_id = %s AND baseline_date = %s
                    FOR UPDATE
                    """,
                    (account_id, on_date),
                )
                row = cur.fetchone()
                if row:
                    new_value = Decimal(str(row["start_value"])) + delta
                    cur.execute(
                        """
                        UPDATE portfolio_daily_baseline
                        SET start_value = %s
                        WHERE account_id = %s AND baseline_date = %s
                        """,
                        (new_value, account_id, on_date),
                    )
                else:
                    base = create_from if create_from is not None else Decimal("0")
                    new_value = base + delta
                    cur.execute(
                        """
                        INSERT INTO portfolio_daily_baseline (account_id, baseline_date, start_value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (account_id, baseline_date) DO UPDATE
                        SET start_value = portfolio_daily_baseline.start_value + %s
                        """,
                        (account_id, on_date, new_value, delta),
                    )
                    cur.execute(
                        """
                        SELECT start_value FROM portfolio_daily_baseline
                        WHERE account_id = %s AND baseline_date = %s
                        """,
                        (account_id, on_date),
                    )
                    refreshed = cur.fetchone()
                    if refreshed:
                        new_value = Decimal(str(refreshed["start_value"]))
            conn.commit()
            return new_value

    def count_orders_on_date(self, account_id: str, on_date: date) -> int:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM orders
                    WHERE account_id = %s
                      AND (created_at AT TIME ZONE 'UTC')::date = %s
                    """,
                    (account_id, on_date),
                )
                row = cur.fetchone()
                return int(row["n"]) if row else 0

    def get_mark_at_or_before(self, account_id: str, at: datetime) -> dict | None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT marked_at, total_value
                    FROM portfolio_marks
                    WHERE account_id = %s AND marked_at <= %s
                    ORDER BY marked_at DESC
                    LIMIT 1
                    """,
                    (account_id, at),
                )
                return cur.fetchone()

    def maybe_record_mark(
        self,
        account_id: str,
        total_value: Decimal,
        cash: Decimal,
        equity: Decimal,
    ) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT marked_at FROM portfolio_marks
                    WHERE account_id = %s
                    ORDER BY marked_at DESC
                    LIMIT 1
                    """,
                    (account_id,),
                )
                last = cur.fetchone()
                if last and last["marked_at"]:
                    marked_at = last["marked_at"]
                    if marked_at.tzinfo is None:
                        marked_at = marked_at.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) - marked_at < timedelta(seconds=MARK_MIN_INTERVAL_SECONDS):
                        return
                cur.execute(
                    """
                    INSERT INTO portfolio_marks (account_id, total_value, cash_balance, equity)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (account_id, total_value, cash, equity),
                )
            conn.commit()

    def get_marks_since(self, account_id: str, since: datetime) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT marked_at, total_value
                    FROM portfolio_marks
                    WHERE account_id = %s AND marked_at >= %s
                    ORDER BY marked_at ASC
                    """,
                    (account_id, since),
                )
                return list(cur.fetchall())

    def get_daily_last_marks(self, account_id: str, days: int) -> list[dict]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (marked_at::date)
                      marked_at::date AS mark_date,
                      total_value,
                      marked_at
                    FROM portfolio_marks
                    WHERE account_id = %s
                      AND marked_at >= (CURRENT_DATE - %s::int)
                    ORDER BY marked_at::date, marked_at DESC
                    """,
                    (account_id, days),
                )
                rows = list(cur.fetchall())
                rows.sort(key=lambda r: r["mark_date"])
                return rows


class MarketClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def get_quote(self, symbol: str) -> dict:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{self._base_url}/quotes/{symbol.upper()}")
            response.raise_for_status()
            return response.json()

    def get_quotes_batch(self, symbols: list[str]) -> list[dict]:
        cleaned = [s.strip().upper() for s in symbols if s and s.strip()]
        if not cleaned:
            return []
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self._base_url}/quotes",
                params={"symbols": ",".join(cleaned)},
            )
            response.raise_for_status()
            return response.json()

    def get_candles(self, symbol: str, chart_range: str) -> list[dict]:
        with httpx.Client(timeout=45.0) as client:
            response = client.get(
                f"{self._base_url}/candles/{symbol.upper()}",
                params={"range": chart_range},
            )
            response.raise_for_status()
            payload = response.json()
        points = payload.get("points") if isinstance(payload, dict) else None
        return list(points or [])


def open_store(database_url: str) -> PortfolioStore:
    store = PortfolioStore(database_url)
    store.ping()
    return store
