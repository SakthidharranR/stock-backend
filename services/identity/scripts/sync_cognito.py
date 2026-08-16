#!/usr/bin/env python3
"""Sync Cognito user pool users into Postgres (same behavior as the Go sync-cognito CLI)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_cognito_region, get_cognito_user_pool_id, get_database_url, load_env
from app.store import open_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def attr_value(attributes: list[dict], name: str) -> str:
    for attr in attributes:
        if attr.get("Name") == name and attr.get("Value") is not None:
            return str(attr["Value"]).strip()
    return ""


def main() -> int:
    load_env()

    pool_id = get_cognito_user_pool_id()
    if not pool_id:
        logger.error("COGNITO_USER_POOL_ID is not set")
        return 1

    region = get_cognito_region()
    database_url = get_database_url()

    store = open_store(database_url)
    client = boto3.client("cognito-idp", region_name=region)

    pagination_token: str | None = None
    synced = 0
    skipped = 0

    while True:
        params: dict = {"UserPoolId": pool_id, "Limit": 60}
        if pagination_token:
            params["PaginationToken"] = pagination_token

        response = client.list_users(**params)

        for user in response.get("Users", []):
            attrs = user.get("Attributes", [])
            sub = attr_value(attrs, "sub")
            email = attr_value(attrs, "email").lower()
            display_name = attr_value(attrs, "name") or attr_value(attrs, "given_name")

            if not sub:
                skipped += 1
                logger.warning(
                    "skipping user without sub username=%s",
                    user.get("Username"),
                )
                continue
            if not email:
                skipped += 1
                logger.warning("skipping user without email sub=%s", sub)
                continue

            store.upsert_user(sub, email, display_name)
            synced += 1
            logger.info("synced user email=%s sub=%s", email, sub)

        pagination_token = response.get("PaginationToken")
        if not pagination_token:
            break

    print(f"Cognito sync complete: {synced} upserted, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
