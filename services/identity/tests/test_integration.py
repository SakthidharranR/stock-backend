import os

import httpx
import pytest

INTEGRATION_URL = os.getenv("IDENTITY_TEST_URL", "http://localhost:8081").rstrip("/")


@pytest.mark.integration
def test_live_health() -> None:
    response = httpx.get(f"{INTEGRATION_URL}/health", timeout=5.0)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
def test_live_register_round_trip() -> None:
    payload = {
        "cognito_sub": "pytest-sub-integration",
        "email": "pytest-integration@example.com",
        "display_name": "Pytest",
    }

    first = httpx.post(f"{INTEGRATION_URL}/register", json=payload, timeout=5.0)
    assert first.status_code == 201
    assert first.json()["message"] in {
        "User registered successfully!",
        "User already registered",
    }

    second = httpx.post(f"{INTEGRATION_URL}/register", json=payload, timeout=5.0)
    assert second.status_code == 201
    assert second.json()["message"] == "User already registered"
