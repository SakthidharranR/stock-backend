from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthUser, get_current_user
from app.main import (
    _apply_quotes_to_holdings,
    _compute_equity,
    _holding_items,
    _resolve_fill_price,
    create_app,
)
from app.store import MarketClient, PortfolioStore


USER_ID = "11111111-1111-1111-1111-111111111111"
ACCOUNT_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def mock_store() -> MagicMock:
    store = MagicMock(spec=PortfolioStore)
    store.get_or_create_account.return_value = {
        "id": ACCOUNT_ID,
        "user_id": USER_ID,
        "cash_balance": Decimal("10000.00"),
    }
    store.get_holdings.return_value = []
    store.get_orders.return_value = []
    store.get_all_orders_asc.return_value = []
    store.get_all_cash_transfers_asc.return_value = []
    store.get_cash_transfers.return_value = []
    store.symbol_exists.return_value = True
    store.get_or_set_daily_baseline.return_value = Decimal("10000.00")
    store.get_daily_baseline_row.return_value = {
        "start_value": Decimal("10000.00"),
        "effective_at": None,
    }
    store.get_marks_since.return_value = []
    store.get_daily_last_marks.return_value = []
    store.get_mark_at_or_before.return_value = None
    store.count_orders_on_date.return_value = 0
    store.maybe_record_mark.return_value = None
    store.set_daily_baseline.return_value = None
    store.adjust_daily_baseline.return_value = Decimal("10000.00")
    return store


@pytest.fixture
def mock_market() -> MagicMock:
    market = MagicMock(spec=MarketClient)
    market.get_quote.return_value = {
        "symbol": "AAPL",
        "name": "Apple Inc",
        "price": 150.0,
        "change": 1.5,
        "change_percent": 1.0,
        "prev_close": 148.5,
    }
    market.get_quotes_batch.return_value = []
    market.get_candles.return_value = []
    return market


@pytest.fixture
def client(mock_store: MagicMock, mock_market: MagicMock) -> TestClient:
    app = create_app(store=mock_store, market=mock_market)

    def _user() -> AuthUser:
        return AuthUser(
            id=USER_ID,
            cognito_sub="sub-1",
            email="trader@example.com",
            display_name="Trader",
        )

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_compute_equity_uses_avg_cost_when_price_missing() -> None:
    holdings = [
        {"shares": Decimal("10"), "price": None, "avg_cost": Decimal("100")},
        {"shares": Decimal("2"), "price": Decimal("50"), "avg_cost": Decimal("40")},
    ]
    assert _compute_equity(holdings) == Decimal("1100")


def test_apply_quotes_to_holdings_merges_market_fields() -> None:
    holdings = [
        {
            "symbol": "AAPL",
            "shares": Decimal("1"),
            "avg_cost": Decimal("100"),
            "name": "Apple",
            "price": None,
            "change": None,
            "change_pct": None,
        }
    ]
    quotes = [
        {
            "symbol": "AAPL",
            "price": 150.0,
            "change": 2.0,
            "change_percent": 1.35,
        }
    ]
    merged = _apply_quotes_to_holdings(holdings, quotes)
    assert merged[0]["price"] == 150.0
    assert merged[0]["change"] == 2.0
    assert merged[0]["change_pct"] == 1.35


def test_holding_items_use_cost_basis_not_finnhub_session() -> None:
    rows = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "shares": Decimal("10"),
            "avg_cost": Decimal("100"),
            "price": Decimal("150"),
            "change": Decimal("1.25"),  # Finnhub session $ — must be ignored
            "change_pct": Decimal("0.84"),
        }
    ]
    items = _holding_items(rows)
    assert items[0].change == pytest.approx(500.0)  # 10 * (150 - 100)
    assert items[0].change_percent == pytest.approx(50.0)
    assert items[0].change != 1.25


