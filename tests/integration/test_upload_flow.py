"""
Integration test: full 3-step chunked upload → ACTIVE state.
Requires LocalStack running (make localstack-up).
"""
import pytest

from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo
from src.repositories import user_repository as user_repo

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def patch_settings(integration_settings, monkeypatch):
    monkeypatch.setattr("src.common.dynamo._write_resource", None)
    monkeypatch.setattr("src.common.dynamo._read_resource", None)
    monkeypatch.setattr("src.common.s3._s3_client", None)


def test_full_upload_flow(integration_settings):
    settings = integration_settings
    user_id = "usr_integration_test"
    image_id = "img_integration_001"
    filename = "test_photo.jpg"
    content_type = "image/jpeg"

    # 1. Create user
    try:
        user_repo.create_user(settings, user_id, "Integration Test User", "itest@example.com")
    except Exception:
        pass  # user may already exist from prior run

    # 2. Initiate upload
    upload_id, s3_key = store_repo.initiate_upload(settings, user_id, image_id, filename, content_type)
    assert upload_id
    assert s3_key.startswith("originals/")

    img_repo.create_pending(
        settings, image_id, user_id, s3_key, upload_id, content_type,
        "Integration Test Image", None, ["test"],
    )

    image = img_repo.get_by_id(settings, image_id, consistent=True)
    assert image.status == "PENDING"

    # 3. Upload a part (small test data — LocalStack accepts any size)
    import boto3
    import io
    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    test_data = b"x" * (5 * 1024 * 1024)  # 5 MB minimum part size
    part_resp = s3_client.upload_part(
        Bucket=settings.originals_bucket,
        Key=s3_key,
        UploadId=upload_id,
        PartNumber=1,
        Body=io.BytesIO(test_data),
    )
    etag = part_resp["ETag"]
    img_repo.record_part(settings, image_id, 1, etag)

    # 4. Complete upload
    store_repo.finalize_upload(settings, s3_key, upload_id, [{"part_number": 1, "etag": etag}])
    img_repo.set_status(settings, image_id, "ACTIVE")

    # 5. Verify ACTIVE
    final = img_repo.get_by_id(settings, image_id, consistent=True)
    assert final.status == "ACTIVE"
    assert final.s3_key == s3_key

    # 6. List by user
    result = img_repo.list_by_user(settings, user_id, status_filter="ACTIVE", limit=10)
    assert any(item.image_id == image_id for item in result.items)

    # 7. Soft delete
    img_repo.soft_delete(settings, image_id)
    with pytest.raises(Exception):
        img_repo.get_by_id(settings, image_id)
