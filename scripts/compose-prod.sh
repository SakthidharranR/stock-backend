#!/usr/bin/env bash
# Run Docker Compose with production overrides.
# Usage (from stock-backend): ./scripts/compose-prod.sh up -d --build
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env.prod ]]; then
  echo "Missing .env.prod. Copy .env.prod.example to .env.prod and fill in values." >&2
  exit 1
fi

DOCKER=(docker)
if ! docker ps >/dev/null 2>&1; then
  DOCKER=(sudo docker)
fi

exec "${DOCKER[@]}" compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml "$@"
