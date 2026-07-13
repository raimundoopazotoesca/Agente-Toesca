"""
Consultas sobre deuda, amortización y financiamiento del portfolio Toesca.
Fuentes: dim_credito, raw_amortizacion, raw_saldo_deuda, raw_pagare_intercompania.
"""
from tools.db.connection import get_conn


def _fmt(v, decimals=0) -> str:
    if v is None:
        return "s/d"
    fmt = f":,.{decimals}f"
    return f"{v:{fmt[1:]}}"


def consultar_financiamiento(tipo: str, fondo: str | None = None,
                             desde: str | None = None, hasta: str | None = None,
                             credito_key: str | None = None,
                             fecha_corte: str | None = None,
                             tipo_valor: str = "bursatil") -> str:
    """
    tipo:
      creditos_vigentes  → lista créditos de un fondo con saldo actual y condiciones
      amortizacion       → amortización capital por período (desde/hasta YYYY-MM)
      saldo_deuda        → saldo de deuda actual por fondo o crédito
      perfil_vencimientos → amortizaciones anuales proyectadas
      pagares            → pagarés intercompañía
      dy_amort           → DY + amortización por serie TRI; fecha_corte YYYY-MM, tipo_valor bursatil|contable
    """
    with get_conn() as conn:
        if tipo == "creditos_vigentes":
            return _creditos_vigentes(conn, fondo)
        elif tipo == "amortizacion":
            return _amortizacion(conn, fondo, credito_key, desde, hasta)
        elif tipo == "saldo_deuda":
            return _saldo_deuda(conn, fondo, credito_key)
        elif tipo == "perfil_vencimientos":
            return _perfil_vencimientos(conn, fondo)
        elif tipo == "pagares":
            return _pagares(conn, fondo)
        elif tipo == "dy_amort":
            return _dy_amort(conn, fecha_corte, tipo_valor)
        else:
            return f"Tipo '{tipo}' no reconocido. Opciones: creditos_vigentes, amortizacion, saldo_deuda, perfil_vencimientos, pagares, dy_amort."


def _creditos_vigentes(conn, fondo):
    q = """
        SELECT credito_key, fondo_key, acreedor, tipo_deuda, part_fondo,
               deuda_inicial_uf, tasa_anual, cuota_mensual_uf,
               fecha_inicio, fecha_vencimiento, estado, perfil_amortizacion
        FROM dim_credito
        WHERE 1=1
    """
    params = []
    if fondo:
        q += " AND UPPER(fondo_key)=UPPER(?)"
        params.append(fondo)
    q += " ORDER BY fondo_key, credito_key"
    rows = conn.execute(q, params).fetchall()
    if not rows:
        return "Sin créditos en DB."

    # Obtener saldo más reciente por crédito
    saldos = {}
    for r in conn.execute("""
        SELECT credito_key, MAX(periodo) periodo, saldo_uf
        FROM raw_amortizacion
        GROUP BY credito_key
    """):
        # usar saldo de raw_amortizacion si disponible
        pass

    from datetime import date
    hoy = date.today().strftime("%Y-%m")
    # Saldo actual: último periodo disponible hasta hoy
    saldo_map = {}
    for ck, periodo, saldo in conn.execute("""
        SELECT a.credito_key, a.periodo, a.saldo_uf
        FROM raw_amortizacion a
        WHERE a.credito_key NOT LIKE '%CONSOLIDADO%'
          AND a.periodo = (
            SELECT MAX(a2.periodo) FROM raw_amortizacion a2
            WHERE a2.credito_key=a.credito_key AND a2.periodo<=?
        )
    """, (hoy,)):
        saldo_map[ck] = (periodo, saldo)

    lines = [f"CRÉDITOS VIGENTES{' — '+fondo if fondo else ''} ({len(rows)} créditos):"]
    for r in rows:
        ck = r[0]
        saldo_info = saldo_map.get(ck)
        saldo_str = f"Saldo {saldo_info[0]}: {_fmt(saldo_info[1])} UF" if saldo_info else ""
        estado_str = f"[{r[10]}]" if r[10] != "VIGENTE" else ""
        lines.append(
            f"\n  {ck} {estado_str}"
            f"\n    Acreedor: {r[2]} | Tipo: {r[3]} | Part. fondo: {r[4]*100:.0f}%"
            f"\n    Deuda inicial: {_fmt(r[5])} UF | Tasa: {r[6]*100:.2f}% | Cuota: {_fmt(r[7])} UF/mes"
            f"\n    Fechas: {r[8]} → {r[9]}"
            + (f"\n    {saldo_str}" if saldo_str else "")
            + f"\n    Perfil: {r[11]}"
        )
    return "\n".join(lines)


