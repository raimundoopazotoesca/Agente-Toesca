"""
Consultas de solo lectura sobre la DB del agente (Fase 1/4).

El agente usa estas funciones para responder preguntas SIN abrir los Excel.
Si un dato no está en la DB, lo reportan como gap para que el agente decida
abrir la planilla correspondiente.
"""
from tools.db.connection import get_conn
from tools.db import repo_kpi, repo_rent_roll, repo_er_activo, repo_flujo, repo_fact
from tools.db.errors import NotFoundError


def consultar_db_kpi(entidad_tipo: str, entidad_key: str, kpi: str,
                     desde: str | None = None, hasta: str | None = None) -> str:
    """Serie temporal de un KPI desde derived_kpi.

    entidad_tipo: 'fondo' | 'activo' | 'serie'
    entidad_key:  ej. 'PT', 'TRI', 'CFITOERI1A'
    kpi:          ej. 'valor_cuota_libro', 'NOI', 'vacancia'
    desde/hasta:  'YYYY-MM' opcionales.
    """
    with get_conn() as conn:
        rows = repo_kpi.serie_temporal(conn, entidad_tipo, entidad_key, kpi, desde, hasta)
    if not rows:
        return (f"Sin datos en DB para {kpi} de {entidad_tipo} '{entidad_key}'"
                f"{f' ({desde}..{hasta})' if desde or hasta else ''}. "
                "Si el dato debería existir, revisar la planilla.")
    lines = [f"{kpi} — {entidad_tipo} '{entidad_key}' (DB):"]
    for r in rows:
        uni = f" {r['unidad']}" if r["unidad"] else ""
        lines.append(f"  {r['periodo']}: {r['valor']:,.4f}{uni}  [{r['recipe']}]")
    if len(rows) >= 2 and rows[-2]["valor"]:
        var = (rows[-1]["valor"] - rows[-2]["valor"]) / rows[-2]["valor"] * 100
        signo = "▲" if var >= 0 else "▼"
        lines.append(f"  Variación último período: {signo} {abs(var):.2f}%")
    return "\n".join(lines)


def consultar_db_precio(nemotecnico: str, fecha: str | None = None) -> str:
    """Precio de cuota desde fact_precio_cuota. Sin fecha → el más reciente."""
    nemotecnico = nemotecnico.strip().upper()
    with get_conn() as conn:
        if fecha:
            try:
                row = repo_fact.get_precio(conn, nemotecnico, fecha)
            except NotFoundError:
                return f"Sin precio en DB para {nemotecnico} al {fecha}."
            return f"{nemotecnico} al {fecha}: {row['precio']:,.4f} [{row['fuente'] or 's/f'}]"
        cur = conn.execute(
            "SELECT fecha, precio, fuente FROM fact_precio_cuota "
            "WHERE nemotecnico=? ORDER BY fecha DESC LIMIT 12",
            (nemotecnico,),
        )
        rows = cur.fetchall()
    if not rows:
        return f"Sin precios en DB para {nemotecnico}."
    lines = [f"Precios {nemotecnico} (DB, últimos {len(rows)}):"]
    for r in rows:
        lines.append(f"  {r['fecha']}: {r['precio']:,.4f} [{r['fuente'] or 's/f'}]")
    return "\n".join(lines)


def consultar_db_rent_roll(activo_key: str, periodo: str) -> str:
    """Rent roll de un activo y período desde raw_rent_roll_line."""
    with get_conn() as conn:
        rows = repo_rent_roll.list_by_periodo(conn, activo_key, periodo)
    if not rows:
        return f"Sin rent roll en DB para '{activo_key}' en {periodo}."
    lines = [f"Rent roll '{activo_key}' — {periodo} (DB, {len(rows)} unidades):"]
    for r in rows[:50]:
        partes = [f"Local {r['unidad']}"]
        if r["arrendatario"]:
            partes.append(r["arrendatario"])
        if r["m2"] is not None:
            partes.append(f"{r['m2']:,.1f} m²")
        if r["renta_uf"] is not None:
            partes.append(f"{r['renta_uf']:.4f} UF/m²")
        if r["vencimiento"]:
            partes.append(f"vence {r['vencimiento']}")
        lines.append("  " + " | ".join(partes))
    if len(rows) > 50:
        lines.append(f"  ... y {len(rows) - 50} más.")
    return "\n".join(lines)


