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
    return os.getenv("PORT", "8082").strip() or "8082"


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def get_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").strip()
    return [o.strip() for o in raw.split(",") if o.strip()]


def get_finnhub_api_key() -> str:
    return os.getenv("FINNHUB_API_KEY", "").strip()


def is_finnhub_configured() -> bool:
    key = get_finnhub_api_key()
    if not key or len(key) < 10:
        return False
    lowered = key.lower()
    if lowered.startswith("your_") or lowered in ("changeme", "placeholder"):
        return False
    return True


def get_quote_ttl_seconds() -> int:
    return int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "60"))


def get_news_ttl_seconds() -> int:
    return int(os.getenv("NEWS_CACHE_TTL_SECONDS", "21600"))


def get_admin_key() -> str:
    return os.getenv("ADMIN_API_KEY", "").strip()


def redact_db_url(url: str) -> str:
    return re.sub(r"://([^:@]+):([^@]*)@", r"://\1:***@", url)
