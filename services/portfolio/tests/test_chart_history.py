from datetime import datetime, timezone
from decimal import Decimal

from app.chart_history import infer_starting_cash, reconstruct_portfolio_chart


def test_infer_starting_cash_undoes_buys_and_sells() -> None:
    orders = [
        {
            "side": "buy",
            "total": Decimal("1000"),
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
        {
            "side": "sell",
            "total": Decimal("200"),
            "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        },
    ]
    # Current cash 9200 after buy 1000 then sell 200 from 10000
    assert infer_starting_cash(Decimal("9200"), orders) == Decimal("10000")


def test_reconstruct_tracks_holding_price_moves() -> None:
    buy_ts = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
    t1 = int(datetime(2026, 7, 10, tzinfo=timezone.utc).timestamp())
    t2 = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp())
    now_ts = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp())

    orders = [
        {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": Decimal("10"),
            "fill_price": Decimal("100"),
            "total": Decimal("1000"),
            "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        }
    ]
    candles = {
        "AAPL": [
            {"time": buy_ts, "close": 100.0},
            {"time": t1, "close": 110.0},
            {"time": t2, "close": 120.0},
            {"time": now_ts, "close": 150.0},
        ]
    }

    # Started 10000, bought 1000 → cash 9000; live total 9000 + 10*150 = 10500
    points = reconstruct_portfolio_chart(
        orders_asc=orders,
        candles_by_symbol=candles,
        current_cash=Decimal("9000"),
        current_total=Decimal("10500"),
        window_start_ts=buy_ts,
        now_ts=now_ts,
    )

    assert len(points) >= 3
    # Window starts at buy time: cash 9000 + 10*100 = 10000
    assert points[0].time == buy_ts
    assert points[0].value == 10000.0
    mid = next(p for p in points if p.time == t1)
    assert mid.value == 10100.0  # 9000 + 10*110
    assert points[-1].value == 10500.0
