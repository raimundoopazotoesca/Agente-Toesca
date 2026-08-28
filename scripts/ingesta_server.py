"""Servidor local de la plataforma: ingesta de datos + factsheet + Asistente.

Uso:
    python -m scripts.ingesta_server
    → http://127.0.0.1:8765/ingesta   (ingesta)
    → http://127.0.0.1:8765/factsheet (factsheet + Asistente)

La ingesta EEFF no requiere API keys propias: el usuario copia un prompt, lo
corre en su ChatGPT junto al PDF del EEFF, y pega la respuesta de vuelta en la
página. El servidor solo valida y persiste; nunca llama a ningún LLM (la única
llamada a LLM es /api/chat, que es el Asistente, no ingesta).

Seguridad: todo /api/* exige el header X-Ingesta-Token. El token se inyecta
automáticamente en las páginas que sirve este servidor, así que el flujo por
navegador no cambia. Consecuencia: abrir factsheet.html como file:// (doble
clic) ya no permite usar el Asistente — hay que abrirlo desde /factsheet.

El servidor escucha en 0.0.0.0: además de 127.0.0.1, queda accesible desde
cualquier equipo de la misma red local (LAN de oficina) vía la IP de esta
máquina, puerto 8765. Cualquiera en esa red que llegue a la URL recibe el
token inyectado igual que en localhost — asumir que la LAN es de confianza.
"""
from __future__ import annotations

import hmac
import io
import os
import re
import secrets
import sys
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_file, send_from_directory
from openpyxl.utils.exceptions import InvalidFileException
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db import ingest_eeff_validated as core  # noqa: E402
from tools.db import ingest_rent_roll_validated as rr_core  # noqa: E402
from tools.db import ingest_mercado as mercado_core  # noqa: E402
from tools.db import ingest_mercado_bodegas as mercado_bodegas_core  # noqa: E402
from tools.db import ingest_mercado_comercio as mercado_comercio_core  # noqa: E402
from tools.db import ingest_variacion_comercio_rm as variacion_comercio_rm_core  # noqa: E402
from tools.db import ingest_parking_pt_mensual as parking_core  # noqa: E402
from tools.db import ingest_balance_consolidado as balance_core  # noqa: E402
from tools.db import ingest_er_activo_web as er_activo_core  # noqa: E402
from tools.db import ingest_er_sucden_fijo as sucden_fijo_core  # noqa: E402
from tools.db import ingest_amortizacion_extra as amort_extra_core  # noqa: E402
from tools.db import ingest_caja_web as caja_core  # noqa: E402
from tools.db import ingest_ocupacion_web as ocupacion_core  # noqa: E402
from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import estado_ingesta  # noqa: E402
from tools import db_chat  # noqa: E402
from scripts import build_factsheet  # noqa: E402
from scripts import recompute_derived_kpis  # noqa: E402
from tools import analyst_api  # noqa: E402
from tools.analyst_workspace import export_markdown  # noqa: E402
from tools.analyst_workspace.store import ValidationError as WorkspaceValidationError  # noqa: E402
from tools.analyst_workspace.store import WorkspaceStoreError  # noqa: E402


def _rebuild_factsheet() -> None:
    """Recalcula KPIs derivados y regenera factsheet.html tras cada ingesta.

    Sin este paso, derived_kpi (ingresos/NOI/tasa arriendo/cap rate) queda
    congelado en el último período en que alguien corrió el script
    consolidate_* a mano — ver scripts/recompute_derived_kpis.py.
    """
    try:
        recompute_derived_kpis.main()
    except Exception as exc:  # no debe romper la respuesta de ingesta
        print(f"WARN: no se pudieron recalcular los KPIs derivados: {exc}")
    try:
        build_factsheet.main()
    except Exception as exc:  # no debe romper la respuesta de ingesta
        print(f"WARN: no se pudo regenerar factsheet.html: {exc}")


def _generar_pdfs_factsheet(
    fondos: list[str], periodo_cb: str, periodo_op: str
) -> tuple[dict[str, bytes], list[str]]:
    """Genera un PDF por fondo vía Playwright headless.

    Devuelve (pdfs_por_fondo, errores) — errores es una lista de mensajes
    legibles para los fondos que no se pudieron generar (sin datos en el
    período pedido, timeout, o excepción).
    """
    from playwright.sync_api import sync_playwright

    pdfs: dict[str, bytes] = {}
    errores: list[str] = []
    base_url = "http://127.0.0.1:8765/factsheet"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for fondo in fondos:
                page = browser.new_page(
                    extra_http_headers={TOKEN_HEADER: API_TOKEN},
                    viewport={"width": 1200, "height": 1000},
                )
                try:
                    url = (
                        f"{base_url}?fondo={fondo}&cb={periodo_cb}"
                        f"&op={periodo_op}&pdfmode=1"
                    )
                    page.goto(url, wait_until="load")
                    page.wait_for_function(
                        "window.__PDF_READY__ !== undefined", timeout=15000
                    )
                    ready = page.evaluate("window.__PDF_READY__")
                    if ready != True:  # noqa: E712 - distingue de "no_data"
                        errores.append(
                            f"{fondo}: sin datos para el período {periodo_op}/{periodo_cb}."
                        )
                        continue

                    # Cada .page (una de las 4 secciones del factsheet) puede
                    # ser más alta que una página A4 landscape impresa — sin
                    # achicar, Chromium la corta en 2 páginas físicas. Se mide
                    # la sección más grande y se calcula un factor de escala
                    # único para las 4, en vez de manipular el DOM con
                    # transform (frágil: colapso de márgenes cortaba
                    # contenido a la mitad).
                    dims = page.evaluate(
                        "Array.from(document.querySelectorAll('.page'))"
                        ".map(el => ({w: el.scrollWidth, h: el.scrollHeight}))"
                    )
                    max_w = max((d["w"] for d in dims), default=1122)
                    max_h = max((d["h"] for d in dims), default=793)
                    # A4 landscape @ 96 CSS px/in, sin márgenes.
                    scale = min(1.0, 1122 / max_w, 793 / max_h)
                    scale = max(0.1, round(scale, 3))

                    pdfs[fondo] = page.pdf(
                        format="A4",
                        landscape=True,
                        print_background=True,
                        margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                        scale=scale,
                    )
                except Exception as exc:  # noqa: BLE001
                    errores.append(f"{fondo}: error generando PDF ({exc}).")
                finally:
                    page.close()
        finally:
            browser.close()

    return pdfs, errores


app = Flask(__name__, static_folder=None)


def _create_analyst_conversation_service():
    """Construct the writable workspace and F4 runtime only on first API use."""
    cached = app.extensions.get("analyst_conversation_service")
    if cached is not None:
        return cached

    from tools.analyst_runtime.session import OpenAIResponsesAnalystSessionFactory
    from tools.analyst_workspace.conversation_service import ConversationService
    from tools.analyst_workspace.store import WorkspaceStore

    workspace = _workspace_store()
    session_factory = OpenAIResponsesAnalystSessionFactory(ROOT / "memory" / "agente_toesca_v2.db")
    service = ConversationService(workspace, session_factory)
    app.extensions["analyst_conversation_service"] = service
    return service


# Kept as a factory (rather than a service instance) so importing this module
# neither creates a workspace DB nor requires an OpenAI credential.
app.config.setdefault("ANALYST_CONVERSATION_SERVICE_FACTORY", _create_analyst_conversation_service)


def _workspace_store():
    from tools.analyst_workspace.store import WorkspaceStore
    factory = app.config.get("ANALYST_WORKSPACE_STORE_FACTORY")
    store = factory() if factory else WorkspaceStore(Path(os.environ.get("ANALYST_WORKSPACE_DB", ROOT / "memory" / "analyst_workspace.db")))
    store.initialize()
    return store


ANALYST_SESSION_COOKIE = "toesca_analyst_session"
app.config.setdefault("ANALYST_SESSION_DAYS", 7)
app.config.setdefault("ANALYST_COOKIE_SECURE", os.environ.get("ANALYST_COOKIE_SECURE", "false").lower() == "true")