def _amortizacion(conn, fondo, credito_key, desde, hasta):
    # Elegir la clave correcta del consolidado
    if credito_key:
        clave = credito_key
    elif fondo and fondo.upper() == "TRI":
        clave = "CONSOLIDADO_TRI"
    elif fondo and fondo.upper() == "PT":
        clave = "CONSOLIDADO_PT"
    else:
        clave = None

    if clave:
        q = "SELECT periodo, capital_uf FROM raw_amortizacion WHERE credito_key=?"
        params = [clave]
    else:
        # Suma por fondo via JOIN
        q = """
            SELECT a.periodo, SUM(a.capital_uf)
            FROM raw_amortizacion a
            JOIN dim_credito c ON a.credito_key=c.credito_key
            WHERE a.credito_key NOT LIKE '%CONSOLIDADO%'
        """
        params = []
        if fondo:
            q += " AND UPPER(c.fondo_key)=UPPER(?)"
            params.append(fondo)
        q += " GROUP BY a.periodo"

    if desde:
        q += " AND periodo >= ?"
        params.append(desde)
    if hasta:
        q += " AND periodo <= ?"
        params.append(hasta)
    q += " ORDER BY periodo"

    rows = conn.execute(q, params).fetchall()
    if not rows:
        return "Sin datos de amortización para los parámetros indicados."

    total = sum(r[1] for r in rows if r[1])
    rango = f"{desde or rows[0][0]} a {hasta or rows[-1][0]}"
    label = clave or fondo or "todos"
    lines = [f"AMORTIZACIÓN CAPITAL — {label} ({rango}):"]
    for p, c in rows:
        lines.append(f"  {p}: {_fmt(c, 2)} UF")
    lines.append(f"\n  TOTAL: {_fmt(total, 2)} UF")
    return "\n".join(lines)


def _saldo_deuda(conn, fondo, credito_key):
    from datetime import date
    hoy = date.today().strftime("%Y-%m")

    if credito_key:
        rows = conn.execute("""
            SELECT a.credito_key, a.periodo, a.saldo_uf
            FROM raw_amortizacion a
            WHERE a.credito_key=?
              AND a.periodo=(SELECT MAX(a2.periodo) FROM raw_amortizacion a2
                             WHERE a2.credito_key=? AND a2.periodo<=?)
        """, (credito_key, credito_key, hoy)).fetchall()
    else:
        q = """
            SELECT a.credito_key, a.periodo, a.saldo_uf
            FROM raw_amortizacion a
            JOIN dim_credito c ON a.credito_key=c.credito_key
            WHERE a.credito_key NOT LIKE '%CONSOLIDADO%'
              AND a.periodo=(
                  SELECT MAX(a2.periodo) FROM raw_amortizacion a2
                  WHERE a2.credito_key=a.credito_key AND a2.periodo<=?
              )
        """
        params = [hoy]
        if fondo:
            q += " AND UPPER(c.fondo_key)=UPPER(?)"
            params.append(fondo)
        q += " ORDER BY a.credito_key"
        rows = conn.execute(q, params).fetchall()

    if not rows:
        return "Sin datos de saldo para los parámetros indicados."

    total = sum(r[2] for r in rows if r[2])
    label = credito_key or fondo or "todos"
    lines = [f"SALDO DEUDA — {label} (último período disponible):"]
    for ck, periodo, saldo in rows:
        lines.append(f"  {ck:<35} [{periodo}]: {_fmt(saldo, 2):>14} UF")
    lines.append(f"\n  TOTAL: {_fmt(total, 2)} UF")
    return "\n".join(lines)


