from __future__ import annotations

from contextlib import contextmanager
import os
import time
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
    store.create_user("raimundo", "Raimundo Opazo", "password")
    store.create_user("gregorio", "Gregorio de la Jara", "password")
    store.create_user("marcos", "Marcos Quiroga", "password")

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
    # El login exitoso corre la transición Toesca (~1.4s) antes de navegar.
    page.wait_for_url(f"{base_url}/analyst", timeout=5_000)


def test_visible_product_name_is_consistent_on_login_and_home(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(2_000)
        page.goto(f"{base_url}/login")
        assert page.title() == "Toesca Real Estate AI Analyst"
        assert page.get_by_role("heading", name="Toesca Real Estate AI Analyst").is_visible()

        _login(page, base_url, "raimundo")
        assert page.title() == "Toesca Real Estate AI Analyst"
        assert page.get_by_text("Toesca Real Estate AI Analyst", exact=True).count() >= 2
        browser.close()


def test_successful_login_shows_the_toesca_transition_before_home(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(3_000)
        page.goto(f"{base_url}/login")
        page.locator("#username").fill("raimundo")
        page.locator("#password").fill("password")
        page.get_by_role("button", name="Entrar").click()

        page.get_by_role("status", name="Cargando Toesca Real Estate AI Analyst").wait_for(state="visible")
        page.wait_for_url(f"{base_url}/analyst", timeout=3_000)
        page.get_by_role("heading", name="Hola, Raimundo").wait_for(state="visible")
        browser.close()


def test_delayed_wrong_password_never_shows_the_toesca_loader(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(3_000)

        def delayed_401(route):
            time.sleep(0.4)
            route.fulfill(status=401, content_type="application/json", body='{"error": "invalid_credentials"}')

        page.route("**/api/auth/login", delayed_401)
        page.goto(f"{base_url}/login")
        page.locator("#username").fill("raimundo")
        page.locator("#password").fill("wrongpass")
        page.get_by_role("button", name="Entrar").click()

        # While the (slow) auth request is still unresolved, the loader must not exist.
        page.wait_for_timeout(150)
        assert page.locator("#toesca-login-loader").count() == 0

        # After the request resolves as a 401, the loader must still never have appeared.
        page.wait_for_selector("text=Usuario o contraseña inválidos.")
        assert page.locator("#toesca-login-loader").count() == 0
        assert page.url == f"{base_url}/login"
        browser.close()


def test_stale_selection_on_login_recovers_to_personalized_home(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(2_000)
        page.goto(f"{base_url}/login")
        page.evaluate("localStorage.setItem('toesca_asistente_conversation_id', 'archived-chat')")

        _login(page, base_url, "raimundo")

        page.get_by_role("heading", name="Hola, Raimundo").wait_for(state="visible")
        assert page.locator(".home-state").is_visible()
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
        page.wait_for_url(f"{base_url}/login", timeout=5_000)

        _login(page, base_url, "gregorio")
        page.get_by_role("heading", name="Hola, Gregorio").wait_for(state="visible")
        assert page.locator(".home-state").is_visible()
        assert not page.locator("#error-banner.show").is_visible()
        assert page.evaluate("localStorage.getItem('toesca_asistente_conversation_id')") is None

        page.get_by_role("button", name="Salir").click()
        page.wait_for_url(f"{base_url}/login", timeout=5_000)
        _login(page, base_url, "marcos")
        page.get_by_role("heading", name="Hola, Marcos").wait_for(state="visible")
        browser.close()