# Tope de subida: los .xlsx de proveedores son de pocos MB; el RR JLL es el mayor.
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

# ── Autenticación ────────────────────────────────────────────────────────────
# El servidor expone la DB completa (lectura vía /api/chat y escritura vía
# /api/*/commit) y escucha en loopback, donde cualquier proceso local —o una
# página web abierta en el mismo navegador— puede alcanzarlo. Se exige un token
# en todo /api/*. Las páginas que sirve el propio servidor lo reciben inyectado,
# así que el flujo normal por navegador no cambia.
TOKEN_HEADER = "X-Ingesta-Token"
_TOKEN_PLACEHOLDER = "__INGESTA_TOKEN__"

# Fijar INGESTA_TOKEN da un valor estable entre reinicios; si no, se genera uno
# por sesión y se imprime al arrancar.
API_TOKEN = os.environ.get("INGESTA_TOKEN") or secrets.token_urlsafe(32)


def _compute_release_revision() -> str | None:
    """Small stable startup-level revision tag -- computed once at import time,
    never per-request, so feedback reports never spawn a git subprocess."""
    override = os.environ.get("ANALYST_RELEASE_REVISION")
    if override and override.strip():
        return override.strip()
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


RELEASE_REVISION = _compute_release_revision()

# Orígenes permitidos para CORS. No se refleja un Origin arbitrario y "null"
# (factsheet abierto como file://) ya no se acepta: abrir el factsheet desde
# http://127.0.0.1:8765/factsheet (o la IP de la red local) lo deja con el
# token inyectado.
def _lan_ip() -> str | None:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


_LAN_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
_lan_ip_addr = _lan_ip()
if _lan_ip_addr:
    _LAN_HOSTS.append(_lan_ip_addr)

_CORS_ORIGINS = frozenset(f"http://{host}:8765" for host in _LAN_HOSTS)


def _token_ok() -> bool:
    supplied = request.headers.get(TOKEN_HEADER, "")
    return bool(supplied) and hmac.compare_digest(supplied, API_TOKEN)


@app.before_request
def _require_token():
    if request.path.startswith("/api/analyst/") or request.path in {"/api/auth/login", "/api/auth/logout", "/api/auth/me"}:
        return None
    if not request.path.startswith("/api/"):
        return None
    if request.method == "OPTIONS":  # preflight: la validación va en la real
        return None
    if not _token_ok():
        return jsonify({
            "ok": False,
            "error": (
                "No autorizado. Abre la interfaz desde "
                "http://127.0.0.1:8765/ingesta (o /factsheet) para que el token "
                "se inyecte automáticamente."
            ),
        }), 401
    return None


def _principal():
    # Test-only authenticated helper; production always uses the opaque cookie.
    if app.config.get("TESTING") and request.headers.get("X-Analyst-Test-User-Id"):
        return {"id": app.config.get("ANALYST_TEST_USER_ID", request.headers["X-Analyst-Test-User-Id"]), "username": "test", "display_name": "Test", "role": "user"}
    token = request.cookies.get(ANALYST_SESSION_COOKIE)
    if not token:
        return None
    return _workspace_store().get_session_user(token)


@app.before_request
def _require_analyst_user():
    if not request.path.startswith("/api/analyst/"):
        return None
    if request.method == "OPTIONS":
        return None
    principal = _principal()
    if principal is None:
        return jsonify({"error": "authentication_required"}), 401
    request.analyst_user = principal
    return None


@app.after_request
def _add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin in _CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = f"Content-Type, {TOKEN_HEADER}"
    response.headers["Vary"] = "Origin"
    return response


@app.route("/api/chat", methods=["OPTIONS"])
def _api_chat_preflight():
    return "", 204


@app.errorhandler(413)
def _too_large(_exc):
    limite_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({"ok": False, "error": f"El archivo supera el límite de {limite_mb} MB."}), 413


# Excepciones típicas de un .xlsx corrupto o de otro formato: son error del
# archivo del proveedor, no un bug. Se traducen a 400 con mensaje legible en vez
# de un 500. Cualquier otra excepción sigue siendo 500 a propósito, para que un
# bug real (como el NameError que rompió la ingesta EEFF) se vea como tal.
_ERRORES_DE_ARCHIVO = (zipfile.BadZipFile, KeyError, InvalidFileException)


def _con_archivo_legible(fn, *args, **kwargs):
    """Ejecuta un validate/commit de archivo traduciendo fallos de lectura."""
    try:
        return fn(*args, **kwargs)
    except _ERRORES_DE_ARCHIVO as exc:
        raise ValueError(
            f"No se pudo leer el archivo: {type(exc).__name__}: {exc}. "
            "Verifica que sea el .xlsx correcto y que no esté corrupto."
        ) from exc


# ── JLL v2 ──────────────────────────────────────────────────────────────────
# El formato nuevo trae varios periodos en un mismo archivo, asi que el periodo
# deja de ser un input del usuario: lo declara el contenido. Las rutas se
# mantienen y se ramifica por formato detectado, para no romper la UI ni los
# tests que ya existen.

def _jll_v2_tmp(file_bytes: bytes, filename: str):
    """Escribe el upload a un temporal y devuelve su ruta de LECTURA.

    El nombre de este temporal (`jll_v2_<random>.xlsx`) nunca debe llegar a
    la DB: se pasa `source_name=file.filename` aparte para que el linaje
    conserve el nombre real del archivo que subio el usuario.
    """
    import tempfile
    sufijo = Path(filename).suffix or ".xlsx"
    fd, ruta = tempfile.mkstemp(suffix=sufijo, prefix="jll_v2_")
    with os.fdopen(fd, "wb") as fh:
        fh.write(file_bytes)
    return ruta


def _es_jll_v2(file_bytes: bytes, filename: str) -> tuple[bool, str | None]:
    """(es_v2, ruta_temporal). La ruta se devuelve para reusar el temporal."""
    from tools.jll_planilla_tools import es_formato_v2
    ruta = _jll_v2_tmp(file_bytes, filename)
    try:
        return es_formato_v2(ruta), ruta
    except Exception:
        os.unlink(ruta)
        return False, None


@app.errorhandler(Exception)
def _api_error_json(exc):
    """El front espera JSON; sin esto un fallo inesperado devuelve HTML de Flask."""
    if isinstance(exc, HTTPException):
        return exc
    if request.path.startswith("/api/"):
        app.logger.exception("Error no manejado en %s", request.path)
        return jsonify({
            "ok": False,
            "error": f"Error inesperado del servidor ({type(exc).__name__}: {exc})",
            "errors": [f"Error inesperado del servidor ({type(exc).__name__}: {exc})"],
            "warnings": [],
        }), 500
    raise exc


def _serve_html_con_token(directory: str | Path, filename: str) -> Response:
    """Sirve un HTML inyectando el token, para que su JS pueda llamar a /api/*."""
    html = (Path(directory) / filename).read_text(encoding="utf-8")
    if _TOKEN_PLACEHOLDER in html:
        html = html.replace(_TOKEN_PLACEHOLDER, API_TOKEN)
    else:
        html = html.replace(
            "<head>", f'<head><script>window.INGESTA_TOKEN="{API_TOKEN}";</script>', 1
        )
    return Response(html, mimetype="text/html")


PROMPTS_DIR = ROOT / "prompts"
WEB_DIR = ROOT / "web"

FONDO_FILE = {"TRI": "eeff_tri.md", "PT": "eeff_pt.md", "APO": "eeff_apo.md"}

PROVEEDOR_ACTIVOS = {
    "jll": ["PT", "Apoquindo", "Apo3001"],
    "tresa_vina": ["Viña Centro"],
    "tresa_curico": ["Mall Curicó"],
}


