"""Unit tests for scan_complete handler — direct Lambda invocation."""
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from src.common.config import Settings
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _event(image_id: str, result: str) -> dict:
    return {"image_id": image_id, "result": result}


def _seed(settings, image_id: str) -> None:
    img_repo.create_pending(settings, image_id, "usr_abc",
        f"originals/usr_abc/{image_id}/f.jpg", "up-1", "image/jpeg", None, None, [])
    img_repo.set_status(settings, image_id, "SCANNING")


@mock_aws
def test_clean_scan_transitions_to_active(dynamodb_tables, mock_settings: Settings):
    _seed(mock_settings, "img_scan1")

    mock_lambda = MagicMock()
    with patch("src.handlers.scan_complete.get_settings", return_value=mock_settings), \
         patch("boto3.client", return_value=mock_lambda):
        from src.handlers.scan_complete import handler
        handler(_event("img_scan1", "CLEAN"), MagicMock())

    assert img_repo.get_by_id(mock_settings, "img_scan1").status == "ACTIVE"


@mock_aws
def test_threat_scan_transitions_to_quarantine(dynamodb_tables, s3_buckets, mock_settings: Settings):
    _seed(mock_settings, "img_scan2")
    img_repo.set_status(mock_settings, "img_scan2", "SCANNING")

    with patch("src.handlers.scan_complete.get_settings", return_value=mock_settings), \
         patch("src.repositories.storage_repository.move_to_quarantine", return_value="quarantine/k"):
        from src.handlers.scan_complete import handler
        handler(_event("img_scan2", "THREAT"), MagicMock())

    assert img_repo.get_by_id(mock_settings, "img_scan2").status == "QUARANTINE"
