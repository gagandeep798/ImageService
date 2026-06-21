"""SQS consumer that generates thumbnail variants and strips EXIF metadata.

Triggered after an image transitions to ACTIVE.  For each image three variants
are produced (128px, 400px, 1200px).  EXIF data — which can contain GPS
coordinates, camera make/model, and owner information — is stripped from every
variant using Pillow's ``exif_transpose`` + JPEG re-save workflow.  Thumbnails
are stored in the thumbnails bucket with a 24-hour public cache header for
CloudFront edge caching.
"""
import io
import json

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from PIL import Image, ImageOps

from src.common.config import get_settings
from src.repositories import image_repository as img_repo
from src.repositories import storage_repository as store_repo

logger = Logger(service="image-service")
tracer = Tracer(service="image-service")
metrics = Metrics(namespace="ImageService")

VARIANTS: dict[str, tuple[int, int]] = {
    "128.jpg": (128, 128),
    "400.jpg": (400, 400),
    "1200.jpg": (1200, 900),
}


def _generate_thumbnail(data: bytes, size: tuple[int, int]) -> bytes:
    """Resize ``data`` to fit within ``size``, correct orientation, strip EXIF, and return JPEG bytes."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # correct orientation
    img.thumbnail(size, Image.LANCZOS)
    # Save without EXIF to strip location and camera metadata
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point — processes thumbnail generation requests from ThumbnailQueue."""
    settings = get_settings()

    for record in event.get("Records", []):
        body = json.loads(record.get("body", "{}"))
        image_id: str = body.get("image_id", "")

        if not image_id:
            continue

        try:
            image = img_repo.get_by_id(settings, image_id)
            raw_data = store_repo.get_object_bytes(settings, image.s3_key, max_bytes=20 * 1024 * 1024)

            thumbnail_keys: dict[str, str] = {}
            for variant_name, size in VARIANTS.items():
                thumb_data = _generate_thumbnail(raw_data, size)
                key = store_repo.put_thumbnail(settings, image_id, variant_name, thumb_data, "image/jpeg")
                thumbnail_keys[variant_name] = key

            img_repo.update_thumbnail_keys(settings, image_id, thumbnail_keys)
            logger.info("thumbnails_generated", image_id=image_id, variants=list(thumbnail_keys.keys()))

        except Exception as exc:
            logger.exception("Failed to generate thumbnails", image_id=image_id)
            raise

    return {"ok": True}
