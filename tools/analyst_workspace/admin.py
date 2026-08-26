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

from tools.analyst_workspace.store import ProductUpdateNotFoundError, ValidationError, WorkspaceStore


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

    grant = subparsers.add_parser("grant-capability")
    grant.add_argument("username")
    grant.add_argument("capability")

    revoke = subparsers.add_parser("revoke-capability")
    revoke.add_argument("username")
    revoke.add_argument("capability")

    create_update = subparsers.add_parser(
        "create-product-update",
        help="Create a Novedades entry (product discovery feed). Draft by default; pass --publish to make it visible.",
    )
    create_update.add_argument("--title", required=True)
    create_update.add_argument("--body", required=True)
    create_update.add_argument("--cta-label", help="Optional CTA button text, e.g. 'Volver al chat'")
    create_update.add_argument(
        "--cta-target",
        help="Optional CTA target: an existing route (starts with '/') or an example chat prompt string.",
    )
    create_update.add_argument(
        "--cta-type", choices=["route", "chat_prompt"],
        help="Force how --cta-target is interpreted; inferred from a leading '/' when omitted.",
    )
    create_update.add_argument("--publish", action="store_true", help="Publish immediately (visible to users right away).")

    deactivate_update = subparsers.add_parser(
        "deactivate-product-update", help="Archive/hide a Novedades entry so it no longer appears to users.",
    )
    deactivate_update.add_argument("update_id")

    args = parser.parse_args()
    workspace = WorkspaceStore(Path(__file__).resolve().parents[2] / "memory" / "analyst_workspace.db")
    workspace.initialize()
    try:
        if args.command in {"create-user", "reset-password"}:
            password = input() if args.password_stdin else getpass.getpass("Password: ")
            if args.command == "create-user":
                if args.role == "admin":
                    workspace.set_initial_admin_password(args.username, password, args.display_name)
                else:
                    workspace.create_user(args.username, args.display_name, password, args.role)
            else:
                workspace.reset_user_password(args.username, password)
        elif args.command in {"grant-capability", "revoke-capability"}:
            user_id = workspace.get_user_id_by_username(args.username)
            if args.command == "grant-capability":
                workspace.grant_capability(user_id, args.capability)
            else:
                workspace.revoke_capability(user_id, args.capability)
        elif args.command == "create-product-update":
            cta_config = None
            if args.cta_target:
                cta_type = args.cta_type or ("route" if args.cta_target.startswith("/") else "chat_prompt")
                cta_config = {"type": cta_type, "value": args.cta_target}
            update = workspace.create_product_update(
                args.title, args.body, cta_label=args.cta_label, cta_config=cta_config, publish=args.publish,
            )
            print(update.id)
        elif args.command == "deactivate-product-update":
            workspace.deactivate_product_update(args.update_id)
    except (ValidationError, ProductUpdateNotFoundError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
