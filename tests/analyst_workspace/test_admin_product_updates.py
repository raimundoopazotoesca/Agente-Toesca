"""Admin CLI for publishing/archiving Novedades entries.

Scope: tools/analyst_workspace/admin.py's create-product-update and
deactivate-product-update subcommands only. No in-product CMS/write path
exists -- publishing is CLI/store-only, matching the pattern used by
create-user/reset-password in this same module.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from tools.analyst_workspace.store import WorkspaceStore


def _wired_admin_module(tmp_path, monkeypatch):
    workspace_db = tmp_path / "memory" / "analyst_workspace.db"
    store = WorkspaceStore(workspace_db)
    store.initialize()
    monkeypatch.setattr(
        "tools.analyst_workspace.admin.__file__",
        str(tmp_path / "tools" / "analyst_workspace" / "admin.py"),
    )
    admin_module = importlib.import_module("tools.analyst_workspace.admin")
    return admin_module, store


def test_cli_creates_a_published_product_update(tmp_path, monkeypatch, capsys):
    admin_module, store = _wired_admin_module(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", [
        "admin.py", "create-product-update",
        "--title", "Reportar problema",
        "--body", "Ahora puedes reportar una respuesta.",
        "--cta-label", "Volver al chat",
        "--cta-target", "/analyst",
        "--publish",
    ])

    exit_code = admin_module.main()

    assert exit_code == 0
    update_id = capsys.readouterr().out.strip()
    assert update_id
    update = store.get_product_update(update_id)
    assert update.title == "Reportar problema"
    assert update.published_at is not None
    assert update.active is True
    assert update.cta_label == "Volver al chat"
    assert update.cta_config == {"type": "route", "value": "/analyst"}


def test_cli_creates_a_draft_when_publish_flag_omitted(tmp_path, monkeypatch, capsys):
    admin_module, store = _wired_admin_module(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", [
        "admin.py", "create-product-update", "--title", "Projects", "--body", "Próximamente.",
    ])

    exit_code = admin_module.main()

    assert exit_code == 0
    update_id = capsys.readouterr().out.strip()
    update = store.get_product_update(update_id)
    assert update.published_at is None
    user_id = store.create_user("alice", "Alice", "password-a")
    assert store.list_product_updates_for_user(user_id) == []


def test_cli_infers_chat_prompt_cta_type_without_leading_slash(tmp_path, monkeypatch, capsys):
    admin_module, store = _wired_admin_module(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", [
        "admin.py", "create-product-update",
        "--title", "Prueba una comparación",
        "--body", "Compara dos activos en una sola pregunta.",
        "--cta-label", "Probar ahora",
        "--cta-target", "Compara Parque Titanium y Apoquindo",
        "--publish",
    ])

    exit_code = admin_module.main()

    assert exit_code == 0
    update_id = capsys.readouterr().out.strip()
    update = store.get_product_update(update_id)
    assert update.cta_config == {"type": "chat_prompt", "value": "Compara Parque Titanium y Apoquindo"}


def test_cli_deactivates_an_update(tmp_path, monkeypatch, capsys):
    admin_module, store = _wired_admin_module(tmp_path, monkeypatch)
    update = store.create_product_update("Title", "Body", publish=True)
    user_id = store.create_user("alice", "Alice", "password-a")
    assert len(store.list_product_updates_for_user(user_id)) == 1

    monkeypatch.setattr(sys, "argv", ["admin.py", "deactivate-product-update", update.id])
    exit_code = admin_module.main()

    assert exit_code == 0
    assert store.list_product_updates_for_user(user_id) == []
    assert store.get_product_update(update.id).active is False