def test_holding_items_zero_right_after_buy_at_same_price() -> None:
    rows = [
        {
            "symbol": "MSFT",
            "name": "Microsoft",
            "shares": Decimal("1"),
            "avg_cost": Decimal("499.99"),
            "price": Decimal("499.99"),
            "change": Decimal("0.13"),
            "change_pct": Decimal("0.026"),
        }
    ]
    items = _holding_items(rows)
    assert items[0].change == pytest.approx(0.0)
    assert items[0].change_percent == pytest.approx(0.0)


def test_resolve_fill_price_uses_market_not_cache(mock_market: MagicMock) -> None:
    mock_market.get_quote.return_value = {"price": 175.5}
    assert _resolve_fill_price(mock_market, "AAPL") == Decimal("175.5")
    mock_market.get_quote.assert_called_once_with("AAPL")


def test_portfolio_refreshes_held_symbols(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_store.get_holdings.return_value = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "shares": Decimal("2"),
            "avg_cost": Decimal("140"),
            "price": Decimal("140"),
            "change": Decimal("0"),
            "change_pct": Decimal("0"),
        },
        {
            "symbol": "NVDA",
            "name": "NVIDIA",
            "shares": Decimal("1"),
            "avg_cost": Decimal("400"),
            "price": None,
            "change": None,
            "change_pct": None,
        },
    ]
    mock_market.get_quotes_batch.return_value = [
        {
            "symbol": "AAPL",
            "price": 150.0,
            "change": 2.0,
            "change_percent": 1.35,
        },
        {
            "symbol": "NVDA",
            "price": 420.0,
            "change": 5.0,
            "change_percent": 1.2,
        },
    ]

    response = client.get("/portfolio?range=1D")
    assert response.status_code == 200
    mock_market.get_quotes_batch.assert_called_once()
    called_symbols = sorted(mock_market.get_quotes_batch.call_args.args[0])
    assert called_symbols == ["AAPL", "NVDA"]

    body = response.json()
    # cash 10000 + 2*150 + 1*420 = 10720
    assert body["total_value"] == pytest.approx(10720.0)
    assert body["equity"] == pytest.approx(720.0)


def test_holdings_returns_cost_basis_change(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_store.get_holdings.return_value = [
        {
            "symbol": "MSFT",
            "name": "Microsoft",
            "shares": Decimal("1"),
            "avg_cost": Decimal("499.99"),
            "price": Decimal("499.99"),
            "change": Decimal("0.13"),
            "change_pct": Decimal("0.026"),
        }
    ]
    mock_market.get_quotes_batch.return_value = [
        {
            "symbol": "MSFT",
            "price": 499.99,
            "change": 0.13,
            "change_percent": 0.026,
        }
    ]

    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["price"] == 499.99
    assert body[0]["change"] == pytest.approx(0.0)
    assert body[0]["change_percent"] == pytest.approx(0.0)


def test_buy_keeps_total_value_stable_with_consistent_quotes(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    fill = Decimal("150.00")
    mock_market.get_quote.return_value = {
        "symbol": "AAPL",
        "price": float(fill),
        "change": 0.0,
        "change_percent": 0.0,
    }
    mock_market.get_quotes_batch.return_value = [
        {
            "symbol": "AAPL",
            "price": float(fill),
            "change": 0.0,
            "change_percent": 0.0,
        }
    ]

    order_id = uuid4()
    created = datetime(2026, 8, 10, tzinfo=timezone.utc)
    mock_store.place_order.return_value = {
        "order": {
            "id": order_id,
            "symbol": "AAPL",
            "side": "buy",
            "quantity": Decimal("1"),
            "fill_price": fill,
            "total": Decimal("150.00"),
            "created_at": created,
        },
        "cash_balance": Decimal("9850.00"),
    }
    # pre: no holdings; post: 1 share
    mock_store.get_holdings.side_effect = [
        [],
        [
            {
                "symbol": "AAPL",
                "name": "Apple Inc",
                "shares": Decimal("1"),
                "avg_cost": fill,
                "price": fill,
                "change": Decimal("0"),
                "change_pct": Decimal("0"),
            }
        ],
    ]
    mock_store.count_orders_on_date.return_value = 1

    order_resp = client.post(
        "/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1},
    )
    assert order_resp.status_code == 201
    assert order_resp.json()["cash_balance"] == 9850.0
    mock_store.set_daily_baseline.assert_called_once()
    _args, kwargs = mock_store.set_daily_baseline.call_args
    assert _args[1] == Decimal("10000.00")  # post_total
    assert kwargs.get("effective_at") == created

    mock_store.get_holdings.side_effect = None
    mock_store.get_holdings.return_value = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "shares": Decimal("1"),
            "avg_cost": fill,
            "price": fill,
            "change": Decimal("0"),
            "change_pct": Decimal("0"),
        }
    ]
    mock_store.get_or_create_account.return_value = {
        "id": ACCOUNT_ID,
        "user_id": USER_ID,
        "cash_balance": Decimal("9850.00"),
    }
    mock_store.get_or_set_daily_baseline.return_value = Decimal("10000.00")
    after = client.get("/portfolio?range=1D")
    assert after.status_code == 200
    assert after.json()["total_value"] == pytest.approx(10000.0)
    assert after.json()["day_change"] == pytest.approx(0.0)


