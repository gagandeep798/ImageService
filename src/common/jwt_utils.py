"""JWT issuance and validation for DynamoDB-native auth."""
from __future__ import annotations

from datetime import datetime, timezone

import jwt as pyjwt

from src.common.config import Settings


def issue_access_token(settings: Settings, user_id: str, is_admin: bool = False) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    return pyjwt.encode(
        {
            "sub": user_id,
            "is_admin": is_admin,
            "type": "access",
            "iat": now,
            "exp": now + settings.jwt_access_token_ttl,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def issue_refresh_token(settings: Settings, user_id: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    return pyjwt.encode(
        {
            "sub": user_id,
            "type": "refresh",
            "iat": now,
            "exp": now + settings.jwt_refresh_token_ttl,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_token(settings: Settings, token: str, expected_type: str) -> dict:
    payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("type") != expected_type:
        raise pyjwt.InvalidTokenError("Wrong token type")
    return payload
