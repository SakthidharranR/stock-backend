import os

import pytest
from fastapi.testclient import TestClient

from app.config import get_database_url
from app.main import create_app
from app.store import open_store

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db_client() -> TestClient:
    try:
        store = open_store(get_database_url())
    except Exception as exc:
        pytest.skip(f"DATABASE_URL not reachable: {exc}")

    with TestClient(create_app(store=store)) as client:
        yield client


def test_db_register_round_trip(db_client: TestClient) -> None:
    payload = {
        "cognito_sub": "pytest-db-sub",
        "email": "pytest-db@example.com",
        "display_name": "DB Test",
    }

    first = db_client.post("/register", json=payload)
    assert first.status_code == 201
    assert first.json()["message"] in {
        "User registered successfully!",
        "User already registered",
    }

    second = db_client.post("/register", json=payload)
    assert second.status_code == 201
    assert second.json()["message"] == "User already registered"
