"""Unit tests for image_repository — CRUD, sharding, pagination, soft delete."""
import pytest
from moto import mock_aws

from src.common.config import Settings
from src.common.dynamo import gsi2_pk, gsi2_pk_all_shards
from src.common.exceptions import NotFoundError
from src.repositories import image_repository as img_repo

pytestmark = pytest.mark.unit


def _create_image(settings: Settings, image_id: str = "img_test001", user_id: str = "usr_abc") -> None:
    img_repo.create_pending(
        settings,
        image_id=image_id,
        user_id=user_id,
        s3_key=f"originals/{user_id}/2026/05/{image_id}/photo.jpg",
        upload_id="upload-123",
        content_type="image/jpeg",
        title="Test Image",
        description=None,
        tags=["nature"],
    )


@mock_aws
def test_create_and_get_image(dynamodb_tables, mock_settings: Settings):
    _create_image(mock_settings)
    image = img_repo.get_by_id(mock_settings, "img_test001", consistent=False)
    assert image.image_id == "img_test001"
    assert image.status == "PENDING"
    assert image.content_type == "image/jpeg"


@mock_aws
def test_get_deleted_image_raises_not_found(dynamodb_tables, mock_settings: Settings):
    _create_image(mock_settings)
    img_repo.soft_delete(mock_settings, "img_test001")
    with pytest.raises(NotFoundError):
        img_repo.get_by_id(mock_settings, "img_test001")


@mock_aws
def test_set_status_transitions(dynamodb_tables, mock_settings: Settings):
    _create_image(mock_settings)
    img_repo.set_status(mock_settings, "img_test001", "SCANNING")
    image = img_repo.get_by_id(mock_settings, "img_test001")
    assert image.status == "SCANNING"


@mock_aws
def test_record_part(dynamodb_tables, mock_settings: Settings):
    _create_image(mock_settings)
    img_repo.record_part(mock_settings, "img_test001", 1, '"abc123"')
    parts = img_repo.get_parts(mock_settings, "img_test001")
    assert parts.get("1") == '"abc123"'


@mock_aws
def test_soft_delete_sets_ttl(dynamodb_tables, mock_settings: Settings):
    _create_image(mock_settings)
    img_repo.soft_delete(mock_settings, "img_test001")

    table = dynamodb_tables.Table(mock_settings.images_table_name)
    item = table.get_item(
        Key={"PK": "IMG#img_test001", "SK": "META#img_test001"}
    )["Item"]
    assert item["status"] == "DELETED"
    assert "ttl" in item
    assert item["ttl"] > 0


@mock_aws
def test_gsi2_sharding_distributes_keys(mock_settings: Settings):
    keys = {gsi2_pk("ACTIVE", f"img_{i:04d}", mock_settings.gsi2_shard_count * 4) for i in range(100)}
    shards = {k.split("#")[2] for k in keys}
    assert len(shards) > 1


def test_gsi2_all_shards_returns_correct_count(mock_settings: Settings):
    shards = gsi2_pk_all_shards("ACTIVE", mock_settings.gsi2_shard_count)
    assert len(shards) == mock_settings.gsi2_shard_count
    assert f"STATUS#ACTIVE#0" in shards
    assert f"STATUS#ACTIVE#{mock_settings.gsi2_shard_count - 1}" in shards


@mock_aws
def test_list_by_user_returns_images(dynamodb_tables, mock_settings: Settings):
    for i in range(3):
        _create_image(mock_settings, f"img_list{i:03d}", "usr_list")
        img_repo.set_status(mock_settings, f"img_list{i:03d}", "ACTIVE")

    result = img_repo.list_by_user(mock_settings, "usr_list", status_filter="ACTIVE", limit=10)
    assert result.count == 3
    assert all(item.status == "ACTIVE" for item in result.items)
