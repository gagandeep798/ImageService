"""Unit tests for middleware helpers."""
import pytest

from src.common import middleware
from src.common.exceptions import ForbiddenError

pytestmark = pytest.mark.unit


def _event(user_id: str = "usr_abc", is_admin: bool = False) -> dict:
    return {
        "requestContext": {
            "requestId": "req-123",
            "authorizer": {
                "claims": {
                    "custom:user_id": user_id,
                    "cognito:groups": "admins" if is_admin else "",
                }
            },
        },
        "queryStringParameters": {},
    }


def test_get_caller_user_id_returns_user_id():
    assert middleware.get_caller_user_id(_event("usr_xyz")) == "usr_xyz"


def test_get_caller_user_id_raises_when_missing():
    event = {"requestContext": {}, "queryStringParameters": {}}
    with pytest.raises(ForbiddenError):
        middleware.get_caller_user_id(event)


def test_dev_bypass_via_query_param():
    event = {
        "requestContext": {},
        "queryStringParameters": {"_dev_user_id": "usr_dev"},
    }
    assert middleware.get_caller_user_id(event) == "usr_dev"


def test_is_admin_returns_true():
    assert middleware.is_admin(_event(is_admin=True)) is True


def test_is_admin_returns_false():
    assert middleware.is_admin(_event(is_admin=False)) is False


def test_get_request_id_extracts_from_context():
    rid = middleware.get_request_id(_event())
    assert rid == "req-123"


def test_get_request_id_returns_empty_when_missing():
    rid = middleware.get_request_id({"requestContext": {}})
    assert rid == ""