def consultar_db_er(activo_key: str, periodo: str) -> str:
    """Líneas del estado de resultado de un activo/período desde raw_er_activo_line."""
    with get_conn() as conn:
        rows = repo_er_activo.list_by_periodo(conn, activo_key, periodo)
    if not rows:
        return f"Sin ER en DB para '{activo_key}' en {periodo}."
    lines = [f"ER '{activo_key}' — {periodo} (DB, {len(rows)} cuentas):"]
    for r in rows[:80]:
        monto = r["monto_clp"]
        monto_str = f"{monto:,.0f}" if monto is not None else "—"
        lines.append(f"  {r['cuenta_nombre']}: {monto_str}")
    if len(rows) > 80:
        lines.append(f"  ... y {len(rows) - 80} más.")
    return "\n".join(lines)


def consultar_db_flujo(activo_key: str, periodo: str) -> str:
    """Líneas de flujo de un activo/período desde raw_flujo_line."""
    with get_conn() as conn:
        rows = repo_flujo.list_by_periodo(conn, activo_key, periodo)
    if not rows:
        return f"Sin flujo en DB para '{activo_key}' en {periodo}."
    lines = [f"Flujo '{activo_key}' — {periodo} (DB, {len(rows)} líneas):"]
    for r in rows[:80]:
        monto = r["monto_clp"]
        monto_str = f"{monto:,.0f}" if monto is not None else "—"
        lines.append(f"  {r['cuenta_nombre']}: {monto_str}")
    if len(rows) > 80:
        lines.append(f"  ... y {len(rows) - 80} más.")
    return "\n".join(lines)


def consultar_db_dividendos(nemotecnico: str) -> str:
    """Historial de dividendos por cuota de una serie desde fact_dividendo."""
    nemotecnico = nemotecnico.strip().upper()
    with get_conn() as conn:
        rows = repo_fact.list_dividendos(conn, nemotecnico)
    if not rows:
        return f"Sin dividendos en DB para {nemotecnico}."
    lines = [f"Dividendos {nemotecnico} (DB, {len(rows)} pagos):"]
    for r in rows[-24:]:
        lines.append(f"  {r['fecha_pago']}: {r['monto']:,.4f}/cuota")
    return "\n".join(lines)


def consultar_db_cobertura() -> str:
    """Resumen de qué datos hay en la DB: filas y rango de períodos por dominio."""
    tablas = {
        "rent_roll":   ("raw_rent_roll_line", "activo_key"),
        "er_activo":   ("raw_er_activo_line", "activo_key"),
        "flujo":       ("raw_flujo_line", "activo_key"),
        "kpi":         ("derived_kpi", "entidad_key"),
    }
    lines = ["Cobertura de la DB del agente:"]
    with get_conn() as conn:
        for dom, (tabla, keycol) in tablas.items():
            total = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
            if total == 0:
                lines.append(f"  {dom}: vacío")
                continue
            rango = conn.execute(
                f"SELECT MIN(periodo), MAX(periodo) FROM {tabla}"
            ).fetchone()
            entidades = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {keycol} FROM {tabla} ORDER BY {keycol}"
            )]
            lines.append(
                f"  {dom}: {total} filas | {rango[0]}..{rango[1]} | "
                f"{', '.join(entidades)}"
            )
        # Precios y UF (sin columna periodo)
        for dom, tabla, fcol in [
            ("precios", "fact_precio_cuota", "fecha"),
            ("uf", "fact_uf", "fecha"),
            ("dividendos", "fact_dividendo", "fecha_pago"),
        ]:
            total = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
            if total == 0:
                lines.append(f"  {dom}: vacío")
                continue
            rango = conn.execute(f"SELECT MIN({fcol}), MAX({fcol}) FROM {tabla}").fetchone()
            lines.append(f"  {dom}: {total} filas | {rango[0]}..{rango[1]}")
    return "\n".join(lines)
