"""
Memoria persistente del agente (SQLite).

Ubicaciones de archivos se mantienen en JSON porque son globales.
Historial, KPIs y contexto son por usuario.
"""
import json
import os
import sqlite3
from datetime import datetime
import streamlit as st

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")
WIKI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "wiki")
DB_PATH = os.path.join(MEMORY_DIR, "agente_toesca.db")
UBICACIONES_FILE = os.path.join(MEMORY_DIR, "ubicaciones.json")

def _get_user():
    try:
        return st.session_state.get("username", "general")
    except Exception:
        return "general"

def _get_conn():
    return sqlite3.connect(DB_PATH)

def load_memory(n_recientes: int = 10) -> str:
    user = _get_user()
    parts = []
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            # Contexto
            cur.execute("SELECT contenido FROM contexto WHERE username = ?", (user,))
            row = cur.fetchone()
            if row and row[0]:
                parts.append(f"## Conocimiento acumulado\n{row[0]}")
            
            # Tareas
            cur.execute(
                "SELECT fecha, instruccion, resumen FROM historial_chat WHERE username = ? ORDER BY id DESC LIMIT ?",
                (user, n_recientes)
            )
            rows = cur.fetchall()
            if rows:
                entries = []
                for fecha, instr, res in reversed(rows):
                    entries.append(f"- [{fecha}] {instr} → {res}")
                parts.append("## Tareas recientes\n" + "\n".join(entries))
    except Exception as e:
        print("Error loading memory:", e)
    
    return "\n\n".join(parts)


def guardar_tarea(instruccion: str, herramientas: list[str], resumen: str) -> None:
    user = _get_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    herrs = json.dumps(herramientas, ensure_ascii=False)
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO historial_chat (username, fecha, instruccion, herramientas, resumen) VALUES (?, ?, ?, ?, ?)",
                (user, fecha, instruccion, herrs, resumen)
            )
    except Exception as e:
        print("Error saving task:", e)

def leer_contexto() -> str:
    user = _get_user()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT contenido FROM contexto WHERE username = ?", (user,))
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
    return "Sin contexto acumulado todavía."

def actualizar_contexto(contenido: str) -> str:
    user = _get_user()
    with _get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO contexto (username, contenido) VALUES (?, ?)", (user, contenido))
    return "Contexto actualizado."

def leer_historial(n: int = 20) -> str:
    user = _get_user()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT fecha, instruccion, herramientas, resumen FROM historial_chat WHERE username = ? ORDER BY id DESC LIMIT ?",
            (user, n)
        )
        rows = cur.fetchall()
        if not rows:
            return "Sin historial todavía."
        
        resultado = []
        for fecha, instr, herr_str, res in reversed(rows):
            herr = ", ".join(json.loads(herr_str)) if herr_str else ""
            resultado.append(
                f"[{fecha}] {instr}\n  Tools: {herr}\n  Resumen: {res}"
            )
        return "\n\n".join(resultado)

def registrar_kpi(fondo: str, periodo: str, kpi: str, valor: float, unidad: str = "", fuente: str = "") -> str:
    user = _get_user()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO kpis (username, fecha_registro, fondo, periodo, kpi, valor, unidad, fuente) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user, fecha, fondo, periodo, kpi, valor, unidad, fuente)
        )
    unidad_str = f" {unidad}" if unidad else ""
    return f"KPI registrado: {fondo} | {periodo} | {kpi} = {valor:,.4f}{unidad_str}"

def consultar_kpi(fondo: str, kpi: str, n_periodos: int = 12) -> str:
    user = _get_user()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT periodo, valor, unidad, fuente FROM kpis WHERE username = ? AND fondo = ? AND kpi = ? ORDER BY periodo DESC LIMIT ?",
            (user, fondo, kpi, n_periodos)
        )
        rows = cur.fetchall()
        if not rows:
            return f"Sin registros de '{kpi}' para '{fondo}'."
        
        rows.reverse()
        lines = [f"Historial {kpi} — {fondo} (últimos {len(rows)} períodos):"]
        for per, val, uni, fue in rows:
            uni_str = f" {uni}" if uni else ""
            fue_str = f" [{fue}]" if fue else ""
            lines.append(f"  {per}: {val:,.4f}{uni_str}{fue_str}")
        
        if len(rows) >= 2:
            v_ant = rows[-2][1]
            v_act = rows[-1][1]
            if v_ant != 0:
                var = (v_act - v_ant) / v_ant * 100
                signo = "▲" if var >= 0 else "▼"
                lines.append(f"\n  Variación último período: {signo} {abs(var):.2f}%")
        return "\n".join(lines)

