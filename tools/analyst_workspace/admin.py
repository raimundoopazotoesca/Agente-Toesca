"""Explicit local-user bootstrap and administration commands for the pilot
workspace.

``reset-password`` is a plain administrative store operation: it never
requires the caller to be an authenticated admin session, never touches
role/is_active/ownership, and has no HTTP-exposed counterpart -- no
forgot-password/email flow exists or is intended here.
"""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from tools.analyst_workspace.store import ValidationError, WorkspaceStore


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", choices=["admin", "user"], default="user")
    create.add_argument("--password-stdin", action="store_true")

    reset = subparsers.add_parser("reset-password")
    reset.add_argument("username")
    reset.add_argument("--password-stdin", action="store_true")

    args = parser.parse_args()
    password = input() if args.password_stdin else getpass.getpass("Password: ")
    workspace = WorkspaceStore(Path(__file__).resolve().parents[2] / "memory" / "analyst_workspace.db")
    workspace.initialize()
    try:
        if args.command == "create-user":
            if args.role == "admin":
                workspace.set_initial_admin_password(args.username, password, args.display_name)
            else:
                workspace.create_user(args.username, args.display_name, password, args.role)
        else:
            workspace.reset_user_password(args.username, password)
    except ValidationError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
