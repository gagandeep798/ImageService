"""Lambda TOKEN authorizer — validates Bearer JWTs issued by this service."""
from __future__ import annotations

from aws_lambda_powertools import Logger

from src.common import jwt_utils
from src.common.config import get_settings

logger = Logger(service="image-service")


def handler(event: dict, _context: object) -> dict:
    token = event.get("authorizationToken", "").removeprefix("Bearer ").strip()
    settings = get_settings()

    try:
        payload = jwt_utils.decode_token(settings, token, "access")
    except Exception:
        raise Exception("Unauthorized")

    user_id = payload["sub"]
    is_admin = str(payload.get("is_admin", False)).lower()

    return {
        "principalId": user_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": "Allow",
                    "Resource": event["methodArn"],
                }
            ],
        },
        "context": {
            "user_id": user_id,
            "is_admin": is_admin,
        },
    }
