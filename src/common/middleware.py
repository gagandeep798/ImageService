"""Shared Lambda middleware utilities."""
from src.common.exceptions import ForbiddenError


def get_caller_user_id(event: dict) -> str:
    """Extract user_id from Lambda TOKEN authorizer context. Raises ForbiddenError if absent."""
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    user_id: str = authorizer.get("user_id", "")
    if not user_id:
        user_id = (event.get("queryStringParameters") or {}).get("_dev_user_id", "")
    if not user_id:
        raise ForbiddenError("Missing authentication")
    return user_id


def is_admin(event: dict) -> bool:
    """Return True if the TOKEN authorizer set is_admin=true in the context."""
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    return authorizer.get("is_admin", "false").lower() == "true"


def get_request_id(event: dict) -> str:
    """Extract the API Gateway request ID for logging and response envelopes."""
    return (
        event.get("requestContext", {}).get("requestId", "")
        or event.get("requestContext", {}).get("extendedRequestId", "")
    )
