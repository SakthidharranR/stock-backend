#!/usr/bin/env bash
# Apply SQL migrations to the production Postgres container.
# Usage (from stock-backend): ./scripts/apply-migrations.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DOCKER=(docker)
if ! docker ps >/dev/null 2>&1; then
  DOCKER=(sudo docker)
fi

COMPOSE=("${DOCKER[@]}" compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml)

echo "Waiting for Postgres..."
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T postgres pg_isready -U stockapp -d stockapp >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! "${COMPOSE[@]}" exec -T postgres pg_isready -U stockapp -d stockapp >/dev/null 2>&1; then
  echo "Postgres did not become ready." >&2
  exit 1
fi

apply() {
  local file="$1"
  echo "Applying $(basename "$file")..."
  "${COMPOSE[@]}" exec -T postgres psql -U stockapp -d stockapp -v ON_ERROR_STOP=1 < "$file"
}

apply "$ROOT/services/identity/migrations/001_users.sql"

while IFS= read -r -d '' file; do
  apply "$file"
done < <(find "$ROOT/migrations" -maxdepth 1 -name '*.sql' -print0 | sort -z)

echo "Migrations complete."
