#!/usr/bin/env python3
"""Change an existing user's password.

This script updates the bcrypt password hash for an existing user and
invalidates that user's active sessions so the new password takes effect
immediately.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import getpass
import sys
from pathlib import Path

# Ensure repo root and src are on sys.path when running from other working directories
ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import bcrypt  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

from open_workshop_manager.limits import LIMITS  # noqa: E402
from open_workshop_manager.sql_logic import sql_account as account  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Change the password for an existing user.",
    )
    parser.add_argument(
        "username",
        help="Username whose password should be updated.",
    )
    parser.add_argument(
        "--password",
        help="New password. If omitted, you will be prompted.",
    )
    return parser.parse_args()


def prompt_password() -> str:
    while True:
        first = getpass.getpass("New password: ")
        second = getpass.getpass("Repeat new password: ")
        if first != second:
            print("Passwords do not match. Try again.", file=sys.stderr)
            continue
        return first


def validate_username(username: str) -> None:
    if len(username) < LIMITS.profile.username_min:
        raise ValueError(
            f"Username must be at least {LIMITS.profile.username_min} characters."
        )
    if len(username) > LIMITS.profile.username_max:
        raise ValueError(
            f"Username must be at most {LIMITS.profile.username_max} characters."
        )


def validate_password(password: str) -> None:
    if len(password) < LIMITS.profile.password_min:
        raise ValueError(
            f"Password must be at least {LIMITS.profile.password_min} characters."
        )
    if len(password) > LIMITS.profile.password_max:
        raise ValueError(
            f"Password must be at most {LIMITS.profile.password_max} characters."
        )


async def main() -> int:
    args = parse_args()

    username = args.username.strip()
    try:
        validate_username(username)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    password = args.password or prompt_password()
    try:
        validate_password(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    session = account.AsyncSessionLocal()
    try:
        result = await session.execute(
            select(account.Account).where(account.Account.username == username)
        )
        users = result.scalars().all()
        if not users:
            print(
                f"User not found for username={username!r}.",
                file=sys.stderr,
            )
            return 1
        if len(users) > 1:
            print(
                f"Multiple users found for username={username!r}. "
                "Use a unique username or clean up duplicate records first.",
                file=sys.stderr,
            )
            return 1

        user = users[0]

        now = dt.datetime.now()
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(9)
        ).decode("utf-8")

        user.password_hash = password_hash
        user.last_password_reset = now

        revoked_sessions_result = await session.execute(
            update(account.Session)
            .where(account.Session.owner_id == user.id, account.Session.broken.is_(None))
            .values(broken="password changed")
        )
        revoked_sessions = int(getattr(revoked_sessions_result, "rowcount", 0) or 0)

        await session.commit()

        print(
            f"Updated password for user id={user.id} username={username}; "
            f"invalidated {revoked_sessions} active session(s)."
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - script tool, print error only
        await session.rollback()
        print(f"Error changing password: {exc}", file=sys.stderr)
        return 3
    finally:
        await session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
