"""Regresiones para límites de confianza del agente."""

from pathlib import Path

import pytest

from tools.path_security import UnsafePathError, resolve_within


def test_resolve_within_accepts_relative_path(tmp_path):
    assert Path(resolve_within(tmp_path, "sub", "file.xlsx")) == tmp_path / "sub" / "file.xlsx"


@pytest.mark.parametrize("unsafe", ["../secret.txt", "sub/../../secret.txt"])
def test_resolve_within_rejects_traversal(tmp_path, unsafe):
    with pytest.raises(UnsafePathError):
        resolve_within(tmp_path, unsafe)


def test_resolve_within_rejects_absolute_path(tmp_path):
    with pytest.raises(UnsafePathError):
        resolve_within(tmp_path, tmp_path.parent / "secret.txt")


def test_local_copy_cannot_escape_configured_root(tmp_path, monkeypatch):
    from tools import local_tools

    server = tmp_path / "server"
    work = tmp_path / "work"
    server.mkdir()
    (tmp_path / "secret.xlsx").write_bytes(b"secret")
    monkeypatch.setattr(local_tools, "LOCAL_FILES_DIR", str(server))
    monkeypatch.setattr(local_tools, "WORK_DIR", str(work))

    result = local_tools.copy_from_local("secret.xlsx", "..")
    assert "ruta no permitida" in result
    assert not (work / "secret.xlsx").exists()


def test_sharepoint_operations_cannot_escape_root(tmp_path, monkeypatch):
    from tools import sharepoint_tools

    sharepoint = tmp_path / "sharepoint"
    sharepoint.mkdir()
    monkeypatch.setattr(sharepoint_tools, "SHAREPOINT_DIR", str(sharepoint))

    assert "ruta no permitida" in sharepoint_tools.crear_carpeta_sharepoint("../outside")
    assert not (tmp_path / "outside").exists()


def _tool_names(tools):
    return {tool["function"]["name"] for tool in tools}


def test_read_only_request_does_not_expose_mutating_tools():
    from tools.registry import _select_tools

    names = _tool_names(_select_tools(set(), "revisa los últimos correos"))
    assert "enviar_correo" not in names
    assert "guardar_en_sharepoint" not in names
    assert "reemplazar_en_tool" not in names


def test_explicit_send_request_exposes_email_tool():
    from tools.registry import _select_tools

    names = _tool_names(_select_tools(set(), "envía un correo a Nicole"))
    assert "enviar_correo" in names


def test_self_modification_is_rejected_even_if_dispatched():
    from tools.registry import _dispatch

    result = _dispatch(
        "reemplazar_en_tool",
        {"nombre_archivo": "agent.py", "texto_viejo": "a", "texto_nuevo": "b"},
    )
    assert "deshabilitada por seguridad" in result
