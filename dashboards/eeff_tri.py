"""Dashboard EEFF histórico Fondo TRI.

Run:
    streamlit run dashboards/eeff_tri.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

DB = Path(__file__).resolve().parents[1] / "memory" / "agente_toesca.db"
FONDO = "TRI"

st.set_page_config(page_title="EEFF Fondo TRI", layout="wide", page_icon="📊")


@st.cache_data(ttl=300)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with sqlite3.connect(DB) as con:
        return pd.read_sql_query(sql, con, params=params)


def fmt_clp_millions(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"$ {x/1e6:,.0f} M"


def pivot_by_account(source_sheet: str, periodos: list[str]) -> pd.DataFrame:
    placeholders = ",".join("?" * len(periodos))
    df = q(
        f"""
        SELECT periodo, cuenta_nombre, SUM(monto_clp) AS monto_clp
        FROM raw_eeff_line
        WHERE fondo_key = ?
          AND superseded_at IS NULL
          AND source_sheet = ?
          AND cuenta_nombre IS NOT NULL
          AND periodo IN ({placeholders})
        GROUP BY periodo, cuenta_nombre
        """,
        (FONDO, source_sheet, *periodos),
    )
    if df.empty:
        return df
    return (
        df.pivot_table(index="cuenta_nombre", columns="periodo", values="monto_clp", aggfunc="sum")
        .sort_index(axis=1)
    )


# ─── Sidebar ─────────────────────────────────────────────────────────────────

periodos_df = q(
    """
    SELECT DISTINCT periodo FROM raw_eeff_line
    WHERE fondo_key = ? AND superseded_at IS NULL
    ORDER BY periodo
    """,
    (FONDO,),
)
periodos = periodos_df["periodo"].tolist()

st.sidebar.title("Filtros")
rango = st.sidebar.select_slider(
    "Rango de períodos",
    options=periodos,
    value=(periodos[0], periodos[-1]),
)
periodos_sel = [p for p in periodos if rango[0] <= p <= rango[1]]
st.sidebar.caption(f"{len(periodos_sel)} períodos seleccionados")
st.sidebar.caption(f"Fuente: `raw_eeff_line` · fondo `{FONDO}`")

# ─── Header ──────────────────────────────────────────────────────────────────

nombre_fondo = q("SELECT nombre FROM dim_fondo WHERE fondo_key = ?", (FONDO,)).iloc[0, 0]
st.title(f"📊 EEFF Histórico — {nombre_fondo}")
st.caption(
    f"{len(periodos)} períodos disponibles · desde **{periodos[0]}** hasta **{periodos[-1]}**"
)

# ─── KPIs (último periodo) ───────────────────────────────────────────────────

ultimo = periodos_sel[-1] if periodos_sel else periodos[-1]
anterior = periodos_sel[-2] if len(periodos_sel) >= 2 else None


def kpi_value(cuenta: str, source_sheet: str, periodo: str) -> float | None:
    df = q(
        """
        SELECT SUM(monto_clp) AS v
        FROM raw_eeff_line
        WHERE fondo_key = ? AND superseded_at IS NULL
          AND source_sheet = ? AND cuenta_nombre = ? AND periodo = ?
        """,
        (FONDO, source_sheet, cuenta, periodo),
    )
    v = df.iloc[0, 0]
    return None if pd.isna(v) else float(v)


kpi_specs = [
    ("Patrimonio", "ESF", "Patrimonio"),
    ("Resultado del ejercicio", "ESF", "Resultado del ejercicio"),
    ("Efectivo y equiv.", "ESF", "Efectivo y efectivo equivalente"),
    ("Préstamos", "ESF", "Préstamos"),
]

cols = st.columns(len(kpi_specs))
for col, (label, sheet, cuenta) in zip(cols, kpi_specs):
    v = kpi_value(cuenta, sheet, ultimo)
    delta = None
    if anterior is not None and v is not None:
        v_prev = kpi_value(cuenta, sheet, anterior)
        if v_prev is not None and v_prev != 0:
            delta = f"{(v - v_prev) / abs(v_prev) * 100:+.1f}% vs {anterior}"
    col.metric(label, fmt_clp_millions(v), delta)

st.caption(f"KPIs al período **{ultimo}**")

# ─── Tabs ────────────────────────────────────────────────────────────────────

tab_balance_cuotas, tab_er, tab_esf, tab_efe, tab_ecp, tab_notas, tab_libre = st.tabs(
    [
        "📊 Balance & Cuotas",
        "📈 Estado de Resultados",
        "🏦 Balance (ESF)",
        "💵 Flujo de Efectivo",
        "📜 Patrimonio (ECP)",
        "📎 Anexos / Notas",
        "🔎 Explorador",
    ]
)


def render_sheet_tab(sheet_code: str, default_top: int = 8) -> None:
    pivot = pivot_by_account(sheet_code, periodos_sel)
    if pivot.empty:
        st.info(f"No hay datos de `{sheet_code}` en el rango seleccionado.")
        return

    # Ordenar cuentas por magnitud absoluta en último periodo
    last_col = pivot.columns[-1]
    pivot = pivot.reindex(pivot[last_col].abs().sort_values(ascending=False).index)

    cuentas_all = pivot.index.tolist()
    seleccion = st.multiselect(
        "Cuentas a graficar",
        cuentas_all,
        default=cuentas_all[:default_top],
        key=f"sel_{sheet_code}",
    )

    if seleccion:
        plot_df = (
            pivot.loc[seleccion]
            .T.reset_index()
            .melt(id_vars="periodo", var_name="Cuenta", value_name="CLP")
        )
        fig = px.line(
            plot_df,
            x="periodo",
            y="CLP",
            color="Cuenta",
            markers=True,
            title=f"{sheet_code} — Evolución",
        )
        fig.update_layout(height=500, hovermode="x unified", legend_title=None)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown(f"##### Pivot completo `{sheet_code}` (CLP)")
    # Formato CLP con separador de miles
    st.dataframe(
        pivot.style.format("{:,.0f}", na_rep="—"),
        use_container_width=True,
        height=min(600, 40 + 35 * len(pivot)),
    )


with tab_balance_cuotas:
    st.subheader("Evolución Activos / Pasivos / Patrimonio")

    # ── Activos, Patrimonio (varias nomenclaturas por período), Pasivos = A - P ──
    @st.cache_data(ttl=300)
    def load_balance_tri(periodos_list: tuple) -> pd.DataFrame:
        ph = ",".join("?" * len(periodos_list))
        activos_names = (
            "Total activo", "TOTAL ACTIVO", "TOTAL ACTIVOS",
        )
        patrimonio_names = (
            "Total patrimonio neto", "TOTAL PATRIMONIO NETO",
            "Total patrimonio", "Patrimonio",
        )
        ph_a = ",".join("?" * len(activos_names))
        ph_p = ",".join("?" * len(patrimonio_names))
        with sqlite3.connect(DB) as con:
            df_a = pd.read_sql_query(
                f"""
                SELECT periodo, SUM(monto_clp) AS activos
                FROM raw_eeff_line
                WHERE fondo_key = 'TRI' AND source_sheet = 'ESF'
                  AND superseded_at IS NULL
                  AND cuenta_nombre IN ({ph_a})
                  AND periodo IN ({ph})
                GROUP BY periodo
                """,
                con,
                params=(*activos_names, *periodos_list),
            )
            df_p = pd.read_sql_query(
                f"""
                SELECT periodo, SUM(monto_clp) AS patrimonio
                FROM raw_eeff_line
                WHERE fondo_key = 'TRI' AND source_sheet = 'ESF'
                  AND superseded_at IS NULL
                  AND cuenta_nombre IN ({ph_p})
                  AND periodo IN ({ph})
                GROUP BY periodo
                """,
                con,
                params=(*patrimonio_names, *periodos_list),
            )
        df = df_a.merge(df_p, on="periodo", how="outer").sort_values("periodo")
        df["pasivos"] = df["activos"] - df["patrimonio"]
        return df

    df_bal = load_balance_tri(tuple(periodos_sel))

    if df_bal.empty:
        st.info("Sin datos de balance en el rango seleccionado.")
    else:
        df_melt = df_bal.melt(
            id_vars="periodo",
            value_vars=["activos", "pasivos", "patrimonio"],
            var_name="Componente",
            value_name="CLP",
        )
        df_melt["Componente"] = df_melt["Componente"].map(
            {"activos": "Activos", "pasivos": "Pasivos", "patrimonio": "Patrimonio"}
        )
        col1, col2 = st.columns([3, 1])
        with col1:
            fig_bal = px.line(
                df_melt,
                x="periodo",
                y="CLP",
                color="Componente",
                markers=True,
                color_discrete_map={
                    "Activos": "#1f77b4",
                    "Pasivos": "#d62728",
                    "Patrimonio": "#2ca02c",
                },
                title="Activos · Pasivos · Patrimonio (CLP)",
            )
            fig_bal.update_layout(height=420, hovermode="x unified", legend_title=None)
            fig_bal.update_yaxes(tickformat="$,.0f")
            st.plotly_chart(fig_bal, use_container_width=True)
        with col2:
            ultimo_bal = df_bal.dropna(subset=["activos"]).iloc[-1]
            st.metric("Activos", fmt_clp_millions(ultimo_bal.get("activos")))
            st.metric("Pasivos", fmt_clp_millions(ultimo_bal.get("pasivos")))
            st.metric("Patrimonio", fmt_clp_millions(ultimo_bal.get("patrimonio")))
            leverage = (
                ultimo_bal.get("pasivos", 0) / ultimo_bal.get("activos", 1) * 100
                if ultimo_bal.get("activos")
                else None
            )
            if leverage is not None:
                st.metric("Deuda / Activos", f"{leverage:.1f}%")

        st.dataframe(
            df_bal.set_index("periodo").style.format("{:,.0f}", na_rep="—"),
            use_container_width=True,
        )

    # ── Valores contables de cuotas vs precio bursátil ──────────────────────
    st.divider()
    st.subheader("Valor Contable vs Precio Bursátil — Series TRI")

    @st.cache_data(ttl=300)
    def load_cuotas_tri() -> tuple[pd.DataFrame, pd.DataFrame]:
        with sqlite3.connect(DB) as con:
            vc = pd.read_sql_query(
                """
                SELECT entidad_key AS nemotecnico, periodo AS fecha, valor AS valor_libro
                FROM derived_kpi
                WHERE kpi = 'valor_cuota_libro'
                  AND entidad_key IN (SELECT nemotecnico FROM dim_serie WHERE fondo_key = 'TRI')
                ORDER BY nemotecnico, fecha
                """,
                con,
            )
            precios = pd.read_sql_query(
                """
                SELECT p.nemotecnico, p.fecha, p.precio AS precio_bursatil,
                       u.valor_clp AS uf,
                       p.precio / NULLIF(u.valor_clp, 0) AS precio_uf
                FROM fact_precio_cuota p
                LEFT JOIN fact_uf u ON u.fecha = p.fecha
                WHERE p.nemotecnico IN (SELECT nemotecnico FROM dim_serie WHERE fondo_key = 'TRI')
                ORDER BY p.nemotecnico, p.fecha
                """,
                con,
            )
        return vc, precios

    df_vc, df_precios = load_cuotas_tri()

    series_tri = sorted(set(df_precios["nemotecnico"].tolist() + df_vc["nemotecnico"].tolist()))
    serie_sel = st.selectbox("Serie", series_tri, key="serie_cuota")

    pr = df_precios[df_precios["nemotecnico"] == serie_sel].copy()
    vc = df_vc[df_vc["nemotecnico"] == serie_sel].copy()

    if pr.empty and vc.empty:
        st.info("Sin datos para esta serie.")
    else:
        fig_cuota = px.line(
            pr, x="fecha", y="precio_bursatil", markers=False,
            labels={"precio_bursatil": "CLP", "fecha": "Fecha"},
            title=f"Precio bursátil {serie_sel}",
            color_discrete_sequence=["#1f77b4"],
        )
        fig_cuota.data[0].name = "Precio bursátil"
        fig_cuota.data[0].showlegend = True

        if not vc.empty:
            import plotly.graph_objects as go
            fig_cuota.add_trace(
                go.Scatter(
                    x=vc["fecha"],
                    y=vc["valor_libro"],
                    mode="markers",
                    marker=dict(size=12, color="#d62728", symbol="diamond"),
                    name="Valor libro (contable)",
                )
            )

        fig_cuota.update_layout(height=380, hovermode="x unified", legend_title=None)
        fig_cuota.update_yaxes(tickformat="$,.0f")
        st.plotly_chart(fig_cuota, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            if not pr.empty:
                st.caption(f"Precio bursátil más reciente ({pr.iloc[-1]['fecha']})")
                st.dataframe(
                    pr[["fecha", "precio_bursatil", "precio_uf"]].tail(12).set_index("fecha")
                    .style.format({"precio_bursatil": "{:,.0f}", "precio_uf": "{:.4f}"}),
                    use_container_width=True,
                )
        with c2:
            if not vc.empty:
                st.caption("Valor contable (libro) disponible")
                st.dataframe(
                    vc[["fecha", "valor_libro"]].set_index("fecha")
                    .style.format("{:,.2f}"),
                    use_container_width=True,
                )


with tab_er:
    st.subheader("Estado de Resultados")
    render_sheet_tab("ER")

with tab_esf:
    st.subheader("Estado de Situación Financiera")
    render_sheet_tab("ESF", default_top=10)

with tab_efe:
    st.subheader("Estado de Flujo de Efectivo")
    render_sheet_tab("EFE")

with tab_ecp:
    st.subheader("Estado de Cambios en el Patrimonio")
    render_sheet_tab("ECP")

with tab_notas:
    st.subheader("Anexos y Notas")
    sheets_extra = q(
        """
        SELECT source_sheet, COUNT(*) AS lineas
        FROM raw_eeff_line
        WHERE fondo_key = ? AND superseded_at IS NULL
          AND source_sheet NOT IN ('ER','ESF','EFE','ECP')
        GROUP BY source_sheet ORDER BY lineas DESC
        """,
        (FONDO,),
    )
    if sheets_extra.empty:
        st.info("Sin anexos/notas cargados.")
    else:
        sheet_pick = st.selectbox(
            "Anexo / Nota",
            sheets_extra["source_sheet"].tolist(),
            format_func=lambda s: f"{s} ({int(sheets_extra.loc[sheets_extra.source_sheet == s, 'lineas'].iloc[0])} líneas)",
        )
        render_sheet_tab(sheet_pick)

with tab_libre:
    st.subheader("Explorador de cuentas")
    todas = q(
        """
        SELECT DISTINCT cuenta_nombre, source_sheet
        FROM raw_eeff_line
        WHERE fondo_key = ? AND superseded_at IS NULL AND cuenta_nombre IS NOT NULL
        ORDER BY cuenta_nombre
        """,
        (FONDO,),
    )
    todas["label"] = todas["cuenta_nombre"] + "  ·  " + todas["source_sheet"]
    pick = st.multiselect("Selecciona cuentas (de cualquier estado)", todas["label"].tolist())
    if pick:
        keys = todas[todas["label"].isin(pick)][["cuenta_nombre", "source_sheet"]].values.tolist()
        placeholders = ",".join("(?,?)" for _ in keys)
        flat = [v for pair in keys for v in pair]
        ph_period = ",".join("?" * len(periodos_sel))
        df = q(
            f"""
            SELECT periodo, cuenta_nombre, source_sheet, SUM(monto_clp) AS monto_clp
            FROM raw_eeff_line
            WHERE fondo_key = ? AND superseded_at IS NULL
              AND (cuenta_nombre, source_sheet) IN ({placeholders})
              AND periodo IN ({ph_period})
            GROUP BY periodo, cuenta_nombre, source_sheet
            ORDER BY periodo
            """,
            (FONDO, *flat, *periodos_sel),
        )
        df["label"] = df["cuenta_nombre"] + " (" + df["source_sheet"] + ")"
        fig = px.line(df, x="periodo", y="monto_clp", color="label", markers=True)
        fig.update_layout(height=500, hovermode="x unified", legend_title=None)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(
            df.pivot_table(index="label", columns="periodo", values="monto_clp").style.format(
                "{:,.0f}", na_rep="—"
            ),
            use_container_width=True,
        )
    else:
        st.caption("Selecciona una o más cuentas para graficar.")
