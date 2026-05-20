"""Unit tests for JWT claims middleware helpers."""
import pytest

from src.common.exceptions import ForbiddenError
from src.common import middleware

pytestmark = pytest.mark.unit


def _event(sub: str = "usr_abc", groups: str = "") -> dict:
    return {
        "requestContext": {
            "requestId": "req-123",
            "authorizer": {"jwt": {"claims": {"sub": sub, "cognito:groups": groups}}},
        },
        "queryStringParameters": {},
    }


def test_get_caller_user_id_returns_sub():
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


def test_get_caller_groups_parses_cognito_groups():
    groups = middleware.get_caller_groups(_event(groups="[admin,editor]"))
    assert "admin" in groups
    assert "editor" in groups


def test_get_caller_groups_empty_when_no_claim():
    groups = middleware.get_caller_groups(_event(groups=""))
    assert groups == []


def test_is_admin_returns_true_for_admin_group():
    assert middleware.is_admin(_event(groups="[admin]")) is True


def test_is_admin_returns_false_for_non_admin():
    assert middleware.is_admin(_event(groups="[editor]")) is False


def test_get_request_id_extracts_from_context():
    rid = middleware.get_request_id(_event())
    assert rid == "req-123"


def test_get_request_id_returns_empty_when_missing():
    rid = middleware.get_request_id({"requestContext": {}})
    assert rid == ""
