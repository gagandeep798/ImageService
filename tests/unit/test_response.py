"""Unit tests for the Lambda response envelope builder."""
import json

import pytest

from src.common.exceptions import ForbiddenError, NotFoundError, QuotaExceededError
from src.common import response as resp

pytestmark = pytest.mark.unit


def test_ok_returns_200():
    r = resp.ok({"key": "value"}, request_id="req-1")
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["data"] == {"key": "value"}
    assert body["error"] is None
    assert body["meta"]["request_id"] == "req-1"


def test_accepted_returns_202():
    r = resp.accepted({"image_id": "img_1"})
    assert r["statusCode"] == 202
    assert json.loads(r["body"])["data"]["image_id"] == "img_1"


def test_created_returns_201():
    r = resp.created({})
    assert r["statusCode"] == 201


def test_redirect_returns_302_with_location():
    r = resp.redirect("https://example.com/image.jpg")
    assert r["statusCode"] == 302
    assert r["headers"]["Location"] == "https://example.com/image.jpg"


def test_error_maps_domain_exception_status():
    r = resp.error(NotFoundError("not found"), request_id="req-2")
    assert r["statusCode"] == 404
    body = json.loads(r["body"])
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["data"] is None


def test_error_maps_forbidden():
    r = resp.error(ForbiddenError("denied"))
    assert r["statusCode"] == 403
    assert json.loads(r["body"])["error"]["code"] == "FORBIDDEN"


def test_error_maps_quota_exceeded():
    r = resp.error(QuotaExceededError("over quota"))
    assert r["statusCode"] == 402


def test_error_generic_exception_returns_500():
    r = resp.error(ValueError("oops"))
    assert r["statusCode"] == 500
    body = json.loads(r["body"])
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "oops" not in body["error"]["message"]


def test_ok_includes_security_headers():
    r = resp.ok({})
    assert r["headers"]["X-Content-Type-Options"] == "nosniff"
    assert r["headers"]["X-Frame-Options"] == "DENY"
