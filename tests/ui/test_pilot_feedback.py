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


def test_pilot_feedback_ui_submits_immutable_report_and_reviewer_updates_status(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        reporter = browser.new_page()
        reporter.set_default_timeout(3_000)
        _login(reporter, base_url, "raimundo")
        reporter.locator("#composer-input").fill("Hola")
        reporter.get_by_role("button", name="Enviar").click()
        reporter.get_by_role("button", name="Reportar problema").wait_for(state="visible")
        reporter.get_by_role("button", name="Reportar problema").click()
        reporter.locator("#report-comment").fill("La respuesta necesita más detalle.")
        reporter.get_by_role("button", name="Enviar reporte").click()
        reporter.get_by_text("Reporte enviado. Gracias.").wait_for(state="visible")

        reviewer = browser.new_page()
        reviewer.set_default_timeout(3_000)
        _login(reviewer, base_url, "reviewer")
        reviewer.goto(f"{base_url}/pilot-feedback")
        assert reviewer.title() == "Toesca Real Estate AI Analyst — Reportes del piloto"
        reviewer.get_by_text("La respuesta necesita más detalle.").wait_for(state="visible")
        reviewer.get_by_text("La respuesta necesita más detalle.").click()
        reviewer.get_by_text("Conversación al momento del reporte").wait_for(state="visible")
        reviewer.locator("#status-select").select_option("reviewing")
        reviewer.get_by_text("Guardado").wait_for(state="visible")
        browser.close()
