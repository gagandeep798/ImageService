"""Direct-invocation handler that generates thumbnail variants and strips EXIF metadata.

Invoked asynchronously by ScanCompleteFunction with payload ``{image_id}``.
Produces three JPEG variants (128px, 400px, 1200px) with EXIF stripped.
Thumbnails are stored in the thumbnails bucket with a 24-hour cache header.
"""
import io

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
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img.thumbnail(size, Image.LANCZOS)
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    """Lambda entry point — generates thumbnails for a single image."""
    settings = get_settings()
    image_id: str = event.get("image_id", "")

    if not image_id:
        return {"ok": False, "error": "missing image_id"}

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

    except Exception:
        logger.exception("Failed to generate thumbnails", image_id=image_id)
        raise

    return {"ok": True}
