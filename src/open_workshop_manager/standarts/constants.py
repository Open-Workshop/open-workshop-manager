from __future__ import annotations

from typing import Final

HTTP_STATUS_TITLES: Final[dict[int, str]] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    410: "Gone",
    412: "Precondition Failed",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}

HTTP_STATUS_TITLES_RU: Final[dict[int, str]] = HTTP_STATUS_TITLES

STANDARD_PROBLEM_TYPE: Final[str] = "about:blank"
STANDARD_PROBLEM_MEDIA_TYPE: Final[str] = "application/problem+json"

DEFAULT_UNAUTHORIZED_DETAIL: Final[str] = "Unauthorized."
DEFAULT_FORBIDDEN_DETAIL: Final[str] = "Forbidden."
DEFAULT_ADMIN_FORBIDDEN_DETAIL: Final[str] = "Admin privileges required."
DEFAULT_INTERNAL_SERVER_ERROR_DETAIL: Final[str] = "Internal server error."

VALIDATION_ERROR_DETAIL: Final[str] = "Validation error."
VALIDATION_ERROR_CODE: Final[str] = "VALIDATION_ERROR"

UNSUPPORTED_OWNER_TYPE_TITLE: Final[str] = "Bad Request"
UNSUPPORTED_OWNER_TYPE_DETAIL: Final[str] = "Unsupported owner_type."
UNSUPPORTED_OWNER_TYPE_CODE: Final[str] = "OWNER_TYPE_UNSUPPORTED"

AVATAR_DELETION_FAILED_TITLE: Final[str] = "Bad Gateway"
AVATAR_DELETION_FAILED_DETAIL: Final[str] = "Failed to delete avatar."
AVATAR_DELETION_FAILED_CODE: Final[str] = "AVATAR_DELETE_FAILED"
