"""Dashboard TIR histórica Fondo TRI — evolución de los 6 tipos de TIR por serie.

Run:
    streamlit run dashboards/tir_tri.py
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path
from datetime import date

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "memory" / "agente_toesca_v2.db"
SKILL_SCRIPTS = Path.home() / ".claude" / "skills" / "real-estate-finance-expert" / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from compute_or_fetch import obtener  # noqa: E402

SERIES = [
    ("CFITOERI1A", "Serie A"),
    ("CFITOERI1C", "Serie C"),
    ("CFITOERI1I", "Serie I"),
]

KPIS_BURSATIL = [
    ("tir_bursatil_desde_inicio", "Bursátil desde inicio"),
    ("tir_bursatil_ytd",          "Bursátil YTD"),
    ("tir_bursatil_u12m",         "Bursátil U12M"),
]

KPIS_CONTABLE = [
    ("tir_contable_desde_inicio", "Contable desde inicio"),
    ("tir_contable_ytd",          "Contable YTD"),
    ("tir_contable_u12m",         "Contable U12M"),
]

# Líneas continuas para contable, punteadas para bursátil
LINE_STYLES = {
    "tir_bursatil_desde_inicio": dict(color="#1f77b4", dash="dot"),
    "tir_bursatil_ytd":          dict(color="#ff7f0e", dash="dot"),
    "tir_bursatil_u12m":         dict(color="#2ca02c", dash="dot"),
    "tir_contable_desde_inicio": dict(color="#1f77b4", dash="solid"),
    "tir_contable_ytd":          dict(color="#ff7f0e", dash="solid"),
    "tir_contable_u12m":         dict(color="#2ca02c", dash="solid"),
}


def get_periodos(tipo: str) -> list[str]:
    """Obtiene períodos únicos en formato YYYY-MM."""
    tabla = "raw_valor_cuota_contable" if tipo == "contable" else "raw_valor_cuota_bursatil"
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            f"SELECT DISTINCT fecha FROM {tabla} "
            "WHERE nemotecnico='CFITOERI1A' ORDER BY fecha",
        ).fetchall()
    return [r[0][:7] for r in rows]


@st.cache_data(show_spinner=False)
def compute_all_tirs() -> pd.DataFrame:
    """
    Computa los 6 KPIs de TIR para todos los períodos y series.
    Usa la caché interna del skill (SQLite cached_indicators), por lo que
    la primera ejecución es lenta; las siguientes son instantáneas.
    """
    periodos_bursatil = get_periodos("bursatil")
    periodos_contable = get_periodos("contable")

    records = []

    total = len(SERIES) * (
        len(periodos_bursatil) * len(KPIS_BURSATIL) +
        len(periodos_contable) * len(KPIS_CONTABLE)
    )
    bar = st.progress(0, text="Calculando TIRs… (primera vez puede tardar ~2 min)")
    done = 0

    for nemo, serie_label in SERIES:
        # KPIs bursátiles — frecuencia mensual
        for periodo in periodos_bursatil:
            for kpi, _ in KPIS_BURSATIL:
                r = obtener(kpi, "serie", nemo, periodo)
                records.append({
                    "serie": serie_label,
                    "nemotecnico": nemo,
                    "periodo": periodo,
                    "kpi": kpi,
                    "valor": r.get("valor"),
                })
                done += 1
                bar.progress(done / total)

        # KPIs contables — frecuencia trimestral
        for periodo in periodos_contable:
            for kpi, _ in KPIS_CONTABLE:
                r = obtener(kpi, "serie", nemo, periodo)
                records.append({
                    "serie": serie_label,
                    "nemotecnico": nemo,
                    "periodo": periodo,
                    "kpi": kpi,
                    "valor": r.get("valor"),
                })
                done += 1
                bar.progress(done / total)

    bar.empty()
    return pd.DataFrame(records)


def build_chart(df: pd.DataFrame, serie_label: str) -> go.Figure:
    """Construye figura Plotly con 6 líneas para una serie."""
    df_s = df[df["serie"] == serie_label].copy()
    df_s["fecha"] = pd.to_datetime(df_s["periodo"] + "-01")
    df_s = df_s.dropna(subset=["valor"])
    df_s["pct"] = df_s["valor"] * 100

    fig = go.Figure()

    all_kpis = KPIS_BURSATIL + KPIS_CONTABLE
    for kpi, label in all_kpis:
        sub = df_s[df_s["kpi"] == kpi].sort_values("fecha")
        if sub.empty:
            continue
        style = LINE_STYLES[kpi]
        fig.add_trace(go.Scatter(
            x=sub["fecha"],
            y=sub["pct"],
            mode="lines+markers",
            name=label,
            line=dict(color=style["color"], dash=style["dash"], width=2),
            marker=dict(size=4),
            hovertemplate="%{x|%Y-%m}: %{y:.2f}%<extra>" + label + "</extra>",
        ))

    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    fig.update_layout(
        title=f"TIR histórica — {serie_label}",
        xaxis_title=None,
        yaxis_title="TIR anual (%)",
        yaxis_ticksuffix="%",
        legend=dict(orientation="h", y=-0.15, x=0),
        height=420,
        margin=dict(t=50, b=80),
        hovermode="x unified",
    )
    return fig


# ── App ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="TIR Fondo TRI", layout="wide", page_icon="📈")
st.title("TIR histórica — Fondo TRI")
st.caption(
    "Líneas sólidas = contable · Líneas punteadas = bursátil  |  "
    "Bursátil: frecuencia mensual · Contable: frecuencia trimestral"
)

force = st.sidebar.button("Recalcular (ignorar caché)")
if force:
    st.cache_data.clear()

with st.spinner("Cargando datos…"):
    df = compute_all_tirs()

if df.empty:
    st.error("No se encontraron datos. Verifica la DB.")
    st.stop()

cols = st.columns(3)
for col, (nemo, label) in zip(cols, SERIES):
    with col:
        fig = build_chart(df, label)
        st.plotly_chart(fig, use_container_width=True)

# Tabla resumen: último período disponible por serie y KPI
st.subheader("Último período disponible por KPI")
ultimo = (
    df.dropna(subset=["valor"])
    .sort_values("periodo")
    .groupby(["serie", "kpi"])
    .last()
    .reset_index()[["serie", "kpi", "periodo", "valor"]]
)
ultimo["valor"] = (ultimo["valor"] * 100).map("{:.2f}%".format)
ultimo = ultimo.pivot(index="kpi", columns="serie", values="valor")
st.dataframe(ultimo, use_container_width=True)
