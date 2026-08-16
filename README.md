# Stock Backend

Microservices-style layout. Each service lives under `services/` with its own Dockerfile and API.

## Services

| Service    | Port | Stack   | Responsibility                    |
|------------|------|---------|-----------------------------------|
| `identity` | 8081 | Python  | User profile records in Postgres  |

## Quick start

```bash
# Postgres only
docker compose up -d postgres

# Full stack (identity + Postgres)
docker compose up -d --build
```

On Windows, run `.\scripts\dev-reset.ps1` from `stock-backend` to reset Postgres, run migrations, optionally sync Cognito, and start identity.

Interview / public APIs: copy `.env.prod.example` to `.env.prod` and use `docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (or `./scripts/bootstrap-lightsail.sh` on the server). Full walkthrough: [../DEPLOY.md](../DEPLOY.md).

CI/CD (pytest + Lightsail deploy): [CI.md](CI.md).

## Identity service

Python FastAPI app under `services/identity/`. See `services/identity/README.md`.

Migrations: `services/identity/migrations/`

API (same contract as before the Python migration):

- `GET /health` → `{"status":"ok"}`
- `POST /register` → create user profile after Cognito signup
