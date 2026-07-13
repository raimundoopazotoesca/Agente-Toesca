"""
Consultas de solo lectura sobre la DB del agente (Fase 1/4).

El agente usa estas funciones para responder preguntas SIN abrir los Excel.
Si un dato no está en la DB, lo reportan como gap para que el agente decida
abrir la planilla correspondiente.
"""
from tools.db.connection import get_conn
from tools.db import repo_kpi, repo_rent_roll, repo_er_activo, repo_flujo, repo_fact, repo_tasacion
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
        lines.append(f"  {r['periodo']}: {r['valor']:,.4f}{uni}  [{r['formula']}]")
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


def consultar_db_valor_bursatil(
    nemotecnico: str | None = None,
    fecha: str | None = None,
) -> str:
    """VR Bursátil por cuota por serie TRI en UF desde raw_valor_cuota_bursatil.

    = SUM(col M 'Monto UF/cuota') donde Detalle='VR Bursátil', Serie=X, Fecha=exacta.
    Dato mensual. Cobertura: 2017-12 a 2026-03.

    nemotecnico: 'CFITOERI1A' | 'CFITOERI1C' | 'CFITOERI1I' | None (todas)
    fecha:       'YYYY-MM-DD' o 'YYYY-MM' (último día del mes)
    """
    import calendar

    fecha_exacta: str | None = None
    if fecha:
        fc = fecha.strip()
        if len(fc) == 7:
            year, month = int(fc[:4]), int(fc[5:7])
            last_day = calendar.monthrange(year, month)[1]
            fecha_exacta = f"{year}-{month:02d}-{last_day:02d}"
        else:
            fecha_exacta = fc

    with get_conn() as conn:
        if not fecha_exacta:
            cur = conn.execute(
                "SELECT MAX(fecha) FROM raw_valor_cuota_bursatil "
                "WHERE nemotecnico LIKE 'CFITOERI1%'"
            )
            fecha_exacta = cur.fetchone()[0]
            if not fecha_exacta:
                return "Sin datos de VR Bursátil en la DB."

        where = "fecha = ?"
        params: list = [fecha_exacta]
        if nemotecnico:
            where += " AND nemotecnico = ?"
            params.append(nemotecnico.strip().upper())
        else:
            where += " AND nemotecnico LIKE 'CFITOERI1%'"

        rows = conn.execute(
            f"SELECT nemotecnico, fecha, precio_uf, cuotas "
            f"FROM raw_valor_cuota_bursatil WHERE {where} ORDER BY nemotecnico",
            params,
        ).fetchall()

    if not rows:
        filtro = f" para {nemotecnico or 'todas las series'} al {fecha or fecha_exacta}"
        return f"Sin datos de VR Bursátil{filtro}."

    lines = [f"VR Bursátil TRI al {fecha_exacta} (UF/cuota):"]
    for r in rows:
        cuotas_str = f"  {r['cuotas']:>10,.0f} cuotas" if r["cuotas"] else ""
        lines.append(f"  {r['nemotecnico']:15s}  {r['precio_uf']:.9f} UF/cuota{cuotas_str}")
    return "\n".join(lines)


