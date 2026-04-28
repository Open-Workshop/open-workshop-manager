from __future__ import annotations

from http import HTTPStatus

from .constants import HTTP_STATUS_TITLES


def status_title(status_code: int) -> str:
    title = HTTP_STATUS_TITLES.get(status_code)
    if title is not None:
        return title

    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return f"HTTP {status_code}"


def status_code_name(status_code: int) -> str:
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        410: "GONE",
        412: "PRECONDITION_FAILED",
        422: "VALIDATION_ERROR",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }
    if status_code in mapping:
        return mapping[status_code]

    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return f"HTTP_{status_code}"
