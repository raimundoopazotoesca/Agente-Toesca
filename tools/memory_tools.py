"""
Memoria persistente del agente.

Archivos:
  memory/context.md        — conocimiento acumulado (editable por el agente)
  memory/historial.jsonl   — log de tareas completadas (append-only)
"""
import json
import os
from datetime import datetime

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")
CONTEXT_FILE = os.path.join(MEMORY_DIR, "context.md")
HISTORIAL_FILE = os.path.join(MEMORY_DIR, "historial.jsonl")


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


# ── Uso interno (run_agent) ────────────────────────────────────────────────────

def load_memory(n_recientes: int = 10) -> str:
    """
    Retorna un bloque de texto para inyectar en el system prompt:
    contexto acumulado + últimas N tareas del historial.
    Retorna "" si no hay nada todavía.
    """
    _ensure_dir()
    parts = []

    if os.path.isfile(CONTEXT_FILE):
        content = open(CONTEXT_FILE, encoding="utf-8").read().strip()
        if content:
            parts.append(f"## Conocimiento acumulado\n{content}")

    if os.path.isfile(HISTORIAL_FILE):
        lines = [l.strip() for l in open(HISTORIAL_FILE, encoding="utf-8") if l.strip()]
        recientes = lines[-n_recientes:]
        entries = []
        for l in recientes:
            try:
                e = json.loads(l)
                entries.append(
                    f"- [{e.get('fecha','')}] {e.get('instruccion','')} "
                    f"→ {e.get('resumen','')}"
                )
            except Exception:
                pass
        if entries:
            parts.append("## Tareas recientes\n" + "\n".join(entries))

    return "\n\n".join(parts)


def guardar_tarea(instruccion: str, herramientas: list[str], resumen: str) -> None:
    """Registra una tarea completada en historial.jsonl."""
    _ensure_dir()
    entry = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "instruccion": instruccion,
        "herramientas": herramientas,
        "resumen": resumen,
    }
    with open(HISTORIAL_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Tools expuestas al agente ──────────────────────────────────────────────────

def leer_contexto() -> str:
    """Lee el contexto acumulado actual."""
    _ensure_dir()
    if not os.path.isfile(CONTEXT_FILE):
        return "Sin contexto acumulado todavía."
    content = open(CONTEXT_FILE, encoding="utf-8").read().strip()
    return content or "Sin contexto acumulado todavía."


def actualizar_contexto(contenido: str) -> str:
    """
    Reemplaza context.md con el contenido dado.
    Usar cuando se aprende algo nuevo importante sobre el negocio o los datos.
    """
    _ensure_dir()
    with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
        f.write(contenido.strip() + "\n")
    return "Contexto actualizado."


def leer_historial(n: int = 20) -> str:
    """Retorna los últimos N registros del historial en formato legible."""
    _ensure_dir()
    if not os.path.isfile(HISTORIAL_FILE):
        return "Sin historial todavía."
    lines = [l.strip() for l in open(HISTORIAL_FILE, encoding="utf-8") if l.strip()]
    if not lines:
        return "Sin historial todavía."
    resultado = []
    for l in lines[-n:]:
        try:
            e = json.loads(l)
            herr = ", ".join(e.get("herramientas", []))
            resultado.append(
                f"[{e.get('fecha','')}] {e.get('instruccion','')}\n"
                f"  Tools: {herr}\n"
                f"  Resumen: {e.get('resumen','')}"
            )
        except Exception:
            resultado.append(l)
    return "\n\n".join(resultado)