def _perfil_vencimientos(conn, fondo):
    if fondo and fondo.upper() == "TRI":
        clave = "CONSOLIDADO_TRI"
    elif fondo and fondo.upper() == "PT":
        clave = "CONSOLIDADO_PT"
    else:
        clave = "CONSOLIDADO_TRI"  # default

    rows = conn.execute("""
        SELECT SUBSTR(periodo,1,4) yr, ROUND(SUM(capital_uf),0) amort
        FROM raw_amortizacion
        WHERE credito_key=?
        GROUP BY yr
        ORDER BY yr
    """, (clave,)).fetchall()

    if not rows:
        return "Sin datos de perfil de vencimientos."

    label = fondo or "TRI"
    lines = [f"PERFIL AMORTIZACIONES ANUALES — {label}:"]
    total = 0
    for yr, amort in rows:
        if amort and amort > 0:
            bar = "█" * min(int(amort / 20000), 30)
            lines.append(f"  {yr}: {_fmt(amort):>12} UF  {bar}")
            total += amort
    lines.append(f"\n  TOTAL: {_fmt(total)} UF")
    return "\n".join(lines)


def _pagares(conn, fondo):
    q = "SELECT acreedor_fondo, deudor_sociedad, tipo, fecha_inicio, fecha_vencimiento, monto_uf, saldo_c_intereses FROM raw_pagare_intercompania"
    params = []
    if fondo:
        q += " WHERE UPPER(acreedor_fondo) LIKE UPPER(?)"
        params.append(f"%{fondo}%")
    q += " ORDER BY acreedor_fondo, monto_uf DESC"
    rows = conn.execute(q, params).fetchall()
    if not rows:
        return "Sin pagarés intercompañía en DB."

    total = sum(r[6] for r in rows if r[6])
    lines = [f"PAGARÉS INTERCOMPAÑÍA ({len(rows)} registros):"]
    for r in rows:
        lines.append(
            f"  {r[0]} → {r[1]} | {r[2]}"
            f" | Monto: {_fmt(r[5])} UF | Saldo+int: {_fmt(r[6])} UF"
            f" | {r[3]} → {r[4]}"
        )
    lines.append(f"\n  TOTAL saldo c/int: {_fmt(total)} UF")
    return "\n".join(lines)