def test_missing_quote_does_not_undervalue_existing_shares() -> None:
    # 10 shares with null price previously counted as $0; must use avg_cost.
    holdings = [
        {
            "symbol": "AAPL",
            "shares": Decimal("10"),
            "price": None,
            "avg_cost": Decimal("150"),
        }
    ]
    assert _compute_equity(holdings) == Decimal("1500")


def test_midday_buy_preserves_overnight_day_change(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    """Baseline adjusts by post-pre so existing day P&L is not wiped."""
    fill = Decimal("50.00")
    mock_market.get_quote.return_value = {"price": float(fill)}
    mock_market.get_quotes_batch.return_value = [
        {"symbol": "AAPL", "price": 110.0, "change": 10.0, "change_percent": 10.0},
        {"symbol": "XYZ", "price": float(fill), "change": 0.0, "change_percent": 0.0},
    ]

    overnight = {
        "symbol": "AAPL",
        "name": "Apple",
        "shares": Decimal("1"),
        "avg_cost": Decimal("100"),
        "price": Decimal("110"),
        "change": Decimal("10"),
        "change_pct": Decimal("10"),
    }
    after_buy_holdings = [
        overnight,
        {
            "symbol": "XYZ",
            "name": "Other",
            "shares": Decimal("1"),
            "avg_cost": fill,
            "price": fill,
            "change": Decimal("0"),
            "change_pct": Decimal("0"),
        },
    ]
    # pre cash 10000 + 110 equity = 10110; post cash 9950 + 110 + 50 = 10110
    mock_store.get_or_create_account.return_value = {
        "id": ACCOUNT_ID,
        "user_id": USER_ID,
        "cash_balance": Decimal("10000.00"),
    }
    mock_store.get_holdings.side_effect = [[overnight], after_buy_holdings]
    mock_store.count_orders_on_date.return_value = 2  # not first order
    created = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)
    mock_store.place_order.return_value = {
        "order": {
            "id": uuid4(),
            "symbol": "XYZ",
            "side": "buy",
            "quantity": Decimal("1"),
            "fill_price": fill,
            "total": Decimal("50.00"),
            "created_at": created,
        },
        "cash_balance": Decimal("9950.00"),
    }

    resp = client.post("/orders", json={"symbol": "XYZ", "side": "buy", "quantity": 1})
    assert resp.status_code == 201
    mock_store.set_daily_baseline.assert_not_called()
    mock_store.adjust_daily_baseline.assert_called_once()
    delta = mock_store.adjust_daily_baseline.call_args.args[1]
    assert delta == pytest.approx(Decimal("0"))


