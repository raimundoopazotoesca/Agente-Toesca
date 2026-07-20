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

app = Flask(__name__, static_folder=None)

PROMPTS_DIR = ROOT / "prompts"
WEB_DIR = ROOT / "web"

FONDO_FILE = {"TRI": "eeff_tri.md", "PT": "eeff_pt.md", "APO": "eeff_apo.md"}


def _extract_fenced_block(markdown_text: str) -> str:
    """Devuelve el contenido del primer bloque ``` ... ``` (el prompt copiable)."""
    match = re.search(r"```(?:\w+)?\n(.*?)```", markdown_text, re.DOTALL)
    return match.group(1).strip() if match else markdown_text.strip()


@app.get("/ingesta")
def serve_page():
    return send_from_directory(WEB_DIR, "ingesta.html")


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


@app.post("/api/validate")
def api_validate():
    body = request.get_json(force=True, silent=True) or {}
    fondo = str(body.get("fondo", "")).upper()
    texto = body.get("texto", "")
    if not texto.strip():
        return jsonify({"ok": False, "errors": ["Pega la respuesta de ChatGPT antes de validar."], "warnings": []})
    result = core.validate(texto, fondo)
    return jsonify(result.to_dict())


@app.post("/api/ingest")
def api_ingest():
    body = request.get_json(force=True, silent=True) or {}
    fondo = str(body.get("fondo", "")).upper()
    texto = body.get("texto", "")
    try:
        summary = core.commit(texto, fondo)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **summary})


if __name__ == "__main__":
    print("Ingesta EEFF: http://localhost:8765/ingesta")
    app.run(host="127.0.0.1", port=8765, debug=False)
