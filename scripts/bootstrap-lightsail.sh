#!/usr/bin/env bash
# First-time setup on an Ubuntu Lightsail instance.
# Copy stock-backend to the server first, then:
#   cd stock-backend
#   cp .env.prod.example .env.prod   # edit secrets
#   chmod +x scripts/*.sh
#   ./scripts/bootstrap-lightsail.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env.prod ]]; then
  echo "Missing .env.prod. Copy .env.prod.example, fill secrets, then re-run." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "${USER}" || true
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is required." >&2
  exit 1
fi

DOCKER=(docker)
if ! docker ps >/dev/null 2>&1; then
  DOCKER=(sudo docker)
fi

compose() {
  "${DOCKER[@]}" compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml "$@"
}

PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
SSLP_HOST="${PUBLIC_IP//./-}.sslip.io"

if grep -q '^API_PUBLIC_HOST=1-2-3-4.sslip.io' .env.prod || grep -q '^API_PUBLIC_HOST=$' .env.prod; then
  echo "Setting API_PUBLIC_HOST=$SSLP_HOST in .env.prod"
  if grep -q '^API_PUBLIC_HOST=' .env.prod; then
    sed -i "s/^API_PUBLIC_HOST=.*/API_PUBLIC_HOST=$SSLP_HOST/" .env.prod
  else
    echo "API_PUBLIC_HOST=$SSLP_HOST" >> .env.prod
  fi
fi

chmod +x "$ROOT/scripts/"*.sh

echo "Building and starting services..."
compose up -d --build

echo "Applying migrations..."
"$ROOT/scripts/apply-migrations.sh"

echo "Waiting for identity..."
for _ in $(seq 1 30); do
  if curl -fsS "https://$SSLP_HOST/identity/health" >/dev/null 2>&1 \
    || curl -kfsS "https://$SSLP_HOST/identity/health" >/dev/null 2>&1 \
    || compose exec -T identity python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health')" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "Syncing Finnhub symbols (optional)..."
compose exec -T market python scripts/sync_symbols.py || echo "Symbol sync skipped or failed (seeded symbols still work)."

echo
echo "APIs should be reachable at:"
echo "  https://$SSLP_HOST/identity/health"
echo "  https://$SSLP_HOST/market/health"
echo "  https://$SSLP_HOST/portfolio/health"
echo
echo "Put these in stock-frontend/.env.production:"
echo "  VITE_IDENTITY_API_URL=https://$SSLP_HOST/identity"
echo "  VITE_MARKET_API_URL=https://$SSLP_HOST/market"
echo "  VITE_PORTFOLIO_API_URL=https://$SSLP_HOST/portfolio"
echo
echo "After CloudFront exists, set CORS_ALLOWED_ORIGINS in .env.prod to that https://….cloudfront.net URL,"
echo "then run:  ./scripts/compose-prod.sh up -d"
