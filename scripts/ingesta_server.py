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
"""
from __future__ import annotations

import hmac
import os
import re
import secrets
import sys
import zipfile
from datetime import date
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_from_directory
from openpyxl.utils.exceptions import InvalidFileException
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db import ingest_eeff_validated as core  # noqa: E402
from tools.db import ingest_rent_roll_validated as rr_core  # noqa: E402
from tools.db import ingest_mercado as mercado_core  # noqa: E402
from tools.db import ingest_parking_pt_mensual as parking_core  # noqa: E402
from tools.db import ingest_balance_consolidado as balance_core  # noqa: E402
from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import estado_ingesta  # noqa: E402
from tools import db_chat  # noqa: E402
from scripts import build_factsheet  # noqa: E402


def _rebuild_factsheet() -> None:
    """Regenera factsheet.html para que toda ingesta se refleje de inmediato."""
    try:
        build_factsheet.main()
    except Exception as exc:  # no debe romper la respuesta de ingesta
        print(f"WARN: no se pudo regenerar factsheet.html: {exc}")

app = Flask(__name__, static_folder=None)

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

# Orígenes permitidos para CORS. No se refleja un Origin arbitrario y "null"
# (factsheet abierto como file://) ya no se acepta: abrir el factsheet desde
# http://127.0.0.1:8765/factsheet lo deja con el token inyectado.
_CORS_ORIGINS = frozenset(
    f"http://{host}:8765" for host in ("127.0.0.1", "localhost", "[::1]")
)


def _token_ok() -> bool:
    supplied = request.headers.get(TOKEN_HEADER, "")
    return bool(supplied) and hmac.compare_digest(supplied, API_TOKEN)


@app.before_request
def _require_token():
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


@app.after_request
def _add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin in _CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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
    return send_from_directory(WEB_DIR, "chat_bubble.js", mimetype="application/javascript")


@app.post("/api/chat")
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    question = str(body.get("question", ""))
    history = body.get("history") or []
    if not isinstance(history, list):
        history = []
    try:
        result = db_chat.answer(question, history)
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "answer_md": f"⚠️ Error inesperado: {exc}",
            "error": "server_error",
        }), 500
    return jsonify(result)


@app.get("/api/estado_ingesta")
def api_estado_ingesta():
    con = get_conn_for(str(estado_ingesta.DB_PATH))
    try:
        return jsonify(estado_ingesta.estado_ingesta(con))
    finally:
        con.close()


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
    if not periodo:
        return jsonify({"ok": False, "errors": ["Falta el período (YYYY-MM)."], "warnings": []})
    file_bytes = file.read()
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
    if not periodo:
        return jsonify({"ok": False, "error": "Falta el período (YYYY-MM)."}), 400
    file_bytes = file.read()
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


if __name__ == "__main__":
    print("Ingesta EEFF: http://127.0.0.1:8765/ingesta")
    print("Factsheet:    http://127.0.0.1:8765/factsheet")
    if not os.environ.get("INGESTA_TOKEN"):
        print(
            f"\nToken de esta sesión: {API_TOKEN}\n"
            "  (se inyecta solo en las páginas que sirve este servidor; fija\n"
            "   INGESTA_TOKEN en el .env si quieres uno estable entre reinicios)"
        )
    # debug=False: el debugger de Werkzeug expone una consola interactiva a
    # cualquier proceso local que alcance el puerto.
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)