def test_range_1d_vs_all_use_chart_start(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_store.get_holdings.return_value = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "shares": Decimal("1"),
            "avg_cost": Decimal("100"),
            "price": Decimal("150"),
            "change": Decimal("1"),
            "change_pct": Decimal("0.67"),
        }
    ]
    mock_market.get_quotes_batch.return_value = [
        {
            "symbol": "AAPL",
            "price": 150.0,
            "change": 1.0,
            "change_percent": 0.67,
        }
    ]
    mock_store.get_or_create_account.return_value = {
        "id": ACCOUNT_ID,
        "user_id": USER_ID,
        "cash_balance": Decimal("10000.00"),
    }
    # total = 10150
    mock_store.get_or_set_daily_baseline.return_value = Decimal("10150.00")
    mock_store.get_daily_baseline_row.return_value = {
        "start_value": Decimal("10150.00"),
        "effective_at": datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc),
    }
    mock_store.get_marks_since.return_value = []
    mock_store.get_daily_last_marks.return_value = [
        {
            "mark_date": datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
            "total_value": Decimal("9800.00"),
            "marked_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        },
        {
            "mark_date": datetime(2026, 8, 10, tzinfo=timezone.utc).date(),
            "total_value": Decimal("10150.00"),
            "marked_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        },
    ]

    day = client.get("/portfolio?range=1D")
    all_range = client.get("/portfolio?range=ALL")
    assert day.status_code == 200
    assert all_range.status_code == 200

    day_body = day.json()
    all_body = all_range.json()
    assert day_body["total_value"] == pytest.approx(10150.0)
    assert day_body["day_change"] == pytest.approx(0.0)
    # ALL chart starts at earliest in-window daily mark (9800)
    assert all_body["day_change"] == pytest.approx(350.0)
    assert day_body["day_change"] != all_body["day_change"]


def test_multiday_range_zero_without_history(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_store.get_holdings.side_effect = None
    mock_store.get_holdings.return_value = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "shares": Decimal("1"),
            "avg_cost": Decimal("100"),
            "price": Decimal("150"),
            "change": Decimal("1"),
            "change_pct": Decimal("0.67"),
        }
    ]
    mock_market.get_quotes_batch.return_value = [
        {"symbol": "AAPL", "price": 150.0, "change": 1.0, "change_percent": 0.67}
    ]
    mock_store.get_daily_last_marks.return_value = []
    mock_store.get_marks_since.return_value = []
    mock_store.get_all_orders_asc.return_value = []
    mock_market.get_candles.return_value = []
    mock_store.get_or_set_daily_baseline.return_value = Decimal("10150.00")

    week = client.get("/portfolio?range=1W")
    month = client.get("/portfolio?range=1M")
    assert week.status_code == 200
    assert month.status_code == 200
    assert week.json()["day_change"] == pytest.approx(0.0)
    assert month.json()["day_change"] == pytest.approx(0.0)


def test_month_chart_uses_candle_history_when_marks_missing(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_store.get_holdings.side_effect = None
    mock_store.get_holdings.return_value = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc",
            "shares": Decimal("10"),
            "avg_cost": Decimal("100"),
            "price": Decimal("150"),
            "change": Decimal("50"),
            "change_pct": Decimal("50"),
        }
    ]
    mock_store.get_or_create_account.return_value = {
        "id": ACCOUNT_ID,
        "user_id": USER_ID,
        "cash_balance": Decimal("9000.00"),
    }
    mock_market.get_quotes_batch.return_value = [
        {"symbol": "AAPL", "price": 150.0, "change": 1.0, "change_percent": 0.67}
    ]
    mock_store.get_daily_last_marks.return_value = []
    mock_store.get_marks_since.return_value = []
    mock_store.get_all_orders_asc.return_value = [
        {
            "id": uuid4(),
            "symbol": "AAPL",
            "side": "buy",
            "quantity": Decimal("10"),
            "fill_price": Decimal("100"),
            "total": Decimal("1000"),
            "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        }
    ]
    mock_market.get_candles.return_value = [
        {"time": int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()), "close": 100.0},
        {"time": int(datetime(2026, 7, 15, tzinfo=timezone.utc).timestamp()), "close": 120.0},
        {"time": int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()), "close": 150.0},
    ]

    month = client.get("/portfolio?range=1M")
    assert month.status_code == 200
    body = month.json()
    assert body["total_value"] == pytest.approx(10500.0)
    assert len(body["chart_points"]) >= 3
    # Should reflect historical move, not a flat 0 change stub.
    assert body["day_change"] != pytest.approx(0.0)
    mock_market.get_candles.assert_called()


