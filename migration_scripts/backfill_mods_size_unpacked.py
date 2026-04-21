#!/usr/bin/env python3
"""Backfill mods.size_unpacked using HEAD metadata from Storage.

Flow:
1) Find mods where size_unpacked IS NULL and condition = 0.
2) HEAD storage /download/archive/mods/{mod_id}/main.zip.
3) Read unpacked bytes header and update DB.
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

import aiohttp
from sqlalchemy import select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from open_workshop_manager import settings as config  # noqa: E402
from open_workshop_manager.sql_logic import sql_catalog as catalog  # noqa: E402

DEFAULT_UNPACKED_HEADERS = (
    "X-Unpacked-Bytes",
    "X-Archive-Unpacked-Bytes",
    "X-OW-Unpacked-Bytes",
)


@dataclass(slots=True)
class ProbeResult:
    mod_id: int
    status: str
    unpacked_bytes: Optional[int] = None
    http_status: Optional[int] = None
    details: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill mods.size_unpacked via Storage HEAD requests.",
    )
    parser.add_argument(
        "--storage-base",
        default=os.environ.get("OW_STORAGE_URL", getattr(config, "STORAGE_URL", "")).rstrip("/"),
        help="Storage base URL (default: OW_STORAGE_URL or package settings STORAGE_URL).",
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
        help="Limit number of mods to process (0 = no limit).",
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


async def load_mod_ids(limit: int) -> list[int]:
    async with catalog.AsyncSessionLocal() as session:
        query = (
            select(catalog.Mod.id)
            .where(catalog.Mod.condition == 0)
            .where(catalog.Mod.size_unpacked.is_(None))
            .order_by(catalog.Mod.id.asc())
        )
        if limit > 0:
            query = query.limit(limit)
        result = await session.execute(query)
        return [int(mod_id) for mod_id in result.scalars().all()]


async def flush_updates(rows: list[dict[str, int]], dry_run: bool) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)

    async with catalog.AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE mods "
                "SET size_unpacked=:size_unpacked "
                "WHERE id=:id AND size_unpacked IS NULL"
            ),
            rows,
        )
        await session.commit()
        return len(rows)


def _parse_positive_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


async def probe_mod(
    session: aiohttp.ClientSession,
    storage_base: str,
    mod_id: int,
    semaphore: asyncio.Semaphore,
) -> ProbeResult:
    url = f"{storage_base}/download/archive/mods/{mod_id}/main.zip"
    async with semaphore:
        try:
            async with session.head(url, allow_redirects=True) as response:
                status = response.status
                if status == 404:
                    return ProbeResult(
                        mod_id=mod_id,
                        status="not_found",
                        http_status=status,
                        details="archive missing",
                    )
                if status in (401, 403):
                    return ProbeResult(
                        mod_id=mod_id,
                        status="forbidden",
                        http_status=status,
                        details="access denied",
                    )
                if status >= 400:
                    return ProbeResult(
                        mod_id=mod_id,
                        status="http_error",
                        http_status=status,
                        details=f"status={status}",
                    )

                unpacked: Optional[int] = None
                unpacked_header = ""
                for key in DEFAULT_UNPACKED_HEADERS:
                    candidate = _parse_positive_int(response.headers.get(key))
                    if candidate is not None:
                        unpacked = candidate
                        unpacked_header = key
                        break

                if unpacked is None:
                    return ProbeResult(
                        mod_id=mod_id,
                        status="header_missing",
                        http_status=status,
                        details="unpacked size header is missing",
                    )

                return ProbeResult(
                    mod_id=mod_id,
                    status="ok",
                    unpacked_bytes=unpacked,
                    http_status=status,
                    details=f"header={unpacked_header}",
                )
        except asyncio.TimeoutError:
            return ProbeResult(mod_id=mod_id, status="timeout", details="request timeout")
        except aiohttp.ClientError as exc:
            return ProbeResult(mod_id=mod_id, status="client_error", details=str(exc))


async def run(args: argparse.Namespace) -> int:
    storage_base = ensure_value("storage-base", args.storage_base)

    mod_ids = await load_mod_ids(args.limit)
    total = len(mod_ids)
    if total == 0:
        logging.info("No mods with NULL size_unpacked found")
        return 0

    logging.info(
        "Start mods size_unpacked migration: total=%s concurrency=%s dry_run=%s",
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
        "not_found": 0,
        "forbidden": 0,
        "header_missing": 0,
        "timeout": 0,
        "client_error": 0,
        "http_error": 0,
    }

    semaphore = asyncio.Semaphore(max(1, int(args.concurrency)))

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            asyncio.create_task(
                probe_mod(
                    session=session,
                    storage_base=storage_base,
                    mod_id=mod_id,
                    semaphore=semaphore,
                )
            )
            for mod_id in mod_ids
        ]

        for future in asyncio.as_completed(tasks):
            result = await future
            processed += 1
            counters[result.status] = counters.get(result.status, 0) + 1

            if result.status == "ok" and result.unpacked_bytes is not None:
                pending_updates.append(
                    {"id": result.mod_id, "size_unpacked": int(result.unpacked_bytes)}
                )
                logging.info(
                    "MOD %s -> unpacked=%s (%s)",
                    result.mod_id,
                    result.unpacked_bytes,
                    result.details,
                )
            else:
                logging.warning(
                    "MOD %s -> %s (http=%s details=%s)",
                    result.mod_id,
                    result.status,
                    result.http_status,
                    result.details,
                )

            if len(pending_updates) >= max(1, int(args.batch_size)):
                updated += await flush_updates(pending_updates, args.dry_run)
                pending_updates.clear()

            if processed % 100 == 0 or processed == total:
                logging.info(
                    "Progress: %s/%s processed, updated=%s",
                    processed,
                    total,
                    updated,
                )

    if pending_updates:
        updated += await flush_updates(pending_updates, args.dry_run)
        pending_updates.clear()

    logging.info(
        "Done mods size_unpacked migration: total=%s updated=%s counters=%s",
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
