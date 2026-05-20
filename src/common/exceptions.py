"""Domain exceptions for the image service.

Each exception carries an HTTP status_code and a machine-readable error_code
so that the response envelope builder can produce consistent error payloads
without knowing HTTP semantics.
"""


class ImageServiceError(Exception):
    """Base class for all image-service domain errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"


class NotFoundError(ImageServiceError):
    """Raised when a requested resource does not exist or has been soft-deleted."""

    status_code = 404
    error_code = "NOT_FOUND"


class ForbiddenError(ImageServiceError):
    """Raised when the caller lacks permission to perform the requested action."""

    status_code = 403
    error_code = "FORBIDDEN"


class ValidationError(ImageServiceError):
    """Raised when incoming request data fails validation (bad content type, missing field, etc.)."""

    status_code = 400
    error_code = "VALIDATION_ERROR"


class QuotaExceededError(ImageServiceError):
    """Raised when an upload would push the user's storage_used_bytes past their quota."""

    status_code = 402
    error_code = "QUOTA_EXCEEDED"


class ConflictError(ImageServiceError):
    """Raised when an operation conflicts with the current resource state."""

    status_code = 409
    error_code = "CONFLICT"


class UploadAbortedError(ImageServiceError):
    """Raised when an operation is attempted on an upload that has been aborted."""

    status_code = 400
    error_code = "UPLOAD_ABORTED"