def consultar_db_valor_libro(
    nemotecnico: str | None = None,
    fecha: str | None = None,
) -> str:
    """VR Contable (valor libro) por cuota por serie TRI desde raw_valor_cuota_contable.

    Devuelve precio_uf (UF/cuota) para la fecha exacta solicitada.
    Fuente preferida: EEFF PDF. Fallback: A&R Rentas cdg_extract.xlsx.
    Si no se especifica fecha, devuelve la última disponible.

    nemotecnico: 'CFITOERI1A' | 'CFITOERI1C' | 'CFITOERI1I' | None (todas)
    fecha:       'YYYY-MM-DD' o 'YYYY-MM' (se resuelve al último día del mes)
    """
    import calendar

    fecha_exacta: str | None = None
    if fecha:
        fc = fecha.strip()
        if len(fc) == 7:
            year, month = int(fc[:4]), int(fc[5:7])
            last_day = calendar.monthrange(year, month)[1]
            fecha_exacta = f"{year}-{month:02d}-{last_day:02d}"
        else:
            fecha_exacta = fc

    with get_conn() as conn:
        if not fecha_exacta:
            cur = conn.execute(
                "SELECT MAX(fecha) FROM raw_valor_cuota_contable "
                "WHERE fondo_key = 'TRI'"
            )
            fecha_exacta = cur.fetchone()[0]
            if not fecha_exacta:
                return "Sin datos de valor libro en la DB."

        where = "fondo_key = 'TRI' AND fecha = ?"
        params: list = [fecha_exacta]
        if nemotecnico:
            where += " AND nemotecnico = ?"
            params.append(nemotecnico.strip().upper())

        # Priorizar EEFF PDF sobre A&R Rentas; si hay duplicados tomar el más reciente cargado
        rows = conn.execute(
            f"SELECT nemotecnico, fecha, precio_uf, cuotas, source_file "
            f"FROM raw_valor_cuota_contable WHERE {where} "
            f"ORDER BY nemotecnico, "
            f"  CASE WHEN source_file LIKE '%cdg_extract%' THEN 1 ELSE 0 END, "
            f"  loaded_at DESC",
            params,
        ).fetchall()

    # Deduplicar: tomar primera fila por nemotecnico (ya ordenada por prioridad)
    seen: set = set()
    deduped = []
    for r in rows:
        if r["nemotecnico"] not in seen:
            seen.add(r["nemotecnico"])
            deduped.append(r)

    if not deduped:
        filtro = f" para {nemotecnico or 'todas las series'} al {fecha or fecha_exacta}"
        return f"Sin datos de valor libro{filtro}."

    label = f"al {fecha_exacta}"
    lines = [f"VR Contable TRI {label} (UF/cuota):"]
    for r in deduped:
        src = "EEFF" if "cdg_extract" not in (r["source_file"] or "") else "A&R"
        cuotas_str = f"  {r['cuotas']:>10,.0f} cuotas" if r["cuotas"] else ""
        lines.append(f"  {r['nemotecnico']:15s}  {r['precio_uf']:.9f} UF/cuota{cuotas_str}  [{src}]")
    return "\n".join(lines)


def consultar_db_patrimonio_bursatil(
    nemotecnico: str | None = None,
    fecha: str | None = None,
) -> str:
    """Patrimonio Bursátil por serie TRI desde raw_valor_cuota_bursatil.

    Devuelve el VR Bursátil en UF (precio_uf * cuotas) para la fecha exacta solicitada.
    Si no se especifica fecha, devuelve la última disponible.

    nemotecnico: 'CFITOERI1A' | 'CFITOERI1C' | 'CFITOERI1I' | None (todas)
    fecha:       'YYYY-MM-DD' o 'YYYY-MM' (se resuelve al último día del mes)
    """
    import calendar

    tri_series = ("CFITOERI1A", "CFITOERI1C", "CFITOERI1I")

    fecha_exacta: str | None = None
    if fecha:
        fc = fecha.strip()
        if len(fc) == 7:
            year, month = int(fc[:4]), int(fc[5:7])
            last_day = calendar.monthrange(year, month)[1]
            fecha_exacta = f"{year}-{month:02d}-{last_day:02d}"
        else:
            fecha_exacta = fc

    placeholders = ",".join("?" * len(tri_series))

    with get_conn() as conn:
        if not fecha_exacta:
            cur = conn.execute(
                f"SELECT MAX(fecha) FROM raw_valor_cuota_bursatil "
                f"WHERE nemotecnico IN ({placeholders}) AND patrimonio_bursatil_uf IS NOT NULL",
                tri_series,
            )
            fecha_exacta = cur.fetchone()[0]
            if not fecha_exacta:
                return "Sin datos de patrimonio bursátil en la DB."

        where = f"nemotecnico IN ({placeholders}) AND fecha = ? AND patrimonio_bursatil_uf IS NOT NULL"
        params: list = [*tri_series, fecha_exacta]

        if nemotecnico:
            where += " AND nemotecnico = ?"
            params.append(nemotecnico.strip().upper())

        rows = conn.execute(
            f"SELECT nemotecnico, fecha, patrimonio_bursatil_uf AS patrimonio_uf "
            f"FROM raw_valor_cuota_bursatil WHERE {where} ORDER BY nemotecnico",
            params,
        ).fetchall()

    if not rows:
        filtro = f" para {nemotecnico or 'todas las series'} al {fecha or fecha_exacta}"
        return f"Sin datos de patrimonio bursátil{filtro}."

    lines = [f"Patrimonio Bursátil TRI al {fecha_exacta} (precio_uf × cuotas):"]
    total = 0.0
    for r in rows:
        lines.append(f"  {r['nemotecnico']:15s}  {r['patrimonio_uf']:>14,.2f} UF")
        total += r["patrimonio_uf"]
    if not nemotecnico:
        lines.append(f"  {'TOTAL':15s}  {total:>14,.2f} UF")
    return "\n".join(lines)


