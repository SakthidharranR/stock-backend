import logging

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import (
    dev_auth_bypass_enabled,
    get_cognito_app_client_id,
    get_cognito_region,
    get_cognito_user_pool_id,
)
from app.store import PortfolioStore

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)
_jwk_client: PyJWKClient | None = None
_user_store: PortfolioStore | None = None


class AuthUser:
    def __init__(self, id: str, cognito_sub: str, email: str, display_name: str | None) -> None:
        self.id = id
        self.cognito_sub = cognito_sub
        self.email = email
        self.display_name = display_name


def set_user_store(store: PortfolioStore) -> None:
    global _user_store
    _user_store = store


def _get_store() -> PortfolioStore:
    if _user_store is None:
        raise RuntimeError("portfolio store is not initialized")
    return _user_store


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client
    pool_id = get_cognito_user_pool_id()
    region = get_cognito_region()
    if not pool_id:
        raise HTTPException(status_code=503, detail="cognito not configured")
    if _jwk_client is None:
        url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"
        _jwk_client = PyJWKClient(url, cache_keys=True)
    return _jwk_client


def _decode_cognito_token(token: str) -> dict:
    client_id = get_cognito_app_client_id()
    pool_id = get_cognito_user_pool_id()
    region = get_cognito_region()
    if not client_id or not pool_id:
        raise HTTPException(status_code=503, detail="cognito not configured")

    issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        logger.warning("jwt validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="invalid token") from exc

    token_use = claims.get("token_use")
    if token_use == "access":
        if claims.get("client_id") != client_id:
            raise HTTPException(status_code=401, detail="invalid token audience")
    elif token_use == "id":
        if claims.get("aud") != client_id:
            raise HTTPException(status_code=401, detail="invalid token audience")
    else:
        raise HTTPException(status_code=401, detail="unsupported token type")

    return claims


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_dev_email: str | None = Header(default=None, alias="X-Dev-Email"),
    store: PortfolioStore = Depends(_get_store),
) -> AuthUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="missing authorization")

    token = credentials.credentials
    if token.startswith("dev-") and dev_auth_bypass_enabled():
        email = (x_dev_email or "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="X-Dev-Email required for dev auth")
        row = store.get_user_by_email(email)
        if not row:
            raise HTTPException(status_code=401, detail="dev user not found")
        return AuthUser(
            id=str(row["id"]),
            cognito_sub=row["cognito_sub"],
            email=row["email"],
            display_name=row.get("display_name"),
        )

    claims = _decode_cognito_token(token)
    cognito_sub = claims.get("sub")
    if not cognito_sub:
        raise HTTPException(status_code=401, detail="invalid token claims")

    row = store.get_user_by_cognito_sub(cognito_sub)
    if not row:
        raise HTTPException(status_code=404, detail="user not registered")

    return AuthUser(
        id=str(row["id"]),
        cognito_sub=row["cognito_sub"],
        email=row["email"],
        display_name=row.get("display_name"),
    )
