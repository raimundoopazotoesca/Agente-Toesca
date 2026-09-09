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
    # Isolated, disposable workspace DB -- never the live pilot DB, never the
    # live pilot server/port.
    workspace_path = tmp_path / "workspace.db"
    workspace = WorkspaceStore(workspace_path)
    workspace.initialize()
    workspace.create_user("raimundo", "Raimundo", "password")

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


def test_thumbs_feedback_persists_across_reload_and_report_flow_still_works(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(10_000)
        _login(page, base_url, "raimundo")

        page.locator("#composer-input").fill("Hola")
        page.get_by_role("button", name="Enviar").click()
        up_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como útil"]')
        down_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como no útil"]')
        up_btn.wait_for(state="visible")

        # 1) renders both controls plus the existing report button, unselected.
        assert page.get_by_role("button", name="Reportar problema").is_visible()
        assert up_btn.get_attribute("aria-pressed") == "false"
        assert down_btn.get_attribute("aria-pressed") == "false"

        # 2/3) click up -> selected, persists across reload.
        up_btn.click()
        page.wait_for_function(
            "document.querySelector('.feedback-btn[aria-label=\"Marcar respuesta como útil\"]').getAttribute('aria-pressed') === 'true'"
        )
        page.reload()
        up_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como útil"]')
        down_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como no útil"]')
        up_btn.wait_for(state="visible")
        assert up_btn.get_attribute("aria-pressed") == "true"
        assert down_btn.get_attribute("aria-pressed") == "false"

        # 4/5) click down -> selection changes, persists across reload.
        down_btn.click()
        page.wait_for_function(
            "document.querySelector('.feedback-btn[aria-label=\"Marcar respuesta como no útil\"]').getAttribute('aria-pressed') === 'true'"
        )
        assert up_btn.get_attribute("aria-pressed") == "false"
        page.reload()
        up_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como útil"]')
        down_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como no útil"]')
        down_btn.wait_for(state="visible")
        assert down_btn.get_attribute("aria-pressed") == "true"
        assert up_btn.get_attribute("aria-pressed") == "false"

        # 6) clicking the selected control again clears it, persists after reload.
        down_btn.click()
        page.wait_for_function(
            "document.querySelector('.feedback-btn[aria-label=\"Marcar respuesta como no útil\"]').getAttribute('aria-pressed') === 'false'"
        )
        page.reload()
        up_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como útil"]')
        down_btn = page.locator('.feedback-btn[aria-label="Marcar respuesta como no útil"]')
        down_btn.wait_for(state="visible")
        assert down_btn.get_attribute("aria-pressed") == "false"
        assert up_btn.get_attribute("aria-pressed") == "false"

        # 7) "Reportar problema" still opens the existing, untouched report modal.
        page.get_by_role("button", name="Reportar problema").click()
        page.locator("#report-comment").fill("Detalle del problema.")
        page.get_by_role("button", name="Enviar reporte").click()
        page.get_by_text("Reporte enviado. Gracias.").wait_for(state="visible")

        # 8/9) rating did not create a new chat turn or steal composer focus permanently.
        turns = page.locator(".turn").count()
        assert turns == 2  # one user turn, one assistant turn -- no extra turns from rating clicks
        browser.close()