def consultar_db_capital_suscrito(
    nemotecnico: str | None = None,
    fecha_corte: str | None = None,
) -> str:
    """Capital suscrito acumulado por serie TRI desde raw_capital_suscrito.

    Para cada serie devuelve el último valor acumulado en o antes de fecha_corte.
    Fuente: movimientos A&R (Aportes + Canjes - Disminuciones) acumulados.

    nemotecnico: 'CFITOERI1A' | 'CFITOERI1C' | 'CFITOERI1I' | None (todas)
    fecha_corte: 'YYYY-MM-DD' o 'YYYY-MM' (se expande al último día del mes) | None = último disponible
    """
    # Normalizar fecha_corte a YYYY-MM-DD
    if fecha_corte:
        fc = fecha_corte.strip()
        if len(fc) == 7:  # YYYY-MM → último día del mes
            import calendar
            year, month = int(fc[:4]), int(fc[5:7])
            last_day = calendar.monthrange(year, month)[1]
            fc = f"{year}-{month:02d}-{last_day:02d}"
    else:
        fc = "9999-12-31"

    with get_conn() as conn:
        nemo_filter = "AND nemotecnico = ?" if nemotecnico else ""
        params = [fc]
        if nemotecnico:
            params.append(nemotecnico.strip().upper())

        sql = f"""
            SELECT nemotecnico, fecha_fin_periodo, capital_suscrito_uf
            FROM raw_capital_suscrito
            WHERE fondo_key = 'TRI'
              AND fecha_fin_periodo <= ?
              {nemo_filter}
            GROUP BY nemotecnico
            HAVING fecha_fin_periodo = MAX(fecha_fin_periodo)
            ORDER BY nemotecnico
        """
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        filtro = f" para {nemotecnico or 'todas las series'}{f' al {fecha_corte}' if fecha_corte else ''}"
        return f"Sin datos de capital suscrito{filtro}."

    label = f"al {fecha_corte}" if fecha_corte else "(último disponible)"
    lines = [f"Capital suscrito TRI {label} (fuente: A&R Rentas acumulado):"]
    total = 0.0
    for r in rows:
        lines.append(f"  {r['nemotecnico']:15s}  {r['fecha_fin_periodo']}  {r['capital_suscrito_uf']:>14,.2f} UF")
        total += r["capital_suscrito_uf"]
    if not nemotecnico:
        lines.append(f"  {'TOTAL':15s}  {'':10s}  {total:>14,.2f} UF")
    return "\n".join(lines)


def consultar_db_cobertura() -> str:
    """Reporta qué hay disponible en la DB y dónde hay gaps mensuales por activo/fondo."""
    import json
    from tools.db.coverage import audit_coverage
    with get_conn() as conn:
        coverage = audit_coverage(conn)
    return json.dumps(coverage, ensure_ascii=False, indent=2)


