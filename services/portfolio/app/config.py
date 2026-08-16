import os
import re
from pathlib import Path

from dotenv import load_dotenv

_SERVICE_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_ROOT = _SERVICE_ROOT.parent.parent


def load_env() -> None:
    for path in (
        Path.cwd() / ".env",
        _SERVICE_ROOT / ".env",
        _BACKEND_ROOT / ".env",
    ):
        if path.is_file():
            load_dotenv(path, override=True)


load_env()


def get_port() -> str:
    return os.getenv("PORT", "8083").strip() or "8083"


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def get_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").strip()
    return [o.strip() for o in raw.split(",") if o.strip()]


def get_market_service_url() -> str:
    return os.getenv("MARKET_SERVICE_URL", "http://localhost:8082").strip().rstrip("/")


def get_cognito_region() -> str:
    region = os.getenv("COGNITO_REGION", "").strip()
    if region:
        return region
    return os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"


def get_cognito_user_pool_id() -> str:
    return os.getenv("COGNITO_USER_POOL_ID", "").strip()


def get_cognito_app_client_id() -> str:
    return os.getenv("COGNITO_APP_CLIENT_ID", "").strip()


def dev_auth_bypass_enabled() -> bool:
    return os.getenv("DEV_AUTH_BYPASS", "").strip().lower() in ("1", "true", "yes")


def redact_db_url(url: str) -> str:
    return re.sub(r"://([^:@]+):([^@]*)@", r"://\1:***@", url)
