"""Shared Lambda middleware utilities.

Provides helpers for extracting identity from API Gateway JWT authorizer
claims and for reading the API Gateway request ID used in response envelopes.
In local/dev mode the ``_dev_user_id`` query-string parameter may substitute
for a real JWT so that ``sam local`` can be used without Cognito.
"""
from typing import Any

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit

from src.common.exceptions import ForbiddenError

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


def get_caller_user_id(event: dict) -> str:
    """Extract user_id from JWT authorizer claims. Raises ForbiddenError if absent."""
    claims: dict = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    user_id: str = claims.get("sub", "")
    if not user_id:
        # Fallback for sam local / dev bypass
        user_id = event.get("queryStringParameters", {}).get("_dev_user_id", "")
    if not user_id:
        raise ForbiddenError("Missing authentication")
    return user_id


def get_caller_groups(event: dict) -> list[str]:
    """Return the list of Cognito groups the caller belongs to.

    Parses the ``cognito:groups`` claim from the JWT authorizer context.
    Returns an empty list when no groups claim is present.
    """
    claims: dict = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    groups_raw: str = claims.get("cognito:groups", "")
    if not groups_raw:
        return []
    return [g.strip() for g in groups_raw.strip("[]").split(",") if g.strip()]


def is_admin(event: dict) -> bool:
    """Return True if the caller belongs to the ``admin`` Cognito group."""
    return "admin" in get_caller_groups(event)


def get_request_id(event: dict) -> str:
    """Extract the API Gateway request ID from the event context for logging and response envelopes."""
    return (
        event.get("requestContext", {}).get("requestId", "")
        or event.get("requestContext", {}).get("extendedRequestId", "")
    )
