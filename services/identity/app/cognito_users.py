"""Look up Cognito auth providers for an email (password vs Google SSO)."""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_cognito_region, get_cognito_user_pool_id

logger = logging.getLogger(__name__)


def _attr_map(user: dict[str, Any]) -> dict[str, str]:
    attrs = user.get("Attributes") or user.get("UserAttributes") or []
    out: dict[str, str] = {}
    for item in attrs:
        name = item.get("Name")
        value = item.get("Value")
        if isinstance(name, str) and isinstance(value, str):
            out[name] = value
    return out


def _providers_from_identities(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    providers: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("providerName") or entry.get("providerType")
        if isinstance(name, str) and name.strip():
            providers.append(name.strip())
    return providers


def lookup_password_options(email: str) -> dict[str, Any]:
    """
    Returns whether this email can use Cognito password reset/change.

    External-provider-only accounts (e.g. Google SSO) cannot reset a password.
    """
    normalized = email.strip().lower()
    pool_id = get_cognito_user_pool_id()
    if not pool_id or not normalized:
        return {
            "email": normalized,
            "found": False,
            "can_use_password": True,
            "providers": [],
            "message": None,
        }

    try:
        client = boto3.client("cognito-idp", region_name=get_cognito_region())
        # Username is often email for native users; federated users need a filter.
        users: list[dict[str, Any]] = []
        try:
            direct = client.admin_get_user(UserPoolId=pool_id, Username=normalized)
            users = [direct]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"UserNotFoundException", "ResourceNotFoundException"}:
                raise
            listed = client.list_users(
                UserPoolId=pool_id,
                Filter=f'email = "{normalized}"',
                Limit=1,
            )
            users = list(listed.get("Users") or [])

        if not users:
            return {
                "email": normalized,
                "found": False,
                "can_use_password": True,
                "providers": [],
                "message": None,
            }

        user = users[0]
        attrs = _attr_map(user)
        providers = _providers_from_identities(attrs.get("identities"))
        status = str(user.get("UserStatus") or "")
        sso_managed = status == "EXTERNAL_PROVIDER" or bool(providers)

        if sso_managed:
            label = next(
                (p for p in providers if p.lower() == "google"),
                providers[0] if providers else "Google",
            )
            return {
                "email": normalized,
                "found": True,
                "can_use_password": False,
                "providers": providers or ["Google"],
                "message": (
                    f"This account uses {label} sign-in, so there is no password to "
                    "change or reset. Use Continue with Google on the login page."
                ),
            }

        return {
            "email": normalized,
            "found": True,
            "can_use_password": True,
            "providers": providers,
            "message": None,
        }
    except (ClientError, BotoCoreError):
        logger.exception("cognito password-options lookup failed email=%s", normalized)
        # Fail open so native forgot-password still works if AWS lookup fails.
        return {
            "email": normalized,
            "found": False,
            "can_use_password": True,
            "providers": [],
            "message": None,
        }
