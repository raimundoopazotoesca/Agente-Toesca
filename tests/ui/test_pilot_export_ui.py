"""Playwright UI tests for the two PILOT EXPORT v1 download buttons:

- "Descargar reportes (.md)" on /pilot-feedback
- "Descargar seleccionadas (.md)" on /pilot-control (Conversaciones tab)

Mirrors the server/fixture pattern of tests/ui/test_pilot_feedback.py (a real
werkzeug server against a real temp-file WorkspaceStore).
"""
from __future__ import annotations

from contextlib import contextmanager
from threading import Thread

import pytest
from werkzeug.serving import make_server

from scripts import ingesta_server
from tools.analyst_runtime.session import AnalystSessionResult
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import WorkspaceStore

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


class _Session:
    def ask(self, text):
        return AnalystSessionResult(f"Respuesta: {text}")


class _Factory:
    def create(self, *_args, **_kwargs):
        return _Session()


@contextmanager
def _server(monkeypatch, tmp_path):
    workspace_path = tmp_path / "workspace.db"
    workspace = WorkspaceStore(workspace_path)
    workspace.initialize()
    workspace.create_user("raimundo", "Raimundo", "password")
    reviewer_id = workspace.create_user("reviewer", "Revisor", "password")
    workspace.grant_capability(reviewer_id, "feedback_reviewer")
    observer_id = workspace.create_user("observer", "Observador", "password")
    workspace.grant_capability(observer_id, "pilot_observer")

    monkeypatch.setitem(ingesta_server.app.config, "TESTING", False)
    monkeypatch.setitem(ingesta_server.app.config, "ANALYST_WORKSPACE_STORE_FACTORY", lambda: WorkspaceStore(workspace_path))
    monkeypatch.setitem(
        ingesta_server.app.config,
        "ANALYST_CONVERSATION_SERVICE_FACTORY",
        lambda: ConversationService(WorkspaceStore(workspace_path), _Factory()),
    )
    ingesta_server.app.extensions.pop("analyst_conversation_service", None)
    server = make_server("127.0.0.1", 0, ingesta_server.app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        ingesta_server.app.extensions.pop("analyst_conversation_service", None)


def _login(page, base_url: str, username: str) -> None:
    page.goto(f"{base_url}/login")
    page.locator("#username").fill(username)
    page.locator("#password").fill("password")
    with page.expect_navigation(
        url=f"{base_url}/analyst",
        wait_until="domcontentloaded",
        timeout=10_000,
    ):
        page.get_by_role("button", name="Entrar").click(no_wait_after=True)
    page.locator(".home-state").wait_for(state="visible", timeout=10_000)


def test_pilot_feedback_export_button_downloads_markdown_file(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        reporter = browser.new_page()
        reporter.set_default_timeout(10_000)
        _login(reporter, base_url, "raimundo")
        reporter.locator("#composer-input").fill("Hola")
        reporter.get_by_role("button", name="Enviar").click()
        reporter.get_by_role("button", name="Reportar problema").wait_for(state="visible")
        reporter.get_by_role("button", name="Reportar problema").click()
        reporter.locator("#report-comment").fill("Se necesita más detalle.")
        # Wait on the actual network response, not just the toast: the toast
        # auto-hides after ~2.6s (see analyst_workspace.js's toastTimer), so
        # polling for it after the fact can miss a narrow visible window
        # under a slow/contended runner even when the POST succeeded. This
        # anchors the test to the real completion signal and still asserts
        # the toast afterwards.
        with reporter.expect_response(
            lambda response: response.url.endswith("/api/analyst/feedback_reports") and response.request.method == "POST"
        ) as response_info:
            reporter.get_by_role("button", name="Enviar reporte").click()
        assert response_info.value.ok
        reporter.get_by_text("Reporte enviado. Gracias.").wait_for(state="visible")

        reviewer = browser.new_page()
        reviewer.set_default_timeout(10_000)
        _login(reviewer, base_url, "reviewer")
        reviewer.goto(f"{base_url}/pilot-feedback")
        reviewer.get_by_role("button", name="Descargar reportes (.md)").wait_for(state="visible")

        with reviewer.expect_download() as download_info:
            reviewer.get_by_role("button", name="Descargar reportes (.md)").click()
        download = download_info.value
        assert download.suggested_filename.startswith("toesca_pilot_feedback_")
        assert download.suggested_filename.endswith(".md")

        browser.close()


def test_pilot_control_export_button_downloads_selected_conversations(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        member = browser.new_page()
        member.set_default_timeout(10_000)
        _login(member, base_url, "raimundo")
        member.locator("#composer-input").fill("Cual es el NOI de PT")
        member.get_by_role("button", name="Enviar").click()
        member.get_by_role("button", name="Reportar problema").wait_for(state="visible")

        observer = browser.new_page()
        observer.set_default_timeout(10_000)
        _login(observer, base_url, "observer")
        observer.goto(f"{base_url}/pilot-control")
        observer.get_by_role("button", name="Conversaciones").click()
        observer.locator(".conv-check").first.wait_for(state="visible")

        export_btn = observer.get_by_role("button", name="Descargar seleccionadas (.md)")
        assert export_btn.is_disabled()

        observer.get_by_role("button", name="Seleccionar página").click()
        observer.get_by_text("1 seleccionadas").wait_for(state="visible")
        assert not export_btn.is_disabled()

        with observer.expect_download() as download_info:
            export_btn.click()
        download = download_info.value
        assert download.suggested_filename.startswith("toesca_pilot_conversations_")
        assert download.suggested_filename.endswith(".md")

        observer.get_by_role("button", name="Limpiar selección").click()
        observer.get_by_text("0 seleccionadas").wait_for(state="visible")
        assert export_btn.is_disabled()

        browser.close()
