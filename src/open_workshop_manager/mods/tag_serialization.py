"""Shared tag serialization helpers."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.exc import NoInspectionAvailable

from open_workshop_manager.api_models import TagGroupRead, TagRead
from open_workshop_manager.sql_logic import sql_catalog as catalog


def serialize_tag_group(group: catalog.TagGroup) -> TagGroupRead:
    return TagGroupRead(id=int(group.id), name=str(group.name))


def serialize_tag(tag: catalog.Tag) -> TagRead:
    group = _loaded_group(tag)
    return TagRead(
        id=int(tag.id),
        name=str(tag.name),
        group=serialize_tag_group(group) if group is not None else None,
    )


def _loaded_group(tag: catalog.Tag) -> catalog.TagGroup | None:
    try:
        state = inspect(tag)
    except NoInspectionAvailable:
        return getattr(tag, "group", None)

    if "group" in state.unloaded:
        return None
    return getattr(tag, "group", None)
