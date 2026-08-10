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
from datetime import date
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
from tools.db import ingest_parking_pt_mensual as parking_core  # noqa: E402
from tools.db import ingest_balance_consolidado as balance_core  # noqa: E402
from tools.db import ingest_er_activo_web as er_activo_core  # noqa: E402
from tools.db import ingest_er_sucden_fijo as sucden_fijo_core  # noqa: E402
from tools.db import ingest_amortizacion_extra as amort_extra_core  # noqa: E402
from tools.db import ingest_caja_web as caja_core  # noqa: E402
from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import estado_ingesta  # noqa: E402
from tools import db_chat  # noqa: E402
from scripts import build_factsheet  # noqa: E402
from scripts import recompute_derived_kpis  # noqa: E402


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
    resp = send_from_directory(WEB_DIR, "chat_bubble.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.post("/api/chat")
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    question = str(body.get("question", ""))
    history = body.get("history") or []
    if not isinstance(history, list):
        history = []
    # No hay autenticación por usuario (token es compartido); usamos la IP
    # del cliente como session_id de conversación, único identificador que
    # ya nos da Flask sin inventar un mecanismo nuevo.
    session_id = request.remote_addr or "default"
    try:
        result = db_chat.answer(question, history, session_id=session_id)
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
