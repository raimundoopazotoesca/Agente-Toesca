"""Página dashboard de los fondos Toesca — fact sheets dinámicos desde la DB.

Vistas: Portfolio (comparativa) + fact sheet por fondo (TRI, PT, Apo).
Fuente única: memory/agente_toesca_v2.db. Los bloques cuyo dato aún no está
poblado se ocultan solos — al poblar la DB aparecen sin tocar código.

Run:
    streamlit run dashboards/fondos.py
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "memory" / "agente_toesca_v2.db"

# ── Identidad Toesca ─────────────────────────────────────────────────────────
# Paleta categórica validada (dataviz six-checks, light mode)
PALETTE = ["#149E63", "#3E6FA8", "#C08A2E", "#B05A7A", "#7461C9"]
GREEN = "#149E63"
GREEN_DARK = "#0F6B44"
MINT = "#DDF2E4"
INK = "#1c1c1e"
MUTED = "#6b7280"
LINE = "#e5e7eb"
BG = "#fcfcfb"

CSS = f"""
<style>
  .stApp {{ background: {BG}; }}
  .block-container {{ padding-top: 0.8rem; max-width: 1250px; }}
  header[data-testid="stHeader"] {{ background: transparent; }}

  .tsc-band {{
    background: #0e0e0f; color: #fff; border-radius: 8px;
    padding: 18px 26px; margin-bottom: 4px;
    display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap;
  }}
  .tsc-logo {{ font-family: Georgia, 'Times New Roman', serif; font-size: 30px;
               font-weight: 600; letter-spacing: .5px; }}
  .tsc-logo .dot {{ color: {GREEN}; }}
  .tsc-band .sub {{ color: #b9b9bd; font-size: 13px; text-transform: uppercase;
                    letter-spacing: .12em; }}
  .tsc-band .per {{ margin-left: auto; color: {GREEN}; font-size: 13px;
                    letter-spacing: .08em; text-transform: uppercase; }}

  .tsc-h2 {{
    background: {MINT}; color: {GREEN_DARK}; font-size: 13px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .08em;
    padding: 6px 12px; border-radius: 4px; margin: 26px 0 12px;
  }}

  .tsc-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 10px; }}
  .tsc-card {{ background: #fff; border: 1px solid {LINE}; border-radius: 8px;
               padding: 12px 14px; }}
  .tsc-card .k {{ color: {MUTED}; font-size: 11px; text-transform: uppercase;
                  letter-spacing: .06em; }}
  .tsc-card .v {{ color: {INK}; font-size: 22px; font-weight: 650; margin-top: 2px;
                  font-variant-numeric: tabular-nums; }}
  .tsc-card .s {{ color: {MUTED}; font-size: 11px; margin-top: 2px; }}
  .tsc-card.accent .v {{ color: {GREEN_DARK}; }}

  .tsc-note {{ color: {MUTED}; font-size: 12px; margin: 4px 0 0; }}