def consultar_dividend_yield(
    nemotecnico: str,
    periodo: str | None = None,
    anio: int | None = None,
    tipo: str = "contable",
) -> str:
    """Dividend yield de una serie TRI en UF/cuota.

    Fórmula: SUM(dividendos UF/cuota del año calendario) / precio_UF_cuota al cierre del año.
    Usa dividendos del año calendario (no ventana U12M).

    tipo:
      'contable'  → DY = div_año / valor_libro_UF_cuota al cierre  (default)
      'bursatil'  → DY = div_año / precio_bursatil_UF_cuota al cierre
      'total'     → total UF/cuota repartidos en el año (sin dividir)

    nemotecnico: 'CFITOERI1A' | 'CFITOERI1C' | 'CFITOERI1I'
    periodo:     'YYYY-MM' — cierre del período. Si se omite y hay anio, usa ANIO-12.
    anio:        año calendario (ej. 2025). Alternativo a periodo.
    """
    import calendar as cal

    nemo = nemotecnico.strip().upper()

    if not periodo and anio:
        periodo = f"{anio}-12"
    elif not periodo:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(substr(fecha_pago,1,4)) FROM raw_dividendo "
                "WHERE nemotecnico=? AND superseded_at IS NULL",
                (nemo,)
            ).fetchone()
        anio_max = int(row[0]) if row and row[0] else 2025
        periodo = f"{anio_max}-12"

    anio_ref = int(periodo[:4])
    mes_ref = int(periodo[5:7])
    ultimo_dia = cal.monthrange(anio_ref, mes_ref)[1]
    fecha_fin = f"{anio_ref}-{mes_ref:02d}-{ultimo_dia:02d}"
    fecha_inicio = f"{anio_ref}-01-01"

    with get_conn() as conn:
        # Dividendos del año calendario
        div_row = conn.execute(
            "SELECT SUM(monto_uf_cuota), COUNT(monto_uf_cuota), MIN(fecha_pago), MAX(fecha_pago) "
            "FROM raw_dividendo "
            "WHERE nemotecnico=? AND fecha_pago>=? AND fecha_pago<=? "
            "AND superseded_at IS NULL AND monto_uf_cuota IS NOT NULL",
            (nemo, fecha_inicio, fecha_fin)
        ).fetchone()

        div_total = div_row[0] if div_row and div_row[0] else None
        n_pagos = div_row[1] if div_row else 0
        f_min = div_row[2] if div_row else None
        f_max = div_row[3] if div_row else None

        # Precio de cierre (último disponible hasta fecha_fin)
        if tipo == "contable":
            precio_row = conn.execute(
                "SELECT precio_uf FROM raw_valor_cuota_contable "
                "WHERE nemotecnico=? AND fecha<=? AND superseded_at IS NULL "
                "ORDER BY fecha DESC LIMIT 1",
                (nemo, fecha_fin)
            ).fetchone()
        else:
            precio_row = conn.execute(
                "SELECT precio_uf FROM raw_valor_cuota_bursatil "
                "WHERE nemotecnico=? AND fecha<=? AND precio_uf IS NOT NULL "
                "ORDER BY fecha DESC LIMIT 1",
                (nemo, fecha_fin)
            ).fetchone()
        precio = precio_row[0] if precio_row and precio_row[0] else None

    if tipo == "total":
        if not div_total:
            return f"Sin dividendos en DB para {nemo} en {anio_ref}."
        lines = [
            f"Dividendos repartidos {nemo} — {anio_ref}:",
            f"  Total UF/cuota: {div_total:.6f}",
            f"  Número de pagos: {n_pagos}",
            f"  Rango: {f_min} -> {f_max}",
        ]
        if precio:
            label = "valor libro" if tipo == "contable" else "precio bursátil"
            lines.append(f"  {label.capitalize()} al cierre: {precio:.6f} UF/cuota")
        return "\n".join(lines)

    if not div_total:
        return f"Sin dividendos en DB para {nemo} en {anio_ref}."
    if not precio:
        tipo_label = "contable" if tipo == "contable" else "bursátil"
        return f"Sin precio {tipo_label} en DB para {nemo} al {fecha_fin}."

    dy = div_total / precio
    label = "valor libro" if tipo == "contable" else "precio bursátil"

    lines = [
        f"Dividend Yield {nemo} — {anio_ref}:",
        f"  DY sobre {label}: {dy * 100:.4f}%",
        f"  Dividendos año UF/cuota: {div_total:.6f} ({n_pagos} pagos, {f_min} -> {f_max})",
        f"  {label.capitalize()} al cierre ({fecha_fin}): {precio:.6f} UF/cuota",
    ]
    return "\n".join(lines)


