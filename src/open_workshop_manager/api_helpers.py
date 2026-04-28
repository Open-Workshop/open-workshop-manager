from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from open_workshop_manager.api_models import Pagination
from open_workshop_manager import standarts


def make_pagination(*, page: int, page_size: int, total: int) -> Pagination:
    offset = page * page_size
    has_previous = page > 0
    has_next = offset + page_size < total
    return Pagination(
        page=page,
        page_size=page_size,
        offset=offset,
        total=total,
        has_next=has_next,
        has_previous=has_previous,
    )


def make_list_response(items: list[Any], *, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {
        "items": items,
        "pagination": make_pagination(
            page=page,
            page_size=page_size,
            total=total,
        ).model_dump(mode="json", exclude_none=True),
    }


def ensure_non_empty_patch(payload: dict[str, Any]) -> None:
    if not any(value is not None for value in payload.values()):
        raise standarts.RequestRejectedError(
            detail="The request is empty",
        )


def unique_ints(values: Iterable[int | str]) -> list[int]:
    seen: set[int] = set()
    output: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        output.append(parsed)
    return output