def _extract_fenced_block(markdown_text: str) -> str:
    """Devuelve el contenido del primer bloque ``` ... ``` (el prompt copiable)."""
    match = re.search(r"```(?:\w+)?\n(.*?)```", markdown_text, re.DOTALL)
    return match.group(1).strip() if match else markdown_text.strip()


@app.get("/")
def index():
    return redirect("/ingesta")


@app.get("/ingesta")
def serve_page():
    return _serve_html_con_token(WEB_DIR, "ingesta.html")


@app.get("/db-diagrama")
def serve_db_diagram():
    return send_from_directory(WEB_DIR, "db_diagrama_interactivo.html")


@app.get("/factsheet")
def serve_factsheet():
    return _serve_html_con_token(ROOT, "factsheet.html")


@app.get("/chat_bubble.js")
def serve_chat_bubble():
    source = (WEB_DIR / "quick_chat_controller.js").read_text(encoding="utf-8")
    source += "\n" + (WEB_DIR / "chat_markdown.js").read_text(encoding="utf-8")
    source += "\n" + (WEB_DIR / "chat_bubble.js").read_text(encoding="utf-8")
    resp = app.response_class(source, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/analyst")
def serve_analyst_workspace():
    if _principal() is None:
        return redirect("/login")
    return _serve_html_con_token(WEB_DIR, "analyst.html")


@app.get("/analyst/chat/<conversation_id>")
def serve_analyst_workspace_chat(conversation_id: str):
    # conversation_id se resuelve en el cliente (fetch a /api/analyst/...);
    # el servidor solo sirve el mismo shell para cualquier id, igual que una SPA.
    if _principal() is None:
        return redirect("/login")
    return _serve_html_con_token(WEB_DIR, "analyst.html")


@app.get("/pilot-feedback")
def serve_pilot_feedback():
    principal = _principal()
    if principal is None:
        return redirect("/login")
    if not _workspace_store().user_has_capability(principal["id"], "feedback_reviewer"):
        return Response("No autorizado.", status=403)
    return send_from_directory(WEB_DIR, "pilot_feedback.html")


@app.get("/pilot-control")
def serve_pilot_control():
    principal = _principal()
    if principal is None:
        return redirect("/login")
    if not _workspace_store().user_has_capability(principal["id"], "pilot_observer"):
        return Response("No autorizado.", status=403)
    return send_from_directory(WEB_DIR, "pilot_control.html")


@app.get("/login")
def serve_login():
    if _principal() is not None:
        return redirect("/analyst")
    return send_from_directory(WEB_DIR, "login.html")


@app.post("/api/auth/login")
def analyst_login():
    body = request.get_json(silent=True) or {}
    username, password = body.get("username"), body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "invalid_credentials"}), 401
    from tools.analyst_workspace.store import AuthenticationError
    try:
        user = _workspace_store().authenticate(username, password)
    except AuthenticationError:
        return jsonify({"error": "invalid_credentials"}), 401
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=int(app.config["ANALYST_SESSION_DAYS"]))
    _workspace_store().create_session(user["id"], token, expires.isoformat().replace("+00:00", "Z"))
    from tools.analyst_workspace.models import preferred_name
    response = jsonify({"username": user["username"], "display_name": user["display_name"], "short_name": preferred_name(user["display_name"])})
    response.set_cookie(ANALYST_SESSION_COOKIE, token, httponly=True, samesite="Lax", secure=bool(app.config["ANALYST_COOKIE_SECURE"]), path="/", expires=expires)
    return response


@app.post("/api/auth/logout")
def analyst_logout():
    token = request.cookies.get(ANALYST_SESSION_COOKIE)
    if token:
        _workspace_store().revoke_session(token)
    response = jsonify({"ok": True})
    response.delete_cookie(ANALYST_SESSION_COOKIE, path="/")
    return response


@app.get("/api/auth/me")
def analyst_me():
    user = _principal()
    if user is None: return jsonify({"error": "authentication_required"}), 401
    from tools.analyst_workspace.models import preferred_name
    return jsonify({"username": user["username"], "display_name": user["display_name"], "short_name": preferred_name(user["display_name"]), "role": user["role"]})


@app.get("/analyst_workspace.js")
def serve_analyst_workspace_js():
    source = (WEB_DIR / "quick_chat_controller.js").read_text(encoding="utf-8")
    source += "\n" + (WEB_DIR / "chat_markdown.js").read_text(encoding="utf-8")
    source += "\n" + (WEB_DIR / "analyst_workspace.js").read_text(encoding="utf-8")
    resp = app.response_class(source, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/assets/<path:filename>")
def serve_analyst_asset(filename: str):
    return send_from_directory(ROOT / "assets", filename)


@app.post("/api/chat")
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    question = str(body.get("question", ""))
    history = body.get("history") or []
    if not isinstance(history, list):
        history = []
    # Session key para el estado conversacional del Asistente: preferimos un
    # conversation_id generado por el cliente (persistido en sessionStorage
    # del navegador, unico por pestaña/sesion). Si el cliente no lo manda
    # (llamada legacy o sin JS), caemos a la IP como antes.
    conversation_id = body.get("conversation_id") or request.headers.get("X-Conversation-Id")
    # Truncate to bound state-dict key size; an oversized/malicious value
    # can't be used to fan out unbounded distinct session keys.
    conversation_id = str(conversation_id)[:128] if conversation_id else None
    session_id = conversation_id or (request.remote_addr or "default")
    try:
        result = db_chat.answer(question, history, session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "answer_md": f"⚠️ Error inesperado: {exc}",
            "error": "server_error",
        }), 500
    return jsonify(result)


@app.post("/api/restart_servidores")
def api_restart_servidores():
    """Relanza restart_servidores.bat (mata y vuelve a levantar 8765 y 5000).

    El propio proceso actual queda en la lista de PIDs que el .bat mata en el
    puerto 8765, así que basta con lanzarlo desacoplado del proceso: el .bat
    sobrevive a que este proceso termine.
    """
    import subprocess

    bat_path = ROOT / "restart_servidores.bat"
    if not bat_path.exists():
        return jsonify({"ok": False, "error": f"No se encontró {bat_path}"}), 500
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            cwd=str(ROOT),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError as exc:
        return jsonify({"ok": False, "error": f"No se pudo lanzar el script: {exc}"}), 500
    return jsonify({"ok": True, "mensaje": "Reiniciando servidores. La página se recargará sola en unos segundos."})


