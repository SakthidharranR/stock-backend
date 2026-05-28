# identity service (Go)

Handles app user records and JWT validation. **Passwords stay in Cognito.**

## Planned endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/users/me` | Current user profile (JWT) |
| POST | `/users/me` | Create profile on first login (JWT) |
| PUT | `/users/me` | Update display name (JWT) |

## Implement yourself

1. `go mod init` in this folder
2. `cmd/server/main.go` — HTTP server
3. `internal/auth` — validate Cognito JWT via JWKS
4. `internal/store` — Postgres (`users` table)
5. Run migrations from `migrations/`

## Local run (without Docker)

```bash
export DATABASE_URL=postgres://stockapp:stockapp_dev@localhost:5432/stockapp?sslmode=disable
go run ./cmd/server
```

## Env

See `../../.env.example` plus `PORT`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`.