def consultar_db_tasaciones(
    activo_key: str | None = None,
    periodo: str | None = None,
) -> str:
    """Tasaciones de activos inmobiliarios (fact_tasacion).

    Muestra las dos tasadoras por año y el promedio.
    activo_key: ej. 'PT', 'Viña Centro', 'INMOSA' | None = todos
    periodo:    YYYY | None = todos los años
    """
    with get_conn() as conn:
        rows = repo_tasacion.list_tasaciones(conn, activo_key, periodo)

    if not rows:
        filtro = f"'{activo_key}'" if activo_key else "todos los activos"
        extra = f" período {periodo}" if periodo else ""
        return f"Sin tasaciones en DB para {filtro}{extra}."

    # Agrupar por (activo, periodo)
    from collections import defaultdict
    grupos: dict = defaultdict(list)
    for r in rows:
        grupos[(r["activo_key"], r["periodo"])].append(r)

    lines = ["Tasaciones (DB):"]
    for (ak, per), tas_list in sorted(grupos.items()):
        valores_uf = [t["valor_uf"] for t in tas_list if t["valor_uf"] is not None]
        promedio = sum(valores_uf) / len(valores_uf) if valores_uf else None
        prom_str = f"  → Promedio: {promedio:,.0f} UF" if promedio else ""
        lines.append(f"\n  {ak} — {per}{prom_str}")
        for t in tas_list:
            campos = [f"    {t['tasador']:20s}"]
            if t["valor_uf"] is not None:
                campos.append(f"{t['valor_uf']:>12,.0f} UF")
            if t["uf_m2"] is not None:
                campos.append(f"{t['uf_m2']:.1f} UF/m²")
            if t["cap_rate"] is not None:
                campos.append(f"cap rate {t['cap_rate']*100:.2f}%")
            if t["tasa_dcto"] is not None:
                campos.append(f"tasa dcto {t['tasa_dcto']*100:.2f}%")
            if t["ltv"] is not None:
                campos.append(f"LTV {t['ltv']*100:.1f}%")
            lines.append("  ".join(campos))
    return "\n".join(lines)


def consultar_db_adquisiciones(activo_key: str | None = None) -> str:
    """Valores de compra de activos inmobiliarios (fact_adquisicion).

    activo_key: ej. 'PT' | None = todos los activos
    """
    with get_conn() as conn:
        if activo_key:
            row = repo_tasacion.get_adquisicion(conn, activo_key)
            rows = [row] if row else []
        else:
            rows = repo_tasacion.list_adquisiciones(conn)

    if not rows:
        filtro = f"'{activo_key}'" if activo_key else "ningún activo"
        return f"Sin valor de adquisición en DB para {filtro}."

    lines = ["Valores de adquisición (DB):"]
    for r in rows:
        partes = [f"  {r['activo_key']:15s}  {r['fecha_adquisicion']}"]
        if r["precio_uf"] is not None:
            partes.append(f"precio fondo: {r['precio_uf']:>12,.0f} UF")
        if r["valor_activo_uf"] is not None:
            partes.append(f"valor 100%: {r['valor_activo_uf']:>12,.0f} UF")
        if r["uf_m2"] is not None:
            partes.append(f"{r['uf_m2']:.2f} UF/m²")
        if r["porcentaje_adquirido"] is not None:
            partes.append(f"{r['porcentaje_adquirido']*100:.1f}% adquirido")
        lines.append("  ".join(partes))
    return "\n".join(lines)


_INMOSA_RESIDENCIAS = (
    "('Residencia Arturo Medina','Residencia Candil','Residencia Colombia',"
    "'Residencia Coventry','Residencia Domingo Calderón','Residencia Padre Errázuriz')"
)


