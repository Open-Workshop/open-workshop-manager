#!/usr/bin/env python3
"""Backfill resources.size using HEAD metadata from Storage.

Flow:
1) Find resources where size IS NULL.
2) For local resources (url starts with local/), HEAD storage /download/resource/{path}.
3) Read Content-Length and update DB.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import aiohttp
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import ow_config as config  # noqa: E402
from sql_logic import sql_catalog as catalog  # noqa: E402


@dataclass(slots=True)
class ResourceProbeResult:
    resource_id: int
    status: str
    size_bytes: Optional[int] = None
    http_status: Optional[int] = None
    details: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill resources.size via Storage HEAD requests.",
    )
    parser.add_argument(
        "--storage-base",
        default=os.environ.get("OW_STORAGE_URL", getattr(config, "STORAGE_URL", "")).rstrip("/"),
        help="Storage base URL (default: OW_STORAGE_URL or ow_config.STORAGE_URL).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("OW_MIGRATION_CONCURRENCY", "200")),
        help="Concurrent HEAD requests (default: 200).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("OW_MIGRATION_TIMEOUT", "30")),
        help="HTTP timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of resources to process (0 = no limit).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="DB update batch size (default: 500).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe only, do not write DB.",
    )
    return parser.parse_args()


def ensure_value(name: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"Missing required value: {name}")
    return value


def load_resources(limit: int) -> list[tuple[int, str]]:
    session = sessionmaker(bind=catalog.engine)()
    try:
        query = (
            session.query(catalog.Resource.id, catalog.Resource.url)
            .filter(catalog.Resource.size.is_(None))
            .order_by(catalog.Resource.id.asc())
        )
        if limit > 0:
            query = query.limit(limit)
        return [(int(row.id), str(row.url or "")) for row in query.all()]
    finally:
        session.close()


def flush_updates(rows: list[dict[str, int]], dry_run: bool) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)

    session = sessionmaker(bind=catalog.engine)()
    try:
        session.execute(
            text(
                "UPDATE resources "
                "SET size=:size "
                "WHERE id=:id AND size IS NULL"
            ),
            rows,
        )
        session.commit()
        return len(rows)
    finally:
        session.close()


def _parse_non_negative(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


async def probe_resource(
    session: aiohttp.ClientSession,
    storage_base: str,
    resource_id: int,
    resource_url: str,
    semaphore: asyncio.Semaphore,
) -> ResourceProbeResult:
    if not resource_url.startswith("local/"):
        return ResourceProbeResult(
            resource_id=resource_id,
            status="non_local",
            details="external resource URL",
        )

    rel_path = resource_url.replace("local/", "", 1)
    encoded_rel_path = quote(rel_path, safe="/")
    url = f"{storage_base}/download/resource/{encoded_rel_path}"

    async with semaphore:
        try:
            async with session.head(url, allow_redirects=True) as response:
                status = response.status
                if status == 404:
                    return ResourceProbeResult(
                        resource_id=resource_id,
                        status="not_found",
                        http_status=status,
                        details=rel_path,
                    )
                if status >= 400:
                    return ResourceProbeResult(
                        resource_id=resource_id,
                        status="http_error",
                        http_status=status,
                        details=f"status={status}",
                    )

                content_length = _parse_non_negative(response.headers.get("Content-Length"))
                if content_length is None:
                    return ResourceProbeResult(
                        resource_id=resource_id,
                        status="header_missing",
                        http_status=status,
                        details="Content-Length missing",
                    )

                return ResourceProbeResult(
                    resource_id=resource_id,
                    status="ok",
                    size_bytes=content_length,
                    http_status=status,
                    details=rel_path,
                )
        except asyncio.TimeoutError:
            return ResourceProbeResult(
                resource_id=resource_id,
                status="timeout",
                details="request timeout",
            )
        except aiohttp.ClientError as exc:
            return ResourceProbeResult(
                resource_id=resource_id,
                status="client_error",
                details=str(exc),
            )


async def run(args: argparse.Namespace) -> int:
    storage_base = ensure_value("storage-base", args.storage_base)

    resources = load_resources(args.limit)
    total = len(resources)
    if total == 0:
        logging.info("No resources with NULL size found")
        return 0

    logging.info(
        "Start resources size migration: total=%s concurrency=%s dry_run=%s",
        total,
        args.concurrency,
        args.dry_run,
    )

    timeout = aiohttp.ClientTimeout(total=max(float(args.timeout), 1.0))

    updated = 0
    processed = 0
    pending_updates: list[dict[str, int]] = []

    counters = {
        "ok": 0,
        "non_local": 0,
        "not_found": 0,
        "header_missing": 0,
        "timeout": 0,
        "client_error": 0,
        "http_error": 0,
    }

    semaphore = asyncio.Semaphore(max(1, int(args.concurrency)))

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            asyncio.create_task(
                probe_resource(
                    session=session,
                    storage_base=storage_base,
                    resource_id=resource_id,
                    resource_url=resource_url,
                    semaphore=semaphore,
                )
            )
            for resource_id, resource_url in resources
        ]

        for future in asyncio.as_completed(tasks):
            result = await future
            processed += 1
            counters[result.status] = counters.get(result.status, 0) + 1

            if result.status == "ok" and result.size_bytes is not None:
                pending_updates.append({"id": result.resource_id, "size": int(result.size_bytes)})
                logging.info(
                    "RESOURCE %s -> size=%s (%s)",
                    result.resource_id,
                    result.size_bytes,
                    result.details,
                )
            elif result.status == "non_local":
                logging.info(
                    "RESOURCE %s -> skip non-local (%s)",
                    result.resource_id,
                    result.details,
                )
            else:
                logging.warning(
                    "RESOURCE %s -> %s (http=%s details=%s)",
                    result.resource_id,
                    result.status,
                    result.http_status,
                    result.details,
                )

            if len(pending_updates) >= max(1, int(args.batch_size)):
                updated += flush_updates(pending_updates, args.dry_run)
                pending_updates.clear()

            if processed % 100 == 0 or processed == total:
                logging.info(
                    "Progress: %s/%s processed, updated=%s",
                    processed,
                    total,
                    updated,
                )

    if pending_updates:
        updated += flush_updates(pending_updates, args.dry_run)
        pending_updates.clear()

    logging.info(
        "Done resources size migration: total=%s updated=%s counters=%s",
        total,
        updated,
        counters,
    )
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        args = parse_args()
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        logging.warning("Interrupted by user")
        return 130
    except Exception as exc:  # noqa: BLE001
        logging.exception("Migration failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
