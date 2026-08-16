import pytest
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation
from unittest.mock import MagicMock

from app.main import create_app
from app.store import UserStore


@pytest.fixture
def mock_store() -> MagicMock:
    return MagicMock(spec=UserStore)


@pytest.fixture
def client(mock_store: MagicMock) -> TestClient:
    app = create_app(store=mock_store)
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_register_success(client: TestClient, mock_store: MagicMock) -> None:
    response = client.post(
        "/register",
        json={
            "cognito_sub": "sub-123",
            "email": "User@Example.com",
            "display_name": "Test User",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["display_name"] == "Test User"
    assert body["cognito_sub"] == "sub-123"
    assert body["message"] == "User registered successfully!"
    mock_store.create_user.assert_called_once_with(
        "sub-123",
        "user@example.com",
        "Test User",
    )


def test_register_duplicate(client: TestClient, mock_store: MagicMock) -> None:
    mock_store.create_user.side_effect = UniqueViolation("duplicate key")

    response = client.post(
        "/register",
        json={
            "cognito_sub": "sub-123",
            "email": "user@example.com",
        },
    )
    assert response.status_code == 201
    assert response.json()["message"] == "User already registered"


def test_register_missing_email(client: TestClient) -> None:
    response = client.post(
        "/register",
        json={"cognito_sub": "sub-123", "email": "   "},
    )
    assert response.status_code == 400
    assert response.json() == {"error": "email is required"}


def test_register_missing_cognito_sub(client: TestClient) -> None:
    response = client.post(
        "/register",
        json={"email": "user@example.com", "cognito_sub": ""},
    )
    assert response.status_code == 400
    assert response.json() == {"error": "cognito_sub is required"}


def test_register_invalid_json(client: TestClient) -> None:
    response = client.post(
        "/register",
        content="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid request body"}


def test_register_ignores_password(client: TestClient, mock_store: MagicMock) -> None:
    response = client.post(
        "/register",
        json={
            "cognito_sub": "sub-456",
            "email": "user@example.com",
            "password": "secret",
        },
    )
    assert response.status_code == 201
    mock_store.create_user.assert_called_once()