</style>
"""

FICHA = {
    "TRI": {
        "titulo": "Toesca Rentas Inmobiliarias",
        "subtitulo": "Fondo de inversión en Liquidación",
        "info": [
            ("Fecha inicio período liquidación", "30 abril 2024"),
            ("Moneda del fondo", "CLP"),
            ("Duración", "30 abril 2027 (+2 renovaciones automáticas de 1 año)"),
            ("Remuneración fija (liquidación)", "A 0,75% · C 0,50% · WM 0,45% · I 0,40% + IVA s/ capital pagado"),
        ],
    },
    "PT": {
        "titulo": "Toesca Rentas Inmobiliarias PT",
        "subtitulo": "Fondo de inversión",
        "info": [
            ("Fecha inicio operaciones", "16 de noviembre de 2017"),
            ("Moneda del fondo", "CLP"),
            ("Duración", "15 años (30 julio 2032)"),
            ("Remuneración fija", "0,4% + IVA sobre capital pagado"),
        ],
    },
    "Apo": {
        "titulo": "Toesca Rentas Inmobiliarias Apoquindo",
        "subtitulo": "Fondo de inversión",
        "info": [
            ("Fecha inicio operaciones", "2 de enero de 2019"),
            ("Moneda del fondo", "CLP"),
            ("Duración", "10 años (16 noviembre 2028)"),
            ("Remuneración fija", "0,5355% + IVA sobre capital pagado"),
        ],
    },
}

# noi_mensual usa keys propias; mapa fondo → entidades NOI (100% del activo)
NOI_ACTIVOS = {
    "TRI": ["Viña Centro", "Mall Curicó", "INMOSA", "Sucden", "Apo3001", "PT", "Apoquindo"],
    "PT": ["PT Torre A", "PT Boulevard"],
    "Apo": ["Apoquindo"],
}
# rent roll usa otras keys
RR_ACTIVOS = {
    "TRI": ["Viña Centro", "Mall Curicó", "Apo3001", "PT", "Apoquindo"],
    "PT": ["PT"],
    "Apo": ["Apoquindo"],
}

FILAS_RENTAB = [
    ("Rentabilidad desde el inicio (anualizada)", "tir_{v}_desde_inicio", None),
    ("Rentabilidad YTD (anualizada)", "rent_ytd_{v}", None),
    ("Rentabilidad últimos 12 meses", "tir_{v}_u12m", None),
    ("Dividend Yield", "dy", "{v}"),
    ("Dividend Yield + Amortización", "dy_amort", "{v}"),
]


# ── Data access ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with sqlite3.connect(DB) as con:
        return pd.read_sql_query(sql, con, params=params)


def fmt_clp(x, dec=0):
    if x is None or pd.isna(x):
        return "—"
    s = f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"${s}"


def fmt_uf(x, dec=0):
    if x is None or pd.isna(x):
        return "—"
    s = f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"UF {s}"


def fmt_pct(x, dec=1):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:,.{dec}f}%".replace(".", ",")


def fmt_num(x, dec=0):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def base_layout(fig: go.Figure, ytitle: str = "", height: int = 340) -> go.Figure:
    fig.update_layout(
        template="none",
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11, color=MUTED)),
        hovermode="x unified",
        yaxis=dict(title=ytitle, gridcolor=LINE, zerolinecolor=LINE,
                   tickfont=dict(color=MUTED)),
        xaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color=MUTED)),
    )
    return fig


def h2(txt: str) -> None:
    st.markdown(f'<div class="tsc-h2">{txt}</div>', unsafe_allow_html=True)


def cards(items: list[tuple[str, str, str]]) -> None:
    """items = [(label, value, sub)]"""
    html = '<div class="tsc-cards">'
    for k, v, s in items:
        html += (f'<div class="tsc-card accent"><div class="k">{k}</div>'
                 f'<div class="v">{v}</div><div class="s">{s}</div></div>')
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ── Queries de negocio ───────────────────────────────────────────────────────
def series_fondo(fondo: str) -> pd.DataFrame:
    return q("SELECT nemotecnico, serie, transa_bolsa FROM dim_serie WHERE fondo_key=? "
             "ORDER BY serie", (fondo,))


def kpi_ultimo(entidad: str, kpi: str, variante: str | None = None):
    """Último valor (periodo, valor) de un KPI en derived_kpi."""
    if variante:
        df = q("SELECT periodo, valor FROM derived_kpi WHERE entidad_key=? AND kpi=? "
               "AND variante=? ORDER BY periodo DESC LIMIT 1", (entidad, kpi, variante))
    else:
        df = q("SELECT periodo, valor FROM derived_kpi WHERE entidad_key=? AND kpi=? "
               "ORDER BY periodo DESC LIMIT 1", (entidad, kpi))
    if df.empty:
        return None, None
    return df.iloc[0]["periodo"], df.iloc[0]["valor"]


def kpi_serie_hist(entidad: str, kpi: str, variante: str | None = None) -> pd.DataFrame:
    if variante:
        return q("SELECT periodo, valor FROM derived_kpi WHERE entidad_key=? AND kpi=? "
                 "AND variante=? ORDER BY periodo", (entidad, kpi, variante))
    return q("SELECT periodo, valor FROM derived_kpi WHERE entidad_key=? AND kpi=? "
             "ORDER BY periodo", (entidad, kpi))


def valor_cuota(fondo: str, tipo: str) -> pd.DataFrame:
    """tipo: 'contable' | 'bursatil'. Devuelve fecha, nemotecnico, valor."""
    tabla = f"raw_valor_cuota_{tipo}"
    vigente = "AND v.superseded_at IS NULL" if tipo == "contable" else ""
    return q(
        f"SELECT v.fecha, v.nemotecnico, s.serie, v.precio_clp AS valor "
        f"FROM {tabla} v JOIN dim_serie s ON s.nemotecnico = v.nemotecnico "
        f"WHERE s.fondo_key=? {vigente} ORDER BY v.fecha",
        (fondo,))


def repartos_u12m(fondo: str) -> pd.DataFrame:
    df = q(
        "SELECT d.fecha_pago, d.tipo, s.serie, MAX(d.monto_clp_cuota) AS monto "
        "FROM raw_dividendo d JOIN dim_serie s ON s.nemotecnico = d.nemotecnico "
        "WHERE s.fondo_key=? AND d.superseded_at IS NULL "
        "GROUP BY d.fecha_pago, d.tipo, s.serie ORDER BY d.fecha_pago DESC",
        (fondo,))
    if df.empty:
        return df
    tope = df["fecha_pago"].max()
    corte = (pd.Timestamp(tope) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
    return df[df["fecha_pago"] > corte]


def deuda_fondo(fondo: str) -> pd.DataFrame:
    """Último saldo por crédito vigente del fondo (histórico, no proyección futura)."""
    hoy = date.today().strftime("%Y-%m")
    return q(
        "SELECT c.credito_key, c.activo_key, c.acreedor, c.tasa_anual, "
        "       c.fecha_vencimiento, s.saldo_uf, s.periodo "
        "FROM dim_credito c "
        "JOIN raw_saldo_deuda s ON s.credito_key = c.credito_key "
        "WHERE c.fondo_key=? AND s.periodo = ("
        "   SELECT MAX(periodo) FROM raw_saldo_deuda s2 "
        "   WHERE s2.credito_key = c.credito_key AND s2.periodo <= ?) "
        "AND s.saldo_uf > 0",
        (fondo, hoy))


def deuda_historia(fondo: str) -> pd.DataFrame:
    hoy = date.today().strftime("%Y-%m")
    return q(
        "SELECT s.periodo, SUM(s.saldo_uf) AS deuda_uf "
        "FROM raw_saldo_deuda s JOIN dim_credito c ON c.credito_key = s.credito_key "
        "WHERE c.fondo_key=? AND s.periodo <= ? GROUP BY s.periodo ORDER BY s.periodo",
        (fondo, hoy))


def tasaciones(fondo: str) -> pd.DataFrame:
    # Si existe fila tasador='Promedio' se usa esa; si no, promedio de tasadores.
    return q(
        "SELECT t.activo_key, a.nombre, t.periodo, "
        "  COALESCE(MAX(CASE WHEN t.tasador='Promedio' THEN t.valor_uf END), "
        "           AVG(CASE WHEN t.tasador!='Promedio' THEN t.valor_uf END)) AS valor_uf "
        "FROM fact_tasacion t JOIN dim_activo a ON a.activo_key = t.activo_key "
        "WHERE a.fondo_key=? AND t.valor_uf > 0 AND t.periodo = ("
        "   SELECT MAX(periodo) FROM fact_tasacion t2 "
        "   WHERE t2.activo_key = t.activo_key AND t2.valor_uf > 0) "
        "GROUP BY t.activo_key, a.nombre, t.periodo",
        (fondo,))


def noi_series(entidades: list[str]) -> pd.DataFrame:
    ph = ",".join("?" * len(entidades))
    return q(
        f"SELECT entidad_key, periodo, valor FROM derived_kpi "
        f"WHERE kpi='noi_mensual' AND entidad_key IN ({ph}) ORDER BY periodo",
        tuple(entidades))


def vacancia_rr(activos: list[str]) -> pd.DataFrame:
    ph = ",".join("?" * len(activos))
    return q(
        f"SELECT activo_key, periodo, "
        f"  SUM(CASE WHEN LOWER(COALESCE(arrendatario,'vacante')) LIKE 'vacante%' "
        f"      THEN m2 ELSE 0 END) * 1.0 / NULLIF(SUM(m2),0) AS vacancia "
        f"FROM raw_rent_roll_line "
        f"WHERE superseded_at IS NULL AND activo_key IN ({ph}) "
        f"GROUP BY activo_key, periodo ORDER BY periodo",
        tuple(activos))


def patrimonio_fondo(fondo: str) -> pd.DataFrame:
    return q(
        "SELECT nemotecnico, periodo, valor_libro_clp, cuotas, patrimonio_libro_uf "
        "FROM v_serie_patrimonio WHERE fondo_key=? AND periodo = ("
        "  SELECT MAX(periodo) FROM v_serie_patrimonio WHERE fondo_key=?)",
        (fondo, fondo))


# ── Bloques de página ────────────────────────────────────────────────────────
def bloque_header(fondo: str) -> None:
    f = FICHA[fondo]
    st.markdown(
        f'<div class="tsc-band"><span class="tsc-logo">toesca<span class="dot">.</span></span>'
        f'<span><strong>{f["titulo"]}</strong><br><span class="sub">{f["subtitulo"]}</span></span>'
        f'<span class="per">Fact sheet dinámico</span></div>',
        unsafe_allow_html=True)


def bloque_kpis(fondo: str) -> None:
    pat = patrimonio_fondo(fondo)
    deuda = deuda_fondo(fondo)
    tas = tasaciones(fondo)
    items: list[tuple[str, str, str]] = []

    if not pat.empty:
        per = pat["periodo"].iloc[0]
        items.append(("Patrimonio contable",
                      fmt_uf(pat["patrimonio_libro_uf"].sum()), per))
        vc = pat.sort_values("nemotecnico").iloc[0]
        items.append(("Valor cuota libro", fmt_clp(vc["valor_libro_clp"]),
                      f"{vc['nemotecnico']} · {per}"))
    if not deuda.empty:
        total_deuda = deuda["saldo_uf"].sum()
        items.append(("Deuda financiera", fmt_uf(total_deuda),
                      deuda["periodo"].max()))
        tasa = (deuda["tasa_anual"] * deuda["saldo_uf"]).sum() / total_deuda
        items.append(("Tasa promedio", fmt_pct(tasa), "ponderada por saldo"))
        if not tas.empty:
            ltv = total_deuda / tas["valor_uf"].sum()
            items.append(("LTV", fmt_pct(ltv), f"tasaciones {tas['periodo'].max()}"))
        if not pat.empty:
            lev = total_deuda / pat["patrimonio_libro_uf"].sum()
            items.append(("Leverage", f"{lev:.2f} x".replace(".", ","), "deuda / patrimonio"))
    if items:
        cards(items)


def bloque_rentabilidad(fondo: str) -> None:
    series = series_fondo(fondo)
    if series.empty:
        return
    h2("Rentabilidad del fondo (en UF)")
    colnames, data, periodos = [], {}, set()
    for _, s in series.iterrows():
        nemo, nombre = s["nemotecnico"], f"Serie {s['serie']}"
        variantes = [("bursatil", "Bursátil")] if s["transa_bolsa"] else []
        variantes += [("contable", "Libro")]
        if not s["transa_bolsa"]:
            variantes = [("contable", "Libro")]
        for vkey, vlabel in variantes:
            col = f"{nombre} · {vlabel}"
            colnames.append(col)
            vals = []
            for label, kpi_tpl, var_tpl in FILAS_RENTAB:
                kpi = kpi_tpl.format(v=vkey)
                var = var_tpl.format(v=vkey) if var_tpl else None
                # Apo: dy_amort se guarda con variante 'capital'
                if fondo == "Apo" and kpi == "dy_amort":
                    var = "capital"
                per, val = kpi_ultimo(nemo, kpi, var)
                vals.append(val)
                if per:
                    periodos.add(per)
            data[col] = vals
    df = pd.DataFrame(data, index=[f[0] for f in FILAS_RENTAB])
    st.dataframe(
        df.style.format(lambda v: fmt_pct(v) if pd.notna(v) else "—"),
        use_container_width=True)
    if periodos:
        st.markdown(
            f'<p class="tsc-note">Último dato por indicador: bursátil {max(periodos)} · '
            f'contable al último EEFF trimestral disponible.</p>', unsafe_allow_html=True)


def bloque_valor_cuota(fondo: str) -> None:
    vc_c = valor_cuota(fondo, "contable")
    vc_b = valor_cuota(fondo, "bursatil")
    if vc_c.empty and vc_b.empty:
        return
    h2("Valor cuota")
    c1, c2 = st.columns(2)
    for col, df, titulo in ((c1, vc_c, "Libro (CLP)"), (c2, vc_b, "Bursátil (CLP)")):
        if df.empty:
            continue
        fig = go.Figure()
        for i, (serie, g) in enumerate(df.groupby("serie")):
            fig.add_trace(go.Scatter(
                x=g["fecha"], y=g["valor"], name=f"Serie {serie}", mode="lines",
                line=dict(color=PALETTE[i % len(PALETTE)], width=2)))
        base_layout(fig, "CLP / cuota")
        fig.update_layout(title=dict(text=titulo, font=dict(size=13, color=MUTED)))
        col.plotly_chart(fig, use_container_width=True)


def bloque_repartos(fondo: str) -> None:
    df = repartos_u12m(fondo)
    if df.empty:
        return
    h2("Repartos últimos 12 meses (pesos por cuota)")
    pivot = df.pivot_table(index=["fecha_pago", "tipo"], columns="serie",
                           values="monto").reset_index()
    pivot = pivot.rename(columns={"fecha_pago": "Fecha pago", "tipo": "Concepto"})
    pivot["Concepto"] = pivot["Concepto"].map(
        {"dividendo": "Dividendo provisorio", "disminucion": "Disminución de capital"})
    fmt = {c: (lambda v: fmt_clp(v, 1)) for c in pivot.columns[2:]}
    st.dataframe(pivot.style.format(fmt), use_container_width=True, hide_index=True)


def bloque_endeudamiento(fondo: str) -> None:
    deuda = deuda_fondo(fondo)
    if deuda.empty:
        return
    h2("Endeudamiento consolidado (en UF)")
    total = deuda["saldo_uf"].sum()

    # Perfil de vencimiento por saldo
    hoy = pd.Timestamp(date.today())
    def bucket(v):
        try:
            años = (pd.Timestamp(v) - hoy).days / 365.25
        except Exception:
            return "s/d"
        if años <= 3:
            return "0-3 años"
        if años <= 7:
            return "3-7 años"
        if años <= 10:
            return "7-10 años"
        return ">10 años"
    deuda["bucket"] = deuda["fecha_vencimiento"].map(bucket)
    perfil = deuda.groupby("bucket")["saldo_uf"].sum() / total
    orden = ["0-3 años", "3-7 años", "7-10 años", ">10 años"]
    perfil = perfil.reindex([b for b in orden if b in perfil.index])

    c1, c2 = st.columns([3, 2])
    hist = deuda_historia(fondo)
    if not hist.empty:
        fig = go.Figure(go.Scatter(x=hist["periodo"], y=hist["deuda_uf"],
                                   mode="lines", name="Deuda UF",
                                   line=dict(color=PALETTE[0], width=2),
                                   fill="tozeroy",
                                   fillcolor="rgba(20,158,99,0.12)"))
        base_layout(fig, "UF")
        fig.update_layout(title=dict(text="Evolución deuda financiera (UF)",
                                     font=dict(size=13, color=MUTED)),
                          showlegend=False)
        c1.plotly_chart(fig, use_container_width=True)

    fig2 = go.Figure(go.Bar(
        x=perfil.values, y=perfil.index, orientation="h",
        marker=dict(color=PALETTE[0], cornerradius=4),
        text=[fmt_pct(v, 0) for v in perfil.values], textposition="outside"))
    base_layout(fig2, "")
    fig2.update_layout(title=dict(text="Perfil de vencimiento (saldo)",
                                  font=dict(size=13, color=MUTED)),
                       xaxis=dict(tickformat=".0%", gridcolor=LINE),
                       showlegend=False)
    c2.plotly_chart(fig2, use_container_width=True)

    det = deuda[["activo_key", "acreedor", "tasa_anual", "fecha_vencimiento", "saldo_uf"]] \
        .sort_values("saldo_uf", ascending=False) \
        .rename(columns={"activo_key": "Activo", "acreedor": "Acreedor",
                         "tasa_anual": "Tasa", "fecha_vencimiento": "Vencimiento",
                         "saldo_uf": "Saldo UF"})
    st.dataframe(det.style.format({"Tasa": lambda v: fmt_pct(v, 2),
                                   "Saldo UF": lambda v: fmt_uf(v)}),
                 use_container_width=True, hide_index=True)


def bloque_noi(fondo: str) -> None:
    ents = NOI_ACTIVOS.get(fondo, [])
    df = noi_series(ents)
    if df.empty:
        return
    h2("NOI mensual por activo (UF, 100% del activo)")
    ult = df["periodo"].max()
    u12 = df[df["periodo"] > (pd.Period(ult) - 12).strftime("%Y-%m")]
    cards([("NOI U12M", fmt_uf(u12["valor"].sum()), f"hasta {ult}"),
           ("NOI último mes", fmt_uf(df[df['periodo'] == ult]['valor'].sum()), ult)])
    fig = go.Figure()
    for i, (ent, g) in enumerate(df.groupby("entidad_key")):
        fig.add_trace(go.Scatter(x=g["periodo"], y=g["valor"], name=ent, mode="lines",
                                 line=dict(color=PALETTE[i % len(PALETTE)], width=2),
                                 stackgroup="noi"))
    base_layout(fig, "UF / mes", height=380)
    st.plotly_chart(fig, use_container_width=True)


def bloque_vacancia(fondo: str) -> None:
    acts = RR_ACTIVOS.get(fondo, [])
    df = vacancia_rr(acts)
    if df.empty:
        return
    h2("Vacancia (m², desde rent roll)")
    fig = go.Figure()
    for i, (act, g) in enumerate(df.groupby("activo_key")):
        fig.add_trace(go.Scatter(x=g["periodo"], y=g["vacancia"], name=act,
                                 mode="lines+markers",
                                 line=dict(color=PALETTE[i % len(PALETTE)], width=2),
                                 marker=dict(size=7)))
    base_layout(fig, "% m² vacantes")
    fig.update_layout(yaxis=dict(tickformat=".0%", gridcolor=LINE))
    st.plotly_chart(fig, use_container_width=True)


def bloque_tasaciones(fondo: str) -> None:
    tas = tasaciones(fondo)
    if tas.empty:
        return
    h2("Indicadores activos — tasación y LTV")
    deuda = deuda_fondo(fondo)
    d_act = deuda.groupby("activo_key")["saldo_uf"].sum() if not deuda.empty else pd.Series(dtype=float)
    tas = tas.copy()
    tas["deuda_uf"] = tas["activo_key"].map(d_act)
    tas["ltv"] = tas["deuda_uf"] / tas["valor_uf"]
    out = tas[["nombre", "periodo", "valor_uf", "deuda_uf", "ltv"]].rename(columns={
        "nombre": "Activo", "periodo": "Tasación", "valor_uf": "Valor tasación UF",
        "deuda_uf": "Deuda UF", "ltv": "LTV"})
    tot = pd.DataFrame([{
        "Activo": "Total fondo", "Tasación": "",
        "Valor tasación UF": out["Valor tasación UF"].sum(),
        "Deuda UF": out["Deuda UF"].sum(),
        "LTV": out["Deuda UF"].sum() / out["Valor tasación UF"].sum(),
    }])
    out = pd.concat([out, tot], ignore_index=True)
    st.dataframe(out.style.format({
        "Valor tasación UF": lambda v: fmt_uf(v),
        "Deuda UF": lambda v: fmt_uf(v),
        "LTV": lambda v: fmt_pct(v)}),
        use_container_width=True, hide_index=True)


def bloque_ficha(fondo: str) -> None:
    h2("El fondo")
    df = pd.DataFrame(FICHA[fondo]["info"], columns=["", "Valor"])
    pat = patrimonio_fondo(fondo)
    if not pat.empty:
        cuotas = pat["cuotas"].sum()
        extra = pd.DataFrame([("Nº cuotas suscritas y pagadas",
                               fmt_num(cuotas))], columns=["", "Valor"])
        df = pd.concat([df, extra], ignore_index=True)
    st.dataframe(df, use_container_width=True, hide_index=True)


def pagina_fondo(fondo: str) -> None:
    bloque_header(fondo)
    bloque_kpis(fondo)
    bloque_rentabilidad(fondo)
    bloque_valor_cuota(fondo)
    bloque_repartos(fondo)
    bloque_endeudamiento(fondo)
    bloque_noi(fondo)
    bloque_vacancia(fondo)
    bloque_tasaciones(fondo)
    bloque_ficha(fondo)


# ── Portfolio ────────────────────────────────────────────────────────────────
def pagina_portfolio() -> None:
    st.markdown(
        '<div class="tsc-band"><span class="tsc-logo">toesca<span class="dot">.</span></span>'
        '<span><strong>Fondos Inmobiliarios</strong><br>'
        '<span class="sub">Portfolio — TRI · PT · Apoquindo</span></span>'
        '<span class="per">Dashboard</span></div>', unsafe_allow_html=True)

    # KPI cards por fondo
    fondos = ["TRI", "PT", "Apo"]
    items = []
    for f in fondos:
        pat = patrimonio_fondo(f)
        if not pat.empty:
            items.append((f"Patrimonio {f}", fmt_uf(pat["patrimonio_libro_uf"].sum()),
                          pat["periodo"].iloc[0]))
    for f in fondos:
        d = deuda_fondo(f)
        if not d.empty:
            items.append((f"Deuda {f}", fmt_uf(d["saldo_uf"].sum()), d["periodo"].max()))
    if items:
        cards(items)

    # Comparativa de rentabilidad por serie
    h2("Rentabilidad — comparativa por serie")
    filas = []
    series = q("SELECT s.nemotecnico, s.fondo_key, s.serie, s.transa_bolsa "
               "FROM dim_serie s ORDER BY s.fondo_key, s.serie")
    for _, s in series.iterrows():
        nemo = s["nemotecnico"]
        v = "bursatil" if s["transa_bolsa"] else "contable"
        _, tir = kpi_ultimo(nemo, f"tir_{v}_desde_inicio")
        _, ytd = kpi_ultimo(nemo, f"rent_ytd_{v}")
        _, u12 = kpi_ultimo(nemo, f"tir_{v}_u12m")
        _, dy = kpi_ultimo(nemo, "dy", v if nemo != "Apo" else "contable")
        _, dya = kpi_ultimo(nemo, "dy_amort", "capital" if nemo == "Apo" else v)
        filas.append({"Fondo": s["fondo_key"], "Serie": s["serie"],
                      "Base": "Bursátil" if s["transa_bolsa"] else "Libro",
                      "Desde inicio (anual.)": tir, "YTD (anual.)": ytd,
                      "U12M": u12, "Dividend Yield": dy, "DY + Amortización": dya})
    dfr = pd.DataFrame(filas)
    pct_cols = dfr.columns[3:]
    st.dataframe(dfr.style.format({c: (lambda v: fmt_pct(v)) for c in pct_cols}),
                 use_container_width=True, hide_index=True)

    # TIR bursátil desde inicio — evolución
    h2("TIR desde inicio — evolución (bursátil)")
    fig = go.Figure()
    i = 0
    for nemo, label in [("CFITOERI1A", "TRI Serie A"), ("CFITOERI1C", "TRI Serie C"),
                        ("CFITOERI1I", "TRI Serie I"), ("CFITRIPT-E", "PT")]:
        g = kpi_serie_hist(nemo, "tir_bursatil_desde_inicio")
        if g.empty:
            continue
        fig.add_trace(go.Scatter(x=g["periodo"], y=g["valor"], name=label, mode="lines",
                                 line=dict(color=PALETTE[i % len(PALETTE)], width=2)))
        i += 1
    base_layout(fig, "TIR anualizada", height=380)
    fig.update_layout(yaxis=dict(tickformat=".0%", gridcolor=LINE))
    st.plotly_chart(fig, use_container_width=True)

    # NOI portfolio por categoría
    h2("NOI mensual del portfolio (UF, 100% de los activos)")
    ents = ["Viña Centro", "Mall Curicó", "INMOSA", "Sucden", "Apo3001",
            "PT Torre A", "PT Boulevard", "Apoquindo"]
    df = noi_series(ents)
    if not df.empty:
        cat = {"Viña Centro": "Centros Comerciales", "Mall Curicó": "Centros Comerciales",
               "INMOSA": "Residencias", "Sucden": "Industrial",
               "Apo3001": "Oficinas", "PT Torre A": "Oficinas",
               "PT Boulevard": "Oficinas", "Apoquindo": "Oficinas"}
        df["categoria"] = df["entidad_key"].map(cat)
        g = df.groupby(["categoria", "periodo"])["valor"].sum().reset_index()
        fig = go.Figure()
        for i, (c, gg) in enumerate(g.groupby("categoria")):
            fig.add_trace(go.Scatter(x=gg["periodo"], y=gg["valor"], name=c,
                                     mode="lines", stackgroup="noi",
                                     line=dict(color=PALETTE[i % len(PALETTE)], width=2)))
        base_layout(fig, "UF / mes", height=380)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown('<p class="tsc-note">Fuente: memory/agente_toesca_v2.db · '
                'Los bloques aparecen a medida que la DB se va poblando.</p>',
                unsafe_allow_html=True)


# ── Main ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Toesca · Fondos Inmobiliarios", layout="wide",
                   page_icon="🏢")
st.markdown(CSS, unsafe_allow_html=True)

st.sidebar.markdown(
    '<div style="font-family:Georgia,serif;font-size:26px;margin-bottom:6px">'
    f'toesca<span style="color:{GREEN}">.</span></div>', unsafe_allow_html=True)
vista = st.sidebar.radio("Vista", [
    "Portfolio",
    "TRI — Rentas Inmobiliarias",
    "PT — Parque Titanium",
    "Apo — Apoquindo",
], label_visibility="collapsed")
st.sidebar.caption("Fact sheets dinámicos alimentados por la base de datos del agente. "
                   "Corte bursátil: mensual · corte contable: EEFF trimestral.")

if vista == "Portfolio":
    pagina_portfolio()
else:
    pagina_fondo({"TRI — Rentas Inmobiliarias": "TRI",
                  "PT — Parque Titanium": "PT",
                  "Apo — Apoquindo": "Apo"}[vista])
