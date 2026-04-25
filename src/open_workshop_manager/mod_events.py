"""NATS JetStream publisher for mod lifecycle events."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from open_workshop_manager import settings as config

logger = logging.getLogger(__name__)

MOD_EVENT_ADDED = "added"
MOD_EVENT_CHANGED = "changed"
MOD_EVENT_DELETED = "deleted"
MOD_EVENT_TYPES = {MOD_EVENT_ADDED, MOD_EVENT_CHANGED, MOD_EVENT_DELETED}

_nats_client: Any | None = None
_jetstream: Any | None = None


def _subject_prefix() -> str:
    prefix = str(getattr(config, "NATS_MOD_EVENTS_SUBJECT_PREFIX", "mods") or "mods")
    return prefix.strip(". ") or "mods"


def _subject_for(event_type: str) -> str:
    return f"{_subject_prefix()}.{event_type}"


def _stream_subjects() -> list[str]:
    return [_subject_for(event_type) for event_type in sorted(MOD_EVENT_TYPES)]


def _nats_servers() -> list[str]:
    servers: list[str] = []
    url = str(getattr(config, "NATS_URL", "") or "").strip()
    if url:
        servers.append(url)

    configured_urls = getattr(config, "NATS_URLS", []) or []
    for item in configured_urls:
        server = str(item or "").strip()
        if server:
            servers.append(server)

    return list(dict.fromkeys(servers))


def _enabled() -> bool:
    return bool(getattr(config, "NATS_MOD_EVENTS_ENABLED", False))


def _required() -> bool:
    return bool(getattr(config, "NATS_MOD_EVENTS_REQUIRED", False))


def _build_payload(
    event_type: str,
    mod_id: int,
    title: str | None,
    full_description: str | None,
) -> dict[str, object]:
    if event_type not in MOD_EVENT_TYPES:
        raise ValueError(f"Unsupported mod event type: {event_type}")

    return {
        "event": f"mod.{event_type}",
        "id": int(mod_id),
        "title": title or "",
        "full_description": full_description or "",
        "occurred_at": datetime.now(UTC).isoformat(),
    }


async def start() -> None:
    """Connect to NATS and ensure the JetStream stream exists when enabled."""
    global _jetstream, _nats_client

    if not _enabled():
        logger.info("NATS mod events disabled")
        return

    servers = _nats_servers()
    if not servers:
        message = "NATS mod events enabled but no NATS_URL or NATS_URLS configured"
        if _required():
            raise RuntimeError(message)
        logger.warning(message)
        return

    try:
        import nats
        from nats.js.errors import NotFoundError
    except ModuleNotFoundError:
        message = "nats-py is not installed; NATS mod events are unavailable"
        if _required():
            raise RuntimeError(message)
        logger.exception(message)
        return

    try:
        _nats_client = await nats.connect(
            servers=servers,
            connect_timeout=float(getattr(config, "NATS_CONNECT_TIMEOUT_SECONDS", 2)),
            name="open-workshop-manager",
        )
        _jetstream = _nats_client.jetstream()

        stream_name = str(getattr(config, "NATS_MOD_EVENTS_STREAM", "MOD_EVENTS"))
        try:
            await _jetstream.stream_info(stream_name)
        except NotFoundError:
            await _jetstream.add_stream(name=stream_name, subjects=_stream_subjects())

        logger.info(
            "NATS mod events ready stream=%s subjects=%s",
            stream_name,
            _stream_subjects(),
        )
    except Exception:
        _jetstream = None
        if _nats_client is not None:
            try:
                await _nats_client.close()
            except Exception:
                logger.exception("Failed to close NATS client after startup error")
            _nats_client = None
        if _required():
            raise
        logger.exception("NATS mod events startup failed")


async def stop() -> None:
    """Close the NATS connection if it was opened."""
    global _jetstream, _nats_client

    client = _nats_client
    _jetstream = None
    _nats_client = None
    if client is None:
        return

    try:
        await client.drain()
    except Exception:
        logger.exception("Failed to drain NATS client")
        try:
            await client.close()
        except Exception:
            logger.exception("Failed to close NATS client")


async def publish_mod_event(
    event_type: str,
    mod_id: int,
    title: str | None,
    full_description: str | None,
) -> None:
    """Publish a mod lifecycle event to JetStream."""
    if not _enabled():
        return

    if _jetstream is None:
        message = "NATS mod event skipped because publisher is not connected"
        if _required():
            raise RuntimeError(message)
        logger.warning("%s event=%s mod_id=%s", message, event_type, mod_id)
        return

    payload = _build_payload(
        event_type=event_type,
        mod_id=mod_id,
        title=title,
        full_description=full_description,
    )
    encoded_payload = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    subject = _subject_for(event_type)
    stream_name = str(getattr(config, "NATS_MOD_EVENTS_STREAM", "MOD_EVENTS"))

    try:
        ack = await _jetstream.publish(
            subject,
            encoded_payload,
            timeout=float(getattr(config, "NATS_PUBLISH_TIMEOUT_SECONDS", 2)),
            stream=stream_name,
        )
        logger.debug(
            "NATS mod event published event=%s mod_id=%s stream=%s seq=%s",
            event_type,
            mod_id,
            getattr(ack, "stream", stream_name),
            getattr(ack, "seq", None),
        )
    except Exception:
        if _required():
            raise
        logger.exception(
            "NATS mod event publish failed event=%s mod_id=%s subject=%s",
            event_type,
            mod_id,
            subject,
        )
