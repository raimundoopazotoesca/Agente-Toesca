"""
Memoria persistente del agente.

Archivos:
  memory/context.md        — conocimiento acumulado (editable por el agente)
  memory/historial.jsonl   — log de tareas completadas (append-only)
  memory/kpis.jsonl        — log estructurado de KPIs por fondo/período

KPIs soportados:
  valor_cuota_bursatil     — valor cuota de mercado (CLP)
  valor_cuota_contable     — valor cuota libro (CLP)
  noi                      — Net Operating Income (CLP)
  rcsd                     — Debt Service Coverage Ratio
  tir                      — TIR del fondo (%)
  ltv                      — Loan to Value (%)
  dividend_yield           — Dividend yield (%)
  dividendo_por_cuota      — Dividendo pagado por cuota (CLP)
  aporte_por_cuota         — Aporte de capital por cuota (CLP)
  vacancia                 — Tasa de vacancia (%)
  superficie_vacante       — Superficie vacante (m²)
  ingresos_arriendo        — Ingresos por arriendo (CLP)
"""
import json
import os
from datetime import datetime

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")
CONTEXT_FILE = os.path.join(MEMORY_DIR, "context.md")
HISTORIAL_FILE = os.path.join(MEMORY_DIR, "historial.jsonl")
KPIS_FILE = os.path.join(MEMORY_DIR, "kpis.jsonl")


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


# ── KPIs ───────────────────────────────────────────────────────────────────────

def registrar_kpi(fondo: str, periodo: str, kpi: str, valor: float,
                  unidad: str = "", fuente: str = "") -> str:
    """
    Registra un KPI para un fondo y período.

    Args:
        fondo:   Nombre del fondo (ej: "A&R PT", "A&R Rentas", "A&R Apoquindo",
                 "Viña Centro", "Mall Curicó", "Parque Titanium", etc.)
        periodo: Período en formato YYYY-MM (ej: "2026-03")
        kpi:     Nombre del KPI (ej: "valor_cuota_bursatil", "noi", "vacancia")
        valor:   Valor numérico
        unidad:  Unidad (ej: "CLP", "%", "m²", "UF") — opcional
        fuente:  Origen del dato (ej: "CMF", "EEFF", "RR JLL") — opcional
    """
    _ensure_dir()
    entry = {
        "fecha_registro": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fondo": fondo,
        "periodo": periodo,
        "kpi": kpi,
        "valor": valor,
        "unidad": unidad,
        "fuente": fuente,
    }
    with open(KPIS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    unidad_str = f" {unidad}" if unidad else ""
    return f"KPI registrado: {fondo} | {periodo} | {kpi} = {valor:,.4f}{unidad_str}"


def consultar_kpi(fondo: str, kpi: str, n_periodos: int = 12) -> str:
    """
    Retorna el historial de un KPI para un fondo, ordenado por período.
    Muestra los últimos n_periodos registros.
    """
    _ensure_dir()
    if not os.path.isfile(KPIS_FILE):
        return "Sin KPIs registrados todavía."

    registros = []
    for l in open(KPIS_FILE, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            e = json.loads(l)
            if e.get("fondo") == fondo and e.get("kpi") == kpi:
                registros.append(e)
        except Exception:
            pass

    if not registros:
        return f"Sin registros de '{kpi}' para '{fondo}'."

    # Ordenar por período y tomar los últimos n
    registros.sort(key=lambda x: x.get("periodo", ""))
    registros = registros[-n_periodos:]

    lines = [f"Historial {kpi} — {fondo} (últimos {len(registros)} períodos):"]
    for e in registros:
        unidad_str = f" {e['unidad']}" if e.get("unidad") else ""
        fuente_str = f" [{e['fuente']}]" if e.get("fuente") else ""
        lines.append(f"  {e['periodo']}: {e['valor']:,.4f}{unidad_str}{fuente_str}")

    # Variación si hay al menos 2 registros
    if len(registros) >= 2:
        v_ant = registros[-2]["valor"]
        v_act = registros[-1]["valor"]
        if v_ant != 0:
            variacion = (v_act - v_ant) / v_ant * 100
            signo = "▲" if variacion >= 0 else "▼"
            lines.append(f"\n  Variación último período: {signo} {abs(variacion):.2f}%")

    return "\n".join(lines)


def resumen_kpis(fondo: str, periodo: str) -> str:
    """
    Muestra todos los KPIs registrados para un fondo en un período específico.
    """
    _ensure_dir()
    if not os.path.isfile(KPIS_FILE):
        return "Sin KPIs registrados todavía."

    registros = []
    for l in open(KPIS_FILE, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            e = json.loads(l)
            if e.get("fondo") == fondo and e.get("periodo") == periodo:
                registros.append(e)
        except Exception:
            pass

    if not registros:
        return f"Sin KPIs para '{fondo}' en período '{periodo}'."

    # Si hay duplicados por kpi, quedarse con el más reciente
    por_kpi: dict = {}
    for e in registros:
        por_kpi[e["kpi"]] = e

    lines = [f"KPIs — {fondo} | {periodo}:"]
    for kpi_name, e in sorted(por_kpi.items()):
        unidad_str = f" {e['unidad']}" if e.get("unidad") else ""
        fuente_str = f" [{e['fuente']}]" if e.get("fuente") else ""
        lines.append(f"  {kpi_name}: {e['valor']:,.4f}{unidad_str}{fuente_str}")

    return "\n".join(lines)


def comparar_periodos(fondo: str, periodo_base: str, periodo_actual: str) -> str:
    """
    Compara todos los KPIs de un fondo entre dos períodos.
    Útil para detectar variaciones y anomalías.
    """
    _ensure_dir()
    if not os.path.isfile(KPIS_FILE):
        return "Sin KPIs registrados todavía."

    def _get_kpis(p: str) -> dict:
        result = {}
        for l in open(KPIS_FILE, encoding="utf-8"):
            l = l.strip()
            if not l:
                continue
            try:
                e = json.loads(l)
                if e.get("fondo") == fondo and e.get("periodo") == p:
                    result[e["kpi"]] = e
            except Exception:
                pass
        return result

    base = _get_kpis(periodo_base)
    actual = _get_kpis(periodo_actual)
    todos_kpis = sorted(set(base) | set(actual))

    if not todos_kpis:
        return f"Sin KPIs para '{fondo}' en los períodos indicados."

    lines = [f"Comparación {fondo} — {periodo_base} vs {periodo_actual}:"]
    lines.append(f"  {'KPI':<30} {'Base':>15} {'Actual':>15} {'Var%':>8}")
    lines.append("  " + "-" * 72)

    for kpi_name in todos_kpis:
        v_base = base.get(kpi_name, {}).get("valor")
        v_act = actual.get(kpi_name, {}).get("valor")
        unidad = (actual.get(kpi_name) or base.get(kpi_name) or {}).get("unidad", "")

        base_str = f"{v_base:,.2f} {unidad}".strip() if v_base is not None else "—"
        act_str = f"{v_act:,.2f} {unidad}".strip() if v_act is not None else "—"

        if v_base and v_act and v_base != 0:
            var = (v_act - v_base) / v_base * 100
            signo = "▲" if var >= 0 else "▼"
            var_str = f"{signo}{abs(var):.1f}%"
        else:
            var_str = "—"

        lines.append(f"  {kpi_name:<30} {base_str:>15} {act_str:>15} {var_str:>8}")

    return "\n".join(lines)
