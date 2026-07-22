"""Genera factsheet.html — recreación dinámica de la página 1 del fact sheet
para los 3 fondos (TRI, PT, Apo) con selectores de fondo y período.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "agente_toesca_v2.db"
OUT = ROOT / "factsheet.html"
ASSETS = ROOT / "assets"


def _data_uri(filename: str) -> str:
    data = (ASSETS / filename).read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode()}"


def _notas_template(has_bursatil: bool) -> list[str]:
    """Notas (i)-(x) de metodología de la página 4 — boilerplate prácticamente
    igual entre fondos (ver fact sheet Apo octubre 2025, que usa el formato dual
    bursátil/contable en las notas aun cuando el fondo no tenga valor bursátil
    vigente en el período — es el texto metodológico genérico, no depende de si
    hay dato real). `has_bursatil` solo cambia si se describe la opción bursátil
    además de la contable.

    Las fechas concretas (cierre EEFF/contable, cierre bursátil/operacional, mes
    operacional) NO se hardcodean acá: se insertan en runtime vía spans
    data-slot="fecha-cb" / "fecha-op" / "mes-op", rellenados en render() según
    el período seleccionado en cada momento (ver fillNotasFechas()).
    """
    fcb = "<span class=\"auto\" data-slot=\"fecha-cb\">—</span>"
    fop = "<span class=\"auto\" data-slot=\"fecha-op\">—</span>"
    mop = "<span class=\"auto\" data-slot=\"mes-op\">—</span>"
    val_ab = (
        f"a) aportes, repartos y venta de los inmuebles al valor bursátil de las cuotas al {fop}, y "
        f"b) aportes, repartos y venta de los inmuebles al valor contable al {fcb}"
        if has_bursatil else
        f"aportes, repartos y venta de los inmuebles al valor contable al {fcb}"
    )
    div_ab = (
        f"a) valor bursátil de las cuotas al {fop}, y b) valor libro de las cuotas al {fcb}"
        if has_bursatil else f"valor libro de las cuotas al {fcb}"
    )
    patrim_ab = (
        "la suma del valor bursátil del patrimonio y el saldo insoluto de la deuda"
        if has_bursatil else
        "la suma del valor libro del patrimonio y el saldo insoluto de la deuda"
    )
    return [
        f"Rentabilidad considerando: {val_ab}.",
        f"Suma de los dividendos de los últimos 12 meses sobre: {div_ab}. "
        "Para este informe se consideró los últimos 4 dividendos repartidos.",
        f"Además de la suma de los dividendos de los últimos 12 meses, considera la amortización "
        f"de capital en las cuotas de financiamiento de los últimos 12 meses, sobre: {div_ab}.",
        f"Deuda consolidada del Fondo al {fcb} / Patrimonio contable al {fcb}.",
        f"Deuda consolidada del Fondo al {fcb} / Valor Activos según tasación.",
        f"Costo promedio de la deuda financiera del fondo, calculada ponderando la tasa de cada "
        f"financiamiento con el saldo insoluto respectivo al {fcb}.",
        f"Promedio ponderado del vencimiento de la deuda financiera del Fondo al {fcb}, "
        "calculado utilizando la fórmula de Macaulay.",
        f"Porcentaje de la deuda financiera que se amortiza dentro de cada periodo a partir del {fcb}.",
        f"Ingreso renta percibido últimos 12 meses (hasta {mop}) / Valor Activo (considera {patrim_ab}, "
        f"neto de la caja consolidada del fondo y de las inversiones en construcción al {fop}).",
        f"NOI percibido últimos 12 meses (hasta {mop}) / Valor Activo (considera {patrim_ab}, neto de "
        f"la caja consolidada del fondo y de las inversiones en construcción al {fop}).",
    ]


FONDOS_CFG = {
    "TRI": {
        "nombre": "Toesca Rentas Inmobiliarias",
        "sub": "Fondo de inversión en Liquidación",
        "series": [
            {"nemo": "CFITOERI1A", "label": "A"},
            {"nemo": "CFITOERI1C", "label": "C"},
            {"nemo": "CFITOERI1I", "label": "I"},
        ],
        "has_bursatil": True,
        "fecha_label": "Fecha Inicio Periodo Liquidación",
        "fecha_valor": "30 abril 2024",
        "moneda": "CLP",
        "duracion": "30 abril 2027 (+ 2 renovaciones automáticas de 1 año c/u)",
        "cuotas_emitidas": "4.000.000",
        "objetivo": (
            "El Fondo de Inversión Toesca Rentas Inmobiliarias tiene como objetivo invertir "
            "indirectamente en propiedades destinadas a la renta comercial, principalmente en Chile. "
            "El Fondo podrá invertir en oficinas, centros comerciales, bodegas y residencias para "
            "adultos mayores, mediante estrategias Core y Value Added."
        ),
        "remuneracion_fija": [
            ("Serie A", "0,75% + IVA sobre capital pagado"),
            ("Serie C", "0,50% + IVA sobre capital pagado"),
            ("Serie WM", "0,45% + IVA sobre capital pagado"),
            ("Serie I", "0,40% + IVA sobre capital pagado"),
        ],
        "remuneracion_variable": [
            ("Durante la vigencia<br/><span class='rv-sub'>exceso sobre Dividend Yield UF + 5% anual</span>", "A – C – WM", "20% + IVA"),
            ("Durante la vigencia<br/><span class='rv-sub'>exceso sobre Dividend Yield UF + 5% anual</span>", "I", "15% + IVA"),
            ("Al momento de liquidación<br/><span class='rv-sub'>exceso sobre TIR UF + 6%</span>", "A – C – WM", "20% + IVA"),
            ("Al momento de liquidación<br/><span class='rv-sub'>exceso sobre TIR UF + 6%</span>", "I", "15% + IVA"),
        ],
        "tickers": [
            ("Serie A", "TOERIMA CI Equity"),
            ("Serie C", "TOERI1C CI Equity"),
            ("Serie I", "TOERIMI CI Equity"),
        ],
        "comite": "Eduardo Castillo A.<br/>Roger Magrovejo<br/>Paul Mazoyer R.",
        "contacto": "distribución@toesca.com",
        "resumen": (
            "El Fondo de Inversión Toesca Rentas Inmobiliarias se constituyó el 11 de mayo del 2017, "
            "con el objetivo de adquirir propiedades destinadas a la renta comercial en Chile. "
            "A la fecha de emisión de este informe el Fondo ha realizado ocho inversiones en activos "
            "inmobiliarios. El Fondo entró en liquidación a partir del 30 de abril del 2024."
        ),
        "noticias_template": (
            "Los Estados Financieros al <span class='auto' data-slot='eeff'>30/06/2025</span> "
            "se encuentran publicados en la CMF"
            "<span data-wrap='cmf'> desde el <span class='ed' data-slot='cmf'>—</span></span>."
            "<span data-wrap='div'> Además, el "
            "<span class='auto' data-slot='div'>—</span> hubo reparto de dividendos.</span>"
        ),
        # Página 2 — TRI consolida a nivel de fondo (no por sociedad/edificio como PT/Apo):
        # cada activo/sub-consolidado es una columna simple (sin sub-columnas por tipo de
        # espacio). "Centros Comerciales" es subtotal Viña+Curicó; "Fondo Apoquindo" y
        # "Fondo Rentas PT" consolidan los edificios de esos subfondos. La columna Total
        # final la agrega el renderer genérico (perf_groups + Total implícito).
        # perf_data aún no implementado para TRI en _fetch_perf_data — placeholders hasta
        # wire de raw_rent_roll_line consolidado a nivel fondo paraguas.
        "page2": {
            "perf_groups": [
                {"label": "Paseo Viña Centro", "cols": [""]},
                {"label": "Paseo Curicó", "cols": [""]},
                {"label": "Centros Comerciales", "cols": [""]},
                {"label": "Residencias Adulto Mayor", "cols": [""]},
                {"label": "Bodegas Sucden", "cols": [""]},
                {"label": "Apoquindo 3001", "cols": [""]},
                {"label": "Fondo Apoquindo", "cols": [""]},
                {"label": "Fondo Rentas PT", "cols": [""]},
            ],
            "perf_rows": [
                "m² útiles", "m² vacantes", "% vacancia (m²)",
                "Renta mensual (UF)", "Renta vacante (UF)", "Renta en gracia (UF)", "Renta en descuento (UF)", "% vacancia (UF)",
                "Absorción bruta m² 3M", "Absorción bruta UF 3M", "Absorción neta m² 3M", "Absorción neta UF 3M",
                "Absorción bruta m² 12M", "Absorción bruta UF 12M", "Absorción neta m² 12M", "Absorción neta UF 12M",
            ],
            "rubro_arrendatario": [
                "Otro", "Mejoramiento del hogar", "Banco", "Supermercado", "Retail",
                "Residencia Adulto Mayor", "Agroindustrial", "Salud", "Gastronomía",
                "Servicios", "Financiera", "Deporte", "Inmobiliaria",
            ],
            "tipo_activo": ["Oficinas", "Comercial", "Industrial", "Residencias"],
        },
    },
    "PT": {
        "nombre": "Toesca Rentas Inmobiliarias PT",
        "sub": "Fondo de Inversión",
        "series": [{"nemo": "CFITRIPT-E", "label": "Única"}],
        "has_bursatil": True,
        "fecha_label": "Fecha Inicio Operaciones",
        "fecha_valor": "16 de noviembre de 2017",
        "moneda": "CLP",
        "duracion": "15 años (30 julio 2032)",
        "cuotas_emitidas": "1.800.000",
        "objetivo": (
            "El Fondo de Inversión Toesca Rentas Inmobiliarias PT tiene como objetivo invertir "
            "indirectamente en la Torre A, el Local 100, ciertos locales comerciales y ciertos "
            "estacionamientos, los cuales forman parte del conjunto armónico Parque Titanium "
            "ubicado en Avenida Costanera Sur 2710, comuna de Las Condes."
        ),
        "remuneracion_fija": [
            ("Serie Única", "0,4% + IVA sobre capital pagado"),
        ],
        "remuneracion_variable": [
            ("Al vencimiento<br/><span class='rv-sub'>exceso sobre TIR UF + 6,5% anual</span>", "Única", "15% + IVA"),
        ],
        "tickers": [("Serie Única", "TRIPTE CI Equity")],
        "activos": [
            ("Torre A S.A.", "Torre A - Parque Titanium", "100%", "19.755"),
            ("Inmobiliaria Boulevard PT SpA", "Locales Comerciales", "100%", "7.663"),
        ],
        # Página 2 — layout específico de PT (Resumen performance / gráficos).
        # TRI y Apo tienen su propia página 2 (pendiente de traer su fact sheet de referencia
        # y definir aquí su propio bloque "page2"; no reutilizar este layout entre fondos).
        "page2": {
            "perf_groups": [
                {"label": "Torre A S.A.", "cols": ["Oficinas", "Locales Comerciales", "Total", "Bodegas", "Estacionamientos"]},
                {"label": "Inmob. Boulevard PT SpA", "cols": ["Locales Comerciales", "Bodegas", "Estacionamientos"]},
            ],
            "perf_rows": [
                "m² útiles", "m² vacantes", "% vacancia (m²)",
                "Renta mensual (UF)", "Renta vacante (UF)", "Renta en gracia (UF)", "Renta en descuento (UF)", "% vacancia (UF)",
                "Absorción bruta m² 3M", "Absorción bruta UF 3M", "Absorción neta m² 3M", "Absorción neta UF 3M",
                "Absorción bruta m² 12M", "Absorción bruta UF 12M", "Absorción neta m² 12M", "Absorción neta UF 12M",
            ],
            "rubro_arrendatario": ["Banco", "Deporte", "Padel", "Seguros", "Construcción", "Otro"],
            "tipo_activo": ["Oficina", "Locales Comerciales", "Estacionamiento", "Bodega"],
        },
        "comite": "Gonzalo Urzúa G.<br/>Cristóbal Kaltwasser B.<br/>José Ignacio de Almorzara V.",
        "contacto": "distribucion@toesca.com",
        "resumen": (
            "El Fondo de Inversión Toesca Rentas Inmobiliarias PT se constituye el 31 de julio "
            "año 2017 con el único propósito de invertir indirectamente en el portafolio de "
            "activos del complejo Parque Titanium, los que incluyen la Torre A y el Local 100 "
            "del condominio Parque Titanium, entre otros."
        ),
        "noticias_template": (
            "Los Estados Financieros al <span class='auto' data-slot='eeff'>30/06/2025</span> "
            "se encuentran publicados en la CMF"
            "<span data-wrap='cmf'> desde el <span class='ed' data-slot='cmf'>12 de septiembre de 2025</span></span>."
            "<span data-wrap='div'> Además, el "
            "<span class='auto' data-slot='div'>—</span> hubo reparto de dividendos.</span>"
        ),
    },
    "Apo": {
        "nombre": "Toesca Rentas Inmobiliarias Apoquindo",
        "sub": "Fondo de Inversión",
        "series": [{"nemo": "Apo", "label": "Única"}],
        "has_bursatil": False,
        "fecha_label": "Fecha Inicio Operaciones",
        "fecha_valor": "2 de enero de 2019",
        "moneda": "CLP",
        "duracion": "10 años (16 noviembre 2028)",
        "cuotas_emitidas": "2.000.000",
        "objetivo": (
            "El Fondo de Inversión Toesca Rentas Inmobiliarias Apoquindo tiene como objetivo "
            "invertir indirectamente en los bienes raíces no habitacionales para renta ubicados "
            "en Avenida Apoquindo 4501 y Avenida Apoquindo 4700, comuna de Las Condes; compuestos "
            "ambos por oficinas, locales comerciales, estacionamientos y bodegas."
        ),
        "remuneracion_fija": [
            ("Serie Única", "0,5355% + IVA sobre capital pagado"),
        ],
        "remuneracion_variable": [
            ("Anual<br/><span class='rv-sub'>exceso sobre NOI 2024</span>", "Única", "23,8%"),
        ],
        "tickers": [("Serie Única", "No transa en bolsa")],
        "activos": [
            ("Inmobiliaria Apoquindo S.A.", "Edificio Apoquindo 4700", "100%", "7.151"),
            ("Inmobiliaria Apoquindo S.A.", "Edificio Apoquindo 4501", "100%", "21.708"),
        ],
        # Página 2 — layout específico de Apo (basado en fact sheet Apo octubre 2025).
        # Grupos por edificio en vez de por sociedad (ambos activos están bajo la
        # misma Inmobiliaria Apoquindo S.A.). perf_data aún no implementado para
        # Apo en _fetch_perf_data (solo PT) — la tabla se muestra con placeholders
        # hasta wire a raw_rent_roll_line.
        "page2": {
            "perf_groups": [
                {"label": "Apoquindo 4501", "cols": ["Oficinas", "Locales Comerciales", "Total", "Bodegas", "Estacionamientos"]},
                {"label": "Apoquindo 4700", "cols": ["Oficinas", "Locales Comerciales", "Total", "Bodegas", "Estacionamientos"]},
            ],
            "perf_rows": [
                "m² útiles", "m² vacantes", "% vacancia (m²)",
                "Renta mensual (UF)", "Renta vacante (UF)", "Renta en gracia (UF)", "Renta en descuento (UF)", "% vacancia (UF)",
                "Absorción bruta m² 3M", "Absorción bruta UF 3M", "Absorción neta m² 3M", "Absorción neta UF 3M",
                "Absorción bruta m² 12M", "Absorción bruta UF 12M", "Absorción neta m² 12M", "Absorción neta UF 12M",
            ],
            "rubro_arrendatario": [
                "Otro", "Servicios", "Inmobiliaria", "Salud", "Minería", "Financiera",
                "Tecnología", "Gimnasio", "Logística", "Consultoría", "Empresa Pública",
                "Instituto profesional", "Infraestructura",
            ],
            "tipo_activo": ["Oficinas", "Locales Comerciales", "Estacionamientos", "Bodegas"],
        },
        # Página 3 — "Detalle de Activos" (fact sheet Apo octubre 2025).
        # Solo ESTRUCTURA (secciones, orden, filas/columnas de cada tabla, edificios) — sin
        # datos reales todavía. A la espera de confirmar el orden exacto contra el PDF de
        # referencia (que quedó fuera de contexto) antes de rellenar valores.
        "page3": {
            "titulo": "Apoquindo 4501 / Apoquindo 4700",
            "edificios": ["Apoquindo 4501", "Apoquindo 4700"],
            "aspectos": [
                ("Dirección", None),
                ("Superficie Arrendable", None),
                ("Principal Arrendatario", None),
                ("Financiamiento", None),
                ("Administración", None),
                ("Vacancia (m²)", None),
            ],
            "fotos": {
                "Apoquindo 4501": _data_uri("apo4501fs.png"),
                "Apoquindo 4700": _data_uri("apo4700fs.png"),
            },
            "donut_gla": [("Apoquindo 4501", None), ("Apoquindo 4700", None)],
            "donut_ingresos": [("Apoquindo 4501", None), ("Apoquindo 4700", None)],
            "status_oficinas": [("Apoquindo 4501", None), ("Apoquindo 4700", None)],
            "status_locales": [("Apoquindo 4501", None), ("Apoquindo 4700", None)],
            "aspectos_mes": [
                ("Colocaciones", None),
                ("Resultados", None),
                ("Recaudación", None),
                ("Vencimientos", None),
            ],
            "vacancia_periodo": ("Mes anterior", "Mes actual"),
            "vacancia_edificios": [
                {"nombre": "Apoquindo 4501", "rows": ["Locales", "Oficinas", "Edificio"]},
                {"nombre": "Apoquindo 4700", "rows": ["Oficinas", "Edificio", "Locales"]},
            ],
            "resumen_anual_edificios": [
                {"nombre": "Apoquindo 4501", "rows": [
                    "Vencimientos", "(+) Renovados", "(-) No Renovaciones",
                    "(-) Salidas", "(+) Nuevos contratos", "Neto",
                ]},
                {"nombre": "Apoquindo 4700", "rows": [
                    "Vencimientos", "(+) Renovados", "(-) No Renovaciones",
                    "(-) Salidas", "(+) Nuevos contratos", "Neto",
                ]},
            ],
            "tasaciones_edificios": ["Apoquindo 4501", "Apoquindo 4700"],
            "tasaciones_total_nombre": "Fondo Rentas Apoquindo",
            "tasaciones_periodo": ("Tasación año anterior", "Tasación año actual"),
        },
        # Página 4 — "Notas y Análisis de Mercado" (basado en fact sheet Apo octubre 2025).
        # Notas (i)-(x): boilerplate metodológico, prácticamente igual entre fondos —
        # solo cambia si el fondo tiene serie bursátil (S.has_bursatil).
        "page4": {
            # Nota: la PDF real de Apo usa el formato dual bursátil/contable en las
            # notas metodológicas aunque el fondo no tenga valor bursátil vigente
            # (S.has_bursatil=False más arriba) — es boilerplate genérico compartido.
            "notas": _notas_template(has_bursatil=True),
            "submercado": "Las Condes",
            "mercado_rows": [
                {"comuna": "Las Condes (CBD)", "clase": "Total"},
                {"comuna": "Providencia", "clase": "Total"},
                {"comuna": "Santiago Centro", "clase": "Total"},
                {"comuna": "Vitacura", "clase": "Total"},
                {"comuna": "Ciudad empresarial", "clase": "Total"},
                {"comuna": "Estoril", "clase": "Total"},
                {"comuna": "Santiago", "clase": "Total", "total": True},
                {"comuna": "Las Condes (CBD)", "clase": "A"},
                {"comuna": "Providencia", "clase": "A"},
                {"comuna": "Santiago Centro", "clase": "A"},
                {"comuna": "Santiago", "clase": "A", "total": True},
                {"comuna": "Las Condes (CBD)", "clase": "B"},
                {"comuna": "Providencia", "clase": "B"},
                {"comuna": "Santiago Centro", "clase": "B"},
                {"comuna": "Vitacura", "clase": "B"},
                {"comuna": "Ciudad empresarial", "clase": "B"},
                {"comuna": "Estoril", "clase": "B"},
                {"comuna": "Santiago", "clase": "B", "total": True},
            ],
        },
        "comite": "Eduardo Castillo A.<br/>Aníbal Silva S.<br/>Rodrigo Swett B.",
        "contacto": "distribución@toesca.com",
        "resumen": (
            "El Fondo de Inversión Toesca Rentas Inmobiliarias Apoquindo se constituye el 16 de "
            "noviembre del año 2018 con el único propósito de invertir indirectamente en la compra "
            "de los edificios ubicados en Avenida Apoquindo 4501 y Avenida Apoquindo 4700, ambos "
            "compuestos por oficinas, locales comerciales, estacionamientos y bodegas, que "
            "comprenden un total de aproximadamente 30.000 m² arrendables."
        ),
        "noticias_template": (
            "Los Estados Financieros al <span class='auto' data-slot='eeff'>30/09/2025</span> "
            "fueron publicados en la CMF"
            "<span data-wrap='cmf'> el <span class='ed' data-slot='cmf'>30 de noviembre de 2025</span></span>."
            "<span data-wrap='div'> Además, el "
            "<span class='auto' data-slot='div'>—</span> hubo reparto de dividendos.</span>"
        ),
    },
}


def _fetch_mercado_rows(db_path: str, periodo: str, proveedor: str = "JLL") -> list[dict]:
    """Lee raw_mercado_oficinas para el periodo/proveedor dado, ordenado igual
    que la tabla del fact sheet (Total, luego A, luego B; Santiago al final
    de cada bloque)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT submercado, clase, inventario_m2, absorcion_u12m_m2,
                      vacancia_pct, renta_uf_m2, construccion_m2, es_total
               FROM raw_mercado_oficinas
               WHERE periodo = ? AND proveedor = ? AND superseded_at IS NULL
               ORDER BY
                   CASE clase WHEN 'Total' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
                   es_total, id""",
            (periodo, proveedor),
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "comuna": r[0],
            "clase": r[1],
            "inventario_m2": r[2],
            "absorcion_u12m_m2": r[3],
            "vacancia_pct": r[4],
            "renta_uf_m2": r[5],
            "construccion_m2": r[6],
            "total": bool(r[7]),
        }
        for r in rows
    ]


def fetch_fondo(con: sqlite3.Connection, fondo_key: str, cfg: dict) -> dict:
    cur = con.cursor()
    series_nemos = [s["nemo"] for s in cfg["series"]]
    placeholders = ",".join("?" * len(series_nemos))

    # ---- CONTABLE ----
    contable = defaultdict(lambda: {"series": {}})
    for fondo_row, nemo, periodo, precio_clp, fecha, cuotas_rvc in cur.execute(
        f"SELECT fondo_key, nemotecnico, periodo, precio_clp, fecha, cuotas FROM raw_valor_cuota_contable "
        f"WHERE nemotecnico IN ({placeholders}) AND (superseded_at IS NULL OR superseded_at='')",
        series_nemos,
    ):
        serie = contable[periodo]["series"].setdefault(nemo, {})
        prefer_new = (
            serie.get("valor_libro_clp") is None
            or (precio_clp is not None and str(fondo_row).upper() == str(fondo_key).upper())
        )
        if prefer_new:
            serie["valor_libro_clp"] = precio_clp
            contable[periodo]["fecha"] = fecha
        if cuotas_rvc is not None:
            serie["cuotas"] = cuotas_rvc

    kpi_contable_map = {
        "tir_contable_desde_inicio": "tir_desde_inicio",
        "rent_ytd_contable": "rent_ytd",
        "tir_contable_u12m": "tir_u12m",
    }
    for kpi_db, kpi_out in kpi_contable_map.items():
        for entkey, periodo, valor in cur.execute(
            f"SELECT entidad_key, periodo, valor FROM derived_kpi "
            f"WHERE entidad_key IN ({placeholders}) AND kpi=? AND variante IS NULL",
            (*series_nemos, kpi_db),
        ):
            contable[periodo]["series"].setdefault(entkey, {})[kpi_out] = valor
    for entkey, periodo, valor in cur.execute(
        f"SELECT entidad_key, periodo, valor FROM derived_kpi "
        f"WHERE entidad_key IN ({placeholders}) AND kpi='dy' AND variante='contable'",
        series_nemos,
    ):
        contable[periodo]["series"].setdefault(entkey, {})["dy"] = valor
    # Apo usa variante 'capital' para dy_amort; TRI/PT usan 'contable'
    for entkey, periodo, valor in cur.execute(
        f"SELECT entidad_key, periodo, valor FROM derived_kpi "
        f"WHERE entidad_key IN ({placeholders}) AND kpi='dy_amort' AND variante IN ('contable','capital')",
        series_nemos,
    ):
        contable[periodo]["series"].setdefault(entkey, {})["dy_amort"] = valor
    # Cargar cuotas por serie; los períodos pueden no coincidir exactamente con los
    # períodos contables (e.g., raw_cuota tiene 2018-04 pero contable tiene 2018-03).
    # Se asigna cada cuota al último período contable <= cuota_periodo, de modo que
    # cuota de abr-2018 quede en el EEFF de mar-2018.
    cuotas_by_serie: dict[str, list[tuple[str, float]]] = {}
    for entkey, periodo, cuotas in cur.execute(
        f"SELECT nemotecnico, periodo, cuotas FROM raw_cuota_en_circulacion "
        f"WHERE nemotecnico IN ({placeholders}) AND (superseded_at IS NULL OR superseded_at='') "
        f"ORDER BY nemotecnico, periodo",
        series_nemos,
    ):
        cuotas_by_serie.setdefault(entkey, []).append((periodo, cuotas))

    contable_periods = sorted(contable.keys())
    for nemo, cuota_list in cuotas_by_serie.items():
        for cuota_periodo, cuotas in cuota_list:
            # Último período contable <= cuota_periodo
            candidates = [p for p in contable_periods if p <= cuota_periodo]
            target = candidates[-1] if candidates else (contable_periods[0] if contable_periods else None)
            if target:
                # Sobrescribe para quedarnos con la cuota más reciente por período contable
                contable[target]["series"].setdefault(nemo, {})["cuotas"] = cuotas

    # ---- KPIs a nivel fondo ----
    fondo_kpi = defaultdict(dict)
    for kpi in ("ltv", "leverage_financiero", "tasa_promedio", "duration_deuda", "deuda_financiera_neta",
                "tasa_arriendo_ajustada_contable", "cap_rate_implicito_contable", "ingresos_u12m", "noi_u12m",
                "tasa_arriendo_ajustada_bursatil", "cap_rate_implicito_bursatil", "ingresos_mes", "noi_mes"):
        for periodo, valor in cur.execute(
            "SELECT periodo, valor FROM derived_kpi WHERE entidad_key=? AND kpi=? AND variante IS NULL",
            (fondo_key, kpi),
        ):
            fondo_kpi[periodo][kpi] = valor
    for periodo, variante, valor in cur.execute(
        "SELECT periodo, variante, valor FROM derived_kpi WHERE entidad_key=? AND kpi='perfil_vencimiento'",
        (fondo_key,),
    ):
        fondo_kpi[periodo].setdefault("perfil_venc", {})[variante] = valor

    # ---- Balance consolidado ----
    balance = defaultdict(dict)
    for periodo, cuenta, monto in cur.execute(
        "SELECT periodo, cuenta_codigo, SUM(monto_clp) FROM raw_balance_consolidado_line "
        "WHERE fondo_key=? AND (superseded_at IS NULL OR superseded_at='') "
        "GROUP BY periodo, cuenta_codigo",
        (fondo_key,),
    ):
        balance[periodo][cuenta] = monto

    # ---- BURSÁTIL ----
    bursatil = defaultdict(lambda: {"series": {}})
    if cfg["has_bursatil"]:
        for nemo, fecha, precio_clp in cur.execute(
            f"SELECT nemotecnico, fecha, precio_clp FROM raw_valor_cuota_bursatil "
            f"WHERE nemotecnico IN ({placeholders}) AND fecha IS NOT NULL",
            series_nemos,
        ):
            periodo = fecha[:7]
            prev = bursatil[periodo]["series"].get(nemo, {})
            if not prev or fecha > prev.get("_fecha", ""):
                bursatil[periodo]["series"][nemo] = {"valor_bursatil_clp": precio_clp, "_fecha": fecha}
                bursatil[periodo]["fecha"] = fecha

        kpi_burs_map = {
            "tir_bursatil_desde_inicio": "tir_desde_inicio",
            "rent_ytd_bursatil": "rent_ytd",
            "tir_bursatil_u12m": "tir_u12m",
            "tasa_arriendo_ajustada_bursatil": "tasa_arriendo_ajustada_bursatil",
            "cap_rate_implicito_bursatil": "cap_rate_implicito_bursatil",
        }
        for kpi_db, kpi_out in kpi_burs_map.items():
            for entkey, periodo, valor in cur.execute(
                f"SELECT entidad_key, periodo, valor FROM derived_kpi "
                f"WHERE entidad_key IN ({placeholders}) AND kpi=? AND variante IS NULL",
                (*series_nemos, kpi_db),
            ):
                bursatil[periodo]["series"].setdefault(entkey, {})[kpi_out] = valor
        for entkey, periodo, valor in cur.execute(
            f"SELECT entidad_key, periodo, valor FROM derived_kpi "
            f"WHERE entidad_key IN ({placeholders}) AND kpi='dy' AND variante='bursatil'",
            series_nemos,
        ):
            bursatil[periodo]["series"].setdefault(entkey, {})["dy"] = valor
        for entkey, periodo, valor in cur.execute(
            f"SELECT entidad_key, periodo, valor FROM derived_kpi "
            f"WHERE entidad_key IN ({placeholders}) AND kpi='dy_amort' AND variante='bursatil'",
            series_nemos,
        ):
            bursatil[periodo]["series"].setdefault(entkey, {})["dy_amort"] = valor

        for p in bursatil.values():
            for s in p["series"].values():
                s.pop("_fecha", None)

    # ---- Gastos del fondo (desde EEFF, por periodo) ----
    gastos = defaultdict(dict)
    gasto_cuentas = (
        "ER.comision_admin",
        "ER.honorarios_custodia",
        "ER.otros_gastos",
        "ER.remun_comite",
        "ER.costos_transaccion",
        "ER.total_gastos_operacion",
    )
    for periodo, cuenta, monto in cur.execute(
        f"SELECT periodo, cuenta_codigo_canonical, SUM(monto_clp) FROM raw_eeff_line "
        f"WHERE fondo_key=? AND cuenta_codigo_canonical IN ({','.join('?'*len(gasto_cuentas))}) "
        f"AND (superseded_at IS NULL OR superseded_at='') "
        f"GROUP BY periodo, cuenta_codigo_canonical",
        (fondo_key.upper(), *gasto_cuentas),
    ):
        gastos[periodo][cuenta] = abs(monto) if monto is not None else None

    # ---- UF de cierre por período (para toggle UF / millones de pesos) ----
    periodos_uf = sorted(set(balance) | set(gastos) | set(fondo_kpi))
    uf_diaria = cur.execute("SELECT fecha, valor FROM fact_uf ORDER BY fecha").fetchall()
    uf_por_periodo: dict[str, float] = {}
    idx = 0
    ultimo_valor = None
    for periodo in periodos_uf:
        limite = periodo + "-31"
        while idx < len(uf_diaria) and uf_diaria[idx][0] <= limite:
            ultimo_valor = uf_diaria[idx][1]
            idx += 1
        if ultimo_valor is not None:
            uf_por_periodo[periodo] = ultimo_valor

    # ---- Dividendos ----
    dividendos = []
    for nemo, fecha_pago, monto_clp, periodo in cur.execute(
        f"SELECT nemotecnico, fecha_pago, monto_clp_cuota, periodo FROM raw_dividendo "
        f"WHERE nemotecnico IN ({placeholders}) AND source_file='cdg_extract.xlsx' "
        f"AND (superseded_at IS NULL OR superseded_at='') "
        f"ORDER BY fecha_pago",
        series_nemos,
    ):
        dividendos.append({"nemo": nemo, "fecha": fecha_pago, "monto_clp": monto_clp, "periodo": periodo})

    static_cfg = cfg
    if fondo_key == "APO" and cfg.get("page4"):
        periodos_disponibles = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT periodo FROM raw_mercado_oficinas "
                "WHERE proveedor='JLL' AND superseded_at IS NULL ORDER BY periodo DESC"
            )
        ]
        mercado_rows_db = (
            _fetch_mercado_rows(str(DB), periodos_disponibles[0])
            if periodos_disponibles else []
        )
        if mercado_rows_db:
            static_cfg = {**cfg, "page4": {**cfg["page4"], "mercado_rows": mercado_rows_db}}

    return {
        "static": static_cfg,
        "contable": dict(sorted(contable.items())),
        "bursatil": dict(sorted(bursatil.items())),
        "fondo_kpi": dict(sorted(fondo_kpi.items())),
        "balance": dict(sorted(balance.items())),
        "gastos": dict(sorted(gastos.items())),
        "uf": uf_por_periodo,
        "dividendos": dividendos,
        "perf_data": _fetch_perf_data(fondo_key),
    }


def _fetch_perf_data(fondo_key: str) -> dict:
    """Tabla "Resumen Performance Activos" de la página 2 (rent roll), por
    período. Solo implementada para PT hoy — ver tools/db/rent_roll_stats.py.
    Apo y TRI ya tienen su layout de page2 definido en FONDOS_CFG pero sin
    fuente de datos wired aún (Apo: agrupar raw_rent_roll_line por edificio
    Apoquindo 4501/4700; TRI: consolidar a nivel fondo paraguas por
    activo/subfondo). Ambos quedan en placeholder hasta esa implementación.
    """
    if fondo_key != "PT":
        return {}
    from tools.db.rent_roll_stats import get_perf_table, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles("PT"):
        tabla = get_perf_table("PT", periodo)
        if tabla is None:
            continue
        celdas = {}
        for key, val in tabla.items():
            if isinstance(key, tuple):
                grupo, tipo = key
                celdas[f"{grupo}|||{tipo}"] = val
        celdas["_absorcion_3m"] = tabla["_absorcion_3m"]
        celdas["_absorcion_12m"] = tabla["_absorcion_12m"]
        out[periodo] = celdas
    return out


# Metadata de trazabilidad por KPI. Se sirve al frontend para el modo admin.
# Placeholders soportados en `sql`: {serie}, {fondo}, {periodo}, {variante}.
KPI_META = {
    # ---- Rentabilidad (por serie) ----
    "tir_desde_inicio": {
        "label": "Rentabilidad desde el inicio (anualizada)",
        "verbal": (
            "IRR mensual sobre flujos desde inicio del fondo hasta el período. "
            "Contable: (-) capital pagado × valor cuota contable inicial; (+) dividendos + disminuciones; "
            "(+) al final valor cuota contable × cuotas. Bursátil: usa precios cuota bursátil. "
            "Anualizada: (1+irr_mensual)^12 − 1."
        ),
        "python": (
            "from scipy.optimize import brentq\n"
            "def npv(r, flows): return sum(f/(1+r)**i for i,f in enumerate(flows))\n"
            "irr_m = brentq(lambda r: npv(r, flows), -0.99, 10)\n"
            "tir_anual = (1 + irr_m)**12 - 1"
        ),
        "sources": [
            "raw_ar_event (aportes/disminuciones/canjes)",
            "raw_dividendo",
            "raw_valor_cuota_contable · raw_valor_cuota_bursatil",
            "raw_cuota_en_circulacion",
        ],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{serie}' AND kpi='tir_{variante}_desde_inicio'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_tir_desde_inicio)",
    },
    "rent_ytd": {
        "label": "Rentabilidad YTD (anualizada)",
        "verbal": (
            "Rentabilidad acumulada desde el 31-dic del año anterior hasta el período, anualizada."
        ),
        "python": (
            "rent_ytd = (1 + irr_ytd_mensual)**12 - 1\n"
            "# irr_ytd sobre flujos desde 31-dic-(año-1) hasta período seleccionado"
        ),
        "sources": [
            "raw_dividendo (YTD)",
            "raw_valor_cuota_contable · raw_valor_cuota_bursatil",
        ],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{serie}' AND kpi='rent_ytd_{variante}'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_rent_ytd)",
    },
    "tir_u12m": {
        "label": "Rentabilidad Últimos 12 meses",
        "verbal": (
            "IRR mensual sobre flujos de los 12 meses previos: (-) valor cuota inicial × cuotas; "
            "(+) dividendos del período; (+) valor cuota final × cuotas. Anualizada."
        ),
        "python": "irr_u12m = brentq(lambda r: npv(r, flows_12m), -0.99, 10); tir = (1+irr_u12m)**12 - 1",
        "sources": ["raw_dividendo (12m)", "raw_valor_cuota_contable · raw_valor_cuota_bursatil"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{serie}' AND kpi='tir_{variante}_u12m'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_tir_u12m)",
    },
    "dy": {
        "label": "Dividend Yield (12 meses)",
        "verbal": (
            "Suma de dividendos pagados en los últimos 12 meses dividida por el denominador según variante. "
            "Contable: valor cuota contable del período. Bursátil: valor cuota bursátil. "
            "Apoquindo usa 'capital' = capital suscrito por cuota."
        ),
        "python": "dy = sum(div_12m_por_cuota) / precio_referencia",
        "sources": ["raw_dividendo (12m)", "raw_valor_cuota_contable | raw_valor_cuota_bursatil | raw_capital_suscrito"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{serie}' AND kpi='dy'\n"
            "  AND variante='{variante}' AND periodo='{periodo}'"
        ),
        "script": "tools/db/backfill.py (kpi_dy)",
    },
    "dy_amort": {
        "label": "Dividend Yield + Amortización de capital",
        "verbal": (
            "Igual que DY pero el numerador suma dividendos + amortizaciones/disminuciones de capital "
            "por cuota en los últimos 12 meses. Se incluyen refinanciamientos (nunca excluir)."
        ),
        "python": "dy_amort = (sum(div_12m) + sum(amort_12m)) / precio_referencia",
        "sources": ["raw_dividendo", "raw_amortizacion / raw_ar_event", "denominador según fondo"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{serie}' AND kpi='dy_amort'\n"
            "  AND variante IN ('contable','capital','bursatil') AND periodo='{periodo}'"
        ),
        "script": "tools/db/backfill.py (kpi_dy_amort)",
    },
    # ---- Endeudamiento (por fondo) ----
    "leverage_financiero": {
        "label": "Leverage financiero",
        "verbal": "Deuda financiera consolidada / patrimonio neto, en UF, a fecha de cierre trimestral.",
        "python": "leverage = deuda_financiera_uf / patrimonio_neto_uf",
        "sources": ["raw_saldo_deuda", "raw_balance_consolidado_line (ESF.patrimonio_neto)"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='leverage_financiero'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_leverage_financiero)",
    },
    "ltv": {
        "label": "Loan-to-Value (LTV)",
        "verbal": "Deuda financiera consolidada / valor de propiedades de inversión, ambos en UF.",
        "python": "ltv = deuda_financiera_uf / propiedades_inversion_uf",
        "sources": ["raw_saldo_deuda", "raw_balance_consolidado_line (ESF.propiedades_inversion)"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='ltv'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_ltv)",
    },
    "tasa_promedio": {
        "label": "Tasa promedio ponderada de la deuda",
        "verbal": "Promedio ponderado de tasas de créditos vigentes por saldo insoluto UF.",
        "python": "tasa = sum(saldo_uf * tasa) / sum(saldo_uf)  # sobre créditos VIGENTES",
        "sources": ["dim_credito (estado='VIGENTE')", "raw_saldo_deuda"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='tasa_promedio'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_tasa_promedio)",
    },
    "duration_deuda": {
        "label": "Duration de deuda (años)",
        "verbal": (
            "Metodología Toesca: ∑ (saldo_i × años_al_vencimiento_i) / ∑ saldo_i sobre créditos vigentes."
        ),
        "python": "duration = sum(saldo * years_to_maturity) / sum(saldo)",
        "sources": ["dim_credito (fechas y saldos)", "raw_saldo_deuda"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='duration_deuda'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_duration_deuda)",
    },
    "deuda_financiera_neta": {
        "label": "Deuda financiera neta",
        "verbal": "Saldo insoluto consolidado de créditos vigentes menos efectivo y equivalente, en UF.",
        "python": "dfn = deuda_financiera_uf - efectivo_uf",
        "sources": ["raw_saldo_deuda", "raw_balance_consolidado_line (ESF.efectivo)"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='deuda_financiera_neta'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "tools/db/backfill.py (kpi_deuda_financiera_neta)",
    },
    "ingresos_u12m": {
        "label": "Ingresos U12M",
        "verbal": "Ingresos por arriendo de los últimos 12 meses, en UF, consolidado a nivel fondo.",
        "python": "ingresos_u12m = sum(monto_uf where seccion='INGRESOS_OPERACION', ultimos 12 meses)",
        "sources": ["raw_er_activo_line"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='ingresos_u12m'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "cálculo manual, consolidado en derived_kpi (2026-07-09)",
    },
    "noi_u12m": {
        "label": "NOI U12M",
        "verbal": "Net Operating Income (ingresos - gastos operacionales) de los últimos 12 meses, en UF, consolidado a nivel fondo.",
        "python": "noi_u12m = sum(monto_uf, es_operacional=1, ultimos 12 meses)",
        "sources": ["raw_er_activo_line"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='noi_u12m'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "cálculo manual, consolidado en derived_kpi (2026-07-09)",
    },
    "ingresos_mes": {
        "label": "Ingresos del mes",
        "verbal": "Ingresos por arriendo del mes de cierre del período, en UF, consolidado a nivel fondo.",
        "python": "ingresos_mes = sum(monto_uf where seccion='INGRESOS_OPERACION', periodo=mes)",
        "sources": ["raw_er_activo_line"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='ingresos_mes'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "cálculo manual, consolidado en derived_kpi (2026-07-09)",
    },
    "noi_mes": {
        "label": "NOI del mes",
        "verbal": "Net Operating Income (ingresos - gastos operacionales) del mes de cierre del período, en UF, consolidado a nivel fondo.",
        "python": "noi_mes = sum(monto_uf, es_operacional=1, periodo=mes)",
        "sources": ["raw_er_activo_line"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='noi_mes'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "cálculo manual, consolidado en derived_kpi (2026-07-09)",
    },
    "tasa_arriendo_ajustada_contable": {
        "label": "Tasa de Arriendo Ajustada Contable",
        "verbal": "Ingresos U12M / (patrimonio contable + deuda financiera - (caja - caja mínima)), todo en UF.",
        "python": "tasa = ingresos_u12m / (patrimonio_uf + deuda_uf - (caja_uf - caja_minima_uf))",
        "sources": ["raw_er_activo_line", "raw_valor_cuota_contable", "raw_saldo_deuda", "raw_caja",
                    "derived_kpi (caja_minima = % de ESF.total_activo)"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='tasa_arriendo_ajustada_contable'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "cálculo manual, consolidado en derived_kpi (2026-07-09)",
    },
    "cap_rate_implicito_contable": {
        "label": "Cap Rate Implícito Contable",
        "verbal": "NOI U12M / (patrimonio contable + deuda financiera - (caja - caja mínima)), todo en UF.",
        "python": "cap_rate = noi_u12m / (patrimonio_uf + deuda_uf - (caja_uf - caja_minima_uf))",
        "sources": ["raw_er_activo_line", "raw_valor_cuota_contable", "raw_saldo_deuda", "raw_caja",
                    "derived_kpi (caja_minima = % de ESF.total_activo)"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='cap_rate_implicito_contable'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "cálculo manual, consolidado en derived_kpi (2026-07-09)",
    },
    "tasa_arriendo_ajustada_bursatil": {
        "label": "Tasa de Arriendo Ajustada Bursátil",
        "verbal": "Ingresos U12M / (market cap bursátil + deuda financiera - (caja - caja mínima)), todo en UF.",
        "python": "tasa = ingresos_u12m / (market_cap_uf + deuda_uf - (caja_uf - caja_minima_uf))",
        "sources": ["raw_er_activo_line", "raw_valor_cuota_bursatil", "raw_saldo_deuda", "raw_caja",
                    "derived_kpi (caja_minima = % de ESF.total_activo)"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{serie}' AND kpi='tasa_arriendo_ajustada_bursatil'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "scripts/consolidate_kpis_bursatil_pt.py (Apo/PT) · scripts/consolidate_kpis_bursatil_tri.py (TRI, por serie: market_cap = cuotas totales del fondo x precio de esa serie)",
    },
    "cap_rate_implicito_bursatil": {
        "label": "Cap Rate Implícito Bursátil",
        "verbal": "NOI U12M / (market cap bursátil + deuda financiera - (caja - caja mínima)), todo en UF.",
        "python": "cap_rate = noi_u12m / (market_cap_uf + deuda_uf - (caja_uf - caja_minima_uf))",
        "sources": ["raw_er_activo_line", "raw_valor_cuota_bursatil", "raw_saldo_deuda", "raw_caja",
                    "derived_kpi (caja_minima = % de ESF.total_activo)"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{serie}' AND kpi='cap_rate_implicito_bursatil'\n"
            "  AND periodo='{periodo}' AND variante IS NULL"
        ),
        "script": "scripts/consolidate_kpis_bursatil_pt.py (Apo/PT) · scripts/consolidate_kpis_bursatil_tri.py (TRI, por serie: market_cap = cuotas totales del fondo x precio de esa serie)",
    },
    "perfil_vencimiento": {
        "label": "Perfil de vencimiento de deuda",
        "verbal": "Distribución % del saldo insoluto de créditos vigentes por tramo de años al vencimiento.",
        "python": "pct[tramo] = sum(saldo where tramo) / sum(saldo)",
        "sources": ["dim_credito", "raw_saldo_deuda"],
        "sql": (
            "SELECT valor FROM derived_kpi\n"
            "WHERE entidad_key='{fondo}' AND kpi='perfil_vencimiento'\n"
            "  AND variante='{variante}' AND periodo='{periodo}'"
        ),
        "script": "tools/db/backfill.py (kpi_perfil_vencimiento)",
    },
    # ---- Balance consolidado (raw) ----
    "ESF.efectivo": {"label": "Efectivo y Efectivo Equivalente", "raw": True},
    "ESF.otros_activos_corrientes": {"label": "Otros Activos Corrientes", "raw": True},
    "ESF.propiedades_inversion": {"label": "Propiedades de Inversión", "raw": True},
    "ESF.otros_activos_no_corrientes": {"label": "Otros Activos No Corrientes", "raw": True},
    "ESF.total_activo": {"label": "Total Activos", "raw": True},
    "ESF.prestamos": {"label": "Préstamos Bancarios", "raw": True},
    "ESF.pasivos_impuestos_diferidos": {"label": "Pasivos por Impuestos Diferidos", "raw": True},
    "ESF.otros_pasivos": {"label": "Otros Pasivos", "raw": True},
    "ESF.patrimonio_neto": {"label": "Patrimonio Neto", "raw": True},
    "ESF.total_pasivo_patrimonio": {"label": "Total Pasivos + Patrimonio", "raw": True},
    # ---- Gastos (raw EEFF ER) ----
    "ER.comision_admin": {"label": "Comisión de administración", "raw": True, "er": True},
    "ER.honorarios_custodia": {"label": "Honorarios de custodia", "raw": True, "er": True},
    "ER.remun_comite": {"label": "Remuneración comité", "raw": True, "er": True},
    "ER.otros_gastos": {"label": "Otros gastos no recurrentes", "raw": True, "er": True},
    "ER.total_gastos_operacion": {"label": "Total gastos de operación", "raw": True, "er": True},
    "ER.recurrentes": {
        "label": "Gastos recurrentes",
        "raw": True, "er": True,
        "verbal_extra": "= honorarios_custodia + remun_comite",
    },
}


def _raw_meta(cuenta_codigo: str) -> dict:
    """Trace record for raw balance/ER accounts fetched by SUM(monto_clp)."""
    m = KPI_META.get(cuenta_codigo, {})
    is_er = m.get("er", False)
    tabla = "raw_eeff_line" if is_er else "raw_balance_consolidado_line"
    col = "cuenta_codigo_canonical" if is_er else "cuenta_codigo"
    return {
        "label": m.get("label", cuenta_codigo),
        "verbal": (
            f"Suma de líneas de {tabla} para el fondo y período, con {col} = '{cuenta_codigo}'. "
            + m.get("verbal_extra", "")
        ).strip(),
        "python": f"SUM(monto_clp) FROM {tabla} WHERE {col}='{cuenta_codigo}' AND fondo_key=? AND periodo=?",
        "sources": [tabla],
        "sql": (
            f"SELECT SUM(monto_clp) FROM {tabla}\n"
            f"WHERE fondo_key='{{fondo}}' AND {col}='{cuenta_codigo}'\n"
            f"  AND periodo='{{periodo}}' AND (superseded_at IS NULL OR superseded_at='')"
        ),
        "script": "tools/db/ingest_eeff_pt.py · ingest_eeff_tri_series.py",
    }


HTML_TEMPLATE = r"""<!-- ARCHIVO AUTOGENERADO por scripts/build_factsheet.py — NO editar factsheet.html a mano, los cambios se pierden al regenerar. Editar HTML_TEMPLATE en el script y correr `python scripts/build_factsheet.py`. -->
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<title>Toesca · Fact Sheets dinámicos</title>
<style>
  :root {
    --green: #00B27A;
    --green-soft: #C8ECD8;
    --green-header: #A6DEC1;
    --text: #202020;
    --border: #A6A6A6;
  }
  * { box-sizing: border-box; }
  body {
    font-family: "Segoe UI", Arial, sans-serif;
    color: var(--text);
    margin: 0;
    background: #F4F4F4;
    font-size: 12px;
  }
  .page {
    max-width: 1180px;
    margin: 12px auto;
    background: #fff;
    padding: 24px 32px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }
  header {
    background: linear-gradient(180deg,#3d3d3d,#2b2b2b);
    color: #fff;
    padding: 22px 32px 18px;
    margin: -24px -32px 0;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }
  header h1 { margin: 0; font-size: 30px; font-weight: 300; letter-spacing: 0.5px; }
  header h2 { margin: 4px 0 0; font-size: 12px; font-weight: 400; color: #dedede;
              font-variant: small-caps; letter-spacing: 1px; }
  header .logo { height: 32px; width: auto; display: block; }
  .month-bar { background: #fff; padding: 8px 0 4px;
               font-weight: 700; font-size: 14px; letter-spacing: 1px;
               border-bottom: 2px solid var(--green); }
  .month-bar > span { text-align: right; }
  .selectors {
    display: flex; flex-direction: column; gap: 0;
    padding: 0; background: transparent;
    border-left: none; margin: 0;
  }
  .selectors .field { display:flex; flex-direction:column; gap:6px; padding: 14px 0; border-bottom: 1px solid #e5e5e5; }
  .selectors .field-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.8px;
    text-transform: uppercase; color: #4a6b5c;
  }
  .selectors .fund-btns, .selectors .year-btns, .selectors .q-btns { display:flex; gap:4px; }
  .selectors .fund-btn {
    padding: 6px 16px; border: 1px solid var(--green);
    background: #fff; cursor: pointer; font-weight: 600;
    color: var(--green); border-radius: 3px;
    transition: background-color 150ms ease, color 150ms ease;
    font-size: 12px;
  }
  .selectors .fund-btn:hover { background: #E6F5EC; }
  .selectors .fund-btn.active { background: var(--green); color:#fff; }
  .selectors .year-btns {
    max-width: 340px; overflow-x: auto; padding-bottom: 2px;
    scrollbar-width: thin;
  }
  .selectors .year-btn {
    padding: 5px 10px; border: 1px solid transparent;
    background: transparent; cursor: pointer;
    font-weight: 600; color: #555; border-radius: 3px;
    font-size: 12px; font-variant-numeric: tabular-nums;
    transition: background-color 150ms ease, color 150ms ease;
    flex-shrink: 0;
  }
  .selectors .year-btn:hover { background: #E6F5EC; color: var(--green); }
  .selectors .year-btn.active {
    background: #fff; color: var(--text);
    border-color: var(--green);
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  }
  .selectors .q-group {
    display: inline-flex; background: #fff;
    border: 1px solid var(--border); border-radius: 4px; overflow: hidden;
  }
  .selectors .q-btn {
    padding: 6px 12px; border: none; background: #fff;
    cursor: pointer; font-weight: 600; font-size: 12px;
    color: #555; min-width: 42px;
    transition: background-color 150ms ease, color 150ms ease;
    border-right: 1px solid #e5e5e5;
  }
  .selectors .q-btn:last-child { border-right: none; }
  .selectors .q-btn:hover:not(:disabled) { background: #E6F5EC; color: var(--green); }
  .selectors .q-btn.active { background: var(--green); color: #fff; }
  .selectors .q-btn:disabled {
    color: #c8c8c8; cursor: not-allowed; background: #fafafa;
  }
  .period-nav-group {
    display: flex; gap: 6px; align-items: flex-start; flex-direction: column;
    padding: 14px 0;
  }
  .period-nav-group:not(:last-child) {
    border-bottom: 1px solid #e5e5e5;
  }
  .period-nav-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    color: var(--green); letter-spacing: 0.5px; white-space: nowrap;
  }
  .period-nav-controls {
    display: flex; gap: 4px; align-items: center;
  }
  .nav-arrow {
    background: transparent; border: 1px solid var(--green);
    color: var(--green); cursor: pointer; font-weight: 700;
    padding: 4px 8px; border-radius: 3px; font-size: 12px;
    min-width: 34px; min-height: 36px; display: flex; align-items: center;
    justify-content: center; transition: background-color 150ms ease, color 150ms ease;
  }
  .nav-arrow:hover:not(:disabled) { background: #E6F5EC; }
  .nav-arrow:disabled { color: #c8c8c8; cursor: not-allowed; }
  .period-display {
    font-weight: 600; color: var(--text); cursor: pointer;
    padding: 4px 8px; border-radius: 3px;
    transition: background-color 150ms ease;
    position: relative;
  }
  .period-display:hover { background: #E6F5EC; }
  .period-dropdown {
    position: fixed; background: #fff; border: 1px solid #ccc;
    border-radius: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    z-index: 300; max-height: 250px; overflow-y: auto;
    min-width: 150px;
  }
  .period-dropdown-item {
    padding: 8px 12px; cursor: pointer; font-size: 12px;
    border-bottom: 1px solid #f0f0f0; transition: background-color 150ms ease;
  }
  .period-dropdown-item:hover { background: #F0F8F4; }
  .period-dropdown-item.active {
    background: var(--green-soft); color: var(--green); font-weight: 600;
  }
  .period-dropdown-item:last-child { border-bottom: none; }
  .cols { display: grid; grid-template-columns: 30% 1fr; gap: 24px; }
  .cols-page3 { grid-template-columns: 1fr 34%; }
  .cols-page3-lower { grid-template-columns: 1fr 34%; align-items: start; }
  .section-title {
    background: var(--green-header); color: #000;
    font-weight: 700; font-size: 11px;
    padding: 4px 8px; text-transform: uppercase;
    letter-spacing: 0.5px; margin: 10px 0 6px;
  }
  table {
    width: 100%; border-collapse: collapse;
    font-variant-numeric: tabular-nums;
  }
  table th, table td {
    padding: 6px 8px; font-size: 11px; line-height: 1.45;
    border-bottom: 1px solid #E6E6E6; text-align: right;
  }
  table th:first-child, table td:first-child { text-align: left; }
  table th {
    background: #F6F9F7; color: #33413b; font-weight: 700;
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
    border-bottom: 2px solid var(--green);
  }
  table tbody tr { transition: background-color 120ms ease; }
  table tbody tr:nth-child(even) { background: #FAFBFA; }
  table tbody tr:hover { background: #EAF7F0; }
  table tbody tr:last-child td { border-bottom: 1px solid #C6C6C6; }
  table tbody tr.row-total, table tbody tr.row-total:nth-child(even) {
    background: var(--green-soft); font-weight: 700; color: #0d3a29;
  }
  table tbody tr.row-total:hover { background: #B4E5CC; }
  table tbody tr.row-total td { border-bottom: 2px solid var(--green); }

  .kv { border-collapse: collapse; }
  .kv tr { border-bottom: 1px solid #EDEDED; transition: background-color 120ms ease; }
  .kv tr:last-child { border-bottom: none; }
  .kv tr:nth-child(even) { background: #FAFBFA; }
  .kv tr:hover { background: #EAF7F0; }
  .kv td { padding: 5px 6px; font-size: 11px; }
  .kv td:first-child { color: #464646; font-weight: 500; }
  .kv td:last-child {
    text-align: right; font-weight: 700; color: #1a1a1a;
    font-variant-numeric: tabular-nums;
  }
  p, ul { font-size: 11px; line-height: 1.4; margin: 4px 0; }
  ul { padding-left: 16px; }
  .small { font-size: 10px; color: #555; }
  .placeholder { color: #a0a0a0; font-style: italic; }
  .hidden { display: none !important; }
  .admin-toggle {
    float: right; font-size: 10px; padding: 2px 8px; margin-top: -2px;
    border: 1px solid var(--green); background: #fff; color: var(--green);
    border-radius: 3px; cursor: pointer; text-transform: none;
  }
  .admin-toggle.on { background: var(--green); color: #fff; }
  .rv-table td:first-child { text-align: left; }
  .rv-table td:nth-child(2) { text-align: center; color: #464646; font-weight: 500; white-space: nowrap; }
  .rv-table td:last-child {
    text-align: right; font-weight: 700; color: var(--green);
    font-variant-numeric: tabular-nums; white-space: nowrap;
  }
  .rv-table .rv-sub { display: block; font-weight: 400; font-style: italic; color: #7a7a7a; font-size: 10px; margin-top: 1px; }
  span.ed, span.auto { padding: 0 2px; }
  input.date-input-inline {
    font: inherit; font-size: 11px; padding: 2px 6px;
    border: 1px solid var(--green); border-radius: 4px;
    background: #fff; color: var(--text); cursor: pointer;
    vertical-align: baseline; line-height: 1.4;
  }
  input.date-input-inline:hover { background: var(--green-soft); }
  input.date-input-inline:focus { outline: 2px solid var(--green); outline-offset: 1px; }

  /* Modo admin: celdas trazables */
  body.admin [data-trace] {
    cursor: help;
    border-bottom: 1px dotted #0088cc;
    background: rgba(0,136,204,0.04);
  }
  body.admin [data-trace]:hover { background: rgba(0,136,204,0.14); }

  /* Modal trazabilidad */
  .trace-modal-bg {
    position: fixed; inset: 0; background: rgba(0,0,0,0.45);
    display: none; align-items: flex-start; justify-content: center;
    z-index: 1000; padding: 40px 16px;
  }
  .trace-modal-bg.open { display: flex; }
  .trace-modal {
    background: #fff; max-width: 780px; width: 100%;
    max-height: calc(100vh - 80px); overflow-y: auto;
    border-radius: 6px; box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    padding: 20px 24px;
    font-size: 12px; line-height: 1.5;
  }
  .trace-modal h3 { margin: 0 0 4px; font-size: 16px; color: var(--text); }
  .trace-modal .trace-sub { color: #666; font-size: 11px; margin-bottom: 12px; }
  .trace-modal .trace-value {
    display: inline-block; padding: 4px 10px; background: var(--green-soft);
    border-radius: 3px; font-weight: 700; font-size: 14px;
    font-variant-numeric: tabular-nums; margin-bottom: 12px;
  }
  .trace-modal h4 {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px;
    color: #4a6b5c; margin: 14px 0 4px; border-bottom: 1px solid #ddd;
    padding-bottom: 3px;
  }
  .trace-modal p { margin: 4px 0; }
  .trace-modal pre {
    background: #f6f8f7; padding: 10px 12px; border-radius: 4px;
    font-size: 11px; overflow-x: auto; margin: 4px 0;
    border-left: 3px solid var(--green);
    font-family: "Consolas","Monaco",monospace;
    white-space: pre-wrap; word-break: break-word;
  }
  .trace-modal ul { padding-left: 18px; margin: 4px 0; }
  .trace-modal .trace-close {
    float: right; border: none; background: transparent; font-size: 22px;
    cursor: pointer; color: #888; line-height: 1; padding: 0 4px;
  }
  .trace-modal .trace-close:hover { color: #000; }
  .trace-modal .trace-inputs td { padding: 3px 8px; font-size: 11px; border-bottom: 1px solid #eee; }
  .trace-modal .trace-inputs td:first-child { color: #555; }
  .trace-modal .trace-inputs td:last-child { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }

  /* Página 2: resumen de performance de activos + gráficos */
  .charts-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 10px 0 16px; }
  .chart-box {
    border: 1px dashed var(--border); border-radius: 6px; padding: 12px 14px;
    min-height: 220px; display: flex; flex-direction: column;
  }
  .chart-box .chart-title {
    font-weight: 700; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; color: #33413b; margin-bottom: 8px;
  }
  .chart-placeholder {
    flex: 1; display: flex; align-items: center; justify-content: center;
    color: #999; font-style: italic; font-size: 11px; text-align: center;
    padding: 12px; border-radius: 4px;
    background: repeating-linear-gradient(45deg, #fafafa, #fafafa 10px, #f2f2f2 10px, #f2f2f2 20px);
  }
  #tbl-perf-activos td.placeholder, #tbl-perf-activos th { text-align: right; }

  /* Página 3: aspectos del mes (caja gris) + tablas por edificio lado a lado */
  .aspectos-mes-box {
    background: #F4F4F4; border-radius: 6px; padding: 12px 16px; margin: 4px 0 16px;
  }
  .aspectos-mes-box p { margin: 4px 0; font-size: 11px; }
  .subtable-box { border: 1px solid #EDEDED; border-radius: 6px; padding: 10px 12px; }
  .subtable-box .subtable-title { font-weight: 700; font-size: 11px; margin-bottom: 6px; color: #33413b; }
  .subtable-box table { width: 100%; }
  .subtable-box td, .subtable-box th { padding: 3px 4px; font-size: 11px; text-align: right; }
  .subtable-box td:first-child, .subtable-box th:first-child { text-align: left; }
  #tbl-tasaciones td, #tbl-tasaciones th,
  #tbl-tasaciones-comp td, #tbl-tasaciones-comp th { text-align: right; padding: 4px 8px; font-size: 11px; }
  #tbl-tasaciones td:first-child, #tbl-tasaciones th:first-child,
  #tbl-tasaciones-comp td:first-child, #tbl-tasaciones-comp th:first-child { text-align: left; }

  /* Donut chart (conic-gradient) con leyenda */
  .donut-wrap { flex: 1; display: flex; align-items: center; justify-content: center; gap: 14px; }
  .donut { width: 84px; height: 84px; border-radius: 50%; position: relative; flex: none; }
  .donut::after { content: ""; position: absolute; inset: 17px; background: #fff; border-radius: 50%; }
  .donut-legend { font-size: 10px; }
  .donut-legend .row { display: flex; align-items: center; gap: 6px; margin: 3px 0; }
  .donut-legend .dot { width: 9px; height: 9px; border-radius: 2px; display: inline-block; flex: none; }

  /* Barra de ocupación (reemplaza el treemap de la referencia — mismo dato, layout simplificado) */
  .occ-box { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 8px; padding: 8px 6px; }
  .occ-bar { background: #EDEDED; border-radius: 4px; height: 14px; overflow: hidden; }
  .occ-bar-fill { background: var(--green); height: 100%; }
  .occ-label { font-size: 11px; text-align: center; font-weight: 600; color: #33413b; }

  /* Fotos de activos (página 3) */
  .fotos-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
  .foto-box { aspect-ratio: 403/669; border-radius: 6px; overflow: hidden; background: #F4F4F4;
    display: flex; align-items: center; justify-content: center; }
  .foto-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .foto-box .foto-placeholder { font-size: 10px; color: #999; text-align: center; padding: 8px; }
  .foto-caption { font-size: 10px; text-align: center; color: #666; margin-top: 3px; }
  #tbl-perf-activos td:first-child, #tbl-perf-activos th:first-child { text-align: left; }
  #sidebar {
    position: fixed; left: 0; top: 0;
    width: 240px; height: 100vh;
    background: #fff; border-right: 1px solid #ddd;
    box-shadow: 2px 0 8px rgba(0,0,0,0.07);
    overflow-y: auto; z-index: 200;
    padding: 20px 16px 20px;
    display: flex; flex-direction: column;
  }
  #sidebar-brand {
    font-size: 18px; font-weight: 300; letter-spacing: 0.5px;
    color: #2b2b2b; padding-bottom: 16px;
    border-bottom: 2px solid var(--green); margin-bottom: 2px;
    line-height: 1.2;
  }
  #sidebar-brand span {
    font-size: 10px; font-weight: 700; letter-spacing: 1px;
    color: #888; text-transform: uppercase; display: block; margin-top: 3px;
  }
  #sidebar .admin-toggle {
    float: none; margin: auto 0 0; align-self: flex-start;
    font-size: 11px; padding: 4px 10px;
  }
  #main-content { margin-left: 240px; }
</style>
</head>
<body>
<div id="sidebar">
  <div id="sidebar-brand">TOESCA<br><span>Fact Sheets</span></div>
  <div class="selectors">
    <div class="field">
      <span class="field-label">Fondo</span>
      <div class="fund-btns" id="fund-btns"></div>
    </div>
    <div class="period-nav-group">
      <span class="period-nav-label">EEFF & Bursátil</span>
      <div class="period-nav-controls">
        <button class="nav-arrow" id="nav-prev-cb" onclick="navPeriod(-1, 'cb')">‹</button>
        <span class="period-display" id="period-display-cb" onclick="togglePeriodDropdown('cb')"></span>
        <button class="nav-arrow" id="nav-next-cb" onclick="navPeriod(1, 'cb')">›</button>
      </div>
      <div class="period-dropdown" id="period-dropdown-cb" style="display:none;"></div>
    </div>
    <div class="period-nav-group">
      <span class="period-nav-label">Operacional</span>
      <div class="period-nav-controls">
        <button class="nav-arrow" id="nav-prev-op" onclick="navPeriod(-1, 'op')">‹</button>
        <span class="period-display" id="period-display-op" onclick="togglePeriodDropdown('op')"></span>
        <button class="nav-arrow" id="nav-next-op" onclick="navPeriod(1, 'op')">›</button>
      </div>
      <div class="period-dropdown" id="period-dropdown-op" style="display:none;"></div>
    </div>
    <select id="sel-periodo-cb" style="display:none" aria-hidden="true"></select>
    <select id="sel-periodo-op" style="display:none" aria-hidden="true"></select>
  </div>
  <a href="http://localhost:8765/ingesta" target="_blank" rel="noopener" id="btn-ingesta" class="admin-toggle" style="text-decoration:none;text-align:center;display:block;margin-top:6px" title="Ingestar un nuevo EEFF a la base de datos (requiere tener ingesta.bat corriendo)">Ingesta FS</a>
  <button type="button" id="btn-admin" class="admin-toggle" title="Modo admin: click en cualquier número para ver cómo se calculó, y editar fechas de Noticias">✎ Admin</button>
</div>
<div id="main-content">
<div class="page">
  <header>
    <div>
      <h1 id="hdr-nombre">—</h1>
      <h2 id="hdr-sub">—</h2>
    </div>
    <img class="logo" src="data:image/png;base64,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" alt="Toesca">
  </header>
  <div class="month-bar">
    <span id="month-bar">—</span>
  </div>

  <div class="cols">
    <!-- Columna izquierda -->
    <div>
      <div class="section-title">El Fondo</div>
      <table class="kv" id="tbl-elfondo"></table>

      <div class="section-title">Valor Cuota Libro</div>
      <table id="tbl-vcl"><thead><tr id="tbl-vcl-thead"></tr></thead><tbody></tbody></table>

      <div id="wrap-vcb">
        <div class="section-title">Valor Cuota Bursátil</div>
        <table id="tbl-vcb"><thead><tr id="tbl-vcb-thead"></tr></thead><tbody></tbody></table>
      </div>

      <div class="section-title">Objetivo</div>
      <p id="txt-objetivo">—</p>

      <div class="section-title">Remuneración Fija Anual</div>
      <table class="kv" id="tbl-remfija"></table>

      <div class="section-title">Remuneración Variable</div>
      <table class="rv-table" id="tbl-remvar">
        <thead><tr><th>Condición</th><th>Serie</th><th>Tasa</th></tr></thead>
        <tbody></tbody>
      </table>

      <div id="wrap-tickers">
        <div class="section-title">Ticker Bloomberg</div>
        <table class="kv" id="tbl-tickers"></table>
      </div>

      <div class="section-title">Comité de Vigilancia</div>
      <p id="txt-comite">—</p>

      <div class="section-title">Contacto</div>
      <p id="txt-contacto">—</p>
    </div>

    <!-- Columna derecha -->
    <div>
      <div class="section-title">Resumen</div>
      <p id="txt-resumen">—</p>

      <div class="section-title">Noticias</div>
      <p id="txt-noticias">—</p>

      <div class="section-title">Balance Consolidado <span id="bal-fecha" style="font-weight:400;text-transform:none">— (en miles de pesos)</span>
        <button type="button" id="btn-unit-balance" class="admin-toggle" title="Cambiar unidad monetaria de esta tabla">UF ⇄ MM$</button>
      </div>
      <table id="tbl-balance">
        <tbody>
          <tr><td>Efectivo y Efectivo Equivalente</td><td id="bal-efectivo">—</td>
              <td>Préstamos Bancarios</td><td id="bal-prestamos">—</td></tr>
          <tr><td>Otros Activos Corrientes</td><td id="bal-otros-ac">—</td>
              <td>Pasivos por Impuestos Diferidos</td><td id="bal-imp-dif">—</td></tr>
          <tr><td>Propiedades de Inversión</td><td id="bal-pi">—</td>
              <td>Otros Pasivos</td><td id="bal-otros-p">—</td></tr>
          <tr><td>Otros Activos No Corrientes</td><td id="bal-otros-anc">—</td>
              <td>Patrimonio</td><td id="bal-patrimonio">—</td></tr>
          <tr class="row-total">
              <td>Total Activos</td><td id="bal-total-a">—</td>
              <td>Total Pasivos + Patrimonio</td><td id="bal-total-pp">—</td></tr>
        </tbody>
      </table>

      <div class="section-title">Gastos del Fondo <span id="gastos-fecha" style="font-weight:400;text-transform:none">— (en miles de pesos)</span>
        <button type="button" id="btn-unit-gastos" class="admin-toggle" title="Cambiar unidad monetaria de esta tabla">UF ⇄ MM$</button>
      </div>
      <table>
        <tbody>
          <tr><td>Comisión de administración</td><td id="g-admin">—</td></tr>
          <tr><td>Gastos recurrentes</td><td id="g-recur">—</td></tr>
          <tr><td>Otros gastos no recurrentes</td><td id="g-otros">—</td></tr>
          <tr class="row-total"><td>Total de Gastos</td><td id="g-total">—</td></tr>
        </tbody>
      </table>

      <div id="wrap-activos">
        <div class="section-title">Activos del Fondo</div>
        <table id="tbl-activos">
          <thead><tr><th>Inversión</th><th>Activo Subyacente</th><th>Participación</th><th>GLA (m²)</th></tr></thead>
          <tbody id="tbl-activos-tbody"></tbody>
        </table>
      </div>

      <div class="section-title">Rentabilidad del Fondo (en UF)</div>
      <table id="tbl-rent"><thead id="tbl-rent-thead"></thead><tbody></tbody></table>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div>
          <div class="section-title">Endeudamiento Consolidado (en UF)</div>
          <table class="kv">
            <tr><td>Leverage</td><td id="fld-leverage">—</td></tr>
            <tr><td>LTV</td><td id="fld-ltv">—</td></tr>
            <tr><td>Tasa Promedio</td><td id="fld-tasa">—</td></tr>
            <tr><td>Duration (años)</td><td id="fld-duration">—</td></tr>
            <tr><td>Deuda Financiera Neta <span id="fld-dfn-unit" style="font-weight:400"></span>
              <button type="button" id="btn-unit-dfn" class="admin-toggle" style="float:none;margin-left:4px;padding:0 4px" title="Cambiar unidad monetaria de este campo">⇄</button>
            </td><td id="fld-dfn">—</td></tr>
          </table>
        </div>
        <div>
          <div class="section-title">Perfil Vencimiento Deuda</div>
          <table class="kv">
            <tr><td>0-3 años</td><td id="fld-pv-03">—</td></tr>
            <tr><td>3-7 años</td><td id="fld-pv-37">—</td></tr>
            <tr><td>7-10 años</td><td id="fld-pv-710">—</td></tr>
            <tr><td>&gt;10 años</td><td id="fld-pv-10">—</td></tr>
          </table>
        </div>
      </div>

      <div class="section-title">Otros Indicadores (en UF)</div>
      <table id="tbl-otros"><thead id="tbl-otros-thead"></thead><tbody id="tbl-otros-tbody"></tbody></table>

      <div id="wrap-repartos">
        <div class="section-title">Repartos Últimos 12 Meses <span style="font-weight:400;text-transform:none">(Pesos por cuota)</span></div>
        <table id="tbl-rep"><thead><tr id="tbl-rep-thead"></tr></thead><tbody></tbody></table>
      </div>
    </div>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Página 2: performance de activos + gráficos. Layout específico por fondo (S.page2);
     si el fondo no tiene page2 definido (TRI, Apo) se muestra un aviso de pendiente. -->
<div class="page" id="page2">
  <header>
    <div>
      <h1 id="hdr2-nombre">—</h1>
      <h2 id="hdr2-sub">—</h2>
    </div>
    <img class="logo" src="data:image/png;base64,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" alt="Toesca">
  </header>
  <div class="month-bar"><span id="month-bar2">—</span></div>

  <div id="page2-pending" class="hidden">
    <p class="small placeholder" style="margin-top:16px">
      Página 2 aún no definida para este fondo — pendiente de traer su fact sheet de referencia
      (el layout de esta página no se comparte entre TRI, PT y Apo).
    </p>
  </div>

  <div id="page2-body">
    <div class="section-title">Resumen Performance Activos del Fondo
      <span id="perf-fecha" style="font-weight:400;text-transform:none">— (al —)</span>
    </div>
    <div style="overflow-x:auto">
      <table id="tbl-perf-activos">
        <thead>
          <tr id="tbl-perf-activos-thead1"></tr>
          <tr id="tbl-perf-activos-thead2"></tr>
        </thead>
        <tbody id="tbl-perf-activos-tbody"></tbody>
      </table>
    </div>
    <p class="small placeholder">Pendiente: valores por activo desde rent roll consolidado (raw_rent_roll_line).</p>

    <div class="charts-grid-2">
      <div class="chart-box">
        <div class="chart-title" id="chart-title-rubro">Composición por Rubro del Arrendatario (UF/mes)</div>
        <div class="chart-placeholder" data-chart="rubro-arrendatario">Pendiente de datos</div>
      </div>
      <div class="chart-box">
        <div class="chart-title" id="chart-title-tipo">Composición por Tipo de Activo (UF/mes)</div>
        <div class="chart-placeholder" data-chart="tipo-activo">Pendiente de datos</div>
      </div>
    </div>

    <div class="charts-grid-2">
      <div class="chart-box">
        <div class="chart-title">Evolución NOI y Ratio de Cobertura de Servicio de Deuda</div>
        <div class="chart-placeholder" data-chart="noi-rcsd">Pendiente: serie mensual NOI (UF), cuota financiamiento (UF) y RCSD</div>
      </div>
      <div class="chart-box">
        <div class="chart-title">Evolución Ingresos, NOI y Vacancia (m²)</div>
        <div class="chart-placeholder" data-chart="ingresos-noi-vacancia">Pendiente: serie mensual Ingresos (UF), NOI (UF) y vacancia (m²)</div>
      </div>
    </div>

    <div class="charts-grid-2">
      <div class="chart-box">
        <div class="chart-title">Perfil de Vencimiento de Contratos (UF/mes)
          <span class="small" style="float:right;font-weight:400;text-transform:none">Plazo medio contratos: <b id="fld-plazo-medio">—</b></span>
        </div>
        <div class="chart-placeholder" data-chart="perfil-vencimiento-contratos">Pendiente de datos</div>
      </div>
      <div class="chart-box">
        <div class="chart-title">Recaudación Consolidada U12M
          <span class="small" style="float:right;font-weight:400;text-transform:none">Morosidad promedio: <b id="fld-morosidad">—</b></span>
        </div>
        <div class="chart-placeholder" data-chart="recaudacion-consolidada">Pendiente de datos</div>
      </div>
    </div>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Página 3: detalle de activos (aspectos relevantes, status ocupación por activo,
     vacancia/resumen anual/tasaciones). Layout específico por fondo (S.page3);
     si el fondo no lo tiene definido (TRI, PT) se muestra un aviso de pendiente. -->
<div class="page" id="page3">
  <header>
    <div>
      <h1 id="hdr3-nombre">—</h1>
      <h2 id="hdr3-sub">—</h2>
    </div>
    <img class="logo" src="data:image/png;base64,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" alt="Toesca">
  </header>
  <div class="month-bar"><span id="month-bar3">—</span></div>

  <div id="page3-pending" class="hidden">
    <p class="small placeholder" style="margin-top:16px">
      Página 3 aún no definida para este fondo — pendiente de traer su fact sheet de referencia
      (el layout de esta página no se comparte entre TRI, PT y Apo).
    </p>
  </div>

  <div id="page3-body">
    <div class="section-title" id="page3-titulo">—</div>
    <p class="small placeholder" style="margin-top:-4px">
      Estructura construida — pendiente de datos (raw_rent_roll_line, fact_tasacion).
    </p>

    <div class="cols cols-page3">
      <div>
        <div class="charts-grid-2">
          <div class="chart-box">
            <div class="chart-title">GLA (m²)</div>
            <div class="donut-wrap" id="donut-gla"></div>
          </div>
          <div class="chart-box">
            <div class="chart-title">Ingresos (UF/mes)</div>
            <div class="donut-wrap" id="donut-ingresos"></div>
          </div>
        </div>
        <div class="section-title">Aspectos del Mes</div>
        <div class="aspectos-mes-box" id="txt-aspectos-mes"></div>
      </div>
      <div>
        <div class="section-title">Aspectos Relevantes</div>
        <table class="kv" id="tbl-aspectos"></table>
        <div class="fotos-grid" id="grid-fotos"></div>
      </div>
    </div>

    <div class="cols cols-page3-lower">
      <div>
        <div class="section-title">Gestión de Vacancia
          <span class="small" id="vacancia-periodo-label" style="font-weight:400;text-transform:none"></span>
        </div>
        <div class="charts-grid-2" id="grid-vacancia"></div>
        <p class="small">Fondo: <b id="txt-vacancia-fondo">—</b></p>

        <div class="section-title">Resumen Anual — Vencimientos y Renovaciones</div>
        <div class="charts-grid-2" id="grid-resumen-anual"></div>

        <div class="section-title">Tasaciones</div>
        <div style="overflow-x:auto">
          <table id="tbl-tasaciones">
            <thead><tr><th></th><th>Valor Tasación</th><th>Fecha Tasación</th><th>Deuda</th><th>LTV</th></tr></thead>
            <tbody id="tbl-tasaciones-tbody"></tbody>
          </table>
        </div>
        <div style="overflow-x:auto;margin-top:8px">
          <table id="tbl-tasaciones-comp">
            <thead><tr><th></th><th id="th-tasacion-prev"></th><th id="th-tasacion-actual"></th><th>Var % UF</th></tr></thead>
            <tbody id="tbl-tasaciones-comp-tbody"></tbody>
          </table>
        </div>
      </div>
      <div>
        <div class="section-title">Status Actual Oficinas por Activo</div>
        <div class="charts-grid-2" id="grid-status-oficinas"></div>

        <div class="section-title">Status Actual Locales por Activo</div>
        <div class="charts-grid-2" id="grid-status-locales"></div>
      </div>
    </div>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Página 4: notas metodológicas + análisis de mercado. Layout específico por
     fondo (S.page4); si el fondo no lo tiene definido (TRI, PT) se muestra un
     aviso de pendiente. -->
<div class="page" id="page4">
  <header>
    <div>
      <h1 id="hdr4-nombre">—</h1>
      <h2 id="hdr4-sub">—</h2>
    </div>
    <img class="logo" src="data:image/png;base64,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" alt="Toesca">
  </header>
  <div class="month-bar"><span id="month-bar4">—</span></div>

  <div id="page4-pending" class="hidden">
    <p class="small placeholder" style="margin-top:16px">
      Página 4 aún no definida para este fondo — pendiente de traer su fact sheet de referencia
      (el layout de esta página no se comparte entre TRI, PT y Apo).
    </p>
  </div>

  <div id="page4-body">
    <div class="section-title" id="mercado-titulo">Análisis de Mercado de Oficinas — Submercado —</div>
    <p class="small placeholder" id="txt-mercado-p1">Pendiente: párrafo de vacancia (informe JLL) — actualización manual, no proviene de la DB.</p>
    <p class="small placeholder" id="txt-mercado-p2">Pendiente: párrafo de canon de arriendo (informe JLL) — actualización manual, no proviene de la DB.</p>
    <div style="overflow-x:auto">
      <table id="tbl-mercado">
        <thead><tr>
          <th>Comuna</th><th>Clase</th><th>Inventario (m²)</th>
          <th>Absorción neta U12M (m²)</th><th>Vacancia (%)</th>
          <th>Renta (UF/m²)</th><th>Construcción (m²)</th>
        </tr></thead>
        <tbody id="tbl-mercado-tbody"></tbody>
      </table>
    </div>

    <div class="section-title">Notas</div>
    <ol id="lst-notas" style="font-size:10px;color:#333;padding-left:16px;line-height:1.5"></ol>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Modal trazabilidad (modo admin) -->
<div id="trace-modal-bg" class="trace-modal-bg" aria-hidden="true">
  <div class="trace-modal" role="dialog" aria-modal="true" aria-labelledby="trace-title">
    <button type="button" class="trace-close" id="trace-close" aria-label="Cerrar">×</button>
    <h3 id="trace-title">—</h3>
    <div class="trace-sub" id="trace-sub">—</div>
    <div class="trace-value" id="trace-value">—</div>
    <h4>Fórmula</h4>
    <p id="trace-verbal">—</p>
    <h4>Código Python</h4>
    <pre id="trace-python">—</pre>
    <h4>Query SQL ejecutada</h4>
    <pre id="trace-sql">—</pre>
    <h4>Inputs concretos</h4>
    <table class="trace-inputs" id="trace-inputs" style="width:100%"><tbody></tbody></table>
    <h4>Tablas fuente</h4>
    <ul id="trace-sources"></ul>
    <h4>Script</h4>
    <p id="trace-script" style="color:#555;font-family:monospace;font-size:11px">—</p>
  </div>
</div>

<script>
const FUNDS = __DATA_JSON__;
const KPI_META = __KPI_META_JSON__;
const MESES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];

function mesEspanol(p){ if(!p) return ""; const [y,m]=p.split("-"); return MESES[parseInt(m,10)-1]+" "+y; }
function fmtQ(p){
  if(!p) return "";
  const [y,m] = p.split("-");
  const mm = parseInt(m,10);
  const qMap = {3:"1Q",6:"2Q",9:"3Q",12:"4Q"};
  return (qMap[mm] ? qMap[mm]+" "+y : mesEspanol(p));
}
function periodoToYQ(p){
  const [y,m] = p.split("-"); const mm = parseInt(m,10);
  const q = {3:1,6:2,9:3,12:4}[mm] || null;
  return { year: y, q: q, month: mm };
}
// ---- Trazabilidad admin: marcar celdas con metadata para modal ----
function attachTrace(el, kpi, ctx){
  if (!el || !kpi) return;
  el.setAttribute("data-trace", "1");
  el.setAttribute("data-kpi", kpi);
  if (ctx.fondo) el.setAttribute("data-fondo", ctx.fondo);
  if (ctx.periodo) el.setAttribute("data-periodo", ctx.periodo);
  if (ctx.serie) el.setAttribute("data-serie", ctx.serie);
  if (ctx.variante) el.setAttribute("data-variante", ctx.variante);
  if (ctx.raw_value != null) el.setAttribute("data-raw", ctx.raw_value);
}

function renderTraceModal(el){
  const kpi = el.getAttribute("data-kpi");
  const meta = KPI_META[kpi];
  if (!meta) return;
  const fondo = el.getAttribute("data-fondo") || "";
  const periodo = el.getAttribute("data-periodo") || "";
  const serie = el.getAttribute("data-serie") || fondo;
  const variante = el.getAttribute("data-variante") || "";
  const raw = el.getAttribute("data-raw");

  document.getElementById("trace-title").textContent = meta.label || kpi;
  const subParts = [];
  if (fondo) subParts.push("Fondo: " + fondo);
  if (serie && serie !== fondo) subParts.push("Serie: " + serie);
  if (variante) subParts.push("Variante: " + variante);
  if (periodo) subParts.push("Período: " + mesEspanol(periodo));
  document.getElementById("trace-sub").textContent = subParts.join(" · ");

  document.getElementById("trace-value").textContent = el.textContent.trim();
  document.getElementById("trace-verbal").textContent = meta.verbal || "(sin descripción)";
  document.getElementById("trace-python").textContent = meta.python || "—";
  const sqlRaw = meta.sql || "—";
  document.getElementById("trace-sql").textContent = sqlRaw
    .replace(/\{fondo\}/g, fondo)
    .replace(/\{serie\}/g, serie)
    .replace(/\{periodo\}/g, periodo)
    .replace(/\{variante\}/g, variante || "NULL");

  // Inputs concretos
  const inputsTbody = document.querySelector("#trace-inputs tbody");
  const rows = [];
  if (raw !== null && raw !== "") rows.push(["Valor almacenado (raw)", Number(raw).toLocaleString("es-CL",{maximumFractionDigits:6})]);
  if (fondo) rows.push(["fondo_key", fondo]);
  if (serie && serie !== fondo) rows.push(["entidad_key (serie)", serie]);
  if (periodo) rows.push(["periodo", periodo]);
  if (variante) rows.push(["variante", variante]);
  if (meta.raw && fondo) {
    const F = FUNDS[fondo];
    const uf = F ? ufCierre(F, periodo) : null;
    if (uf) rows.push(["UF de cierre usado en conversión", uf.toLocaleString("es-CL",{maximumFractionDigits:2})]);
  }
  inputsTbody.innerHTML = rows.map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");

  const ulSrc = document.getElementById("trace-sources");
  ulSrc.innerHTML = (meta.sources || []).map(s => `<li>${s}</li>`).join("") || "<li>—</li>";
  document.getElementById("trace-script").textContent = meta.script || "—";

  document.getElementById("trace-modal-bg").classList.add("open");
}

function closeTraceModal(){
  document.getElementById("trace-modal-bg").classList.remove("open");
}

function fmtCLP(v){ if(v==null||isNaN(v)) return "—"; return "$"+Math.round(v).toLocaleString("es-CL"); }
function fmtMiles(v){ if(v==null||isNaN(v)) return "—"; return Math.round(v/1000).toLocaleString("es-CL"); }
function fmtPct(v,d=1){ if(v==null||isNaN(v)) return "—"; return (v*100).toFixed(d).replace(".",",")+"%"; }
function fmtNum(v,d=1){ if(v==null||isNaN(v)) return "—"; return Number(v).toFixed(d).replace(".",","); }
function fmtEnteroMiles(v){ if(v==null||isNaN(v)) return "—"; return Math.round(v).toLocaleString("es-CL"); }
function fmtFechaCorta(iso){ if(!iso) return ""; const p=iso.split("-"); return p[2]+"-"+p[1]+"-"+p[0]; }
function fmtFechaLarga(iso){
  if(!iso) return "";
  const [y,m,d] = iso.split("-").map(Number);
  return d+" de "+MESES[m-1].toLowerCase()+" de "+y;
}

// ---- Toggle UF / millones de pesos, independiente por tabla ----
// unitState: { balance: 'uf'|'clp', gastos: 'uf'|'clp', dfn: 'uf'|'clp' }
const unitState = {
  balance: localStorage.getItem("factsheet_unit_balance") || "uf",
  gastos: localStorage.getItem("factsheet_unit_gastos") || "uf",
  dfn: localStorage.getItem("factsheet_unit_dfn") || "uf",
};
function ufCierre(F, periodo){
  if(!periodo || !F.uf) return null;
  const keys = Object.keys(F.uf).sort();
  const lower = keys.filter(k => k <= periodo);
  const k = lower.length ? lower[lower.length-1] : (keys.length ? keys[0] : null);
  return k!=null ? F.uf[k] : null;
}
function unitLabel(tabla){ return unitState[tabla]==="uf" ? "UF" : "millones de pesos"; }
// v en CLP (Balance, Gastos)
function fmtMontoClp(v, periodo, F, tabla){
  if(v==null||isNaN(v)) return "—";
  if(unitState[tabla]==="uf"){
    const uf = ufCierre(F, periodo);
    return uf ? Math.round(v/uf).toLocaleString("es-CL") : "—";
  }
  return (v/1e6).toLocaleString("es-CL",{minimumFractionDigits:1,maximumFractionDigits:1});
}
// v en UF (Deuda Financiera Neta)
function fmtMontoUf(v, periodo, F, tabla){
  if(v==null||isNaN(v)) return "—";
  if(unitState[tabla]==="uf") return Math.round(v).toLocaleString("es-CL");
  const uf = ufCierre(F, periodo);
  return uf ? (v*uf/1e6).toLocaleString("es-CL",{minimumFractionDigits:1,maximumFractionDigits:1}) : "—";
}
function toggleUnit(tabla){
  unitState[tabla] = unitState[tabla]==="uf" ? "clp" : "uf";
  localStorage.setItem("factsheet_unit_"+tabla, unitState[tabla]);
  if (typeof currentFund !== "undefined" && currentFund) render();
}

// ---- Noticias: fechas editables por admin, persistidas en localStorage ----
const NOTICIAS_STORE_KEY = "factsheet_noticias_overrides";
function loadNoticiasOverrides(){
  try { return JSON.parse(localStorage.getItem(NOTICIAS_STORE_KEY) || "{}"); }
  catch(e){ return {}; }
}
function saveNoticiasOverride(fondo, slot, value){
  const store = loadNoticiasOverrides();
  store[fondo] = store[fondo] || {};
  store[fondo][slot] = value;
  localStorage.setItem(NOTICIAS_STORE_KEY, JSON.stringify(store));
}
function renderNoticias(fondo, S, fechaEeffRaw, fechaDivRaw, cmfDefaultISO){
  const el = document.getElementById("txt-noticias");
  if (!S.noticias_template){ el.innerHTML = "—"; return; }
  el.innerHTML = S.noticias_template;
  const overrides = loadNoticiasOverrides()[fondo] || {};
  const AUTO = {
    eeff: fechaEeffRaw ? fmtFechaCorta(fechaEeffRaw) : "—",
    div: fechaDivRaw ? fmtFechaCorta(fechaDivRaw) : "—",
  };
  const isAdmin = document.body.classList.contains("admin");
  // Cláusula de dividendos: oculta siempre que no haya reparto en el trimestre exhibido
  // (es automática, no editable, así que no hay razón para forzarla en modo admin).
  const updateWrap = (slot, textVal) => {
    const wrap = el.querySelector('[data-wrap="'+slot+'"]');
    if (!wrap) return;
    const empty = !textVal || textVal.trim() === "—";
    wrap.style.display = empty ? "none" : "";
  };
  el.querySelectorAll("span.ed, span.auto").forEach(span => {
    const slot = span.dataset.slot;
    if (slot === "eeff" || slot === "div"){
      // Fecha de EEFF y de repartos: se derivan de la data (contable / raw_dividendo), no editable
      span.textContent = AUTO[slot];
      span.contentEditable = "false";
      if (slot === "div") updateWrap("div", AUTO.div);
      return;
    }
    // Fecha de publicación en la CMF: default = cierre del mes subsiguiente al trimestre;
    // el admin la sobrescribe con un selector de fecha nativo si la real difiere.
    const validOverride = overrides.cmf && /^\d{4}-\d{2}-\d{2}$/.test(overrides.cmf);
    const cmfISO = validOverride ? overrides.cmf : cmfDefaultISO;
    span.textContent = cmfISO ? fmtFechaLarga(cmfISO) : "—";
    span.contentEditable = "false";

    const input = document.createElement("input");
    input.type = "date";
    input.className = "date-input-inline";
    input.value = cmfISO || "";
    input.setAttribute("aria-label", "Fecha de publicación en la CMF");
    input.addEventListener("change", () => {
      saveNoticiasOverride(fondo, "cmf", input.value);
      span.textContent = input.value ? fmtFechaLarga(input.value) : "—";
      updateWrap("cmf", span.textContent);
    });
    span.insertAdjacentElement("afterend", input);
    span.style.display = isAdmin ? "none" : "";
    input.style.display = isAdmin ? "inline-block" : "none";
    updateWrap("cmf", span.textContent);
  });
}

let currentFund = "TRI";

function populateSelect(sel, keys, defVal){
  sel.innerHTML="";
  keys.forEach(k=>{
    const o=document.createElement("option"); o.value=k; o.textContent=mesEspanol(k); sel.appendChild(o);
  });
  if (keys.length) sel.value = defVal || keys[keys.length-1];
}

function initPeriodNav(periodos, defVal, suffix, format){
  const sel = document.getElementById("sel-periodo-" + suffix);
  const dispBtn = document.getElementById("period-display-" + suffix);
  const prevBtn = document.getElementById("nav-prev-" + suffix);
  const nextBtn = document.getElementById("nav-next-" + suffix);

  if (!periodos.length) return;

  const initial = defVal && periodos.includes(defVal) ? defVal : periodos[periodos.length - 1];
  sel.innerHTML = "";
  periodos.forEach(k => {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = format === "quarter" ? fmtQ(k) : fmtMonth(k);
    sel.appendChild(o);
  });
  sel.value = initial;
  sel.dataset.periodFmt = format;

  function fmtMonth(p){
    const [y, m] = p.split("-");
    const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
    return meses[parseInt(m, 10) - 1] + " " + y;
  }

  function updateDisplay(){
    const val = sel.value;
    dispBtn.textContent = format === "quarter" ? fmtQ(val) : fmtMonth(val);
    const idx = periodos.indexOf(val);
    prevBtn.disabled = idx <= 0;
    nextBtn.disabled = idx >= periodos.length - 1;
    hidePeriodDropdown();
  }

  window["navPeriod"] = function(delta, suf){
    const s = document.getElementById("sel-periodo-" + suf);
    const opts = Array.from(s.options).map(function(o){ return o.value; });
    const idx = opts.indexOf(s.value);
    const newIdx = Math.max(0, Math.min(opts.length - 1, idx + delta));
    s.value = opts[newIdx];
    s.dispatchEvent(new Event("change"));
  };

  window["togglePeriodDropdown"] = function(suf){
    const dd = document.getElementById("period-dropdown-" + suf);
    if (!dd.style.display || dd.style.display === "none") window["showPeriodDropdown"](suf);
    else window["hidePeriodDropdown"]();
  };

  window["showPeriodDropdown"] = function(suf){
    window["hidePeriodDropdown"]();
    const dd = document.getElementById("period-dropdown-" + suf);
    const dispEl = document.getElementById("period-display-" + suf);
    const s = document.getElementById("sel-periodo-" + suf);
    const fmt = s.dataset.periodFmt || "month";
    const opts = Array.from(s.options).map(function(o){ return o.value; }).reverse();
    dd.innerHTML = "";
    opts.forEach(function(p){
      const item = document.createElement("div");
      item.className = "period-dropdown-item" + (p === s.value ? " active" : "");
      item.textContent = fmt === "quarter" ? fmtQ(p) : mesEspanol(p);
      item.onclick = function(){ s.value = p; s.dispatchEvent(new Event("change")); };
      dd.appendChild(item);
    });
    const rect = dispEl.getBoundingClientRect();
    dd.style.top = (rect.bottom + 5) + "px";
    dd.style.left = Math.max(4, Math.min(rect.left, window.innerWidth - 160)) + "px";
    dd.style.display = "block";
    const act = dd.querySelector(".active");
    if (act) act.scrollIntoView({ block: "nearest" });
  };

  window["hidePeriodDropdown"] = function(){
    document.querySelectorAll(".period-dropdown").forEach(function(dd){ dd.style.display = "none"; });
  };

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".period-nav-group") && !e.target.closest(".period-dropdown")){
      hidePeriodDropdown();
    }
  });

  sel.addEventListener("change", () => {
    updateDisplay();
    render();
  });

  updateDisplay();
}
function prev(map, key, n){
  const keys = Object.keys(map).sort();
  const idx = keys.indexOf(key);
  if (idx<0) return [];
  return keys.slice(Math.max(0,idx-n+1), idx+1);
}
// Periodos que tienen un valor_libro_clp real (no solo KPIs/cuotas asociados al periodo)
function periodosConValorLibro(F){
  return Object.keys(F.contable).filter(p => {
    const series = F.contable[p].series || {};
    return Object.values(series).some(s => s && s.valor_libro_clp != null);
  }).sort();
}
// Últimos n periodos de `keys` que sean <= key (no requiere que key esté en keys)
function lastNAtOrBefore(keys, key, n){
  const upTo = keys.filter(k => k <= key);
  return upTo.slice(Math.max(0, upTo.length - n));
}

function renderRemVar(rows){
  const tbody = document.querySelector("#tbl-remvar tbody");
  let html = "";
  let i = 0;
  while (i < rows.length){
    const [cond, serie, tasa] = rows[i];
    let span = 1;
    while (i + span < rows.length && rows[i + span][0] === cond) span++;
    html += `<tr><td rowspan="${span}">${cond}</td><td>${serie}</td><td>${tasa}</td></tr>`;
    for (let j = 1; j < span; j++){
      const [, serieJ, tasaJ] = rows[i + j];
      html += `<tr><td>${serieJ}</td><td>${tasaJ}</td></tr>`;
    }
    i += span;
  }
  tbody.innerHTML = html;
}

function switchFund(f){
  currentFund = f;
  const F = FUNDS[f];
  const S = F.static;

  document.getElementById("hdr-nombre").textContent = S.nombre;
  document.getElementById("hdr-sub").textContent = S.sub;

  // Fund buttons
  document.querySelectorAll(".fund-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.fund === f);
  });

  // Repopular navegadores de período — contable/bursátil (trimestral) vs operacional (mensual)
  const periodoActualCb = document.getElementById("sel-periodo-cb").value;
  const periodoActualOp = document.getElementById("sel-periodo-op").value;
  const periodosCb = Object.keys(F.contable).filter(p => ["03","06","09","12"].includes(p.slice(-2))).sort();
  const periodosOp = Object.keys(F.fondo_kpi).sort();
  initPeriodNav(periodosCb, periodoActualCb, "cb", "quarter");
  initPeriodNav(periodosOp, periodoActualOp, "op", "month");

  document.getElementById("wrap-vcb").classList.toggle("hidden", !S.has_bursatil);
  document.getElementById("wrap-tickers").classList.toggle("hidden", !S.has_bursatil);
  document.getElementById("wrap-repartos").classList.toggle("hidden", !S.has_bursatil);

  // Static blocks
  document.getElementById("txt-objetivo").textContent = S.objetivo;
  renderRemVar(S.remuneracion_variable);
  document.getElementById("txt-comite").innerHTML = S.comite;
  document.getElementById("txt-contacto").textContent = S.contacto;
  document.getElementById("txt-resumen").textContent = S.resumen;

  const rf = document.getElementById("tbl-remfija");
  rf.innerHTML = S.remuneracion_fija.map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join("");

  const tk = document.getElementById("tbl-tickers");
  tk.innerHTML = S.tickers.map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join("");

  document.getElementById("wrap-activos").classList.toggle("hidden", !S.activos);
  if (S.activos){
    const ac = document.getElementById("tbl-activos-tbody");
    ac.innerHTML = S.activos.map(([inv,sub,part,gla])=>
      `<tr><td>${inv}</td><td>${sub}</td><td>${part}</td><td>${gla}</td></tr>`
    ).join("");
  }

  // Página 2
  document.getElementById("hdr2-nombre").textContent = S.nombre;
  document.getElementById("hdr2-sub").textContent = S.sub;
  const hasPage2 = !!S.page2;
  document.getElementById("page2-pending").classList.toggle("hidden", hasPage2);
  document.getElementById("page2-body").classList.toggle("hidden", !hasPage2);
  if (hasPage2) renderPerfActivosHeader(S.page2);

  // Página 3 — detalle de activos
  document.getElementById("hdr3-nombre").textContent = S.nombre;
  document.getElementById("hdr3-sub").textContent = S.sub;
  const hasPage3 = !!S.page3;
  document.getElementById("page3-pending").classList.toggle("hidden", hasPage3);
  document.getElementById("page3-body").classList.toggle("hidden", !hasPage3);
  if (hasPage3) {
    const p3 = S.page3;
    document.getElementById("page3-titulo").textContent = p3.titulo;
    document.getElementById("tbl-aspectos").innerHTML =
      p3.aspectos.map(([k]) => `<tr><td>${k}</td><td class="placeholder">—</td></tr>`).join("");

    document.getElementById("grid-fotos").innerHTML =
      p3.edificios.map(n => {
        const src = p3.fotos[n];
        const body = src
          ? `<img src="${src}" alt="${n}">`
          : `<div class="foto-placeholder">📷<br>${n}<br>(sin foto)</div>`;
        return `<div><div class="foto-box">${body}</div><div class="foto-caption">${n}</div></div>`;
      }).join("");

    const donutPending = (containerId) => {
      document.getElementById(containerId).innerHTML =
        `<div class="chart-placeholder" style="width:100%">Pendiente de datos</div>`;
    };
    donutPending("donut-gla");
    donutPending("donut-ingresos");

    const occBox = (nombre) => `
      <div class="chart-box">
        <div class="chart-title">${nombre}</div>
        <div class="occ-box">
          <div class="occ-bar"><div class="occ-bar-fill" style="width:0%"></div></div>
          <div class="occ-label placeholder">Ocupación: —</div>
        </div>
      </div>`;
    document.getElementById("grid-status-oficinas").innerHTML =
      p3.status_oficinas.map(([n]) => occBox(n)).join("");
    document.getElementById("grid-status-locales").innerHTML =
      p3.status_locales.map(([n]) => occBox(n)).join("");

    document.getElementById("txt-aspectos-mes").innerHTML =
      p3.aspectos_mes.map(([k]) => `<p><b>${k}:</b> <span class="placeholder">Pendiente.</span></p>`).join("");

    const [pAnt, pAct] = p3.vacancia_periodo;
    document.getElementById("vacancia-periodo-label").textContent = `(${pAnt} → ${pAct})`;
    const vacanciaBox = (ed) => `
      <div class="subtable-box">
        <div class="subtable-title">${ed.nombre}</div>
        <table>
          <thead><tr><th></th><th>${pAnt}</th><th>${pAct}</th><th>Variación</th></tr></thead>
          <tbody>${ed.rows.map(r => `<tr><td>${r}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`).join("")}</tbody>
        </table>
      </div>`;
    document.getElementById("grid-vacancia").innerHTML = p3.vacancia_edificios.map(vacanciaBox).join("");
    document.getElementById("txt-vacancia-fondo").textContent = "—";

    const resumenBox = (ed) => `
      <div class="subtable-box">
        <div class="subtable-title">${ed.nombre}</div>
        <table>
          <thead><tr><th></th><th>m²</th><th>% del total</th></tr></thead>
          <tbody>${ed.rows.map(r => `<tr><td>${r}</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`).join("")}</tbody>
        </table>
      </div>`;
    document.getElementById("grid-resumen-anual").innerHTML = p3.resumen_anual_edificios.map(resumenBox).join("");

    document.getElementById("tbl-tasaciones-tbody").innerHTML =
      p3.tasaciones_edificios.map(n => `<tr><td>${n}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`).join("")
      + `<tr class="row-total"><td>${p3.tasaciones_total_nombre}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`;

    document.getElementById("th-tasacion-prev").textContent = p3.tasaciones_periodo[0];
    document.getElementById("th-tasacion-actual").textContent = p3.tasaciones_periodo[1];
    document.getElementById("tbl-tasaciones-comp-tbody").innerHTML =
      [...p3.tasaciones_edificios, p3.tasaciones_total_nombre]
        .map(n => `<tr><td>${n}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`).join("");
  }

  // Página 4 — notas metodológicas + análisis de mercado (headers solo, datos después de pc/usadoOp)
  document.getElementById("hdr4-nombre").textContent = S.nombre;
  document.getElementById("hdr4-sub").textContent = S.sub;
  const hasPage4 = !!S.page4;
  document.getElementById("page4-pending").classList.toggle("hidden", hasPage4);
  document.getElementById("page4-body").classList.toggle("hidden", !hasPage4);

  // Headers de tablas dependientes de series
  const seriesCols = S.series.map(s=>`<th>Serie ${s.label}</th>`).join("");
  document.getElementById("tbl-vcl-thead").innerHTML = "<th>Valor Cuota</th>"+seriesCols;
  document.getElementById("tbl-vcb-thead").innerHTML = "<th>Valor Cuota</th>"+seriesCols;
  document.getElementById("tbl-rep-thead").innerHTML = "<th>Fecha Pago</th><th>Concepto</th>"+seriesCols;

  // Otros indicadores header (el body se llena en render(), depende del período)
  document.getElementById("tbl-otros-thead").innerHTML =
    "<tr><th></th>"+seriesCols+"</tr>";

  // Rentabilidad header
  const rentHeadCols = S.has_bursatil
    ? S.series.map(s=>`<th colspan="2">Serie ${s.label}</th>`).join("")
    : S.series.map(s=>`<th>Serie ${s.label}</th>`).join("");
  const rentSubHead = S.has_bursatil
    ? "<tr><th></th>" + S.series.map(_=>`<th>Bursátil</th><th>Libro</th>`).join("") + "</tr>"
    : "<tr><th></th>" + S.series.map(_=>`<th>Libro</th>`).join("") + "</tr>";
  document.getElementById("tbl-rent-thead").innerHTML =
    "<tr><th></th>"+rentHeadCols+"</tr>" + rentSubHead;

  render();
}

// Página 2 — "Resumen Performance Activos del Fondo" según S.page2.perf_groups
// / perf_rows. perfData (si no es null) viene de F.perf_data[periodo] —
// tools/db/rent_roll_stats.py vía scripts/build_factsheet.py::_fetch_perf_data,
// una fila {grupo}|||{col} -> {m2_utiles, m2_vacantes, pct_vacancia_m2,
// renta_mensual_uf} más "__grand_total__|||Total" para la columna Total final.
// Renta vacante/gracia/descuento y absorción por columna no están en el
// schema hoy (raw_rent_roll_line no captura esos campos del RR) — quedan en
// placeholder; solo la absorción a nivel fondo (_absorcion_3m/12m) se llena
// en la columna Total final.
const PERF_ROW_METRIC = {
  "m² útiles": "m2_utiles", "m² vacantes": "m2_vacantes",
  "% vacancia (m²)": "pct_vacancia_m2", "Renta mensual (UF)": "renta_mensual_uf",
};
const PERF_ROW_ABSORCION = {
  "Absorción bruta m² 3M": ["_absorcion_3m", "bruta_m2"], "Absorción bruta UF 3M": ["_absorcion_3m", "bruta_uf"],
  "Absorción neta m² 3M": ["_absorcion_3m", "neta_m2"], "Absorción neta UF 3M": ["_absorcion_3m", "neta_uf"],
  "Absorción bruta m² 12M": ["_absorcion_12m", "bruta_m2"], "Absorción bruta UF 12M": ["_absorcion_12m", "bruta_uf"],
  "Absorción neta m² 12M": ["_absorcion_12m", "neta_m2"], "Absorción neta UF 12M": ["_absorcion_12m", "neta_uf"],
};

function fmtPerfCell(v, esPct){
  if (v === null || v === undefined) return "—";
  const s = Number(v).toLocaleString('es-CL', {maximumFractionDigits: 1});
  return esPct ? s + "%" : s;
}

// Donut chart (conic-gradient) — data: [[label, pct], ...], pct suma 100.
const DONUT_COLORS = ["#00B27A", "#C8ECD8", "#7FCDA0", "#E0E0E0"];
function renderDonut(containerId, data){
  let acc = 0;
  const stops = data.map(([, pct], i) => {
    const start = acc; acc += pct;
    return `${DONUT_COLORS[i % DONUT_COLORS.length]} ${start}% ${acc}%`;
  }).join(", ");
  const legend = data.map(([label, pct], i) =>
    `<div class="row"><span class="dot" style="background:${DONUT_COLORS[i % DONUT_COLORS.length]}"></span>${label} ${pct}%</div>`
  ).join("");
  document.getElementById(containerId).innerHTML =
    `<div class="donut" style="background:conic-gradient(${stops})"></div><div class="donut-legend">${legend}</div>`;
}

function renderPerfActivosHeader(p2, perfData){
  const groups = p2.perf_groups;
  const totalCols = groups.reduce((n,g) => n + g.cols.length, 0);
  document.getElementById("tbl-perf-activos-thead1").innerHTML =
    "<th></th>" + groups.map(g => `<th colspan="${g.cols.length}">${g.label}</th>`).join("") + "<th>Total</th>";
  document.getElementById("tbl-perf-activos-thead2").innerHTML =
    "<th></th>" + groups.map(g => g.cols.map(c => `<th>${c}</th>`).join("")).join("") + "<th></th>";

  const tbody = document.getElementById("tbl-perf-activos-tbody");
  tbody.innerHTML = p2.perf_rows.map(row => {
    const metric = PERF_ROW_METRIC[row];
    const esPct = row === "% vacancia (m²)";
    let cells = "";
    if (metric && perfData) {
      groups.forEach(g => {
        g.cols.forEach(col => {
          const d = perfData[`${g.label}|||${col}`];
          cells += `<td>${fmtPerfCell(d ? d[metric] : null, esPct)}</td>`;
        });
      });
      const gt = perfData["__grand_total__|||Total"];
      cells += `<td>${fmtPerfCell(gt ? gt[metric] : null, esPct)}</td>`;
    } else if (PERF_ROW_ABSORCION[row] && perfData) {
      const [bucket, key] = PERF_ROW_ABSORCION[row];
      cells = "<td class=\"placeholder\">—</td>".repeat(totalCols);
      const d = perfData[bucket];
      cells += `<td>${fmtPerfCell(d ? d[key] : null, false)}</td>`;
    } else {
      cells = "<td class=\"placeholder\">—</td>".repeat(totalCols + 1);
    }
    return `<tr><td>${row}</td>${cells}</tr>`;
  }).join("");
}

function render(){
  const F = FUNDS[currentFund];
  const S = F.static;
  // Período contable/bursátil (trimestral)
  const periodoCb = document.getElementById("sel-periodo-cb").value;
  const cKeysR = Object.keys(F.contable).sort();
  const cLower = cKeysR.filter(k => k <= periodoCb);
  const pc = cLower.length ? cLower[cLower.length-1] : (cKeysR[cKeysR.length-1] || periodoCb);
  const bKeysR = Object.keys(F.bursatil).sort();
  const bLower = bKeysR.filter(k => k <= periodoCb);
  const pb = bLower.length ? bLower[bLower.length-1] : (bKeysR[bKeysR.length-1] || periodoCb);
  const c = F.contable[pc] || {series:{}};
  const b = F.bursatil[pb] || {series:{}};
  // Período operacional (mensual)
  const periodoOp = document.getElementById("sel-periodo-op").value;
  const usadoOp = Object.keys(F.fondo_kpi).includes(periodoOp) ? periodoOp : Object.keys(F.fondo_kpi).sort().pop();
  const tOp = F.fondo_kpi[usadoOp] || {};

  document.getElementById("month-bar").textContent = (S.has_bursatil ? mesEspanol(pb) : mesEspanol(pc)).toUpperCase();

  // El Fondo table
  const fechaC = c.fecha || (pc?pc+"-30":"");

  // Repartos: últimos pagos <= fecha bursátil (o contable si no hay bursátil)
  const refPeriodo = S.has_bursatil ? pb : pc;
  const cutoff = refPeriodo + "-31";
  const por = {};
  F.dividendos.forEach(d => {
    if (d.fecha <= cutoff){
      if (!por[d.fecha]) por[d.fecha] = {};
      por[d.fecha][d.nemo] = d.monto_clp;
    }
  });
  const fechasDiv = Object.keys(por).sort();

  // Dividendo para Noticias: solo si cae dentro del trimestre contable que se está mostrando (pc)
  const [pcY, pcM] = pc.split("-").map(Number);
  const qStart = pcY + "-" + String(pcM - 2).padStart(2,"0") + "-01";
  const qEnd = pc + "-31";
  const divsTrimestre = fechasDiv.filter(f => f >= qStart && f <= qEnd);
  const ultimoDiv = divsTrimestre.length ? divsTrimestre[divsTrimestre.length-1] : "";

  // Fecha default de publicación en CMF: cierre del mes subsiguiente (mes +2) al cierre del trimestre
  let cmfNm = pcM + 2, cmfNy = pcY;
  if (cmfNm > 12){ cmfNm -= 12; cmfNy += 1; }
  const cmfLastDay = new Date(cmfNy, cmfNm, 0).getDate();
  const cmfDefaultISO = cmfNy + "-" + String(cmfNm).padStart(2,"0") + "-" + String(cmfLastDay).padStart(2,"0");

  renderNoticias(currentFund, S, fechaC, ultimoDiv, cmfDefaultISO);
  let elfondoHtml = `
    <tr><td>${S.fecha_label}</td><td>${S.fecha_valor}</td></tr>
    <tr><td>Moneda del Fondo</td><td>${S.moneda}</td></tr>
    <tr><td>Duración</td><td>${S.duracion}</td></tr>
  `;
  S.series.forEach(s => {
    const sd = c.series[s.nemo] || {};
    elfondoHtml += `<tr><td>Valor Libro Cuota Serie ${s.label} <span class="small">${fechaC?fmtFechaCorta(fechaC):""}</span></td><td>${fmtCLP(sd.valor_libro_clp)}</td></tr>`;
  });
  let cuotasSum=0, any=false;
  S.series.forEach(s => {
    const v = (c.series[s.nemo]||{}).cuotas;
    if (v!=null){ cuotasSum+=v; any=true; }
  });
  elfondoHtml += `<tr><td>Nº Cuotas Emitidas</td><td>${S.cuotas_emitidas}</td></tr>`;
  elfondoHtml += `<tr><td>Nº Cuotas Suscritas y Pagadas</td><td>${any?fmtEnteroMiles(cuotasSum):"—"}</td></tr>`;
  document.getElementById("tbl-elfondo").innerHTML = elfondoHtml;

  // Valor Cuota Libro - últimas 3 fechas con valor contable real
  const vclKeys = periodosConValorLibro(F).filter(p => ["03","06","09","12"].includes(p.slice(-2)));
  const trims = lastNAtOrBefore(vclKeys, pc, 3);
  const tbodyVcl = document.querySelector("#tbl-vcl tbody");
  tbodyVcl.innerHTML = trims.map(p => {
    const cc = F.contable[p] || {series:{}};
    const f = cc.fecha || (p+"-30");
    return "<tr><td>"+fmtFechaCorta(f)+"</td>" +
      S.series.map(s => "<td>"+fmtCLP((cc.series[s.nemo]||{}).valor_libro_clp)+"</td>").join("") + "</tr>";
  }).join("");

  // Balance
  const bal = F.balance[pc] || {};
  document.getElementById("bal-fecha").textContent = "al " + (pc?mesEspanol(pc):"—") + " (en " + unitLabel("balance") + ")";
  const setBal = (id,k) => {
    const el = document.getElementById(id);
    el.textContent = fmtMontoClp(bal[k], pc, F, "balance");
    attachTrace(el, k, {fondo: currentFund, periodo: pc, raw_value: bal[k]});
  };
  setBal("bal-efectivo","ESF.efectivo");
  setBal("bal-otros-ac","ESF.otros_activos_corrientes");
  setBal("bal-pi","ESF.propiedades_inversion");
  setBal("bal-otros-anc","ESF.otros_activos_no_corrientes");
  setBal("bal-total-a","ESF.total_activo");
  setBal("bal-prestamos","ESF.prestamos");
  setBal("bal-imp-dif","ESF.pasivos_impuestos_diferidos");
  setBal("bal-otros-p","ESF.otros_pasivos");
  setBal("bal-patrimonio","ESF.patrimonio_neto");
  setBal("bal-total-pp","ESF.total_pasivo_patrimonio");

  document.getElementById("gastos-fecha").textContent = "al " + (pc?mesEspanol(pc):"—") + " (en " + unitLabel("gastos") + ")";

  // Gastos del fondo desde EEFF (montos absolutos, en CLP)
  const g = F.gastos[pc] || {};
  const gAdmin = g["ER.comision_admin"];
  const gCustodia = g["ER.honorarios_custodia"] || 0;
  const gComite = g["ER.remun_comite"] || 0;
  const gRecur = (g["ER.honorarios_custodia"]!=null||g["ER.remun_comite"]!=null) ? (gCustodia + gComite) : null;
  const gOtros = g["ER.otros_gastos"];
  const gTotal = g["ER.total_gastos_operacion"];
  const setG = (id, k, v) => {
    const el = document.getElementById(id);
    el.textContent = fmtMontoClp(v, pc, F, "gastos");
    attachTrace(el, k, {fondo: currentFund, periodo: pc, raw_value: v});
  };
  setG("g-admin", "ER.comision_admin", gAdmin);
  setG("g-recur", "ER.recurrentes", gRecur);
  setG("g-otros", "ER.otros_gastos", gOtros);
  setG("g-total", "ER.total_gastos_operacion", gTotal);

  // Rentabilidad
  const filas = [
    ["Rentabilidad desde el inicio (anualizada)", "tir_desde_inicio", 1],
    ["Rentabilidad YTD (anualizada)", "rent_ytd", 1],
    ["Rentabilidad Últimos 12 meses", "tir_u12m", 1],
    ["Dividend Yield", "dy", 1],
    ["Dividend Yield + Amortización", "dy_amort", 1],
  ];
  const tbodyR = document.querySelector("#tbl-rent tbody");
  tbodyR.innerHTML = filas.map(([lab,key,d]) => {
    let html = "<td>"+lab+"</td>";
    S.series.forEach(s => {
      const sc = c.series[s.nemo] || {};
      if (S.has_bursatil){
        const sb = b.series[s.nemo] || {};
        html += `<td data-trace="1" data-kpi="${key}" data-variante="bursatil" data-serie="${s.nemo}" data-periodo="${pb||''}" data-raw="${sb[key]==null?'':sb[key]}">${fmtPct(sb[key],d)}</td>`;
      }
      html += `<td data-trace="1" data-kpi="${key}" data-variante="contable" data-serie="${s.nemo}" data-periodo="${pc||''}" data-raw="${sc[key]==null?'':sc[key]}">${fmtPct(sc[key],d)}</td>`;
    });
    return "<tr>"+html+"</tr>";
  }).join("");

  // Endeudamiento — buscar más cercano <= pc
  const kpis = F.fondo_kpi;
  const keysK = Object.keys(kpis).sort();
  let usado = pc;
  if (!kpis[pc]){
    const lower = keysK.filter(k => k<=pc);
    usado = lower.length? lower[lower.length-1] : (keysK[keysK.length-1]||null);
  }
  const t = kpis[usado] || {};
  const setKpi = (id, kpi, text, raw) => {
    const el = document.getElementById(id);
    el.textContent = text;
    attachTrace(el, kpi, {fondo: currentFund, periodo: usado, raw_value: raw});
  };
  setKpi("fld-leverage", "leverage_financiero",
    t.leverage_financiero!=null ? fmtNum(t.leverage_financiero,2)+" x" : "—", t.leverage_financiero);
  setKpi("fld-ltv", "ltv", fmtPct(t.ltv,1), t.ltv);
  setKpi("fld-tasa", "tasa_promedio", fmtPct(t.tasa_promedio,1), t.tasa_promedio);
  setKpi("fld-duration", "duration_deuda", fmtNum(t.duration_deuda,1), t.duration_deuda);
  setKpi("fld-dfn", "deuda_financiera_neta",
    fmtMontoUf(t.deuda_financiera_neta, usado, F, "dfn"), t.deuda_financiera_neta);
  document.getElementById("fld-dfn-unit").textContent = unitState.dfn==="uf" ? "(UF)" : "(MM$)";
  const pv = t.perfil_venc || {};
  const setPv = (id, variante, val) => {
    const el = document.getElementById(id);
    el.textContent = fmtPct(val,0);
    attachTrace(el, "perfil_vencimiento", {fondo: currentFund, periodo: usado, variante, raw_value: val});
  };
  setPv("fld-pv-03", "0-3", pv["0-3"]);
  setPv("fld-pv-37", "3-7", pv["3-7"]);
  setPv("fld-pv-710", "7-10", pv["7-10"]);
  setPv("fld-pv-10", ">10", pv[">10"]);

  const mesLbl = S.has_bursatil ? mesEspanol(pb) : mesEspanol(pc);

  // Otros indicadores (nivel fondo, UF) — Tasa Arriendo / Cap Rate / Ingresos-NOI U12M
  const nColsOi = S.series.length;
  const otrosTd = (kpi, text, raw) =>
    `<td colspan="${nColsOi}" data-trace="1" data-kpi="${kpi}" data-fondo="${currentFund}" data-periodo="${usadoOp||''}" data-raw="${raw==null?'':raw}">${text}</td>`;
  // Tasa Arriendo / Cap Rate bursátil: si hay dato por serie (TRI), se muestra una
  // columna por serie (cada una valoriza el fondo completo al precio de su propia
  // serie); si no (Apo/PT, KPI a nivel fondo), se mantiene la fila única colapsada.
  const bKeysOp = Object.keys(F.bursatil).sort();
  const bOpLower = bKeysOp.filter(k => k <= usadoOp);
  const pbOp = bOpLower.length ? bOpLower[bOpLower.length-1] : null;
  const bOp = (pbOp && F.bursatil[pbOp]) || {series:{}};
  const perSerieTasa = S.series.map(s => (bOp.series[s.nemo]||{}).tasa_arriendo_ajustada_bursatil);
  const perSerieCap = S.series.map(s => (bOp.series[s.nemo]||{}).cap_rate_implicito_bursatil);
  const hasPerSerie = perSerieTasa.some(v => v != null);
  const serieTd = (kpi, values) => S.series.map((s,i) =>
    `<td data-trace="1" data-kpi="${kpi}" data-fondo="${currentFund}" data-serie="${s.nemo}" data-periodo="${pbOp||''}" data-raw="${values[i]==null?'':values[i]}">${fmtPct(values[i],2)}</td>`
  ).join("");

  const tasaKpi = tOp.tasa_arriendo_ajustada_bursatil != null
    ? "tasa_arriendo_ajustada_bursatil"
    : "tasa_arriendo_ajustada_contable";
  const capRateKpi = tOp.cap_rate_implicito_bursatil != null
    ? "cap_rate_implicito_bursatil"
    : "cap_rate_implicito_contable";
  const tasaValue = tOp[tasaKpi];
  const capRateValue = tOp[capRateKpi];
  const mesOpLbl = mesEspanol(usadoOp);
  const tasaRow = hasPerSerie
    ? `<tr><td>Tasa Arriendo Bursátil</td>${serieTd("tasa_arriendo_ajustada_bursatil", perSerieTasa)}</tr>`
    : `<tr><td>Tasa Arriendo</td>${otrosTd(tasaKpi, fmtPct(tasaValue,2), tasaValue)}</tr>`;
  const capRow = hasPerSerie
    ? `<tr><td>Cap Rate Implícito Bursátil</td>${serieTd("cap_rate_implicito_bursatil", perSerieCap)}</tr>`
    : `<tr><td>Cap Rate</td>${otrosTd(capRateKpi, fmtPct(capRateValue,2), capRateValue)}</tr>`;
  document.getElementById("tbl-otros-tbody").innerHTML = `
    ${tasaRow}
    ${capRow}
    <tr><td>Ingresos U12M</td>${otrosTd("ingresos_u12m", tOp.ingresos_u12m!=null?fmtEnteroMiles(tOp.ingresos_u12m)+" UF":"—", tOp.ingresos_u12m)}</tr>
    <tr><td>Ingresos ${mesOpLbl}</td>${otrosTd("ingresos_mes", tOp.ingresos_mes!=null?fmtEnteroMiles(tOp.ingresos_mes)+" UF":"—", tOp.ingresos_mes)}</tr>
    <tr><td>NOI U12M</td>${otrosTd("noi_u12m", tOp.noi_u12m!=null?fmtEnteroMiles(tOp.noi_u12m)+" UF":"—", tOp.noi_u12m)}</tr>
    <tr><td>NOI ${mesOpLbl}</td>${otrosTd("noi_mes", tOp.noi_mes!=null?fmtEnteroMiles(tOp.noi_mes)+" UF":"—", tOp.noi_mes)}</tr>
  `;

  // Valor Cuota Bursátil
  if (S.has_bursatil){
    const meses = prev(F.bursatil, pb, 3);
    const tbodyVcb = document.querySelector("#tbl-vcb tbody");
    tbodyVcb.innerHTML = meses.map(p => {
      const bb = F.bursatil[p] || {series:{}};
      const f = bb.fecha || (p+"-30");
      return "<tr><td>"+fmtFechaCorta(f)+"</td>" +
        S.series.map(s => "<td>"+fmtCLP((bb.series[s.nemo]||{}).valor_bursatil_clp)+"</td>").join("") + "</tr>";
    }).join("");
  }

  // Repartos: últimos 4 pagos <= fecha bursátil (o contable si no hay bursátil)
  const fechas = fechasDiv.slice(-4);
  const tbodyRep = document.querySelector("#tbl-rep tbody");
  tbodyRep.innerHTML = fechas.map(f => {
    const d = por[f];
    return "<tr><td>"+fmtFechaCorta(f)+"</td><td>Dividendo provisorio</td>" +
      S.series.map(s => "<td>$"+fmtNum(d[s.nemo],1)+"</td>").join("") + "</tr>";
  }).join("");

  // Página 2
  document.getElementById("month-bar2").textContent = (S.has_bursatil ? mesEspanol(pb) : mesEspanol(pc)).toUpperCase();
  if (S.page2) {
    const perfPeriodo = (F.perf_data || {})[usadoOp] ? usadoOp : null;
    document.getElementById("perf-fecha").textContent = perfPeriodo
      ? "(al " + mesEspanol(perfPeriodo) + ")"
      : "(sin rent roll para " + mesEspanol(usadoOp) + ")";
    renderPerfActivosHeader(S.page2, perfPeriodo ? F.perf_data[perfPeriodo] : null);
  }

  // Página 3 / 4 — mismo mes de referencia que página 2 (no tienen datos por período aún)
  const mesRef = (S.has_bursatil ? mesEspanol(pb) : mesEspanol(pc)).toUpperCase();
  document.getElementById("month-bar3").textContent = mesRef;
  document.getElementById("month-bar4").textContent = mesRef;

  // Página 4: rellenar notas con fechas dinámicas (ahora pc y usadoOp están definidas)
  const hasPage4 = !!S.page4;
  if (hasPage4) {
    document.getElementById("lst-notas").innerHTML =
      S.page4.notas.map(n => `<li>${n}</li>`).join("");

    // Helper: calcular el último día del mes para una fecha en formato YYYY-MM
    const lastDayOfMonth = (periodo) => {
      if (!periodo) return "";
      const [y, m] = periodo.split("-");
      const lastDay = new Date(y, m, 0).getDate();
      return `${y}-${m}-${String(lastDay).padStart(2, "0")}`;
    };

    // Rellenar slots de fecha en las notas
    const fechaCbISO = pc ? lastDayOfMonth(pc) : "";
    const fechaOpISO = usadoOp ? lastDayOfMonth(usadoOp) : "";
    const mesOpLabel = usadoOp ? mesEspanol(usadoOp) : "";
    document.querySelectorAll("[data-slot=\"fecha-cb\"]").forEach(el => {
      el.textContent = fmtFechaLarga(fechaCbISO);
    });
    document.querySelectorAll("[data-slot=\"fecha-op\"]").forEach(el => {
      el.textContent = fmtFechaLarga(fechaOpISO);
    });
    document.querySelectorAll("[data-slot=\"mes-op\"]").forEach(el => {
      el.textContent = mesOpLabel;
    });

    document.getElementById("mercado-titulo").textContent =
      `Análisis de Mercado de Oficinas — Submercado ${S.page4.submercado}`;
    function celdaMercado(v, esPct) {
      if (v === null || v === undefined) return '<td class="placeholder">—</td>';
      const texto = esPct
        ? v.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%"
        : v.toLocaleString("es-CL", {maximumFractionDigits: 2});
      return `<td>${texto}</td>`;
    }
    document.getElementById("tbl-mercado-tbody").innerHTML =
      S.page4.mercado_rows.map(r => {
        const cls = r.total ? ' class="row-total"' : '';
        if (r.inventario_m2 === undefined) {
          // sin datos ingestados para este trimestre: placeholders
          return `<tr${cls}><td>${r.comuna}</td><td>${r.clase}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`;
        }
        return `<tr${cls}><td>${r.comuna}</td><td>${r.clase}</td>` +
          celdaMercado(r.inventario_m2, false) +
          celdaMercado(r.absorcion_u12m_m2, false) +
          celdaMercado(r.vacancia_pct, true) +
          celdaMercado(r.renta_uf_m2, false) +
          celdaMercado(r.construccion_m2, false) +
          `</tr>`;
      }).join("");
  }
}

// Init
(function(){
  const btns = document.getElementById("fund-btns");
  Object.keys(FUNDS).forEach(f => {
    const b = document.createElement("button");
    b.className = "fund-btn";
    b.dataset.fund = f;
    b.textContent = f;
    b.addEventListener("click", () => switchFund(f));
    btns.appendChild(b);
  });
  ["sel-periodo-cb", "sel-periodo-op", "sel-periodo"].forEach((id) => {
    const sel = document.getElementById(id);
    if (sel) sel.addEventListener("change", render);
  });
  document.getElementById("btn-admin").addEventListener("click", () => {
    const on = document.body.classList.toggle("admin");
    document.getElementById("btn-admin").classList.toggle("on", on);
    document.getElementById("btn-admin").textContent = on ? "✓ Admin" : "✎ Admin";
    render();
  });
  // Delegación de clicks para trazabilidad (solo activo con body.admin)
  document.body.addEventListener("click", (ev) => {
    if (!document.body.classList.contains("admin")) return;
    const el = ev.target.closest("[data-trace]");
    if (!el) return;
    ev.preventDefault();
    renderTraceModal(el);
  });
  document.getElementById("trace-close").addEventListener("click", closeTraceModal);
  document.getElementById("trace-modal-bg").addEventListener("click", (ev) => {
    if (ev.target.id === "trace-modal-bg") closeTraceModal();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeTraceModal();
  });
  // ?admin=1 activa modo admin al cargar
  if (new URLSearchParams(location.search).get("admin") === "1") {
    document.getElementById("btn-admin").click();
  }
  document.getElementById("btn-unit-balance").addEventListener("click", () => toggleUnit("balance"));
  document.getElementById("btn-unit-gastos").addEventListener("click", () => toggleUnit("gastos"));
  document.getElementById("btn-unit-dfn").addEventListener("click", () => toggleUnit("dfn"));
  switchFund("TRI");
})();
</script>
</div><!-- #main-content -->
</body>
</html>
"""


def main():
    con = sqlite3.connect(str(DB))
    all_data = {k: fetch_fondo(con, k, cfg) for k, cfg in FONDOS_CFG.items()}
    con.close()
    # Serializar KPI_META (excluye entradas puramente raw sin fórmula extra ya cubiertas por _raw_meta)
    meta_out = {}
    for k, v in KPI_META.items():
        if v.get("raw"):
            meta_out[k] = _raw_meta(k)
        else:
            meta_out[k] = v
    html = (
        HTML_TEMPLATE
        .replace("__DATA_JSON__", json.dumps(all_data, ensure_ascii=False))
        .replace("__KPI_META_JSON__", json.dumps(meta_out, ensure_ascii=False))
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"OK -> {OUT}")
    for k, d in all_data.items():
        print(f"  {k}: contable={len(d['contable'])} bursatil={len(d['bursatil'])} balance={len(d['balance'])} kpi={len(d['fondo_kpi'])} divs={len(d['dividendos'])}")


if __name__ == "__main__":
    main()
