"""API response envelope builders.

Every public function returns a dict that conforms to the Lambda proxy-integration
contract: ``{statusCode, headers, body}``.  The body always follows the envelope::

    {"data": <payload | null>, "error": <null | {code, message}>, "meta": {request_id, timestamp}}
"""
import json
from datetime import UTC, datetime
from typing import Any

from src.common.exceptions import ImageServiceError


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def ok(data: Any, request_id: str = "", status_code: int = 200) -> dict:
    """Return a successful Lambda proxy response with a JSON envelope body.

    Args:
        data: The payload to include in the ``data`` field.
        request_id: The API Gateway request ID for traceability.
        status_code: HTTP status code (default 200).

    Returns:
        Lambda proxy-integration response dict.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
        "body": json.dumps({
            "data": data,
            "error": None,
            "meta": {"request_id": request_id, "timestamp": _now_iso()},
        }),
    }


def created(data: Any, request_id: str = "") -> dict:
    """Return a 201 Created response."""
    return ok(data, request_id, status_code=201)


def accepted(data: Any, request_id: str = "") -> dict:
    """Return a 202 Accepted response (async operation initiated)."""
    return ok(data, request_id, status_code=202)


def redirect(location: str) -> dict:
    """Return a 302 redirect response with a ``Location`` header.

    Used by the download handler to redirect the client directly to a
    pre-signed S3 or CloudFront URL without proxying the binary through Lambda.
    """
    return {
        "statusCode": 302,
        "headers": {
            "Location": location,
            "X-Content-Type-Options": "nosniff",
        },
        "body": "",
    }


def error(exc: Exception, request_id: str = "") -> dict:
    """Convert an exception into a Lambda proxy error response.

    Domain exceptions (``ImageServiceError`` subclasses) map to their declared
    ``status_code`` and ``error_code``.  All other exceptions produce a generic
    500 so internal details are never leaked to the caller.
    """
    if isinstance(exc, ImageServiceError):
        status = exc.status_code
        code = exc.error_code
        message = str(exc) or code
    else:
        status = 500
        code = "INTERNAL_ERROR"
        message = "An unexpected error occurred"

    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "data": None,
            "error": {"code": code, "message": message},
            "meta": {"request_id": request_id, "timestamp": _now_iso()},
        }),
    }
