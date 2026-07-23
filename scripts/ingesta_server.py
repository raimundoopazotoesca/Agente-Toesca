"""Servidor local para la pantalla de ingesta EEFF vía ChatGPT (copy/paste).

Uso:
    python -m scripts.ingesta_server
    → abre http://localhost:8765/ingesta

No requiere API keys propias: el usuario copia un prompt, lo corre en su
ChatGPT junto al PDF del EEFF, y pega la respuesta de vuelta en la página.
El servidor solo valida y persiste; nunca llama a ningún LLM.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db import ingest_eeff_validated as core  # noqa: E402
from tools.db import ingest_rent_roll_validated as rr_core  # noqa: E402
from tools.db import ingest_mercado as mercado_core  # noqa: E402
from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import estado_ingesta  # noqa: E402
from scripts import build_factsheet  # noqa: E402


def _rebuild_factsheet() -> None:
    """Regenera factsheet.html para que toda ingesta se refleje de inmediato."""
    try:
        build_factsheet.main()
    except Exception as exc:  # no debe romper la respuesta de ingesta
        print(f"WARN: no se pudo regenerar factsheet.html: {exc}")

app = Flask(__name__, static_folder=None)

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


@app.get("/ingesta")
def serve_page():
    return send_from_directory(WEB_DIR, "ingesta.html")


@app.get("/api/estado_ingesta")
def api_estado_ingesta():
    con = get_conn_for(str(estado_ingesta.DB_PATH))
    try:
        return jsonify(estado_ingesta.estado_ingesta(con))
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
    result = rr_core.validate(file_bytes, file.filename, periodo)
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


if __name__ == "__main__":
    print("Ingesta EEFF: http://localhost:8765/ingesta")
    app.run(host="127.0.0.1", port=8765, debug=True, use_reloader=True)
