"""DELETE /users/{user_id} — GDPR right to erasure (Article 17).

Paginates through all images owned by the user and soft-deletes each one using
the delete-tier DynamoDB resource, then marks the user record as DELETED with
``gdpr_erased_at`` set — also through the delete-tier resource.

S3 objects are removed asynchronously via DynamoDB Streams + TTL.

Accessible by the user themselves (self-erasure) or an admin.  The erasure
event is logged via CloudTrail for legal compliance — the log contains only
``user_id`` (a system identifier) and timestamps, not personal data.
"""
from datetime import datetime, timezone

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from src.common.config import get_settings
from src.common.exceptions import ForbiddenError, ImageServiceError
from src.common.middleware import get_caller_user_id, get_request_id, is_admin
from src.common import response as resp
from src.repositories import image_repository as img_repo
from src.repositories import user_repository as user_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:  # noqa: ARG001
    """Lambda entry point for DELETE /users/{user_id}.

    Returns 200 with ``{user_id, erased_at, images_deleted}``.
    Both image soft-deletes and the user record update go through the
    delete-tier DynamoDB resource (restricted IAM role).
    """
    settings = get_settings()
    request_id = get_request_id(event)

    try:
        caller_id = get_caller_user_id(event)
        user_id = event["pathParameters"]["user_id"]

        if user_id != caller_id and not is_admin(event):
            raise ForbiddenError("Access denied")

        # Paginate and soft-delete all images via delete-tier resource
        deleted_count = 0
        cursor = None
        while True:
            result = img_repo.list_by_user(settings, user_id, status_filter=None, limit=100, cursor=cursor)
            for item in result.items:
                img_repo.soft_delete(settings, item.image_id)
                deleted_count += 1
            cursor = result.next_cursor
            if not cursor:
                break

        # Erase user record via delete-tier resource (gdpr=True sets gdpr_erased_at + 90-day TTL)
        user_repo.soft_delete_user(settings, user_id, gdpr=True)

        now = datetime.now(timezone.utc).isoformat()
        logger.info("gdpr_erasure_complete", user_id=user_id, images_deleted=deleted_count)

        return resp.ok({"user_id": user_id, "erased_at": now, "images_deleted": deleted_count}, request_id)

    except ImageServiceError as exc:
        return resp.error(exc, request_id)
    except Exception as exc:
        logger.exception("Unhandled error in gdpr_delete_user")
        return resp.error(exc, request_id)