def _analyst_body() -> dict:
    """Parse an object JSON request without exposing Flask parsing details."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def _analyst_error(error: str, status: int, *, details: list[dict[str, str]] | None = None):
    payload = {"error": error}
    if details:
        payload["details"] = details
    return jsonify(payload), status


def _analyst_request_validation_details(exc: ValueError) -> list[dict[str, str]]:
    """Expose only fixed HTTP validation rules, never request contents or traces."""
    known_rules = {
        "JSON body must be an object": ("body", "invalid_json_object", "JSON body must be an object"),
        "text must be a non-blank string": ("text", "invalid_text", "text must be a non-blank string"),
    }
    field, code, message = known_rules.get(
        str(exc), ("request", "invalid_request", "Request validation failed")
    )
    return [{"field": field, "code": code, "message": message}]


def _analyst_adapter() -> analyst_api.ConversationApiAdapter:
    return analyst_api.get_adapter(app.config.get("ANALYST_CONVERSATION_SERVICE_FACTORY"))


def _analyst_user_id() -> str:
    return request.analyst_user["id"]


@app.get("/api/analyst/product_updates")
def analyst_list_product_updates():
    """Published+active Novedades entries for the authenticated user, newest
    first, annotated with this user's own seen state. Pure workspace-store
    read: no LLM call, no tool call, no analytical session."""
    updates = _workspace_store().list_product_updates_for_user(_analyst_user_id())
    return jsonify({"product_updates": updates})


@app.get("/api/analyst/product_updates/unseen_count")
def analyst_product_updates_unseen_count():
    count = _workspace_store().count_unseen_product_updates_for_user(_analyst_user_id())
    return jsonify({"count": count})


@app.post("/api/analyst/product_updates/<update_id>/seen")
def analyst_mark_product_update_seen(update_id: str):
    """Marks the update seen for the SESSION-derived user only -- the request
    body is never consulted for a user id, matching every other
    ``/api/analyst/*`` write in this file."""
    from tools.analyst_workspace.store import ProductUpdateNotFoundError

    try:
        _workspace_store().mark_product_update_seen_for_user(update_id, _analyst_user_id())
        return jsonify({"ok": True})
    except ProductUpdateNotFoundError:
        return _analyst_error("not_found", 404)


@app.get("/api/analyst/conversations")
def analyst_list_conversations():
    try:
        include_archived = request.args.get("include_archived", "false").lower() == "true"
        return jsonify({"conversations": _analyst_adapter().list_conversations(_analyst_user_id(), include_archived=include_archived)})
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.post("/api/analyst/conversations")
def analyst_create_conversation():
    try:
        body = _analyst_body()
        title, context = body.get("title"), body.get("context")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise ValueError("title must be a non-blank string")
        if context is not None and not isinstance(context, dict):
            raise ValueError("context must be an object")
        return jsonify(_analyst_adapter().create_conversation(_analyst_user_id(), title=title.strip() if title else None, context=context)), 201
    except ValueError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/conversations/<conversation_id>")
def analyst_get_conversation(conversation_id: str):
    try:
        return jsonify(_analyst_adapter().get_conversation(conversation_id, _analyst_user_id()))
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/conversations/<conversation_id>/messages")
def analyst_list_messages(conversation_id: str):
    try:
        return jsonify({"messages": _analyst_adapter().list_messages(conversation_id, _analyst_user_id())})
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.patch("/api/analyst/conversations/<conversation_id>")
def analyst_update_conversation(conversation_id: str):
    try:
        body = _analyst_body()
        title, archived = body.get("title"), body.get("archived")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise ValueError("title must be a non-blank string")
        if archived is not None and not isinstance(archived, bool):
            raise ValueError("archived must be a boolean")
        return jsonify(_analyst_adapter().update_conversation(conversation_id, _analyst_user_id(), title=title.strip() if title else None, archived=archived))
    except ValueError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.post("/api/analyst/conversations/<conversation_id>/messages")
def analyst_send_message(conversation_id: str):
    try:
        text = _analyst_body().get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-blank string")
        return jsonify(_analyst_adapter().send_message(conversation_id, _analyst_user_id(), text.strip())), 201
    except ValueError as exc:
        return _analyst_error("validation_error", 400, details=_analyst_request_validation_details(exc))
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400, details=[{
            "field": "request",
            "code": "service_validation",
            "message": "Request was rejected by analyst service",
        }])
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


def _is_feedback_reviewer() -> bool:
    return _workspace_store().user_has_capability(_analyst_user_id(), "feedback_reviewer")


@app.post("/api/analyst/feedback_reports")
def analyst_submit_feedback_report():
    """Pure product action: comment + ids the client owns. The server loads the
    authoritative conversation/message and builds the immutable snapshot -- no
    tool call, no SQL against the knowledge DB, no LLM call, no new turn."""
    try:
        body = _analyst_body()
        conversation_id, anchor_message_id, comment = (
            body.get("conversation_id"), body.get("anchor_message_id"), body.get("comment"),
        )
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("conversation_id must be a non-blank string")
        if not isinstance(anchor_message_id, str) or not anchor_message_id.strip():
            raise ValueError("anchor_message_id must be a non-blank string")
        if not isinstance(comment, str) or not comment.strip():
            raise ValueError("comment must be a non-blank string")
        report = _analyst_adapter().submit_feedback_report(
            _analyst_user_id(), conversation_id.strip(), anchor_message_id.strip(), comment.strip(),
            release_revision=RELEASE_REVISION,
        )
        return jsonify(report), 201
    except ValueError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/feedback_reports")
def analyst_list_feedback_reports():
    if not _is_feedback_reviewer():
        return _analyst_error("forbidden", 403)
    try:
        status = request.args.get("status") or None
        reporter_user_id = request.args.get("reporter_user_id") or None
        reports = _analyst_adapter().list_feedback_reports(status=status, reporter_user_id=reporter_user_id)
        return jsonify({"reports": reports})
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/feedback_reports/<report_id>")
def analyst_get_feedback_report(report_id: str):
    if not _is_feedback_reviewer():
        return _analyst_error("forbidden", 403)
    try:
        return jsonify(_analyst_adapter().get_feedback_report(report_id))
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.patch("/api/analyst/feedback_reports/<report_id>")
def analyst_update_feedback_report(report_id: str):
    if not _is_feedback_reviewer():
        return _analyst_error("forbidden", 403)
    try:
        body = _analyst_body()
        status = body.get("status")
        if status not in {"new", "reviewing", "resolved", "dismissed"}:
            raise ValueError("status must be one of: new, reviewing, resolved, dismissed")
        return jsonify(_analyst_adapter().update_feedback_report_status(report_id, status))
    except ValueError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.post("/api/analyst/messages/<message_id>/feedback")
def analyst_set_feedback(message_id: str):
    """Thumbs up/down (v1). Pure product action, separate from "Reportar
    problema": server-authoritative rating, no LLM/tool/knowledge-DB call,
    no new conversation message. `note` is accepted for forward
    compatibility but the current UI never sends one -- the rating itself
    is the whole signal."""
    try:
        body = _analyst_body()
        rating, note = body.get("rating"), body.get("note")
        if rating not in {"up", "down"}:
            raise ValueError("rating must be 'up' or 'down'")
        if note is not None and not isinstance(note, str):
            raise ValueError("note must be a string")
        return jsonify(_analyst_adapter().set_feedback(message_id, _analyst_user_id(), rating, note))
    except ValueError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.delete("/api/analyst/messages/<message_id>/feedback")
def analyst_clear_feedback(message_id: str):
    """Clear the caller's own rating. Idempotent: clearing an already-absent
    rating still returns 200, it does not error."""
    try:
        _analyst_adapter().clear_feedback(message_id, _analyst_user_id())
        return jsonify({"ok": True})
    except analyst_api.AnalystValidationError:
        return _analyst_error("validation_error", 400)
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/conversations/<conversation_id>/feedback")
def analyst_list_conversation_feedback(conversation_id: str):
    """Current ratings for every rated assistant message in one of the
    caller's own conversations -- used to hydrate the thumbs UI on load,
    without a page refresh, without leaking another user's ratings."""
    try:
        feedback = _analyst_adapter().list_conversation_feedback(conversation_id, _analyst_user_id())
        return jsonify({"feedback": feedback})
    except analyst_api.AnalystNotFoundError:
        return _analyst_error("not_found", 404)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/feedback_summary")
def analyst_feedback_summary():
    """Smallest useful reviewer read surface for thumbs feedback: aggregate
    counts plus a short recent list. Reuses the existing feedback_reviewer
    capability -- no new role, no dashboard."""
    if not _is_feedback_reviewer():
        return _analyst_error("forbidden", 403)
    try:
        adapter = _analyst_adapter()
        summary = adapter.get_feedback_summary()
        summary["recent"] = adapter.list_recent_feedback(limit=20)
        return jsonify(summary)
    except analyst_api.AnalystServiceUnavailableError:
        return _analyst_error("service_unavailable", 503)


def _markdown_attachment(markdown_text: str, filename: str) -> Response:
    response = Response(markdown_text, content_type="text/markdown; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@app.get("/api/analyst/feedback_reports/export.md")
def analyst_export_feedback_reports_md():
    """One markdown file with every (optionally status-filtered) feedback
    report: reporter/status metadata, the exact comment, the IMMUTABLE
    conversation_snapshot taken at report time (never reconstructed from
    live conversation state), the CURRENT live rating of the reported
    response (allowed to differ from snapshot time), and safe technical
    diagnostics via the same allowlist already used by feedback_report
    itself. Reads only the workspace store -- no LLM/tool call, no
    knowledge-DB query, matching every other /api/analyst/* route in this
    file."""
    if not _is_feedback_reviewer():
        return _analyst_error("forbidden", 403)
    try:
        status = request.args.get("status") or None
        store = _workspace_store()
        reports = store.list_feedback_reports(status=status)
        enriched = []
        for report in reports:
            live = store.get_feedback(report.anchor_message_id)
            enriched.append({
                "id": report.id,
                "reporter_user_id": report.reporter_user_id,
                "reporter_display_name": report.reporter_display_name,
                "conversation_id": report.conversation_id,
                "anchor_message_id": report.anchor_message_id,
                "comment": report.comment,
                "conversation_snapshot": report.conversation_snapshot,
                "technical_context": report.technical_context,
                "status": report.status,
                "created_at": report.created_at,
                "updated_at": report.updated_at,
                "live_rating": live.rating if live is not None else None,
            })
        markdown_text = export_markdown.build_feedback_reports_export(enriched)
        return _markdown_attachment(markdown_text, export_markdown.feedback_export_filename())
    except WorkspaceValidationError:
        return _analyst_error("validation_error", 400)
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)


# -- Pilot Control Center (v1) -----------------------------------------------
#
# Read-only observer surface for understanding pilot usage. Gated by the
# `pilot_observer` capability (same generic user_capability mechanism that
# gates /pilot-feedback with `feedback_reviewer`). Never bypasses the normal
# owner-scoped /api/analyst/conversations/* routes above -- those are
# untouched. All data here is derived from existing tables; no new schema.

def _is_pilot_observer() -> bool:
    return _workspace_store().user_has_capability(_analyst_user_id(), "pilot_observer")


@app.get("/api/analyst/pilot_control/overview")
def pilot_control_overview():
    if not _is_pilot_observer():
        return _analyst_error("forbidden", 403)
    try:
        return jsonify(_workspace_store().pilot_overview())
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/pilot_control/users")
def pilot_control_users():
    if not _is_pilot_observer():
        return _analyst_error("forbidden", 403)
    try:
        return jsonify({"users": _workspace_store().list_pilot_users()})
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/pilot_control/users/<user_id>")
def pilot_control_user_detail(user_id: str):
    if not _is_pilot_observer():
        return _analyst_error("forbidden", 403)
    try:
        detail = _workspace_store().get_pilot_user_detail(user_id)
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)
    if detail is None:
        return _analyst_error("not_found", 404)
    return jsonify(detail)


@app.get("/api/analyst/pilot_control/conversations")
def pilot_control_conversations():
    if not _is_pilot_observer():
        return _analyst_error("forbidden", 403)
    try:
        user_id = request.args.get("user_id") or None
        since = request.args.get("since") or None
        search = request.args.get("q") or None
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        conversations = _workspace_store().list_pilot_conversations(
            user_id=user_id, since=since, search=search, limit=limit, offset=offset,
        )
        return jsonify({"conversations": conversations})
    except ValueError:
        return _analyst_error("validation_error", 400)
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/analyst/pilot_control/conversations/<conversation_id>")
def pilot_control_conversation_detail(conversation_id: str):
    if not _is_pilot_observer():
        return _analyst_error("forbidden", 403)
    try:
        detail = _workspace_store().get_pilot_conversation_detail(conversation_id)
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)
    if detail is None:
        return _analyst_error("not_found", 404)
    return jsonify(detail)


@app.get("/api/analyst/pilot_control/questions")
def pilot_control_latest_questions():
    if not _is_pilot_observer():
        return _analyst_error("forbidden", 403)
    try:
        limit = int(request.args.get("limit", 50))
        return jsonify({"questions": _workspace_store().list_latest_pilot_questions(limit=limit)})
    except ValueError:
        return _analyst_error("validation_error", 400)
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)


MAX_CONVERSATION_EXPORT_IDS = 100


@app.post("/api/analyst/pilot_control/conversations/export.md")
def pilot_control_export_conversations_md():
    """One markdown file concatenating every selected conversation: full
    verbatim transcript, per-assistant-message rating/report status, and
    safe diagnostics -- resolved entirely server-side from the ids the
    client sent (never trusting client-supplied text/ratings/diagnostics).
    Rejects the whole batch (no partial export) if any id is nonexistent or
    if the batch exceeds MAX_CONVERSATION_EXPORT_IDS. Reads only the
    workspace store -- no LLM/tool call, no knowledge-DB query."""
    if not _is_pilot_observer():
        return _analyst_error("forbidden", 403)
    try:
        body = _analyst_body()
        raw_ids = body.get("conversation_ids")
        if not isinstance(raw_ids, list) or not raw_ids or not all(
            isinstance(cid, str) and cid.strip() for cid in raw_ids
        ):
            raise ValueError("conversation_ids must be a non-empty array of non-blank strings")
        conversation_ids = list(dict.fromkeys(cid.strip() for cid in raw_ids))
    except ValueError:
        return _analyst_error("validation_error", 400)

    if len(conversation_ids) > MAX_CONVERSATION_EXPORT_IDS:
        return _analyst_error(
            "too_many_conversation_ids", 413,
            details=[{
                "field": "conversation_ids", "code": "limit_exceeded",
                "message": f"at most {MAX_CONVERSATION_EXPORT_IDS} conversation_ids per batch",
            }],
        )

    try:
        store = _workspace_store()
        details, missing = [], []
        for conversation_id in conversation_ids:
            detail = store.get_pilot_conversation_detail(conversation_id)
            if detail is None:
                missing.append(conversation_id)
            else:
                details.append(detail)
        if missing:
            return _analyst_error(
                "conversation_not_found", 400,
                details=[{"field": "conversation_ids", "code": "not_found", "message": cid} for cid in missing],
            )
        markdown_text = export_markdown.build_conversations_export(details)
        return _markdown_attachment(markdown_text, export_markdown.conversations_export_filename())
    except WorkspaceStoreError:
        return _analyst_error("service_unavailable", 503)


@app.get("/api/estado_ingesta")
def api_estado_ingesta():
    con = get_conn_for(str(estado_ingesta.DB_PATH))
    try:
        return jsonify(estado_ingesta.estado_ingesta(con))
    finally:
        con.close()


@app.post("/api/estado_ingesta/refrescar")
def api_estado_ingesta_refrescar():
    """Trae el último dato disponible de UF, USD y valor cuota bursátil y
    reporta el estado actualizado. Best-effort: si una fuente falla, las
    otras dos igual se intentan y se informa el error por separado.
    """
    from tools import uf_web_tools, web_bursatil_tools
    from tools.db import ingest_dolar

    errores: dict[str, str] = {}

    try:
        uf_web_tools.actualizar_uf_desde_web(verbose=False)
    except Exception as e:
        errores["uf"] = str(e)

    try:
        resultado_dolar = ingest_dolar.backfill_dolar_hoy(verbose=False)
        if resultado_dolar.get("sin_datos"):
            errores["dolar"] = "; ".join(resultado_dolar["sin_datos"])
    except Exception as e:
        errores["dolar"] = str(e)

    try:
        hoy = date.today()
        web_bursatil_tools.obtener_precios_mes(hoy.year, hoy.month)
    except Exception as e:
        errores["bursatil"] = str(e)

    con = get_conn_for(str(estado_ingesta.DB_PATH))
    try:
        estado = estado_ingesta.estado_ingesta(con)
    finally:
        con.close()

    return jsonify({"ok": not errores, "errores": errores, **estado})


@app.get("/api/estado_ingesta/timeline_range")
def api_estado_ingesta_timeline_range():
    tipo_id = request.args.get("tipo", "")
    try:
        offset_min = int(request.args.get("offset_min", "-8"))
        offset_max = int(request.args.get("offset_max", "1"))
    except ValueError:
        return jsonify({"error": "offset_min/offset_max inválidos"}), 400
    if tipo_id not in {c["id"] for c in estado_ingesta.CONFIG}:
        return jsonify({"error": f"tipo desconocido: {tipo_id}"}), 400
    if offset_min > offset_max:
        return jsonify({"error": "offset_min no puede ser mayor que offset_max"}), 400
    con = get_conn_for(str(estado_ingesta.DB_PATH))
    try:
        return jsonify(estado_ingesta.timeline_rango(con, tipo_id, date.today(), offset_min, offset_max))
    finally:
        con.close()


@app.get("/api/prompt/<fondo>")
def get_prompt(fondo: str):
    fondo = fondo.upper()
    filename = FONDO_FILE.get(fondo)
    if not filename:
        return jsonify({"error": f"Fondo {fondo!r} inválido"}), 400
    path = PROMPTS_DIR / filename
    if not path.exists():
        return jsonify({"error": f"No existe {path.name}"}), 404
    markdown_text = path.read_text(encoding="utf-8")
    return jsonify({"prompt_text": _extract_fenced_block(markdown_text)})


@app.get("/api/eeff/periodo_check")
def api_eeff_periodo_check():
    fondo = request.args.get("fondo", "").upper()
    periodo = request.args.get("periodo", "")
    if not fondo or not periodo:
        return jsonify({"ya_ingestado": False})
    existentes = core._periodos_existentes(fondo, [periodo])
    n = existentes.get(periodo, 0)
    return jsonify({"ya_ingestado": bool(n), "n_filas": n})


@app.get("/api/rentroll/periodo_check")
def api_rentroll_periodo_check():
    proveedor = request.args.get("proveedor", "")
    periodo = request.args.get("periodo", "")
    if not proveedor or not periodo or proveedor not in PROVEEDOR_ACTIVOS:
        return jsonify({"ya_ingestado": False})
    activos = PROVEEDOR_ACTIVOS[proveedor]
    DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"
    con = get_conn_for(str(DB_PATH))
    try:
        ocupados = {}
        for activo in activos:
            n = con.execute(
                "SELECT COUNT(*) FROM raw_rent_roll_line "
                "WHERE activo_key=? AND periodo=? AND superseded_at IS NULL",
                (activo, periodo),
            ).fetchone()[0]
            if n:
                ocupados[activo] = n
        return jsonify({"ya_ingestado": bool(ocupados), "ocupados": ocupados})
    finally:
        con.close()


@app.post("/api/validate")
def api_validate():
    body = request.get_json(force=True, silent=True) or {}
    fondo = str(body.get("fondo", "")).upper()
    texto = body.get("texto", "")
    periodo_declarado = body.get("periodo_declarado", "")
    fecha_publicacion = body.get("fecha_publicacion", "")
    if not texto.strip():
        return jsonify({"ok": False, "errors": ["Pega la respuesta de ChatGPT antes de validar."], "warnings": []})
    result = core.validate(texto, fondo, periodo_declarado, fecha_publicacion)
    return jsonify(result.to_dict())


@app.post("/api/ingest")
def api_ingest():
    body = request.get_json(force=True, silent=True) or {}
    fondo = str(body.get("fondo", "")).upper()
    texto = body.get("texto", "")
    periodo_declarado = body.get("periodo_declarado", "")
    fecha_publicacion = body.get("fecha_publicacion", "")
    try:
        summary = core.commit(texto, fondo, periodo_declarado, fecha_publicacion)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.post("/api/rentroll/validate")
def api_rentroll_validate():
    file = request.files.get("file")
    periodo = request.form.get("periodo", "")
    if file is None or not file.filename:
        return jsonify({"ok": False, "errors": ["Sube el archivo .xlsx del Rent Roll."], "warnings": []})
    file_bytes = file.read()

    es_v2, ruta = _es_jll_v2(file_bytes, file.filename)
    if es_v2:
        from tools.db import ingest_jll_planilla as jll_v2
        try:
            informe = jll_v2.validate(
                ruta, str(ROOT / "memory" / "agente_toesca_v2.db"),
                source_name=file.filename,
            )
        finally:
            os.unlink(ruta)
        errores, avisos = [], []
        if informe["motivo_bloqueo"]:
            errores.append(informe["motivo_bloqueo"])
        for tipo, n in sorted(informe["anomalias"]["por_tipo"].items()):
            destino = errores if tipo in jll_v2.ANOMALIAS_BLOQUEANTES else avisos
            destino.append(f"{n} filas con anomalía '{tipo}'")
        for c in informe["conflictos_semantica"]:
            errores.append(
                f"{c['activo_key']} {c['periodo']}: ya hay renta con semántica "
                f"{', '.join(c['semanticas_vivas'])}; convertir el período antes de ingestar"
            )
        if informe["mapeo_er"]["unmapped"]:
            avisos.append(
                f"{informe['mapeo_er']['unmapped']} movimientos sin cuenta de ER "
                f"({len(informe['mapeo_er']['rubros_sin_mapping'])} rubros); "
                "se guardan en crudo como 'unmapped'"
            )
        return jsonify({
            "ok": informe["puede_commitear"],
            "formato": "jll_v2",
            "errors": errores,
            "warnings": avisos,
            "periodos": informe["periodos"],
            "filas_por_hoja": informe["filas_por_hoja"],
            "reemplazara": informe["reemplazara"],
            "anomalias": informe["anomalias"],
        })
    if ruta:
        os.unlink(ruta)

    if not periodo:
        return jsonify({"ok": False, "errors": ["Falta el período (YYYY-MM)."], "warnings": []})
    try:
        result = _con_archivo_legible(rr_core.validate, file_bytes, file.filename, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result.to_dict())


@app.post("/api/rentroll/commit")
def api_rentroll_commit():
    file = request.files.get("file")
    periodo = request.form.get("periodo", "")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "Sube el archivo .xlsx del Rent Roll."}), 400
    file_bytes = file.read()

    es_v2, ruta = _es_jll_v2(file_bytes, file.filename)
    if es_v2:
        from tools.db import ingest_jll_planilla as jll_v2
        aceptar = request.form.get("aceptar_anomalias") == "1"
        try:
            summary = jll_v2.commit(
                ruta, str(ROOT / "memory" / "agente_toesca_v2.db"),
                aceptar_anomalias=aceptar,
                source_name=file.filename,
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            os.unlink(ruta)
        if summary["status"] != "ok":
            return jsonify({"ok": False, "formato": "jll_v2", **summary}), 400
        _rebuild_factsheet()
        return jsonify({"ok": True, "formato": "jll_v2", **summary})
    if ruta:
        os.unlink(ruta)

    if not periodo:
        return jsonify({"ok": False, "error": "Falta el período (YYYY-MM)."}), 400
    try:
        summary = rr_core.commit(file_bytes, file.filename, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.get("/api/mercado/periodo_check")
def api_mercado_periodo_check():
    periodo = request.args.get("periodo", "")
    proveedor = request.args.get("proveedor", "JLL")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    con = get_conn_for(str(mercado_core.DB_PATH))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas "
            "WHERE periodo=? AND proveedor=? AND superseded_at IS NULL",
            (periodo, proveedor),
        ).fetchone()[0]
        return jsonify({"ya_ingestado": bool(n), "n_filas": n})
    finally:
        con.close()


@app.post("/api/mercado/validate")
def api_mercado_validate():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    proveedor = body.get("proveedor", "JLL")
    result = mercado_core.validate(texto, periodo, proveedor)
    return jsonify(result.to_dict())


@app.post("/api/mercado/commit")
def api_mercado_commit():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    proveedor = body.get("proveedor", "JLL")
    try:
        summary = mercado_core.commit(texto, periodo, proveedor)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.get("/api/mercado/bodegas/periodo_check")
def api_mercado_bodegas_periodo_check():
    periodo = request.args.get("periodo", "")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    con = get_conn_for(str(mercado_bodegas_core.DB_PATH))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_bodegas "
            "WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        return jsonify({"ya_ingestado": bool(n), "n_filas": n})
    finally:
        con.close()


@app.post("/api/mercado/bodegas/validate")
def api_mercado_bodegas_validate():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    result = mercado_bodegas_core.validate(texto, periodo)
    return jsonify(result.to_dict())


@app.post("/api/mercado/bodegas/commit")
def api_mercado_bodegas_commit():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    try:
        summary = mercado_bodegas_core.commit(texto, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.get("/api/mercado/comercio/periodo_check")
def api_mercado_comercio_periodo_check():
    periodo = request.args.get("periodo", "")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    con = get_conn_for(str(mercado_comercio_core.DB_PATH))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_comercio "
            "WHERE periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        return jsonify({"ya_ingestado": bool(n), "n_filas": n})
    finally:
        con.close()


@app.post("/api/mercado/comercio/validate")
def api_mercado_comercio_validate():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    result = mercado_comercio_core.validate(texto, periodo)
    return jsonify(result.to_dict())


@app.post("/api/mercado/comercio/commit")
def api_mercado_comercio_commit():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    try:
        summary = mercado_comercio_core.commit(texto, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.get("/api/mercado/variacion_rm/ultimo_periodo")
def api_variacion_comercio_rm_ultimo_periodo():
    con = get_conn_for(str(variacion_comercio_rm_core.DB_PATH))
    try:
        row = con.execute(
            "SELECT MAX(periodo) FROM raw_variacion_comercio_rm WHERE superseded_at IS NULL"
        ).fetchone()
        return jsonify({"ultimo_periodo": row[0] if row else None})
    finally:
        con.close()


@app.post("/api/mercado/variacion_rm/validate")
def api_variacion_comercio_rm_validate():
    comercio = request.files.get("comercio")
    supermercado = request.files.get("supermercado")
    if comercio is None or not comercio.filename:
        return jsonify({"ok": False, "errors": ["Sube el XLSX histórico de Índice de Ventas del Comercio RM."], "warnings": []})
    if supermercado is None or not supermercado.filename:
        return jsonify({"ok": False, "errors": ["Sube el XLSX histórico de Índice de Ventas de Supermercados RM."], "warnings": []})
    try:
        result = _con_archivo_legible(
            variacion_comercio_rm_core.validate,
            comercio.read(), comercio.filename, supermercado.read(), supermercado.filename,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result.to_dict())


@app.post("/api/mercado/variacion_rm/commit")
def api_variacion_comercio_rm_commit():
    comercio = request.files.get("comercio")
    supermercado = request.files.get("supermercado")
    if comercio is None or not comercio.filename:
        return jsonify({"ok": False, "error": "Sube el XLSX histórico de Índice de Ventas del Comercio RM."}), 400
    if supermercado is None or not supermercado.filename:
        return jsonify({"ok": False, "error": "Sube el XLSX histórico de Índice de Ventas de Supermercados RM."}), 400
    try:
        summary = _con_archivo_legible(
            variacion_comercio_rm_core.commit,
            comercio.read(), comercio.filename, supermercado.read(), supermercado.filename,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.get("/api/parking/periodo_check")
def api_parking_periodo_check():
    periodo = request.args.get("periodo", "")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"
    con = get_conn_for(str(DB_PATH))
    try:
        n_res = con.execute(
            "SELECT COUNT(*) FROM raw_parking_ingreso_line "
            "WHERE activo_key='Parking PT' AND periodo=? AND superseded_at IS NULL",
            (periodo,),
        ).fetchone()[0]
        n_tk = con.execute(
            "SELECT COUNT(*) FROM raw_parking_ticket_line "
            "WHERE activo_key='Parking PT' AND fecha LIKE ? AND superseded_at IS NULL",
            (f"{periodo}-%",),
        ).fetchone()[0]
        return jsonify({
            "ya_ingestado": bool(n_res or n_tk),
            "n_ingresos": n_res, "n_tickets": n_tk,
        })
    finally:
        con.close()


@app.post("/api/parking/validate")
def api_parking_validate():
    file = request.files.get("file")
    periodo = request.form.get("periodo", "")
    if file is None or not file.filename:
        return jsonify({"ok": False, "errors": ["Sube el archivo .xlsx de la liquidación."], "warnings": []})
    if not periodo:
        return jsonify({"ok": False, "errors": ["Falta el período (YYYY-MM)."], "warnings": []})
    try:
        result = _con_archivo_legible(parking_core.validate, file.read(), file.filename, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result.to_dict())


@app.post("/api/parking/commit")
def api_parking_commit():
    file = request.files.get("file")
    periodo = request.form.get("periodo", "")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "Sube el archivo .xlsx de la liquidación."}), 400
    if not periodo:
        return jsonify({"ok": False, "error": "Falta el período (YYYY-MM)."}), 400
    try:
        summary = parking_core.commit(file.read(), file.filename, periodo)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.get("/api/balance/periodo_check")
def api_balance_periodo_check():
    periodo = request.args.get("periodo", "")
    if not periodo:
        return jsonify({"ya_ingestado": False, "fondos": {}})
    con = get_conn_for(str(balance_core.DB_PATH))
    try:
        rows = con.execute(
            "SELECT fondo_key, COUNT(*) FROM raw_balance_consolidado_line "
            "WHERE periodo=? AND superseded_at IS NULL GROUP BY fondo_key",
            (periodo,),
        ).fetchall()
        fondos = {row[0]: row[1] for row in rows}
        return jsonify({"ya_ingestado": bool(fondos), "fondos": fondos})
    finally:
        con.close()


@app.post("/api/balance/validate")
def api_balance_validate():
    file = request.files.get("file")
    periodo = request.form.get("periodo", "")
    unidad = request.form.get("unidad", "M$")
    if file is None or not file.filename:
        return jsonify({"ok": False, "errors": ["Sube la planilla .xlsx de balances consolidados."], "warnings": []})
    if not periodo:
        return jsonify({"ok": False, "errors": ["Falta el periodo (YYYY-MM)."], "warnings": []})
    try:
        result = _con_archivo_legible(balance_core.validate, file.read(), file.filename, periodo, unidad)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result.to_dict())


@app.post("/api/balance/commit")
def api_balance_commit():
    file = request.files.get("file")
    periodo = request.form.get("periodo", "")
    unidad = request.form.get("unidad", "M$")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "Sube la planilla .xlsx de balances consolidados."}), 400
    if not periodo:
        return jsonify({"ok": False, "error": "Falta el periodo (YYYY-MM)."}), 400
    try:
        summary = balance_core.commit(file.read(), file.filename, periodo, unidad)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, **summary})


@app.get("/api/er_activo/periodo_check")
def api_er_activo_periodo_check():
    activo = request.args.get("activo", "")
    try:
        return jsonify(er_activo_core.periodo_status(activo))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/er_activo/validate")
def api_er_activo_validate():
    activo = request.form.get("activo", "")
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "errors": ["Sube el archivo .xlsx de ingresos/NOI."], "warnings": []})
    try:
        result = _con_archivo_legible(er_activo_core.validate, activo, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result)


@app.post("/api/er_activo/commit")
def api_er_activo_commit():
    activo = request.form.get("activo", "")
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "Sube el archivo .xlsx de ingresos/NOI."}), 400
    try:
        summary = er_activo_core.commit(activo, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not summary.get("ok", True):
        return jsonify(summary), 400
    _rebuild_factsheet()
    return jsonify(summary)


@app.get("/api/er_fijo/periodo_check")
def api_er_fijo_periodo_check():
    from tools.db.connection import get_conn
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(periodo) AS m, COUNT(*) AS n FROM raw_er_activo_line "
            "WHERE activo_key='Sucden' AND superseded_at IS NULL",
        ).fetchone()
        return jsonify({"ultimo_periodo": row["m"], "n_filas": row["n"]})
    finally:
        conn.close()


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


@app.get("/api/er_fijo/valores")
def api_er_fijo_valores():
    return jsonify(sucden_fijo_core.valores_vigentes())


@app.post("/api/er_fijo/validate")
def api_er_fijo_validate():
    data = _json_body()
    periodo = data.get("periodo") or request.form.get("periodo", "")
    overrides = data.get("overrides") or {}
    if not periodo:
        return jsonify({"ok": False, "errors": ["Falta el período (YYYY-MM)."], "warnings": []})
    return jsonify(sucden_fijo_core.validate_periodo(periodo, overrides=overrides))


@app.post("/api/er_fijo/commit")
def api_er_fijo_commit():
    data = _json_body()
    periodo = data.get("periodo") or request.form.get("periodo", "")
    overrides = data.get("overrides") or {}
    permanentes = data.get("permanentes") or []
    if not periodo:
        return jsonify({"ok": False, "error": "Falta el período (YYYY-MM)."}), 400
    try:
        summary = sucden_fijo_core.persist_periodo(periodo, overrides=overrides, permanentes=permanentes)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    _rebuild_factsheet()
    return jsonify({"ok": True, "activo": "Sucden", "periodo": periodo, **summary})


@app.get("/api/er_mensual/periodo_check")
def api_er_mensual_periodo_check():
    activo = request.args.get("activo", "")
    try:
        return jsonify(er_activo_core.periodo_status_mensual(activo))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/er_mensual/validate")
def api_er_mensual_validate():
    activo = request.form.get("activo", "")
    periodo = request.form.get("periodo", "")
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "errors": ["Sube la planilla EEFF del mes."], "warnings": []})
    if not periodo:
        return jsonify({"ok": False, "errors": ["Falta el período (YYYY-MM)."], "warnings": []})
    try:
        result = _con_archivo_legible(er_activo_core.validate_mensual, activo, periodo, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result)


@app.post("/api/er_mensual/commit")
def api_er_mensual_commit():
    activo = request.form.get("activo", "")
    periodo = request.form.get("periodo", "")
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "Sube la planilla EEFF del mes."}), 400
    if not periodo:
        return jsonify({"ok": False, "error": "Falta el período (YYYY-MM)."}), 400
    try:
        summary = er_activo_core.commit_mensual(activo, periodo, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not summary.get("ok", True):
        return jsonify(summary), 400
    _rebuild_factsheet()
    return jsonify(summary)


@app.get("/api/amort_extra/creditos")
def api_amort_extra_creditos():
    con = get_conn_for(str(amort_extra_core.DB_PATH))
    try:
        return jsonify({"creditos": amort_extra_core.listar_creditos(con)})
    finally:
        con.close()


@app.get("/api/amort_extra/historial")
def api_amort_extra_historial():
    credito_key = request.args.get("credito_key", "")
    if not credito_key:
        return jsonify({"eventos": []})
    con = get_conn_for(str(amort_extra_core.DB_PATH))
    try:
        return jsonify({"eventos": amort_extra_core.historial(con, credito_key)})
    finally:
        con.close()


@app.post("/api/amort_extra/commit")
def api_amort_extra_commit():
    data = _json_body()
    credito_key = data.get("credito_key", "")
    fecha = data.get("fecha", "")
    monto_uf = data.get("monto_uf")
    nota = data.get("nota") or None
    if not credito_key or not fecha or monto_uf is None:
        return jsonify({"ok": False, "error": "Faltan credito_key, fecha o monto_uf."}), 400
    con = get_conn_for(str(amort_extra_core.DB_PATH))
    try:
        result = amort_extra_core.commit(con, credito_key, fecha, float(monto_uf), nota)
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        con.close()
    _rebuild_factsheet()
    return jsonify({"ok": True, **result})


@app.get("/api/caja/periodo_check")
def api_caja_periodo_check():
    return jsonify(caja_core.periodo_status())


@app.post("/api/caja/validate")
def api_caja_validate():
    periodo = request.form.get("periodo", "")
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "errors": ["Sube la planilla Saldo Caja + FFMM Inmobiliario."], "warnings": []})
    if not periodo:
        return jsonify({"ok": False, "errors": ["Falta el período (YYYY-MM)."], "warnings": []})
    try:
        result = _con_archivo_legible(caja_core.validate, periodo, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result)


@app.post("/api/caja/commit")
def api_caja_commit():
    periodo = request.form.get("periodo", "")
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "Sube la planilla Saldo Caja + FFMM Inmobiliario."}), 400
    if not periodo:
        return jsonify({"ok": False, "error": "Falta el período (YYYY-MM)."}), 400
    try:
        summary = _con_archivo_legible(caja_core.commit, periodo, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not summary.get("ok", True):
        return jsonify(summary), 400
    _rebuild_factsheet()
    return jsonify(summary)


@app.get("/api/ocupacion/status")
def api_ocupacion_status():
    return jsonify(ocupacion_core.status())


@app.post("/api/ocupacion/validate")
def api_ocupacion_validate():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "errors": ["Sube la planilla Ocupacion Acalis."], "warnings": []})
    try:
        result = _con_archivo_legible(ocupacion_core.validate, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)], "warnings": []})
    return jsonify(result)


@app.post("/api/ocupacion/commit")
def api_ocupacion_commit():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "Sube la planilla Ocupacion Acalis."}), 400
    try:
        summary = _con_archivo_legible(ocupacion_core.commit, file.read(), file.filename)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not summary.get("ok", True):
        return jsonify(summary), 400
    _rebuild_factsheet()
    return jsonify(summary)


@app.post("/api/export-pdf")
def api_export_pdf():
    body = request.get_json(force=True, silent=True) or {}
    fondos = body.get("fondos")
    periodo_cb = str(body.get("periodo_cb", ""))
    periodo_op = str(body.get("periodo_op", ""))

    if not isinstance(fondos, list) or not fondos:
        return jsonify({"ok": False, "error": "Falta seleccionar al menos un fondo."}), 400
    if not periodo_cb or not periodo_op:
        return jsonify({"ok": False, "error": "Faltan los períodos (operacional y EEFF)."}), 400

    pdfs, errores = _generar_pdfs_factsheet(fondos, periodo_cb, periodo_op)

    if not pdfs:
        return jsonify({
            "ok": False,
            "error": "No se pudo generar ningún PDF. " + " ".join(errores),
        }), 422

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fondo, pdf_bytes in pdfs.items():
            zf.writestr(f"FS_{fondo}_{periodo_op}_{periodo_cb}.pdf", pdf_bytes)
        if errores:
            zf.writestr("errores.txt", "\n".join(errores))
    buf.seek(0)

    response = send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="factsheets.zip",
    )
    response.headers["X-Export-Ok"] = str(len(pdfs))
    response.headers["X-Export-Errors"] = str(len(errores))
    return response


if __name__ == "__main__":
    print("Ingesta EEFF: http://127.0.0.1:8765/ingesta")
    print("Factsheet:    http://127.0.0.1:8765/factsheet")
    if _lan_ip_addr:
        print(f"\nAcceso desde la red local (mismo IP/red de la oficina):")
        print(f"  Ingesta:   http://{_lan_ip_addr}:8765/ingesta")
        print(f"  Factsheet: http://{_lan_ip_addr}:8765/factsheet")
        print(f"  DB diagrama: http://{_lan_ip_addr}:8765/db-diagrama")
    if not os.environ.get("INGESTA_TOKEN"):
        print(
            f"\nToken de esta sesión: {API_TOKEN}\n"
            "  (se inyecta solo en las páginas que sirve este servidor; fija\n"
            "   INGESTA_TOKEN en el .env si quieres uno estable entre reinicios)"
        )
    # host=0.0.0.0: escucha en todas las interfaces, no solo loopback, para
    # que el resto del equipo entre desde su propio navegador en la misma
    # red. debug=False: el debugger de Werkzeug expone una consola
    # interactiva a cualquier proceso que alcance el puerto. threaded=True:
    # /api/export-pdf abre la propia URL del factsheet vía Playwright
    # mientras la petición POST sigue en curso — sin esto el server
    # single-threaded se deadlockea consigo mismo.
    app.run(host="0.0.0.0", port=8765, debug=False, use_reloader=False, threaded=True)
