#!/usr/bin/env python3
"""Register a new user with password-based auth.

This script inserts a new row into the `accounts` table with a bcrypt
password hash. It avoids duplicate usernames because password login
resolves by username and would be ambiguous otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import sys
from pathlib import Path

# Ensure repo root is on sys.path when running from other working directories
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import bcrypt
from sqlalchemy.orm import sessionmaker

from sql_logic import sql_account as account
from limits import LIMITS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a new user with password authentication.",
    )
    parser.add_argument(
        "username",
        help="Username for login (must be unique).",
    )
    parser.add_argument(
        "--password",
        help="Password for login. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Grant admin rights to the new user.",
    )
    return parser.parse_args()


def prompt_password() -> str:
    while True:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Repeat password: ")
        if first != second:
            print("Passwords do not match. Try again.", file=sys.stderr)
            continue
        return first


def validate_username(username: str) -> None:
    if len(username) < LIMITS.profile.username_min:
        raise ValueError(f"Username must be at least {LIMITS.profile.username_min} characters.")
    if len(username) > LIMITS.profile.username_max:
        raise ValueError(f"Username must be at most {LIMITS.profile.username_max} characters.")


def validate_password(password: str) -> None:
    if len(password) < LIMITS.profile.password_min:
        raise ValueError(f"Password must be at least {LIMITS.profile.password_min} characters.")
    if len(password) > LIMITS.profile.password_max:
        raise ValueError(f"Password must be at most {LIMITS.profile.password_max} characters.")


def main() -> int:
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

    Session = sessionmaker(bind=account.engine)
    session = Session()
    try:
        existing = session.query(account.Account.id).filter_by(username=username).first()
        if existing:
            print(
                f"Username already exists (id={existing.id}). Choose another username.",
                file=sys.stderr,
            )
            return 1

        now = dt.datetime.now()
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(9)).decode(
            "utf-8"
        )

        new_user = account.Account(
            username=username,
            password_hash=password_hash,
            last_password_reset=now,
            registration_date=now,
            comments=0,
            author_mods=0,
            reputation=0,
            admin=bool(args.admin),
        )

        session.add(new_user)
        session.commit()

        print(f"Created user id={new_user.id} username={username}")
        return 0
    except Exception as exc:  # noqa: BLE001 - script tool, print error only
        session.rollback()
        print(f"Error creating user: {exc}", file=sys.stderr)
        return 3
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