def resumen_kpis(fondo: str, periodo: str) -> str:
    user = _get_user()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT kpi, valor, unidad, fuente FROM kpis WHERE username = ? AND fondo = ? AND periodo = ?",
            (user, fondo, periodo)
        )
        rows = cur.fetchall()
        if not rows:
            return f"Sin KPIs para '{fondo}' en período '{periodo}'."
        
        por_kpi = {}
        for kpi, val, uni, fue in rows:
            por_kpi[kpi] = (val, uni, fue)
        
        lines = [f"KPIs — {fondo} | {periodo}:"]
        for kpi, (val, uni, fue) in sorted(por_kpi.items()):
            uni_str = f" {uni}" if uni else ""
            fue_str = f" [{fue}]" if fue else ""
            lines.append(f"  {kpi}: {val:,.4f}{uni_str}{fue_str}")
        return "\n".join(lines)

def comparar_periodos(fondo: str, periodo_base: str, periodo_actual: str) -> str:
    user = _get_user()
    def _get_kpis(p: str):
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT kpi, valor, unidad FROM kpis WHERE username = ? AND fondo = ? AND periodo = ?", (user, fondo, p))
            return {row[0]: (row[1], row[2]) for row in cur.fetchall()}
            
    base = _get_kpis(periodo_base)
    actual = _get_kpis(periodo_actual)
    todos = sorted(set(base) | set(actual))
    
    if not todos:
        return f"Sin KPIs para '{fondo}' en los períodos indicados."
        
    lines = [f"Comparación {fondo} — {periodo_base} vs {periodo_actual}:"]
    lines.append(f"  {'KPI':<30} {'Base':>15} {'Actual':>15} {'Var%':>8}")
    lines.append("  " + "-" * 72)
    
    for kpi in todos:
        v_base, u_base = base.get(kpi, (None, ""))
        v_act, u_act = actual.get(kpi, (None, ""))
        unidad = u_act or u_base or ""
        
        b_str = f"{v_base:,.2f} {unidad}".strip() if v_base is not None else "—"
        a_str = f"{v_act:,.2f} {unidad}".strip() if v_act is not None else "—"
        
        if v_base and v_act and v_base != 0:
            var = (v_act - v_base) / v_base * 100
            signo = "▲" if var >= 0 else "▼"
            v_str = f"{signo}{abs(var):.1f}%"
        else:
            v_str = "—"
            
        lines.append(f"  {kpi:<30} {b_str:>15} {a_str:>15} {v_str:>8}")
        
    return "\n".join(lines)


# ─── Memoria de ubicaciones ────────────────────────────────────────────────────

def _load_ubicaciones() -> dict:
    if not os.path.isfile(UBICACIONES_FILE):
        return {}
    with open(UBICACIONES_FILE, encoding="utf-8") as f:
        return json.load(f)

def _save_ubicaciones(data: dict) -> None:
    with open(UBICACIONES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def guardar_ubicacion(concepto: str, ruta: str, notas: str = "") -> str:
    data = _load_ubicaciones()
    data[concepto.lower().strip()] = {
        "ruta": ruta,
        "notas": notas,
        "actualizado": datetime.now().isoformat(timespec="seconds"),
    }
    _save_ubicaciones(data)
    return f"Ubicación guardada: '{concepto}' → {ruta}"

def buscar_ubicacion(concepto: str) -> str:
    data = _load_ubicaciones()
    if not data:
        return "Sin ubicaciones guardadas todavía."

    termino = concepto.lower().strip()
    if termino in data:
        e = data[termino]
        return f"Ubicación conocida para '{concepto}':\n  Ruta: {e['ruta']}\n  Notas: {e['notas']}\n  (actualizado: {e['actualizado']})"

    matches = [(k, v) for k, v in data.items() if termino in k or k in termino]
    if not matches:
        palabras = termino.split()
        matches = [(k, v) for k, v in data.items() if any(p in k for p in palabras)]

    if not matches:
        return f"No se encontró ubicación guardada para '{concepto}'. Proceder a buscar en disco."

    lines = [f"Ubicaciones conocidas relacionadas con '{concepto}':"]
    for k, v in matches[:5]:
        lines.append(f"  [{k}] {v['ruta']}")
        if v["notas"]:
            lines.append(f"    Notas: {v['notas']}")
    return "\n".join(lines)


def leer_wiki(pagina: str) -> str:
    """Lee una página de la wiki del agente. Ejemplos: 'sharepoint/index', 'index', 'log'."""
    nombre = pagina.strip().rstrip(".md")
    if not nombre.endswith(".md"):
        nombre += ".md"
    ruta = os.path.join(WIKI_DIR, nombre)
    if not os.path.exists(ruta):
        return f"Página wiki no encontrada: {nombre}. Páginas disponibles en wiki/: {os.listdir(WIKI_DIR)}"
    with open(ruta, encoding="utf-8") as f:
        return f.read()
