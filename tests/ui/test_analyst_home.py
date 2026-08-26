from __future__ import annotations

from contextlib import contextmanager
import os
from threading import Thread

import pytest
from werkzeug.serving import make_server

from scripts import ingesta_server
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import WorkspaceStore

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


class _Session:
    def ask(self, _text):
        from tools.analyst_runtime.session import AnalystSessionResult

        return AnalystSessionResult("Respuesta de prueba")


class _SessionFactory:
    def create(self, *_args, **_kwargs):
        return _Session()


@contextmanager
def _server(monkeypatch, tmp_path):
    workspace_path = tmp_path / "workspace.db"
    store = WorkspaceStore(workspace_path)
    store.initialize()
    store.create_user("raimundo", "Raimundo", "password")
    store.create_user("gregorio", "Gregorio", "password")

    monkeypatch.setitem(ingesta_server.app.config, "TESTING", False)
    monkeypatch.setitem(
        ingesta_server.app.config,
        "ANALYST_WORKSPACE_STORE_FACTORY",
        lambda: WorkspaceStore(workspace_path),
    )
    monkeypatch.setitem(
        ingesta_server.app.config,
        "ANALYST_CONVERSATION_SERVICE_FACTORY",
        lambda: ConversationService(WorkspaceStore(workspace_path), _SessionFactory()),
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
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_url(f"{base_url}/analyst")


def test_stale_selection_on_login_recovers_to_personalized_home(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(2_000)
        page.goto(f"{base_url}/login")
        page.evaluate("localStorage.setItem('toesca_asistente_conversation_id', 'archived-chat')")

        _login(page, base_url, "raimundo")

        assert page.locator(".home-state").is_visible()
        assert page.get_by_role("heading", name="Hola, Raimundo").is_visible()
        assert not page.locator("#error-banner.show").is_visible()
        assert page.url == f"{base_url}/analyst"
        assert page.evaluate("localStorage.getItem('toesca_asistente_conversation_id')") is None
        screenshot_path = os.environ.get("TOESCA_HOME_SCREENSHOT")
        if screenshot_path:
            page.screenshot(path=screenshot_path, full_page=True)
        browser.close()


def test_new_conversation_uses_home_until_the_first_message(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(2_000)
        _login(page, base_url, "raimundo")

        page.get_by_role("button", name="Nueva conversación").click()
        assert page.locator(".home-state").is_visible()
        assert page.locator(".conv-item").count() == 0

        page.locator("#composer-input").fill("Hola")
        page.get_by_role("button", name="Enviar").click()
        page.locator(".turn.user").get_by_text("Hola").wait_for(state="visible")
        page.get_by_text("Respuesta de prueba").wait_for(state="visible")
        assert "/analyst/chat/" in page.url
        browser.close()


def test_logout_clears_selection_before_another_user_logs_in(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(2_000)
        _login(page, base_url, "raimundo")
        page.evaluate("localStorage.setItem('toesca_asistente_conversation_id', 'raimundo-chat')")
        page.get_by_role("button", name="Salir").click()
        page.wait_for_url(f"{base_url}/login")

        _login(page, base_url, "gregorio")
        page.get_by_role("heading", name="Hola, Gregorio").wait_for(state="visible")
        assert page.locator(".home-state").is_visible()
        assert not page.locator("#error-banner.show").is_visible()
        assert page.evaluate("localStorage.getItem('toesca_asistente_conversation_id')") is None
        browser.close()