def consultar_ltv(
    activo_key: str | None = None,
    periodo: str | None = None,
    fondo_key: str | None = None,
) -> str:
    """LTV dinámico por activo (y agregado por fondo).

    LTV = deuda 100% del activo / tasación promedio vigente.
    El saldo de deuda se actualiza mensualmente; la tasación usa el promedio del
    año más reciente disponible (≤ año del periodo).

    activo_key: ej. 'Torre A', 'INMOSA' | None = todos
    periodo:    'YYYY-MM' | None = último mes con datos de saldo
    fondo_key:  'PT' | 'TRI' | 'Apo' | None = todos
    """
    with get_conn() as conn:
        # Resolver periodo por defecto
        if not periodo:
            cur = conn.execute(
                "SELECT MAX(s.periodo) FROM raw_saldo_deuda s WHERE s.is_proyeccion=0"
            )
            periodo = cur.fetchone()[0]
            if not periodo:
                return "Sin datos de saldo de deuda en la DB."

        filtros, params = ["s.is_proyeccion=0", "s.periodo=?"], [periodo]
        if activo_key:
            filtros.append("dc.activo_key=?")
            params.append(activo_key)
        if fondo_key:
            filtros.append("dc.fondo_key=?")
            params.append(fondo_key)
        where = " AND ".join(filtros)

        sql = f"""
        WITH deuda AS (
            SELECT dc.activo_key, dc.fondo_key, MAX(dc.participacion_fondo_deuda) as participacion_fondo_deuda,
                   SUM(s.saldo_uf) as deuda_uf_fondo
            FROM raw_saldo_deuda s
            JOIN dim_credito dc ON dc.credito_key = s.credito_key
            WHERE {where}
            GROUP BY dc.activo_key, dc.fondo_key
        ),
        tas_mapped AS (
            SELECT
                CASE WHEN activo_key IN {_INMOSA_RESIDENCIAS} THEN 'INMOSA' ELSE activo_key END as activo_key,
                periodo as anio,
                SUM(valor_uf) as tasacion_uf
            FROM fact_tasacion WHERE tasador='Promedio'
            GROUP BY 1, 2
        )
        SELECT
            d.activo_key, d.fondo_key, d.deuda_uf_fondo, d.participacion_fondo_deuda,
            (SELECT t.tasacion_uf FROM tas_mapped t
             WHERE t.activo_key = d.activo_key AND t.anio <= substr(?,1,4)
             ORDER BY t.anio DESC LIMIT 1) as tasacion_uf,
            (SELECT t.anio FROM tas_mapped t
             WHERE t.activo_key = d.activo_key AND t.anio <= substr(?,1,4)
             ORDER BY t.anio DESC LIMIT 1) as tasacion_anio
        FROM deuda d
        ORDER BY d.fondo_key, d.activo_key
        """
        rows = conn.execute(sql, params + [periodo, periodo]).fetchall()

    if not rows:
        return f"Sin datos de LTV para {activo_key or 'todos'} en {periodo}."

    lines = [f"LTV por activo — {periodo} (deuda real / tasación promedio):"]
    lines.append(f"  {'Activo':30s}  {'Fondo':5s}  {'Deuda 100%':>12s}  {'Tasación':>12s}  {'Año tas':7s}  {'LTV':>8s}")
    lines.append("  " + "-" * 80)

    fondo_totals: dict = {}
    for r in rows:
        ak = r["activo_key"]
        fk = r["fondo_key"]
        deuda_fondo = r["deuda_uf_fondo"] or 0
        part = r["participacion_fondo_deuda"] or 1
        deuda_total = deuda_fondo / part if part else None
        tasacion = r["tasacion_uf"]
        anio_tas = r["tasacion_anio"] or "—"
        ltv = deuda_total / tasacion if (deuda_total and tasacion) else None
        ltv_str = f"{ltv:.1%}" if ltv is not None else "—"
        deuda_str = f"{deuda_total:>12,.0f}" if deuda_total else "—"
        tas_str = f"{tasacion:>12,.0f}" if tasacion else "s/d"
        lines.append(f"  {ak:30s}  {fk:5s}  {deuda_str}  {tas_str}  {anio_tas:7s}  {ltv_str:>8s}")

        # Acumular por fondo (usando deuda al 100% × part y tasacion × part)
        if tasacion and deuda_total:
            if fk not in fondo_totals:
                fondo_totals[fk] = {"deuda_eco": 0.0, "valor_eco": 0.0}
            fondo_totals[fk]["deuda_eco"] += deuda_fondo        # deuda económica del fondo
            fondo_totals[fk]["valor_eco"] += tasacion * part    # valor económico del fondo

    if len(fondo_totals) >= 1:
        lines.append("")
        lines.append("  LTV por fondo (deuda econ. / valor econ.):")
        for fk, v in sorted(fondo_totals.items()):
            ltv_f = v["deuda_eco"] / v["valor_eco"] if v["valor_eco"] else None
            ltv_f_str = f"{ltv_f:.1%}" if ltv_f else "—"
            lines.append(f"    {fk}: {v['deuda_eco']:>10,.0f} UF deuda econ.  /  {v['valor_eco']:>12,.0f} UF valor econ.  →  LTV {ltv_f_str}")

    return "\n".join(lines)