def test_week_and_month_differ_with_distinct_in_window_marks(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_store.get_holdings.side_effect = None
    mock_store.get_holdings.return_value = []
    mock_market.get_quotes_batch.return_value = []
    mock_store.get_or_create_account.return_value = {
        "id": ACCOUNT_ID,
        "user_id": USER_ID,
        "cash_balance": Decimal("10000.00"),
    }

    week_daily = [
        {
            "mark_date": datetime(2026, 8, 5, tzinfo=timezone.utc).date(),
            "total_value": Decimal("9800.00"),
            "marked_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
        }
    ]
    month_daily = [
        {
            "mark_date": datetime(2026, 7, 15, tzinfo=timezone.utc).date(),
            "total_value": Decimal("9000.00"),
            "marked_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
        },
        {
            "mark_date": datetime(2026, 8, 5, tzinfo=timezone.utc).date(),
            "total_value": Decimal("9800.00"),
            "marked_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
        },
    ]

    mock_store.get_daily_last_marks.side_effect = [week_daily, month_daily]

    week = client.get("/portfolio?range=1W")
    month = client.get("/portfolio?range=1M")
    assert week.status_code == 200
    assert month.status_code == 200
    assert week.json()["day_change"] == pytest.approx(200.0)  # 10000 - 9800
    assert month.json()["day_change"] == pytest.approx(1000.0)  # 10000 - 9000
    assert week.json()["day_change"] != month.json()["day_change"]


def test_cash_deposit_and_withdraw(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_store.get_or_create_account.return_value = {
        "id": ACCOUNT_ID,
        "user_id": USER_ID,
        "cash_balance": Decimal("10000.00"),
    }
    mock_store.get_holdings.return_value = []
    mock_market.get_quotes_batch.return_value = []
    mock_store.transfer_cash.return_value = {
        "transfer": {
            "id": uuid4(),
            "side": "deposit",
            "amount": Decimal("250.00"),
            "created_at": datetime.now(timezone.utc),
        },
        "cash_balance": Decimal("10250.00"),
    }

    deposit = client.post("/cash", json={"side": "deposit", "amount": 250})
    assert deposit.status_code == 201
    assert deposit.json()["cash_balance"] == 10250.0
    mock_store.adjust_daily_baseline.assert_called()

    mock_store.transfer_cash.return_value = {
        "transfer": {
            "id": uuid4(),
            "side": "withdraw",
            "amount": Decimal("100.00"),
            "created_at": datetime.now(timezone.utc),
        },
        "cash_balance": Decimal("10150.00"),
    }
    withdraw = client.post("/cash", json={"side": "withdraw", "amount": 100})
    assert withdraw.status_code == 201
    assert withdraw.json()["cash_balance"] == 10150.0


def test_fill_price_endpoint_calls_market(
    client: TestClient,
    mock_store: MagicMock,
    mock_market: MagicMock,
) -> None:
    mock_market.get_quote.return_value = {"price": 200.0}
    mock_store.place_order.return_value = {
        "order": {
            "id": uuid4(),
            "symbol": "AAPL",
            "side": "buy",
            "quantity": Decimal("1"),
            "fill_price": Decimal("200.00"),
            "total": Decimal("200.00"),
            "created_at": datetime.now(timezone.utc),
        },
        "cash_balance": Decimal("9800.00"),
    }
    mock_store.get_holdings.side_effect = [[], []]
    mock_store.count_orders_on_date.return_value = 1
    mock_market.get_quotes_batch.return_value = []

    response = client.post(
        "/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1},
    )
    assert response.status_code == 201
    mock_market.get_quote.assert_called_with("AAPL")
    mock_store.get_cached_quote.assert_not_called()
