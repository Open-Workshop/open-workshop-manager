from __future__ import annotations

from http import HTTPStatus

from .constants import HTTP_STATUS_TITLES_RU


def status_title(status_code: int) -> str:
    title = HTTP_STATUS_TITLES_RU.get(status_code)
    if title is not None:
        return title

    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return f"HTTP {status_code}"


def status_code_name(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).name.lower()
    except ValueError:
        return f"http_{status_code}"
