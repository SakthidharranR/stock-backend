# Stock Backend

Microservices-style layout. Each service lives under `services/` with its own Dockerfile and API.

## Services

| Service    | Port | Responsibility                          |
|------------|------|-----------------------------------------|
| `identity` | 8081 | User profile sync, JWT validation (Go) |

## Quick start

```bash
# Postgres only (while building identity in Go)
docker compose up -d postgres

# Full stack (after identity service is implemented)
docker compose --profile full up --build
```

## Identity service

Implement manually under `services/identity/`. See `services/identity/README.md`.

Migrations: `services/identity/migrations/`
