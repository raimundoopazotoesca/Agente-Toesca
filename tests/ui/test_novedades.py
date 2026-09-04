"""Browser-driven checks for the Novedades (product updates) feed.

Reuses the same disposable-server pattern as tests/ui/test_analyst_home.py:
a WorkspaceStore built on a tmp_path DB, a stub AnalystSession that never
calls a real provider, and a werkzeug dev server bound to an ephemeral port
(never the live pilot's 8765).
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
    workspace.create_user("raimundo", "Raimundo Opazo", "password")
    workspace.create_user("gregorio", "Gregorio de la Jara", "password")
    workspace.create_product_update(
        "Reportar problema",
        "Ahora puedes reportar una respuesta del Analyst que no cumplió lo esperado, directamente desde el chat.",
        cta_label="Volver al chat",
        cta_config={"type": "route", "value": "/analyst"},
        publish=True,
    )
    workspace.create_product_update(
        "Projects",
        "[Prueba] Próximamente: organiza tus análisis en Projects. Esta es una fila de prueba, no un anuncio real.",
        publish=True,
    )

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
    page.goto(f"{base_url}/login", wait_until="domcontentloaded", timeout=10_000)
    page.locator("#username").fill(username)
    page.locator("#password").fill("password")
    page.get_by_role("button", name="Entrar").click()
    page.wait_for_url(f"{base_url}/analyst", timeout=10_000)


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 1280, "height": 800}])
def test_sidebar_shows_unread_indicator_for_a_fresh_user(monkeypatch, tmp_path, viewport):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport)
        page.set_default_timeout(3_000)
        _login(page, base_url, "raimundo")

        page.get_by_role("button", name="Novedades").wait_for(state="visible")
        page.locator("#novedades-unread-dot.show").wait_for(state="visible", timeout=3_000)
        browser.close()


def test_opening_novedades_shows_updates_without_clutter(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(3_000)
        _login(page, base_url, "raimundo")

        page.get_by_role("button", name="Novedades").click()
        page.locator("#conversation").get_by_text("Reportar problema", exact=True).wait_for(state="visible")
        assert page.get_by_text("Projects", exact=True).is_visible()
        # composer is hidden while browsing Novedades -- it is not a chat surface.
        assert not page.locator("#composer-input").is_visible()
        browser.close()


def test_update_becomes_seen_after_viewing_and_indicator_clears(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(3_000)
        _login(page, base_url, "raimundo")

        page.get_by_role("button", name="Novedades").click()
        page.locator("#conversation").get_by_text("Reportar problema", exact=True).wait_for(state="visible")
        page.wait_for_function(
            "!document.getElementById('novedades-unread-dot').classList.contains('show')", timeout=3_000
        )
        assert page.locator("#novedades-unread-dot.show").count() == 0

        page.reload()
        page.get_by_role("button", name="Novedades").wait_for(state="visible")
        page.wait_for_timeout(300)  # unseen_count re-fetch on the fresh page load
        assert page.locator("#novedades-unread-dot.show").count() == 0
        browser.close()


def test_stale_initial_unseen_count_does_not_restore_indicator(monkeypatch, tmp_path):
    """A delayed initial count must not overwrite the state set by Novedades."""
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(3_000)
        pending = []

        def hold_initial_unseen_count(route):
            pending.append(route)

        page.route("**/api/analyst/product_updates/unseen_count", hold_initial_unseen_count)
        _login(page, base_url, "raimundo")

        page.get_by_role("button", name="Novedades").click()
        page.locator("#conversation").get_by_text("Reportar problema", exact=True).wait_for(state="visible")
        page.wait_for_function(
            "!document.getElementById('novedades-unread-dot').classList.contains('show')", timeout=3_000
        )

        assert len(pending) == 1
        with page.expect_response("**/api/analyst/product_updates/unseen_count"):
            pending.pop().fulfill(status=200, content_type="application/json", body='{"count": 2}')
        assert page.locator("#novedades-unread-dot.show").count() == 0
        browser.close()


def test_init_skips_unseen_count_request_once_novedades_is_active(monkeypatch, tmp_path):
    """Deterministic version of the race in test_stale_initial_unseen_count_does_not_restore_indicator.

    That test relies on init()'s own unseen_count request happening to be
    in flight when the click lands. Here we force the specific unsafe
    interleaving directly: hold /api/auth/me -- the request init() awaits
    (via Promise.all) before it ever reaches the line that schedules the
    initial unseen_count request -- so init() cannot possibly have issued
    that request yet. While it's blocked, open Novedades and let it fully
    settle (list rendered, all updates marked seen, dot cleared). Only then
    release init(). If init() still (unconditionally) schedules its initial
    unseen_count request at that point, this is exactly the old bug's
    reachable ordering. The fix must make init() skip the request entirely
    once Novedades is already active, so no such request should ever be
    observed on the wire.
    """
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(3_000)

        held_auth_me = []
        unseen_count_requests = []

        def hold_auth_me(route):
            held_auth_me.append(route)

        def track_unseen_count(route):
            unseen_count_requests.append(route)
            route.continue_()

        page.route("**/api/auth/me", hold_auth_me)
        page.route("**/api/analyst/product_updates/unseen_count", track_unseen_count)

        page.goto(f"{base_url}/login", wait_until="domcontentloaded", timeout=10_000)
        page.locator("#username").fill("raimundo")
        page.locator("#password").fill("password")
        with page.expect_request("**/api/auth/me", timeout=10_000):
            page.get_by_role("button", name="Entrar").click()

        # init() has now issued (and had it held) the /api/auth/me request it
        # awaits via Promise.all -- it cannot have reached the unseen_count
        # scheduling line yet. (The route handler's own bookkeeping append
        # can lag the "request" event by a tick, so we confirm the count
        # below -- after the real network round trips of opening Novedades --
        # rather than racing it here.)
        assert unseen_count_requests == []

        # Open Novedades while init() is still stuck on the held request, and
        # let it fully establish its own state (list rendered, updates marked
        # seen, dot cleared) -- this is the "openNovedades wins the race"
        # ordering the fix targets.
        page.get_by_role("button", name="Novedades").click()
        page.locator("#conversation").get_by_text("Reportar problema", exact=True).wait_for(state="visible")
        page.wait_for_function(
            "!document.getElementById('novedades-unread-dot').classList.contains('show')", timeout=3_000
        )
        assert page.locator("#novedades-unread-dot.show").count() == 0

        # init() still hasn't reached its unseen_count scheduling point --
        # confirm no such request has escaped before we even release it, and
        # confirm the held /api/auth/me request really was captured (proving
        # init() was genuinely blocked this whole time, not merely slow).
        assert len(held_auth_me) == 1
        assert unseen_count_requests == []

        # Release the held /api/auth/me request so init() can resume past
        # Promise.all and reach the point where it decides whether to
        # schedule the initial unseen_count request.
        with page.expect_response("**/api/auth/me"):
            held_auth_me.pop().continue_()
        page.wait_for_load_state("networkidle")

        assert unseen_count_requests == [], (
            "init() issued an unseen_count request after Novedades was already "
            "active -- the stale-response guard alone cannot protect against "
            "this, the request must never be issued in the first place"
        )
        assert page.locator("#novedades-unread-dot.show").count() == 0
        browser.close()


def test_second_users_indicator_is_independent(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page_a = browser.new_page(viewport={"width": 1440, "height": 900})
        page_a.set_default_timeout(3_000)
        _login(page_a, base_url, "raimundo")
        page_a.get_by_role("button", name="Novedades").click()
        page_a.locator("#conversation").get_by_text("Reportar problema", exact=True).wait_for(state="visible")
        page_a.wait_for_function(
            "!document.getElementById('novedades-unread-dot').classList.contains('show')", timeout=3_000
        )
        assert page_a.locator("#novedades-unread-dot.show").count() == 0

        page_b = browser.new_page(viewport={"width": 1440, "height": 900})
        page_b.set_default_timeout(3_000)
        _login(page_b, base_url, "gregorio")
        page_b.locator("#novedades-unread-dot.show").wait_for(state="visible", timeout=3_000)
        browser.close()


def test_home_stays_minimal_with_composer_primary(monkeypatch, tmp_path):
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(3_000)
        _login(page, base_url, "raimundo")

        page.get_by_role("heading", name="Hola, Raimundo").wait_for(state="visible")
        assert page.locator("#composer-input").is_visible()
        assert page.locator(".home-discovery-card").count() <= 1
        browser.close()


def test_cta_routes_through_the_normal_chat_composer_path(monkeypatch, tmp_path):
    """The Novedades CTA is a chat_prompt CTA in this test fixture's second
    scenario would be a route CTA (/analyst); here we verify the
    'Reportar problema' card's route CTA navigates via the normal app shell
    (no dedicated analytics handler, no new page)."""
    with _server(monkeypatch, tmp_path) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(3_000)
        _login(page, base_url, "raimundo")

        page.get_by_role("button", name="Novedades").click()
        cta = page.get_by_role("button", name="Volver al chat")
        cta.wait_for(state="visible", timeout=10_000)
        cta.click()
        page.wait_for_url(f"{base_url}/analyst", timeout=3_000)
        page.get_by_role("heading", name="Hola, Raimundo").wait_for(state="visible")
        browser.close()
