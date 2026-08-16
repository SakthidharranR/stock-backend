# Identity service (Python / FastAPI)

Handles app user records in Postgres. **Passwords stay in Cognito.**

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/register` | Create profile after Cognito signup (`cognito_sub`, `email`, optional `display_name`) |

`/users/me` JWT endpoints are planned but not implemented yet.

## Local run (without Docker)

```bash
cd services/identity
pip install -r requirements.txt
export DATABASE_URL=postgres://stockapp:stockapp_dev@localhost:5433/stockapp?sslmode=disable
uvicorn app.main:create_application --factory --reload --port 8081
```

## Cognito sync CLI

Imports Cognito users into Postgres (used by `scripts/dev-reset.ps1`):

```bash
python scripts/sync_cognito.py
```

Requires `COGNITO_USER_POOL_ID`, `DATABASE_URL`, and AWS credentials with `cognito-idp:ListUsers`.

## Tests

```bash
pip install -r requirements.txt
pytest

# Against running Docker identity service:
pytest -m integration
```

## Env

See `../../.env.example` plus `PORT`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`.
