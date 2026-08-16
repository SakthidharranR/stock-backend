#!/usr/bin/env python3
"""Sync US stock symbols from Finnhub into the symbols table."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_database_url, get_finnhub_api_key, is_finnhub_configured, load_env
from app.store import FinnhubClient, open_store


def main() -> int:
    load_env()
    if not is_finnhub_configured():
        print(
            "Skipping Finnhub symbol sync: set a real FINNHUB_API_KEY in stock-backend/.env",
            file=sys.stderr,
        )
        return 0

    api_key = get_finnhub_api_key()
    store = open_store(get_database_url())
    client = FinnhubClient(api_key)
    try:
        rows = client.stock_symbols("US")
    except Exception as exc:
        print(f"Finnhub symbol sync failed: {exc}", file=sys.stderr)
        return 1

    count = store.upsert_symbols_batch(rows)
    print(f"Finnhub symbol sync complete: {count} upserted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
