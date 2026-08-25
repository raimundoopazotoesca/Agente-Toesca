"""Explicit local-user bootstrap command for the pilot workspace."""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from tools.analyst_workspace.store import ValidationError, WorkspaceStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create-user"])
    parser.add_argument("username")
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", choices=["admin", "user"], default="user")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    password = input() if args.password_stdin else getpass.getpass("Password: ")
    workspace = WorkspaceStore(Path(__file__).resolve().parents[2] / "memory" / "analyst_workspace.db")
    workspace.initialize()
    try:
        if args.role == "admin":
            workspace.set_initial_admin_password(args.username, password, args.display_name)
        else:
            workspace.create_user(args.username, args.display_name, password, args.role)
    except ValidationError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