def _dy_amort(conn, fecha_corte: str | None = None, tipo_valor: str = "bursatil"):
    """
    DY + amortización TRI usando rolling 12 meses.
    fecha_corte: YYYY-MM (ej. '2026-02'). Por defecto: mes anterior al día de hoy.
    tipo_valor: 'bursatil' | 'contable'
    Fórmula: (dividendos_U12M + amort_U12M_por_cuota) / valor_cuota
    Período: mes siguiente a (fecha_corte - 12 meses) → fecha_corte
    Ej: corte feb-2026 → desde mar-2025 hasta feb-2026 (12 meses exactos)
    """
    from datetime import date
    from dateutil.relativedelta import relativedelta

    if fecha_corte:
        yr, mo = int(fecha_corte[:4]), int(fecha_corte[5:7])
        hasta = fecha_corte
    else:
        hoy = date.today()
        corte = hoy.replace(day=1) - relativedelta(months=1)
        hasta = corte.strftime("%Y-%m")
        yr, mo = corte.year, corte.month

    corte_date = date(yr, mo, 1)
    desde_date = corte_date - relativedelta(months=11)
    desde = desde_date.strftime("%Y-%m")

    # Amortización U12M
    amort_u12m = conn.execute("""
        SELECT ROUND(SUM(capital_uf), 2) FROM raw_amortizacion
        WHERE credito_key='CONSOLIDADO_TRI' AND periodo BETWEEN ? AND ?
    """, (desde, hasta)).fetchone()[0] or 0.0

    # Dividendos U12M (deduplicados por nemotecnico+periodo)
    divs = {nemo: div for nemo, div in conn.execute("""
        SELECT nemotecnico, ROUND(SUM(div_pago), 2)
        FROM (SELECT nemotecnico, periodo, MAX(monto_clp_cuota) div_pago
              FROM raw_dividendo
              WHERE superseded_at IS NULL AND fondo_key='TRI' AND periodo BETWEEN ? AND ?
              GROUP BY nemotecnico, periodo)
        GROUP BY nemotecnico
    """, (desde, hasta))}

    # Cuotas: último período disponible <= hasta (deduplicadas)
    total_q = sum(r[0] for r in conn.execute("""
        SELECT cuotas FROM (
            SELECT cuotas, ROW_NUMBER() OVER (PARTITION BY nemotecnico ORDER BY periodo DESC) rn
            FROM raw_cuota_en_circulacion
            WHERE superseded_at IS NULL AND fondo_key='TRI' AND periodo <= ?
        ) WHERE rn=1
    """, (hasta,)))

    # UF promedio del período
    uf_prom = conn.execute("""
        SELECT ROUND(AVG(uf_dia), 2) FROM raw_valor_cuota_contable
        WHERE fondo_key='TRI' AND uf_dia IS NOT NULL AND SUBSTR(fecha,1,7) BETWEEN ? AND ?
    """, (desde, hasta)).fetchone()[0] or 39000.0

    amort_clp_cuota = amort_u12m * uf_prom / total_q if total_q else None

    # Valor cuota (bursatil o contable) más reciente <= hasta
    if tipo_valor == "contable":
        val_cuota = {nemo: (precio, fecha) for nemo, precio, fecha in conn.execute("""
            SELECT nemotecnico, precio_clp, MAX(fecha)
            FROM raw_valor_cuota_contable
            WHERE fondo_key='TRI' AND SUBSTR(fecha,1,7) <= ?
            GROUP BY nemotecnico
        """, (hasta,))}
    else:
        val_cuota = {nemo: (precio, fecha) for nemo, precio, fecha in conn.execute("""
            SELECT nemotecnico, precio_clp, MAX(fecha)
            FROM raw_valor_cuota_bursatil
            WHERE nemotecnico LIKE 'CFITOERI1%' AND SUBSTR(fecha,1,7) <= ?
            GROUP BY nemotecnico
        """, (hasta,))}

    SERIES = [("CFITOERI1A", "A"), ("CFITOERI1C", "C"), ("CFITOERI1I", "I")]

    lines = [
        f"DY + AMORTIZACIÓN TRI — U12M a {hasta} (período {desde} → {hasta})",
        f"Valor cuota: {tipo_valor.upper()} | Amort: {_fmt(amort_u12m)} UF → {_fmt(amort_clp_cuota)} CLP/cuota",
        f"UF prom: {_fmt(uf_prom)} | Cuotas: {_fmt(total_q)}",
        "",
        f"{'S':<3} {'Div U12M':>10} {'V.Cuota':>10} {'Fecha VC':>10} {'DY%':>6} {'Amort/cuota':>12} {'DY+A%':>7}",
        "-" * 58,
    ]
    for nemo, serie in SERIES:
        div  = divs.get(nemo)
        info = val_cuota.get(nemo)
        vc   = info[0] if info else None
        fec  = info[1] if info else None
        dy   = (div / vc * 100)                       if div and vc else None
        dya  = ((div + amort_clp_cuota) / vc * 100)   if div and vc and amort_clp_cuota else None
        lines.append(
            f"{serie:<3} {_fmt(div):>10} {_fmt(vc):>10} {fec or 's/d':>10}"
            f" {f'{dy:.2f}%' if dy else 's/d':>6} {_fmt(amort_clp_cuota):>12}"
            f" {f'{dya:.2f}%' if dya else 's/d':>7}"
        )

    return "\n".join(lines)
