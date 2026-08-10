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
CHAT_BUBBLE_JS = ROOT / "web" / "chat_bubble.js"


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
            "tipo_activo": ["Oficinas", "Comercial", "Industrial", "Residencias"],
            "perfil_vencimiento_edificios": ["Oficinas", "Activos Comerciales", "Residencias", "Bodegas"],
            # Orden de gráficos validado contra el FS TRI abril 2026 (PDF de
            # referencia): NOI/RCSD + Ingresos-NOI-Vacancia arriba; tablas
            # anuales por tipo de activo (ingresos/NOI) + donut de rubro al
            # medio (sin donut de tipo de activo, a diferencia de PT); perfil
            # de vencimiento + recaudación abajo. Ver PAGE2_CHART_BOXES / JS.
            "charts_layout": [
                ["noi_rcsd", "ingresos_noi_vacancia"],
                ["tablas_anuales", "rubro"],
                ["perfil_vencimiento", "recaudacion"],
            ],
        },
        # Página 3 — "Análisis de Mercado" (fact sheet TRI abril 2026, PDF de
        # referencia): oficinas / bodegas / centros comerciales. A diferencia de
        # PT/Apo (detalle de activos propios), esta página es un reporte de mercado
        # de terceros (JLL, GPS Property, Colliers, CNC). La tabla de oficinas
        # reutiliza raw_mercado_oficinas (misma fuente que Apo.page4.mercado) — los
        # párrafos se redactan en runtime desde la DB (ver renderPage3Mercado()).
        # Bodegas y centros comerciales NO tienen tabla en la DB todavía: solo
        # estructura (zonas/categorías), valores en placeholder hasta que se
        # ingeste una fuente (GPS Property / CNC respectivamente).
        "page3": {
            "modo": "mercado",
            "titulo": "Análisis de Mercado",
            # Estructura fija de la tabla de oficinas (comuna/clase) para meses en
            # que el trimestre JLL correspondiente aún no fue ingestado — se
            # muestra igual, con celdas en placeholder (mismo criterio que Apo).
            # Nota: sin fila/grupo "Total" (clase agregada A+B) — el fact sheet
            # TRI solo muestra los grupos de clase A y B por separado.
            "mercado_rows": [
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
            # Bodegas: sin fuente en DB todavía (no existe raw_mercado_bodegas) —
            # solo estructura (zonas de la tabla). Cuando se ingeste el informe de
            # GPS Property, F.mercado_bodegas debe traer tabla/evolución/párrafos
            # reales y renderPage3() los consume igual que ya hace con oficinas.
            "bodegas": {
                "zonas": ["Centro", "Nor-Poniente", "Norte", "Poniente", "Sur"],
                "total_nombre": "Gran Santiago",
            },
            "centros_comerciales": {
                "categorias": [
                    "Total Comercio", "Vestuario", "Calzado", "Artefactos Eléctricos",
                    "Línea Hogar", "Muebles", "Supermercados",
                ],
            },
            # Evolución anual vacancia/renta Oficinas Las Condes (Clase A/B):
            # datos en DB (raw_mercado_oficinas_evolucion), no acá. Se leen en
            # fetch_fondo() -> F.oficinas_evolucion. Fuente original: SharePoint
            # RAW/"mercado oficinas DB.xlsx", cargada vía
            # tools/db/ingest_mercado_oficinas_evolucion.py.
        },
        # Página 4 — "Indicadores Activos" (tasación/deuda/LTV consolidado,
        # look-through fondo TRI) + "Centro Comercial Paseo Viña Centro".
        # indicadores_rows: la única cifra estática es "participacion"/"part"
        # (participación del fondo TRI en cada activo — misma convención que
        # cfg["activos"] en otros fondos); todo lo demás (valor tasación,
        # deuda, LTV) se computa en fetch_fondo() desde fact_tasacion +
        # raw_saldo_deuda. Ver _fetch page4_indicadores.
        "page4": {
            "indicadores_rows": [
                {"label": "Bodega Sucden", "participacion": "100%", "part": 1.0,
                 "valor_activos": ["Sucden"], "deuda_activos": ["Sucden"]},
                {"label": "Mall Viña Centro", "participacion": "100%", "part": 1.0,
                 "valor_activos": ["Viña Centro"], "deuda_activos": ["Viña Centro"]},
                {"label": "Torre A", "participacion": "33%", "part": 0.33,
                 "valor_activos": ["Torre A"], "deuda_activos": ["Torre A"]},
                {"label": "Inmobiliaria Boulevard", "participacion": "33%", "part": 0.33,
                 "valor_activos": ["Boulevard"], "deuda_activos": ["Boulevard"]},
                {"label": "Apoquindo 4501", "participacion": "30%", "part": 0.30,
                 "valor_activos": ["Apo4501"], "deuda_activos": ["Apo4501", "Apo4700"],
                 "deuda_shared_key": "apo4501_4700"},
                {"label": "Apoquindo 4700", "participacion": "30%", "part": 0.30,
                 "valor_activos": ["Apo4700"], "deuda_activos": ["Apo4501", "Apo4700"],
                 "deuda_shared_key": "apo4501_4700", "deuda_shared_counted": True},
                {"label": "Residencias", "participacion": "43%", "part": 0.43,
                 "valor_activos": [
                     "Residencia Arturo Medina", "Residencia Candil", "Residencia Colombia",
                     "Residencia Coventry", "Residencia Domingo Calderón", "Residencia Padre Errázuriz",
                 ], "deuda_activos": ["INMOSA"]},
                {"label": "Mall Curicó", "participacion": "80%", "part": 0.80,
                 "valor_activos": ["Mall Curicó"], "deuda_activos": ["Mall Curicó"]},
                {"label": "Apoquindo 3001", "participacion": "100%", "part": 1.0,
                 "valor_activos": ["Apo3001"], "deuda_activos": ["Apo3001"]},
            ],
            "total_nombre": "Fondo Toesca Rentas Inmobiliarias",
            "notas": [
                "*Valor según participación en cada sociedad",
                "**Deuda al cierre del trimestre",
            ],
            # Segunda sección: Viña Centro. Dirección/superficie/arrendatarios
            # son hechos estáticos del activo (mismo criterio que cfg["aspectos"]
            # en la página 3 de PT/Apo). Comentarios mensuales (vacancia,
            # ventas, resultados) y los donuts GLA/Ingresos por arrendatario no
            # tienen fuente en DB todavía — quedan en placeholder "pendiente".
            "vina_centro": {
                "titulo": "Centro Comercial Paseo Viña Centro",
                "descripcion": (
                    "Con fecha 29 de diciembre de 2017 Inmobiliaria VC SpA, sociedad filial del Fondo, "
                    "adquirió el 100% de las acciones de Viña Centro SpA, arrendataria con opción de compra "
                    "del Centro Comercial Paseo Viña Centro (ex Espacio Urbano Viña Centro), ubicado en "
                    "Avenida Valparaíso 1070 en la ciudad de Viña del Mar en la 5ta región, a pasos del "
                    "Rodoviario de Viña, de la Quinta Vergara, y en una zona que durante los últimos años ha "
                    "experimentado un fuerte crecimiento tanto inmobiliario como en infraestructura. El "
                    "centro comercial cuenta con una superficie construida de 62.690m2 distribuidos entre 50 "
                    "locales comerciales. Sus principales arrendatarios son un supermercado Hiper Líder "
                    "(7.500m2) y un Homecenter Sodimac (12.300m2) los cuales representan un 73% de los "
                    "ingresos por arriendo del centro comercial."
                ),
                "aspectos": [
                    ("Ubicación", "Viña del Mar, 5ta Región"),
                    ("Tiendas Ancla", "Hiper Líder / Homecenter"),
                    ("Financiamiento", "Mutuo + Crédito privado"),
                    ("Administración", "Tres A"),
                    ("Superficie Arrendable", None),
                    ("Vacancia (m²)", None),
                ],
            },
        },
        # Página 5 — resúmenes de los subfondos PT y Apoquindo (TRI invierte
        # en cuotas de ambos, ver project_estructura_fondos en memoria). Solo
        # "descripcion"/"aspectos" fijos (nombre, fecha, duración, activo
        # subyacente) son estáticos — hechos históricos, mismo criterio que el
        # resto de cfg["aspectos"] en PT/Apo. Superficie arrendable, vacancia
        # y los donuts GLA/Ingresos se calculan en fetch_fondo() (page5_data)
        # reutilizando get_perf_table/get_ingresos_arrendatario/get_gla_edificios
        # ya wireados para las páginas propias de PT y Apo. Fotos: reusa los
        # mismos assets que ya existen para PT (pt_torre_a.png) y Apo
        # (apo4501fs.png/apo4700fs.png).
        "page5": {
            "pt": {
                "titulo": "Toesca Rentas PT Fondo de Inversión",
                "descripcion": (
                    "Con fecha 23 de noviembre 2017, el fondo adquirió un 33% de las cuotas del Fondo "
                    "Toesca Rentas Inmobiliarias PT Fondo de Inversión. Esa misma fecha el Fondo Toesca "
                    "Rentas Inmobiliarias PT compró el 100% de las acciones de Torre A S.A., sociedad que "
                    "tiene un contrato de arrendamiento a largo plazo con el banco Scotiabank por la "
                    "totalidad de los m2 de oficinas de la Torre A, más una serie de estacionamientos y "
                    "bodegas y, por otro lado, la sociedad filial del Fondo Inmobiliaria Boulevard PT SpA "
                    "adquirió una serie de locales comerciales, estacionamientos y bodegas, ubicados en el "
                    "complejo Parque Titanium."
                ),
                "parrafo_remuneracion": (
                    "Es importante destacar que el monto del aporte realizado para la inversión en las "
                    "cuotas de este fondo no es considerado en la base de cálculo para la remuneración de "
                    "la administradora, sino que solo se paga mensualmente la remuneración cobrada por el "
                    "Fondo Rentas Inmobiliarias PT."
                ),
                "parrafo_mas_info": "Más información en la ficha del Fondo Toesca Rentas Inmobiliarias PT, disponible en www.toesca.com.",
                "aspectos": [
                    ("Nombre", "Toesca Rentas Inmobiliarias PT Fondo de Inversión"),
                    ("Fecha inicio Operaciones", "16 de noviembre de 2017"),
                    ("Duración", "15 años (30 de julio de 2032)"),
                    ("Activo Subyacente", "Torre Scotiabank – Local 100 – Local 500"),
                    ("Superficie Arrendable", None),
                    ("Vacancia", None),
                ],
                # Foto pendiente de reemplazo (usuario indicó que la actual
                # va a cambiar) — dejar sin "foto" hasta que llegue la nueva.
            },
            "apo": {
                "titulo": "Toesca Rentas Inmobiliarias Apoquindo Fondo de Inversión",
                "descripcion": (
                    "Con fecha 2 de enero 2019 el Fondo adquirió un 30% de las cuotas de Toesca Rentas "
                    "Inmobiliarias Apoquindo Fondo de Inversión. Un día más tarde, el día 3 de enero de "
                    "2019, Toesca Rentas Apoquindo realizó su primera y única inversión, la cual se "
                    "realizó por medio de su sociedad filial, Inmobiliaria Apoquindo S.A., la cual "
                    "adquirió el 100% de las acciones y créditos de las sociedades Inmobiliaria Uno 2008 "
                    "SpA e Inmobiliaria SCI Apoquindo SpA, sociedades que eran de propiedad de dos fondos "
                    "administrados por Capital Advisors, y que con fecha 11 de marzo fueron fusionadas con "
                    "Inmobiliaria Apoquindo S.A. y posteriormente disueltas."
                ),
                "parrafo_remuneracion": (
                    "Es importante destacar que el monto del aporte realizado para la inversión en las "
                    "cuotas de este fondo no es considerado en la base de cálculo para la remuneración de "
                    "la administradora, sino que solo se paga mensualmente la remuneración cobrada por el "
                    "Fondo Rentas Inmobiliarias Apoquindo."
                ),
                "parrafo_mas_info": "Más información en la ficha del Fondo Toesca Rentas Inmobiliarias Apoquindo, disponible en www.toesca.com.",
                "aspectos": [
                    ("Nombre", "Toesca Rentas Inmobiliarias Apoquindo Fondo de Inversión"),
                    ("Fecha inicio Operaciones", "2 de enero de 2019"),
                    ("Duración", "10 años (16 de noviembre de 2028)"),
                    ("Activo Subyacente", "Edificio Apoquindo 4501 / Edificio Apoquindo 4700"),
                    ("Superficie Arrendable", None),
                    ("Vacancia", None),
                ],
                "foto_4501": _data_uri("apo4501fs.png"),
                "foto_4700": _data_uri("apo4700fs.png"),
            },
        },
        # Página 6 — INMOSSA (residencias adulto mayor) + Mall Curicó.
        # INMOSSA: contrato triple-net con ACALIS sin rent roll unitario en
        # DB (arriendo a un solo operador) — descripción/tabla de
        # residencias/aspectos son hechos fijos del activo (fechas de
        # apertura, camas, términos contractuales), igual criterio que el
        # resto de cfg["aspectos"] en TRI/PT/Apo. Ocupación histórica y mapa
        # quedan en placeholder — sin fuente en la DB. Mall Curicó SÍ tiene
        # rent roll en DB (activo_key "Mall Curicó") — superficie/vacancia y
        # los donuts GLA/Ingresos se calculan en fetch_fondo() (page6_data).
        "page6": {
            "inmossa": {
                "titulo": "Inmobiliaria e Inversiones Senior Assist Chile S.A.",
                "descripcion": (
                    "Inmobiliaria e Inversiones Senior Assist Chile S.A. (“INMOSSA”) es una inmobiliaria "
                    "cuyo objetivo es el desarrollo de edificios residenciales para el adulto mayor, los "
                    "cuales son arrendados con contratos de largo plazo a ACALIS (ex Senior Assist "
                    "International). INMOSSA busca desarrollar residencias para el adulto mayor, que "
                    "ofrezcan una alternativa real para la creciente población de este segmento en Chile."
                ),
                "residencias": [
                    ("Medina", "abr-13", 101),
                    ("Del Canal", "dic-15", 121),
                    ("Coventry", "sept-16", 128),
                    ("Padre Errázuriz", "sept-16", 107),
                    ("Colombia", "dic-16", 106),
                    ("Domingo Calderón", "abr-23", 146),
                ],
                "residencias_subtotal": 709,
                "aspectos": [
                    ("Arrendatario", "Acalis (ex Senior Assist International)"),
                    ("Duración Contratos", "17,1 años"),
                    ("Salida Anticipada", "No"),
                    ("Tipo de Contrato", "Doble net (operador paga contribuciones y 50% sobretasa)"),
                    ("Garantía", "12 rentas / Prenda de acciones"),
                    ("Financiamiento", "Leasing a un LTV aprox. de 48,7%"),
                    ("Superficie Arrendable", "24.456 m²"),
                ],
            },
            "curico": {
                "titulo": "Centro Comercial Paseo Curicó",
                "descripcion": (
                    "Con fecha 31 de diciembre 2019 el Fondo adquirió el 80% de las acciones de Power "
                    "Center Curicó SpA, arrendataria con opción de compra de un centro comercial ubicado "
                    "en la ciudad de Curicó, séptima región. El centro comercial cuenta con una "
                    "superficie arrendable de 10.763 m2 distribuidos en 43 locales comerciales. Su "
                    "principal arrendatario es un supermercado Tottus, el cual representa un 28% de los "
                    "ingresos por arriendo del centro comercial."
                ),
                "aspectos": [
                    ("Ubicación", "Curicó, 7ª Región"),
                    ("Tiendas Ancla", "Tottus / Smartfit"),
                    ("Financiamiento", "Leasing a un LTV aprox. de 58%"),
                    ("Administración", "Tres A"),
                    ("Superficie Arrendable", None),
                    ("Vacancia (m²)", None),
                ],
            },
        },
        # Página 7 — Edificio Apoquindo 3001 + Bodegas Sucden Chile. Ambos
        # activos SÍ tienen rent roll en DB (activo_key "Apo3001" / "Sucden")
        # — donuts GLA/Ingresos y superficie/vacancia se calculan en
        # fetch_fondo() (page7_data), igual mecanismo que Mall Curicó en
        # página 6. Descripción/aspectos fijos (ubicación, contrato,
        # financiamiento) son hechos estáticos, mismo criterio que el resto
        # del factsheet. Comentarios/renta mensuales quedan en placeholder —
        # sin fuente en la DB.
        "page7": {
            "apo3001": {
                "titulo": "Edificio Apoquindo 3001",
                "descripcion_p1": (
                    "Con fecha 30 de diciembre 2019 Inmobiliaria Chañarcillo, sociedad filial del Fondo, "
                    "adquirió el 68,5% del edificio de oficinas Apoquindo 3001, ubicado en la comuna de "
                    "Las Condes."
                ),
                "descripcion_p2": (
                    "La superficie adquirida corresponde a 3.728 m2 de oficinas, 702 m2 de locales "
                    "comerciales, 64 m2 de bodegas y 71 estacionamientos."
                ),
                "aspectos": [
                    ("Ubicación", "Las Condes, RM"),
                    ("Principal Arrendatario", "Notaría"),
                    ("Financiamiento", "Mutuo Hipotecario a un LTV aprox. de 72%"),
                    ("Administración", "Jones Lang Lasalle (JLL)"),
                    ("Superficie Arrendable", None),
                    ("Vacancia (m²)", None),
                ],
            },
            "sucden": {
                "titulo": "Bodegas Sucden Chile",
                "descripcion_p1": (
                    "Con fecha 15 de diciembre 2017 el Fondo adquirió el 100% de los derechos sociales de "
                    "Inmobiliaria Chañarcillo Limitada (ex Arauco Logística), arrendataria con opción de "
                    "compra de un centro logístico ubicado en Calle Chañarcillo 600 en la comuna de Maipú."
                ),
                "descripcion_p2": (
                    "El inmueble se emplaza en un terreno de 34.729 m2 y cuenta con una superficie "
                    "construida de 14.500 m2. Actualmente el 100% de este centro logístico se encuentra "
                    "arrendado a largo plazo a Sucden Chile S.A., filial de SUCDEN, empresa francesa de "
                    "trading y distribución de azúcar con presencia en Chile desde el año 1982, en aquel "
                    "entonces bajo el nombre Amerop Chile (American Operation Chile), y cuyos principales "
                    "clientes son Embotelladora Andina y Nestlé."
                ),
                "aspectos": [
                    ("Ubicación", "Maipú, Región Metropolitana"),
                    ("Arrendatario", "Sucden Chile S.A."),
                    ("Duración Contrato", "12 años"),
                    ("Salida Anticipada", "No"),
                    ("Tipo de Contrato", "Gastos Comunes y Seguros de cargo del arrendatario"),
                    ("Financiamiento", "Leasing a un LTV aprox. 51%"),
                    ("Superficie Arrendable", None),
                ],
            },
        },
        # Página 8 (última) — Notas metodológicas (i)-(x). Reutiliza el mismo
        # boilerplate _notas_template() que ya usan PT/Apo en su página 4 (con
        # los data-slot fecha-cb/fecha-op/mes-op que ya rellena render() para
        # cualquier página) — TRI necesitaba su página 4 para "Indicadores
        # Activos" con notas propias cortas, así que las 10 notas de método
        # completas van acá en su propia página.
        "page8": {
            "notas": _notas_template(True),
            "nota_final": (
                "*Tanto el NOI como los Ingresos por Arriendo incorporan los descuentos negociados "
                "que no serán recuperados en el futuro."
            ),
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
            "tipo_activo": ["Oficinas", "Locales Comerciales", "Estacionamientos", "Bodegas"],
            "perfil_vencimiento_edificios": ["Torre A S.A.", "Inmob. Boulevard PT SpA"],
        },
        # Página 3 — "Torre A S.A. / Inmobiliaria Boulevard PT SpA" (fact sheet PT
        # julio 2025, PDF de referencia). A diferencia de Apo, PT NO desglosa por
        # edificio en esta página: los donuts GLA/Ingresos son por ARRENDATARIO, y
        # hay un gráfico de "Resultados Parking" que Apo no tiene. Por eso usa
        # "arrendatarios" (modo tenant) en vez de "edificios" (modo Apo) — ver
        # renderPage3() en el JS, que ramifica el layout según cuál de las dos
        # claves esté presente. Ninguna fuente en DB para rent roll por arrendatario
        # ni para parking todavía → placeholders; solo tasaciones tiene datos reales
        # en fact_tasacion (activo_key Torre A / Boulevard) pendiente de wire.
        "page3": {
            "titulo": "Torre A S.A. / Inmobiliaria Boulevard PT SpA",
            # Activa los donuts "GLA (m²)" / "Ingresos (UF/mes)" por
            # arrendatario en la página 3 (layout "tenant"). Sin lista curada
            # de nombres: top-N dinámico por mes + "Otros" (ver
            # tools/db/rent_roll_stats.py::_top_n_arrendatario) — así no queda
            # pegado a los arrendatarios vigentes en un mes puntual.
            "donut_arrendatario": True,
            "aspectos": [
                ("Dirección", "Av. Costanera Sur 2710, Las Condes"),
                ("Superficie Arrendable", None),
                ("Principal Arrendatario", "Banco Scotiabank"),
                ("Financiamiento", "Crédito Sindicado"),
                ("Administración", "Jones Lang Lasalle (JLL)"),
                ("Vacancia (m²)", None),
            ],
            "fotos_list": [
                {"caption": "Parque Titanium", "src": _data_uri("pt_torre_a_complejo.png")},
                {"caption": "Torre A - Parque Titanium", "src": _data_uri("pt_torre_a.png")},
                {"caption": "Inmobiliaria Boulevard - Parque Titanium", "src": _data_uri("pt_boulevard.png")},
            ],
            "aspectos_mes": [
                ("Vacancia del Fondo", None),
                ("Parking", None),
                ("Resultados", None),
                ("Otros Locales", None),
            ],
            "parking": True,
            "tasaciones_edificios": ["Torre A", "Inmobiliaria Boulevard"],
            "tasaciones_activo_map": {"Torre A": "Torre A", "Inmobiliaria Boulevard": "Boulevard"},
            "tasaciones_deuda_por_activo": True,
            "tasaciones_total_nombre": "Fondo Rentas PT",
            "tasaciones_periodo": ("Tasación año anterior", "Tasación año actual"),
        },
        # Página 4 — "Plano Local 100" + Notas metodológicas. A diferencia de Apo,
        # PT no tiene análisis de mercado de oficinas en esta página del PDF de
        # referencia: es plano de planta (Piso -1 / Piso -2) + boilerplate de notas.
        "page4": {
            "notas": _notas_template(has_bursatil=True),
            # Overlay de estado (ocupado/vacante) sobre la imagen real del
            # plano de arquitectura del Local 100 — a diferencia de los
            # gráficos "Status Actual" de Apo (treemap/silueta abstracta),
            # acá el fondo ES la foto del plano y las formas van calcadas
            # encima con un <svg viewBox="0 0 viewbox_w viewbox_h"> (ver
            # renderPlanoPT): la imagen se estira a llenar ese viewBox y los
            # rect/polygon usan las coordenadas del plano ORIGINAL
            # (viewbox_w × viewbox_h) tal cual las midió el usuario sobre esa
            # imagen — así no hay que reescalar a mano si se reemplaza el
            # archivo por una versión de otra resolución (basta con que la
            # composición/encuadre sea la misma). "edificio" = clave activo2
            # cruda del rent roll ("Inmob. CdC", ver
            # tools/db/rent_roll_stats.py::_snapshot), no el label amigable
            # "Inmob. Boulevard PT SpA".
            "plano": {
                "titulo": "Plano Local 100",
                "edificio": "Inmob. CdC",
                "pisos": [
                    {
                        "nombre": "Piso -1",
                        "imagen": _data_uri("pt_plano_piso1.png"),
                        # viewBox en el sistema ORIGINAL (557×395) en el que
                        # el usuario midió estas coordenadas pixel a pixel —
                        # el SVG escala la imagen completa (más grande en
                        # disco) de forma uniforme para llenar ese viewBox,
                        # así que los puntos se usan tal cual, sin
                        # recalcular por la resolución real del archivo.
                        "viewbox_w": 557, "viewbox_h": 395,
                        "locales": [
                            # Coordenadas trazadas a mano por el usuario con
                            # el editor visual interactivo (vértices
                            # arrastrados sobre el plano real).
                            # label_at: el centro del bbox cae fuera del
                            # relleno (formas cóncavas) — punto de anclaje
                            # elegido a mano dentro de la masa ancha inferior.
                            {"unidad": "100-1", "label_at": [495, 305],
                             "poligono": [[437.9, 90.6], [435, 362], [551, 368], [552, 240], [473, 239], [474, 128]]},
                            {"unidad": "100-2", "label_at": [500, 86], "label_box": [26, 58], "orientation": "v",
                             "poligono": [[486.6, 54.4], [532.9, 60.6], [516.6, 80], [551.6, 111.9], [552.3, 152.5], [514.8, 151.3], [514.8, 116.3], [486.6, 116.9]]},
                        ],
                    },
                    {
                        "nombre": "Piso -2",
                        "imagen": _data_uri("pt_plano_piso2.png"),
                        # Mismo criterio que Piso -1: viewbox = resolución
                        # real de la imagen limpia, coordenadas escaladas
                        # 1:1 desde el sistema original (575×410) por el
                        # factor verificado 1485/575≈2.583, 1059/410≈2.583.
                        "viewbox_w": 1485, "viewbox_h": 1059,
                        "locales": [
                            # Bloque principal con un retranqueo en la
                            # esquina superior derecha (desde el borde
                            # superior de Relevé hasta la base, sin volver a
                            # ancho completo) para dejarle su muesca exacta a
                            # 100-7 (Relevé) — antes se montaban.
                            {"unidad": "100-9",
                             "poligono": [[194, 137], [749, 137], [749, 199], [671, 199], [671, 468], [194, 468]]},
                            {"unidad": "100-10", "x": 191, "y": 468, "w": 682, "h": 336},
                            {"unidad": "100-7", "x": 671, "y": 199, "w": 114, "h": 204},
                            {"unidad": "100-5", "x": 783, "y": 176, "w": 452, "h": 227},
                            {"unidad": "100-4", "x": 1232, "y": 178, "w": 106, "h": 225},
                            {"unidad": "100-8", "x": 873, "y": 439, "w": 96, "h": 168},
                            {"unidad": "100-6", "x": 999, "y": 439, "w": 142, "h": 168},
                            {"unidad": "100-3", "x": 1191, "y": 437, "w": 186, "h": 160},
                            # Trazado a mano por el usuario con el editor
                            # visual (modo curva/spline) sobre el plano real.
                            {"unidad": "100-11",
                             "poligono": [[190.1, 803.5], [1382, 801], [1379.2, 995], [1216, 995.3], [1050.1, 989.4],
                                          [887.8, 976.5], [712.5, 954.1], [563.1, 927.1], [391.3, 878.8], [311.3, 854.1],
                                          [240.7, 827.1], [218.4, 818.8]]},
                        ],
                    },
                ],
            },
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
            "tipo_activo": ["Oficinas", "Locales Comerciales", "Estacionamientos", "Bodegas"],
            "perfil_vencimiento_edificios": ["Apoquindo 4501", "Apoquindo 4700"],
        },
        # Página 3 — "Detalle de Activos" (fact sheet Apo octubre 2025).
        # Solo ESTRUCTURA (secciones, orden, filas/columnas de cada tabla, edificios) — sin
        # datos reales todavía. A la espera de confirmar el orden exacto contra el PDF de
        # referencia (que quedó fuera de contexto) antes de rellenar valores.
        "page3": {
            "titulo": "Apoquindo 4501 / Apoquindo 4700",
            "edificios": ["Apoquindo 4501", "Apoquindo 4700"],
            "ingresos_activo_map": {"Apoquindo 4501": "Apo4501", "Apoquindo 4700": "Apo4700"},
            "aspectos": [
                ("Dirección", "Apoquindo 4501/ Apoquindo 4700"),
                ("Superficie Arrendable", None),
                ("Principal Arrendatario", "Coordinador Eléctrico Nacional"),
                ("Financiamiento", None),
                ("Administración", "Jones Lang LaSalle (JLL)"),
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
                {"nombre": "Apoquindo 4700", "rows": ["Locales", "Oficinas", "Edificio"]},
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


def _fetch_oficinas_evolucion(db_path: str, submercado: str = "Las Condes (CBD)") -> dict | None:
    """Lee raw_mercado_oficinas_evolucion (histórico trimestral manual vacancia/
    renta por clase A/B) y arma la estructura {quarters, years, vacancia_a,
    vacancia_b, renta_a, renta_b} que consumen los gráficos de evolución de
    página 3. Complementa con trimestres más nuevos que la ingesta recurrente
    de mercado JLL (raw_mercado_oficinas) ya tenga y el histórico manual
    todavía no cubra — la ingesta JLL guarda vacancia como porcentaje entero
    (5.7 = 5.7%), acá se normaliza a fracción (0.057) para que ambas fuentes
    queden en la misma escala."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT anio, trimestre, clase, vacancia_pct, renta_uf_m2
               FROM raw_mercado_oficinas_evolucion
               WHERE submercado = ? AND superseded_at IS NULL
               ORDER BY anio, trimestre""",
            (submercado,),
        ).fetchall()
        max_periodo = con.execute(
            """SELECT MAX(periodo) FROM raw_mercado_oficinas_evolucion
               WHERE submercado = ? AND superseded_at IS NULL""",
            (submercado,),
        ).fetchone()[0]
        jll_rows = con.execute(
            """SELECT periodo, clase, vacancia_pct, renta_uf_m2
               FROM raw_mercado_oficinas
               WHERE submercado = ? AND clase IN ('A', 'B') AND proveedor = 'JLL'
                 AND superseded_at IS NULL AND (? IS NULL OR periodo > ?)
               ORDER BY periodo""",
            (submercado, max_periodo, max_periodo),
        ).fetchall()
    finally:
        con.close()
    if not rows and not jll_rows:
        return None
    por_periodo: dict[tuple[int, int], dict] = {}
    for anio, trimestre, clase, vacancia_pct, renta_uf_m2 in rows:
        key = (anio, trimestre)
        d = por_periodo.setdefault(key, {})
        if clase == "A":
            d["vacancia_a"], d["renta_a"] = vacancia_pct, renta_uf_m2
        elif clase == "B":
            d["vacancia_b"], d["renta_b"] = vacancia_pct, renta_uf_m2
    for periodo, clase, vacancia_pct, renta_uf_m2 in jll_rows:
        anio, mes = int(periodo[:4]), int(periodo[5:7])
        key = (anio, (mes - 1) // 3 + 1)
        d = por_periodo.setdefault(key, {})
        vacancia_frac = vacancia_pct / 100 if vacancia_pct is not None else None
        if clase == "A":
            d["vacancia_a"], d["renta_a"] = vacancia_frac, renta_uf_m2
        elif clase == "B":
            d["vacancia_b"], d["renta_b"] = vacancia_frac, renta_uf_m2
    periodos = sorted(por_periodo)
    return {
        "quarters": [f"{t}Q" for _, t in periodos],
        "years": sorted({a for a, _ in periodos}),
        # fin de trimestre en formato YYYY-MM, alineado índice a índice con
        # quarters/vacancia_*/renta_* — permite al JS truncar la serie según
        # la fecha operacional seleccionada en los selectores.
        "periodos": [f"{a}-{t * 3:02d}" for a, t in periodos],
        "vacancia_a": [por_periodo[p].get("vacancia_a") for p in periodos],
        "vacancia_b": [por_periodo[p].get("vacancia_b") for p in periodos],
        "renta_a": [por_periodo[p].get("renta_a") for p in periodos],
        "renta_b": [por_periodo[p].get("renta_b") for p in periodos],
    }


_BODEGAS_ZONAS_ORDEN = ["Centro", "Nor-Poniente", "Norte", "Poniente", "Sur"]


def _fetch_bodegas_mercado(db_path: str, periodo: str) -> list[dict] | None:
    """Lee raw_mercado_bodegas para el período dado, ordenado por
    _BODEGAS_ZONAS_ORDEN con el total 'Gran Santiago' al final — mismo orden
    que usa la tabla tbl-bodegas de la página 3 del fact sheet TRI."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT zona, produccion_m2, inventario_final_m2, tasa_vacancia_pct,
                      precio_uf_m2, es_total
               FROM raw_mercado_bodegas
               WHERE periodo = ? AND superseded_at IS NULL""",
            (periodo,),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    por_zona = {r[0]: r for r in rows}
    ordenadas = [por_zona[z] for z in _BODEGAS_ZONAS_ORDEN if z in por_zona]
    if "Gran Santiago" in por_zona:
        ordenadas.append(por_zona["Gran Santiago"])
    return [
        {
            "zona": r[0],
            "produccion_m2": r[1],
            "inventario_final_m2": r[2],
            "tasa_vacancia_pct": r[3],
            "precio_uf_m2": r[4],
            "es_total": bool(r[5]),
        }
        for r in ordenadas
    ]


def _fetch_bodegas_evolucion(db_path: str) -> dict | None:
    """Lee raw_mercado_bodegas_evolucion (histórico semestral, carga única
    desde xlsx) y arma {semestres, uf_m2, vacancia_pct} para
    renderBodegasChart(). vacancia_pct se normaliza a porcentaje entero
    (9.95, no 0.0995) porque el gráfico espera esa escala."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT semestre, uf_m2, vacancia_pct, anio, periodo_num
               FROM raw_mercado_bodegas_evolucion
               WHERE superseded_at IS NULL
               ORDER BY anio, periodo_num"""
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    return {
        "semestres": [r[0] for r in rows],
        "uf_m2": [r[1] for r in rows],
        "vacancia_pct": [round(r[2] * 100, 4) if r[2] is not None else None for r in rows],
        # "YYYY-06"/"YYYY-12" — mismo formato que semesterEndOfM() en JS, para
        # truncar la serie al semestre de la fecha operacional seleccionada.
        "periodos": [f"{r[3]}-{'06' if r[4] == 1 else '12'}" for r in rows],
    }


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
        # fondo_key viene de FONDOS_CFG y ya es la clave canónica ('Apo', no 'APO').
        (fondo_key, *gasto_cuentas),
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

    mercado_por_periodo: dict[str, list[dict]] = {}
    oficinas_evolucion = None
    mercado_bodegas_por_periodo: dict[str, list[dict]] = {}
    bodegas_evolucion = None
    if (cfg.get("page4") or {}).get("submercado") or (cfg.get("page3") or {}).get("modo") == "mercado":
        periodos_disponibles = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT periodo FROM raw_mercado_oficinas "
                "WHERE proveedor='JLL' AND superseded_at IS NULL ORDER BY periodo"
            )
        ]
        for periodo in periodos_disponibles:
            mercado_por_periodo[periodo] = _fetch_mercado_rows(str(DB), periodo)
        oficinas_evolucion = _fetch_oficinas_evolucion(str(DB))

        periodos_bodegas = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT periodo FROM raw_mercado_bodegas WHERE superseded_at IS NULL ORDER BY periodo"
            )
        ]
        for periodo in periodos_bodegas:
            filas = _fetch_bodegas_mercado(str(DB), periodo)
            if filas is not None:
                mercado_bodegas_por_periodo[periodo] = filas
        bodegas_evolucion = _fetch_bodegas_evolucion(str(DB))

    # ---- Página 3: ingresos UF/mes por edificio, para el donut ----
    # Cada fondo define su propio mapeo edificio (label mostrado) -> activo_key
    # (raw_er_activo_line) en page3.ingresos_activo_map; si no lo define, el
    # donut queda en placeholder ("Pendiente de datos").
    ingresos_edificios_por_periodo: dict[str, dict[str, float]] = {}
    ingresos_activo_map = (cfg.get("page3") or {}).get("ingresos_activo_map")
    if ingresos_activo_map:
        activo_key_a_edificio = {v: k for k, v in ingresos_activo_map.items()}
        activo_keys = tuple(ingresos_activo_map.values())
        placeholders_activo = ",".join("?" * len(activo_keys))
        for activo_key, periodo, monto in cur.execute(
            f"SELECT activo_key, periodo, SUM(COALESCE(monto_uf, monto_clp)) FROM raw_er_activo_line "
            f"WHERE seccion='INGRESOS_OPERACION' AND superseded_at IS NULL "
            f"AND activo_key IN ({placeholders_activo}) GROUP BY activo_key, periodo",
            activo_keys,
        ).fetchall():
            edificio = activo_key_a_edificio[activo_key]
            ingresos_edificios_por_periodo.setdefault(periodo, {})[edificio] = monto

    # ---- Página 3: tasaciones por edificio (fact_tasacion, tasador='Promedio') ----
    # Se exporta la serie COMPLETA (todos los años / todos los meses de deuda)
    # en vez de un snapshot fijo: el JS elige en render(), según el período
    # seleccionado por el usuario (usadoOp), el año de tasación y el mes de
    # deuda vigentes a esa fecha ("último dato disponible <= período
    # seleccionado" — así en 2026 sigue mostrando la tasación 2025, la más
    # reciente existente). ingresos_activo_map se reutiliza como fallback
    # cuando el fondo no define tasaciones_activo_map propio (labels
    # coinciden, caso Apo). Por defecto la deuda se combina a nivel fondo
    # (Apo: un solo crédito para ambos edificios); con
    # page3.tasaciones_deuda_por_activo=True además se exporta la deuda por
    # activo_key (PT: Torre A y Boulevard tienen créditos separados).
    tasaciones_data = None
    tasaciones_activo_map = (cfg.get("page3") or {}).get("tasaciones_activo_map") or ingresos_activo_map
    tasaciones_deuda_por_activo = (cfg.get("page3") or {}).get("tasaciones_deuda_por_activo", False)
    if (cfg.get("page3") or {}).get("tasaciones_edificios") and tasaciones_activo_map:
        edificios_out: dict[str, dict] = {}
        for edificio, activo_key in tasaciones_activo_map.items():
            rows = cur.execute(
                "SELECT periodo, fecha, valor_uf, variacion_pct FROM fact_tasacion "
                "WHERE activo_key = ? AND tasador = 'Promedio' ORDER BY periodo",
                (activo_key,),
            ).fetchall()
            if not rows:
                continue
            years = {r[0]: {"fecha": r[1], "valor_uf": r[2], "variacion_pct": r[3]} for r in rows}

            deuda_por_mes_ed = {}
            if tasaciones_deuda_por_activo:
                deuda_por_mes_ed = {
                    r[0]: r[1] for r in cur.execute(
                        "SELECT s.periodo, s.saldo_uf FROM dim_credito c JOIN raw_saldo_deuda s ON s.credito_key = c.credito_key "
                        "WHERE c.fondo_key = ? AND c.activo_key = ? AND c.estado = 'VIGENTE' ORDER BY s.periodo",
                        (fondo_key, activo_key),
                    ).fetchall()
                }
            edificios_out[edificio] = {"years": years, "deuda_por_mes": deuda_por_mes_ed}

        if edificios_out:
            deuda_fondo_por_mes = {
                r[0]: r[1] for r in cur.execute(
                    "SELECT s.periodo, SUM(s.saldo_uf) FROM dim_credito c JOIN raw_saldo_deuda s ON s.credito_key = c.credito_key "
                    "WHERE c.fondo_key = ? AND c.estado = 'VIGENTE' GROUP BY s.periodo ORDER BY s.periodo",
                    (fondo_key,),
                ).fetchall()
            }
            tasaciones_data = {
                "edificios": edificios_out,
                "deuda_por_activo": tasaciones_deuda_por_activo,
                "deuda_fondo_por_mes": deuda_fondo_por_mes,
            }

    # ---- Página 3: "Resultados Parking (UF)" — serie mensual PT ----
    parking_data = None
    if (cfg.get("page3") or {}).get("parking"):
        rows = cur.execute(
            """SELECT r.periodo, r.ingresos_abonados_uf, r.ingresos_variables_uf,
                      r.resultado_neto_uf, o.ocupacion_mensual
                 FROM v_parking_resultado_uf r
                 LEFT JOIN v_parking_ocupacion_mensual o
                        ON o.periodo = r.periodo AND o.activo_key = 'Parking PT'
                ORDER BY r.periodo"""
        ).fetchall()
        if rows:
            parking_data = [
                {
                    "periodo": periodo,
                    "abonados_uf": abonados_uf,
                    "variables_uf": variables_uf,
                    "resultado_uf": resultado_uf,
                    "ocupacion": ocupacion,
                }
                for periodo, abonados_uf, variables_uf, resultado_uf, ocupacion in rows
            ]

    # ---- Página 4 (TRI): "Indicadores Activos" — tabla consolidada de
    # tasación/deuda/LTV por activo, look-through a nivel fondo TRI. 100%
    # calculado desde fact_tasacion (tasador='Promedio') + raw_saldo_deuda vía
    # dim_credito.activo_key — la única cifra estática es la participación del
    # fondo en cada activo (misma convención que cfg["activos"] en otros
    # fondos, ver FONDOS_CFG). Se computa una sola vez al buildear (no sigue
    # el selector de período de la página como sí hace fillTasaciones en
    # página 3) usando el trimestre cerrado más reciente disponible para deuda
    # y el año de tasación más reciente para valor.
    page4_indicadores = None
    indicadores_rows_cfg = (cfg.get("page4") or {}).get("indicadores_rows")
    if indicadores_rows_cfg:
        def _valor_uf(activo_keys):
            total, fecha_max = 0.0, None
            for ak in activo_keys:
                row = cur.execute(
                    "SELECT fecha, valor_uf FROM fact_tasacion WHERE activo_key=? AND tasador='Promedio' "
                    "ORDER BY periodo DESC LIMIT 1",
                    (ak,),
                ).fetchone()
                if not row:
                    return None, None
                fecha, valor = row
                total += valor or 0.0
                if fecha and (fecha_max is None or fecha > fecha_max):
                    fecha_max = fecha
            return total, fecha_max

        def _deuda_uf(activo_keys, periodo):
            placeholders_ak = ",".join("?" * len(activo_keys))
            row = cur.execute(
                f"SELECT SUM(s.saldo_uf) FROM dim_credito c JOIN raw_saldo_deuda s ON s.credito_key = c.credito_key "
                f"WHERE c.activo_key IN ({placeholders_ak}) AND c.estado='VIGENTE' AND s.periodo=?",
                (*activo_keys, periodo),
            ).fetchone()
            return row[0] if row and row[0] is not None else None

        def _target_deuda_periodo():
            # raw_saldo_deuda trae el cronograma completo de amortización
            # (histórico Y proyectado, is_proyeccion no distingue esto de forma
            # confiable acá) — así que el ancla real es el último período
            # efectivamente reportado en EEFF/valor cuota (raw_valor_cuota_contable),
            # llevado al cierre de trimestre <= esa fecha (mismo criterio que
            # "CDG usa EEFF del trimestre anterior" documentado en CLAUDE.md).
            anchor_row = cur.execute(
                f"SELECT MAX(periodo) FROM raw_valor_cuota_contable WHERE nemotecnico IN ({placeholders})",
                series_nemos,
            ).fetchone()
            anchor = anchor_row[0] if anchor_row else None
            if not anchor:
                return None
            y, m = int(anchor[:4]), int(anchor[5:7])
            qm = (m // 3) * 3
            if qm == 0:
                y, qm = y - 1, 12
            return f"{y}-{qm:02d}"

        target_periodo = _target_deuda_periodo()

        rows_out, total_valor, total_deuda = [], 0.0, 0.0
        deuda_cache: dict[tuple, float | None] = {}
        for r in indicadores_rows_cfg:
            valor, fecha = _valor_uf(r["valor_activos"])
            key = tuple(r["deuda_activos"])
            if key not in deuda_cache:
                deuda_cache[key] = _deuda_uf(r["deuda_activos"], target_periodo) if target_periodo else None
            deuda = deuda_cache[key]
            ltv = (deuda / valor) if (deuda is not None and valor) else None
            rows_out.append({
                "label": r["label"], "participacion": r["participacion"], "part": r["part"],
                "valor_uf": valor, "fecha": fecha, "deuda_uf": deuda, "ltv": ltv,
                "deuda_shared_key": r.get("deuda_shared_key"),
            })
            if valor is not None:
                total_valor += valor * r["part"]
            if deuda is not None and not r.get("deuda_shared_counted"):
                total_deuda += deuda * r["part"]

        page4_indicadores = {
            "rows": rows_out,
            "deuda_periodo": target_periodo,
            "total_valor": total_valor,
            "total_deuda": total_deuda,
            "total_ltv": (total_deuda / total_valor) if total_valor else None,
        }

    # ---- Página 5 (TRI): resúmenes de los subfondos PT y Apoquindo ----
    # Reutiliza exactamente las mismas fuentes ya wireadas para las páginas
    # propias de PT/Apo (rent_roll_stats.get_perf_table para
    # superficie/vacancia del fondo completo, get_ingresos_arrendatario/
    # get_m2_arrendatario para los donuts por arrendatario de PT, y
    # raw_er_activo_line + get_gla_edificios para los donuts por edificio de
    # Apo) — nada de esto es hardcode, solo se llaman esas funciones con
    # fondo_key="PT"/"Apo" desde el fetch de TRI en vez de con el fondo_key
    # propio de cada página.
    page5_data = None
    if cfg.get("page5"):
        from tools.db.rent_roll_stats import get_perf_table, _periodos_disponibles

        def _perf_grand_total(activo_key_logico):
            periodos = _periodos_disponibles(activo_key_logico)
            if not periodos:
                return None, None
            tabla = get_perf_table(activo_key_logico, periodos[-1])
            gt = (tabla or {}).get(("__grand_total__", "Total"))
            if not gt:
                return None, None
            return gt.get("m2_utiles"), gt.get("pct_vacancia_m2")

        pt_superficie, pt_vacancia = _perf_grand_total("PT")
        apo_superficie, apo_vacancia = _perf_grand_total("Apoquindo")

        pt_ingresos_por_periodo = _fetch_ingresos_arrendatario("PT")
        pt_gla_por_periodo = _fetch_gla_arrendatario("PT")
        pt_ultimo_periodo = max(pt_ingresos_por_periodo) if pt_ingresos_por_periodo else None
        pt_ingresos = pt_ingresos_por_periodo.get(pt_ultimo_periodo) if pt_ultimo_periodo else None
        pt_gla = pt_gla_por_periodo.get(pt_ultimo_periodo) if pt_ultimo_periodo else None

        apo_gla_edificios = _fetch_gla_apo("Apo")
        apo_ingresos_edificios = None
        apo_map = (FONDOS_CFG.get("Apo", {}).get("page3") or {}).get("ingresos_activo_map")
        if apo_map:
            activo_keys = tuple(apo_map.values())
            placeholders_ak = ",".join("?" * len(activo_keys))
            ultimo_periodo_apo = cur.execute(
                f"SELECT MAX(periodo) FROM raw_er_activo_line WHERE activo_key IN ({placeholders_ak}) "
                f"AND seccion='INGRESOS_OPERACION' AND superseded_at IS NULL",
                activo_keys,
            ).fetchone()[0]
            if ultimo_periodo_apo:
                rows = cur.execute(
                    f"SELECT activo_key, SUM(COALESCE(monto_uf, monto_clp)) FROM raw_er_activo_line "
                    f"WHERE activo_key IN ({placeholders_ak}) AND seccion='INGRESOS_OPERACION' "
                    f"AND periodo=? AND superseded_at IS NULL GROUP BY activo_key",
                    (*activo_keys, ultimo_periodo_apo),
                ).fetchall()
                activo_key_a_edificio = {v: k for k, v in apo_map.items()}
                apo_ingresos_edificios = {activo_key_a_edificio[ak]: monto for ak, monto in rows}

        page5_data = {
            "pt": {
                "superficie_arrendable": pt_superficie, "vacancia_pct": pt_vacancia,
                "ingresos_arrendatario": pt_ingresos, "gla_arrendatario": pt_gla,
            },
            "apo": {
                "superficie_arrendable": apo_superficie, "vacancia_pct": apo_vacancia,
                "gla_edificios": apo_gla_edificios, "ingresos_edificios": apo_ingresos_edificios,
            },
        }

    # ---- Página 6 (TRI): Mall Curicó — superficie/vacancia (raw_rent_roll_line)
    # + donuts GLA/Ingresos por arrendatario (rent_roll_stats, misma fuente que
    # ya usa la página 5 para PT). INMOSSA no tiene rent roll unitario en DB
    # (triple-net a un solo operador) — su contenido es 100% estático (ver
    # cfg["page6"]["inmossa"]).
    page6_data = None
    if cfg.get("page6"):
        from tools.db.rent_roll_stats import get_ingresos_arrendatario, get_m2_arrendatario, _periodos_disponibles

        activo_curico = "Mall Curicó"
        periodos_curico = _periodos_disponibles(activo_curico)
        curico_superficie, curico_vacancia = None, None
        curico_ingresos, curico_gla = None, None
        if periodos_curico:
            ultimo = periodos_curico[-1]
            rows_cur = cur.execute(
                "SELECT arrendatario, m2 FROM raw_rent_roll_line WHERE activo_key=? AND periodo=? "
                "AND superseded_at IS NULL",
                (activo_curico, ultimo),
            ).fetchall()
            tot_m2 = sum(m2 or 0 for _, m2 in rows_cur)
            vac_m2 = sum(m2 or 0 for arr, m2 in rows_cur if arr and "vacante" in arr.lower())
            if tot_m2:
                curico_superficie = tot_m2
                curico_vacancia = vac_m2 / tot_m2 * 100
            curico_ingresos = get_ingresos_arrendatario(activo_curico, ultimo)
            curico_gla = get_m2_arrendatario(activo_curico, ultimo)

        page6_data = {
            "curico": {
                "superficie_arrendable": curico_superficie, "vacancia_pct": curico_vacancia,
                "ingresos_arrendatario": curico_ingresos, "gla_arrendatario": curico_gla,
            },
        }

    # ---- Página 7 (TRI): Apoquindo 3001 + Bodegas Sucden Chile — mismo
    # mecanismo que Mall Curicó en página 6 (raw_rent_roll_line + rent_roll_stats).
    page7_data = None
    if cfg.get("page7"):
        from tools.db.rent_roll_stats import get_ingresos_arrendatario, get_m2_arrendatario, _periodos_disponibles

        def _rent_roll_snapshot(activo_key):
            periodos = _periodos_disponibles(activo_key)
            if not periodos:
                return {"superficie_arrendable": None, "vacancia_pct": None, "ingresos_arrendatario": None, "gla_arrendatario": None}
            ultimo = periodos[-1]
            rows = cur.execute(
                "SELECT arrendatario, m2 FROM raw_rent_roll_line WHERE activo_key=? AND periodo=? "
                "AND superseded_at IS NULL",
                (activo_key, ultimo),
            ).fetchall()
            tot_m2 = sum(m2 or 0 for _, m2 in rows)
            vac_m2 = sum(m2 or 0 for arr, m2 in rows if arr and "vacante" in arr.lower())
            return {
                "superficie_arrendable": tot_m2 if tot_m2 else None,
                "vacancia_pct": (vac_m2 / tot_m2 * 100) if tot_m2 else None,
                "ingresos_arrendatario": get_ingresos_arrendatario(activo_key, ultimo),
                "gla_arrendatario": get_m2_arrendatario(activo_key, ultimo),
            }

        page7_data = {
            "apo3001": _rent_roll_snapshot("Apo3001"),
            "sucden": _rent_roll_snapshot("Sucden"),
        }

    return {
        "static": cfg,
        "contable": dict(sorted(contable.items())),
        "bursatil": dict(sorted(bursatil.items())),
        "fondo_kpi": dict(sorted(fondo_kpi.items())),
        "balance": dict(sorted(balance.items())),
        "gastos": dict(sorted(gastos.items())),
        "uf": uf_por_periodo,
        "dividendos": dividendos,
        "mercado": mercado_por_periodo,
        "oficinas_evolucion": oficinas_evolucion,
        "mercado_bodegas": mercado_bodegas_por_periodo,
        "bodegas_evolucion": bodegas_evolucion,
        "ingresos_edificios": dict(sorted(ingresos_edificios_por_periodo.items())),
        "tasaciones": tasaciones_data,
        "page4_indicadores": page4_indicadores,
        "page5": page5_data,
        "page6": page6_data,
        "page7": page7_data,
        "parking": parking_data,
        "noi_rcsd": _fetch_noi_rcsd(fondo_key),
        "perf_data": _fetch_perf_data(fondo_key),
        "vacancia_apo": _fetch_vacancia_apo(fondo_key),
        "rubro_arrendatario": _fetch_rubro_arrendatario(fondo_key),
        "tipo_activo": _fetch_tipo_activo(fondo_key),
        "perfil_vencimiento": _fetch_perfil_vencimiento(fondo_key),
        "ingresos_arrendatario": _fetch_ingresos_arrendatario(fondo_key),
        "gla_arrendatario": _fetch_gla_arrendatario(fondo_key),
        "gla_edificios": _fetch_gla_apo(fondo_key),
        "status_oficinas": _fetch_status_oficinas_apo(fondo_key),
        "status_locales": _fetch_status_locales_apo(fondo_key),
        "plano_locales": _fetch_plano_pt(fondo_key),
        "ltv_fondo": _fetch_ltv_fondo(fondo_key),
        "vacancia_pt_tipo": _fetch_vacancia_pt_tipo(fondo_key),
        "parking_desempeno": _fetch_parking_desempeno(fondo_key),
        "noi_u12m_yoy": _fetch_noi_u12m_yoy_pt(fondo_key),
        "ingresos_noi_vacancia": _fetch_ingresos_noi_vacancia(fondo_key),
        "tablas_anuales_tri": _fetch_tablas_anuales_tri(fondo_key),
    }


def _fetch_noi_u12m_yoy_pt(fondo_key: str) -> dict:
    """{periodo: pct} — variación % del NOI U12M (12 meses terminados en
    `periodo`) vs. el U12M terminado en el mismo mes del año anterior. Fuente
    para FONDOS_CFG["PT"]["page3"]["aspectos_mes"] fila "Resultados" — ver
    render() -> txt-aspectos-mes-t-resultados. Serie NOI mensual 100% del
    fondo PT: derived_kpi kpi='noi_mensual' formula='raw_er_noi_v1'
    entidad_key='PT' (entidad_tipo queda 'activo' por un mislabeling legacy,
    igual que 'Apoquindo'/'Fondo Apoquindo' — ver docs/matriz-claves-ambiguas-apoquindo.md,
    no confundir con el activo 'Torre A' de dim_activo). None si falta alguno
    de los 24 meses necesarios (evita comparar U12M parciales)."""
    if fondo_key != "PT":
        return {}
    from tools.db.connection import get_conn

    conn = get_conn()
    rows = conn.execute(
        "SELECT periodo, valor FROM derived_kpi WHERE kpi='noi_mensual' AND "
        "formula='raw_er_noi_v1' AND entidad_key='PT' ORDER BY periodo"
    ).fetchall()
    serie = {r["periodo"]: r["valor"] for r in rows}

    def _u12m(hasta: str) -> float | None:
        y, m = int(hasta[:4]), int(hasta[5:7])
        meses = []
        for _ in range(12):
            meses.append(f"{y}-{m:02d}")
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        valores = [serie[p] for p in meses if p in serie]
        return sum(valores) if len(valores) == 12 else None

    out = {}
    for periodo in serie:
        anio, mes = periodo[:4], periodo[5:7]
        actual = _u12m(periodo)
        base = _u12m(f"{int(anio) - 1}-{mes}")
        if actual is not None and base:
            out[periodo] = round((actual / base - 1) * 100, 1)
    return out


_INMOSA_PART_HISTORICA = [("2018-01", 0.3468), ("2018-08", 0.3639), ("2023-01", 0.43)]


def _cuota_tri_look_through(conn, periodos: list[str]) -> dict[str, float]:
    """Cuota de financiamiento TRI (capital+interés, look-through por
    participación efectiva) para períodos SIN dato en la planilla del
    usuario (RAW/Cuotas Leasing TRI.xlsx fila 28) — típicamente el mes en
    curso, antes de que el usuario la actualice. Mismos pesos validados
    2026-08-05 contra el "TOTAL Ponderado" de esa planilla: Mall Curicó al
    80%, Apo3001 y el resto de créditos directos de TRI al 100%,
    Torre A/Boulevard/Apo4501/Apo4700 (créditos de PT/Apo) por
    participación efectiva, TRI_SUCDEN_BICE excluido (duplica
    TRI_CHANARCILLO_LEASING)."""
    part_efectiva = {
        r["activo_key"]: r["participacion_efectiva"]
        for r in conn.execute(
            "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo WHERE fondo_key='TRI'"
        ).fetchall()
    }

    def _peso(activo_key: str, periodo: str, credito_fondo_key: str, credito_key: str) -> float:
        if activo_key == "INMOSA":
            valor = _INMOSA_PART_HISTORICA[0][1]
            for desde, v in _INMOSA_PART_HISTORICA:
                if periodo >= desde:
                    valor = v
            return valor
        if credito_fondo_key != "TRI":
            return part_efectiva.get(activo_key, 1.0)
        if credito_key == "TRI_CURICO_METLIFE":
            return part_efectiva.get(activo_key, 1.0)
        return 1.0

    placeholders = ",".join("?" for _ in periodos)
    rows = conn.execute(
        f"SELECT a.credito_key, a.periodo, a.capital_uf, a.intereses_uf, c.fondo_key, c.activo_key "
        f"FROM raw_amortizacion a JOIN dim_credito c ON c.credito_key = a.credito_key "
        f"WHERE c.fondo_key IN ('TRI','PT','Apo') AND a.credito_key != 'TRI_SUCDEN_BICE' "
        f"AND a.periodo IN ({placeholders})",
        periodos,
    ).fetchall()
    cuota: dict[str, float] = {}
    for r in rows:
        peso = _peso(r["activo_key"], r["periodo"], r["fondo_key"], r["credito_key"])
        total = (r["capital_uf"] or 0.0) + (r["intereses_uf"] or 0.0)
        cuota[r["periodo"]] = cuota.get(r["periodo"], 0.0) + total * peso
    return cuota


def _fetch_noi_rcsd(fondo_key: str) -> list[dict]:
    """Serie mensual [{periodo, noi_uf, cuota_uf, rcsd}] para el chart
    "Evolución NOI y Ratio de Cobertura de Servicio de Deuda".
    noi_uf: derived_kpi entidad_tipo='fondo' kpi='noi_mes' (mismo valor que
    kpi='noi_mensual' formula='raw_er_noi_v1', ver _fetch_noi_u12m_yoy_pt).
    cuota_uf (TRI) — histórico: serie oficial derived_kpi
    entidad_tipo='fondo' entidad_key='TRI' kpi='cuota_financiamiento_uf',
    ingestada directo desde la fila "Cuota Financiamiento (UF)" (fila 28,
    bloque del gráfico de referencia del usuario, filas 24-33) de
    RAW/Cuotas Leasing TRI.xlsx — agregada por el usuario 2026-08-05. Cubre
    2018-01 hasta el último mes que el usuario haya actualizado en la
    planilla (ver scripts/ingest_cuota_tri_oficial.py para recargar).
    cuota_uf (TRI) — períodos posteriores al último dato de esa fila: se
    calculan con el mismo look-through por participación efectiva que se
    usa para PT/Apo (ver más abajo), tomado de raw_amortizacion, hasta que
    el usuario actualice la planilla con esos meses.

    cuota_uf (PT/Apo): capital + interés crudo de raw_amortizacion de los
    créditos del fondo (join dim_credito.fondo_key), sin suavizado — decisión
    del usuario 2026-08-05: se sacó la clasificación bullet/amortizante y el
    reemplazo por mediana (que existía desde 2026-07-30) porque aplanaba la
    cuota real. Solo incluye períodos con ambos datos (NOI y cuota)
    disponibles.

    Look-through TRI (fix 2026-08-05): TRI es el fondo paraguas — la deuda de
    Torre A/Boulevard y Apo4501/Apo4700 está registrada en dim_credito bajo
    fondo_key='PT'/'Apo', no 'TRI'. Filtrar solo fondo_key='TRI' la excluía
    por completo del gráfico (bug real detrás de una cuota que se veía
    artificialmente plana/baja al comparar con la planilla del usuario).
    Se suman ponderadas por participación efectiva de TRI en cada activo
    (v_activo_fondo_efectivo, misma tabla usada para duration/ingresos/NOI
    look-through) — incluyendo INMOSA y Mall Curicó, que estaban bookeados
    directo bajo fondo_key='TRI' pero NO son 100% de TRI (el bug anterior
    los trataba como peso=1.0 solo por estar bajo 'TRI'). INMOSA además tiene
    participación histórica variable (34,68% desde 2018-01 → 36,39% desde
    2018-08 → 43% desde 2023-01, fuente RAW/participaciones tri.xlsx) — el
    resto (PT 33,33%, Apoquindo 30%, Curicó 80%) se mantuvo constante desde
    que cada una arrancó. Validado: PT_TORREA_SECURITY/PT_BOULEVARD_SECURITY/
    APO_APO_EUROAMERICA calzan exacto (100%) contra la planilla manual del
    usuario "RAW/Cuotas Leasing TRI.xlsx" — no es una fuente distinta, es un
    espejo de esta misma tabla.

    Crédito TRI_STRIPMACHALI_LEASING (agregado 2026-08-05, fuente RAW/Cuotas
    Leasing TRI.xlsx fila "Strip Machalí" + RAW/ene-sept 2018 DB.xlsx para
    completar ene-sep 2018): Strip Machalí es un activo_key distinto del
    "Machalí" excluido del portfolio (dim_activo.vigente_hasta='2025-08',
    fondo_key='TRI' directo) — sí corresponde incluirlo en este gráfico
    histórico de deuda mientras estuvo vigente. Cuota constante 555,5485 UF/
    mes desde 2018-01 hasta 2025-09 (último mes con dato real), sin capital
    (leasing interest-only). También se completó TRI_VINA_PRINCIPAL, que en
    raw_amortizacion partía en 2018-10: se agregaron ene-sep 2018 (4592,
    4578, 4596, 3661, 5526, 3577, 3582, 5523, 3579 UF) desde RAW/ene-sept
    2018 DB.xlsx, sin split capital/interés disponible en la fuente (se
    guardó como interés puro, capital_uf=0)."""
    from tools.db.connection import get_conn

    conn = get_conn()
    noi = {
        r["periodo"]: r["valor"]
        for r in conn.execute(
            "SELECT periodo, valor FROM derived_kpi "
            "WHERE entidad_tipo='fondo' AND entidad_key=? AND kpi='noi_mes'",
            (fondo_key,),
        ).fetchall()
    }
    if fondo_key == "TRI":
        cuota = {
            r["periodo"]: r["valor"]
            for r in conn.execute(
                "SELECT periodo, valor FROM derived_kpi "
                "WHERE entidad_tipo='fondo' AND entidad_key='TRI' AND kpi='cuota_financiamiento_uf'"
            ).fetchall()
        }
        rcsd_oficial = {
            r["periodo"]: r["valor"]
            for r in conn.execute(
                "SELECT periodo, valor FROM derived_kpi "
                "WHERE entidad_tipo='fondo' AND entidad_key='TRI' AND kpi='rcsd_oficial'"
            ).fetchall()
        }
        ultimo_periodo_planilla = max(cuota) if cuota else None
        futuros = sorted(p for p in noi if ultimo_periodo_planilla and p > ultimo_periodo_planilla)
        if futuros:
            for p, cu in _cuota_tri_look_through(conn, futuros).items():
                cuota[p] = cu

        periodos = sorted(set(noi) & set(cuota))
        idx = {p: i for i, p in enumerate(periodos)}
        out = []
        for p in periodos:
            n, cu = noi[p], cuota[p]
            rcsd = rcsd_oficial.get(p)
            if rcsd is None:
                # Sin dato oficial (mes posterior a la planilla): misma
                # metodología que "RCSD Media Móvil" del usuario (fila 31) —
                # promedio móvil de 3 meses de NOI dividido por promedio
                # móvil de 3 meses de cuota, no promedio del ratio mes a
                # mes. Verificado contra la planilla: p.ej. mar-2018
                # NOI_MA=21.730 / Cuota_MA=9.808 = 2,2 = RCSD Media Móvil.
                i = idx[p]
                ventana = periodos[max(0, i - 2): i + 1]
                noi_ma = sum(noi[q] for q in ventana) / len(ventana)
                cuota_ma = sum(cuota[q] for q in ventana) / len(ventana)
                rcsd = round(noi_ma / cuota_ma, 3) if cuota_ma else None
            out.append({
                "periodo": p,
                "noi_uf": round(n, 1),
                "cuota_uf": round(cu, 1),
                "rcsd": rcsd,
            })
        return out

    # PT/Apo: sin look-through (fondo_key ya es el dueño directo del crédito).
    rows_amort = conn.execute(
        "SELECT periodo, capital_uf, intereses_uf FROM raw_amortizacion a "
        "JOIN dim_credito c ON c.credito_key = a.credito_key "
        "WHERE c.fondo_key = ?",
        (fondo_key,),
    ).fetchall()
    cuota = {}
    for r in rows_amort:
        total = (r["capital_uf"] or 0.0) + (r["intereses_uf"] or 0.0)
        cuota[r["periodo"]] = cuota.get(r["periodo"], 0.0) + total

    periodos = sorted(set(noi) & set(cuota))
    out = []
    for p in periodos:
        n, cu = noi[p], cuota[p]
        out.append({
            "periodo": p,
            "noi_uf": round(n, 1),
            "cuota_uf": round(cu, 1),
            "rcsd": round(n / cu, 3) if cu else None,
        })
    return out


def _fetch_parking_desempeno(fondo_key: str) -> dict:
    """{periodo: {"resultado_pct": float|None, "tickets_pct": float|None}} —
    variación acumulada (enero -> periodo) del resultado neto del parking (UF)
    y del total de tickets, vs. el mismo rango acumulado de 2024 (año base
    fijo, igual que la narrativa de referencia del usuario). None si el año
    del período es 2024 o anterior (no hay base de comparación previa) o si
    falta data en alguno de los dos rangos. Fuente para
    FONDOS_CFG["PT"]["page3"]["aspectos_mes"] fila "Parking" — ver render()
    -> txt-aspectos-mes-t-parking."""
    if fondo_key != "PT":
        return {}
    from tools.db.connection import get_conn

    conn = get_conn()
    resultado_rows = conn.execute(
        "SELECT periodo, resultado_neto_uf FROM v_parking_resultado_uf"
    ).fetchall()
    resultado_por_periodo = {r["periodo"]: r["resultado_neto_uf"] for r in resultado_rows}

    ticket_rows = conn.execute(
        "SELECT substr(fecha,1,7) AS periodo, SUM(tickets) AS tickets "
        "FROM raw_parking_ticket_line WHERE superseded_at IS NULL GROUP BY periodo"
    ).fetchall()
    tickets_por_periodo = {r["periodo"]: r["tickets"] for r in ticket_rows}

    def _acumulado(data: dict, anio: int, hasta_mes: int) -> float | None:
        meses = [f"{anio}-{m:02d}" for m in range(1, hasta_mes + 1)]
        valores = [data[m] for m in meses if m in data]
        if len(valores) != len(meses):
            return None
        return sum(valores)

    out = {}
    for periodo in sorted(set(resultado_por_periodo) | set(tickets_por_periodo)):
        anio, mes = (int(x) for x in periodo.split("-"))
        if anio <= 2024:
            continue
        res_actual = _acumulado(resultado_por_periodo, anio, mes)
        res_base = _acumulado(resultado_por_periodo, 2024, mes)
        tix_actual = _acumulado(tickets_por_periodo, anio, mes)
        tix_base = _acumulado(tickets_por_periodo, 2024, mes)
        resultado_pct = (
            round((res_actual / res_base - 1) * 100, 1)
            if res_actual is not None and res_base else None
        )
        tickets_pct = (
            round((tix_actual / tix_base - 1) * 100, 1)
            if tix_actual is not None and tix_base else None
        )
        if resultado_pct is None and tickets_pct is None:
            continue
        out[periodo] = {"resultado_pct": resultado_pct, "tickets_pct": tickets_pct}
    return out


def _fetch_vacancia_pt_tipo(fondo_key: str) -> dict:
    """{periodo: {"Oficinas": {...}, "Locales Comerciales": {...}}} — vacancia
    del fondo desglosada por tipo de activo, mes actual vs mes anterior. Fuente
    para la narrativa "Vacancia del Fondo" de FONDOS_CFG["PT"]["page3"]
    ["aspectos_mes"] (texto se compone en JS, ver render() -> txt-aspectos-mes-t
    -vacancia-del-fondo). Ver tools/db/rent_roll_stats.py::get_vacancia_fondo_por_tipo."""
    if fondo_key != "PT":
        return {}
    from tools.db.rent_roll_stats import get_vacancia_fondo_por_tipo, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles("PT"):
        tabla = get_vacancia_fondo_por_tipo("PT", periodo)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


_VACANCIA_TIPO_VIEW = {
    "Apo": "v_vacancia_apoquindo_consolidado_tipo",
    "PT": "v_vacancia_pt_consolidado_tipo",
}

# TRI: vacancia consolidada de fondo (una sola línea, no por tipo de activo —
# ver wiki/fondos/tri-consolidacion-ingresos-noi-vacancia.md). Cada activo usa
# su propio universo de tipo_unidad (None = sin filtro, usa v_vacancia_activo
# que ya excluye Estacionamiento por defecto). Excepción Apo3001: numerador
# ponderado a 1.0 (TRI es dueño 100% de la sociedad Chañarcillo), denominador
# (GLA) ponderado normal (0.685) — validado por el usuario 2026-08-03.
_TRI_VACANCIA_TIPOS = {
    "Apo3001": ("Bodegas", "Oficinas"),
    "Apo4501": ("Locales Comerciales", "Oficinas"),
    "Apo4700": ("Locales Comerciales", "Oficinas"),
}
_TRI_VACANCIA_ACTIVOS_SIMPLE = ["Viña Centro", "INMOSA", "Sucden", "Mall Curicó"]
_TRI_VACANCIA_NUM_OVERRIDE = {"Apo3001": 1.0}
# Torre A y Boulevard NO están en raw_vacancia_manual por edificio: el
# histórico manual los trae ya consolidados bajo la clave 'PT_consolidado'
# desde 2017-11 (con desglose Bodegas/Locales/Oficinas y m²GLA real), unido
# con el rent roll real de cada edificio desde jun-2026 en la vista
# v_vacancia_pt_consolidado_tipo (misma vista que usa el chart de PT). Como
# ambos edificios tienen la misma participación efectiva en TRI (1/3), se
# pondera el combinado una sola vez con la participación de "Torre A".
_TRI_PT_PARTICIPACION_KEY = "Torre A"


def _fetch_vacancia_tri_historica(conn) -> dict[str, float]:
    """{periodo: vacancia_pct} para TRI desde derived_kpi
    (kpi='vacancia_pct', formula=fila 37 de 'Vacancia histórica DB.xlsx')
    — ingestado por tools/db/ingest_vacancia_tri_ponderada.py. Cubre
    2017-06 a 2026-06, el cálculo ponderado por participación que el propio
    usuario armó y validó (ver wiki). Es la fuente de verdad para todo ese
    rango: dos intentos previos de reconstruirlo desde cero (carry-forward,
    y luego recombinando v_vacancia_activo/_tipo) daban números que no
    calzaban contra este cálculo en varios meses históricos."""
    return {
        r["periodo"]: r["valor"]
        for r in conn.execute(
            "SELECT periodo, valor FROM derived_kpi WHERE entidad_tipo='fondo' "
            "AND entidad_key='TRI' AND kpi='vacancia_pct'"
        ).fetchall()
    }


def _fetch_vacancia_tri(conn) -> dict[str, float | None]:
    """{periodo: vacancia_pct} consolidada del fondo TRI, fuente única para
    la línea "Vacancia" del chart de página 2 de TRI.

    Híbrido, por decisión del usuario 2026-08-03: para el histórico
    (2017-06 a 2026-06) manda `_fetch_vacancia_tri_historica` — el cálculo
    ponderado que el usuario ya validó en 'Vacancia histórica DB.xlsx'. De
    ahí en adelante (meses sin fila en esa planilla) se calcula en vivo
    desde los rent roll reales (JLL / Tres Asociados) vía
    v_vacancia_activo_tipo / v_vacancia_pt_consolidado_tipo, ponderado por
    participación efectiva — validado: jun-2026 calculado (5.96%) calza casi
    exacto contra el histórico manual del mismo mes (5.945%), lo que
    respalda usar esta misma fórmula para los meses futuros que la planilla
    manual todavía no cubre."""
    historica = _fetch_vacancia_tri_historica(conn)
    part = {
        r["activo_key"]: r["participacion_efectiva"]
        for r in conn.execute(
            "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo WHERE fondo_key='TRI'"
        ).fetchall()
    }

    # (activo, periodo, fuente) -> {"gla": valor, "vac": valor} — sumado
    # sobre los tipo_unidad relevantes de cada activo.
    tipo_acc: dict[tuple[str, str, str], dict[str, float]] = {}
    # (activo, periodo, fuente) -> (m2_gla, m2_vacantes) — fila total
    # (tipo_unidad IS NULL), fallback cuando no hay desglose por tipo.
    total_acc: dict[tuple[str, str, str], tuple[float, float]] = {}

    tipo_activos = list(_TRI_VACANCIA_TIPOS)
    placeholders = ",".join("?" for _ in tipo_activos)
    for r in conn.execute(
        f"SELECT activo_key, periodo, tipo_unidad, m2_gla, m2_vacantes, fuente "
        f"FROM v_vacancia_activo_tipo WHERE activo_key IN ({placeholders})",
        tipo_activos,
    ).fetchall():
        if r["tipo_unidad"] is None:
            total_acc[(r["activo_key"], r["periodo"], r["fuente"])] = (r["m2_gla"], r["m2_vacantes"])
            continue
        if r["tipo_unidad"] not in _TRI_VACANCIA_TIPOS[r["activo_key"]]:
            continue
        key = (r["activo_key"], r["periodo"], r["fuente"])
        d = tipo_acc.setdefault(key, {"gla": 0.0, "vac": 0.0})
        d["gla"] += r["m2_gla"] or 0.0
        d["vac"] += r["m2_vacantes"] or 0.0

    def _pick_tipo(activo: str, periodo: str) -> tuple[float, float] | None:
        for fuente in ("rent_roll", "manual"):
            d = tipo_acc.get((activo, periodo, fuente))
            if d and d["gla"]:
                return d["gla"], d["vac"]
        for fuente in ("rent_roll", "manual"):
            t = total_acc.get((activo, periodo, fuente))
            if t and t[0]:
                return t[0], t[1] or 0.0
        return None

    # PT combinado (Torre A + Boulevard): rent roll por edificio desde
    # jun-2026 + histórico manual consolidado (v_vacancia_pt_consolidado_tipo
    # ya hace ese UNION, misma vista del chart de PT/Apo).
    pt_acc: dict[tuple[str, str], dict[str, float]] = {}
    for r in conn.execute(
        "SELECT periodo, tipo_unidad, m2_gla, m2_vacantes, fuente FROM v_vacancia_pt_consolidado_tipo"
    ).fetchall():
        if r["tipo_unidad"] not in ("Bodegas", "Locales Comerciales", "Oficinas"):
            continue
        key = (r["periodo"], r["fuente"])
        d = pt_acc.setdefault(key, {"gla": 0.0, "vac": 0.0})
        d["gla"] += r["m2_gla"] or 0.0
        d["vac"] += r["m2_vacantes"] or 0.0

    def _pick_pt(periodo: str) -> tuple[float, float] | None:
        for fuente in ("rent_roll", "manual"):
            d = pt_acc.get((periodo, fuente))
            if d and d["gla"]:
                return d["gla"], d["vac"]
        return None

    # Activos simples restantes (Viña, INMOSA, Sucden, Mall Curicó):
    # v_vacancia_activo ya hace el mismo dedup rent_roll>manual.
    simple_acc: dict[tuple[str, str, str], tuple[float, float]] = {}
    placeholders2 = ",".join("?" for _ in _TRI_VACANCIA_ACTIVOS_SIMPLE)
    for r in conn.execute(
        f"SELECT activo_key, periodo, m2_gla, m2_vacantes, fuente FROM v_vacancia_activo "
        f"WHERE activo_key IN ({placeholders2})",
        _TRI_VACANCIA_ACTIVOS_SIMPLE,
    ).fetchall():
        simple_acc[(r["activo_key"], r["periodo"], r["fuente"])] = (r["m2_gla"], r["m2_vacantes"])

    def _pick_simple(activo: str, periodo: str) -> tuple[float, float] | None:
        for fuente in ("rent_roll", "manual"):
            t = simple_acc.get((activo, periodo, fuente))
            if t and t[0]:
                return t[0], t[1] or 0.0
        return None

    periodos = sorted({
        *(p for (_, p, _) in tipo_acc) , *(p for (_, p, _) in total_acc),
        *(p for (p, _) in pt_acc),
        *(p for (_, p, _) in simple_acc),
    })

    out: dict[str, float | None] = {}
    for periodo in periodos:
        num, den = 0.0, 0.0
        for activo in tipo_activos:
            picked = _pick_tipo(activo, periodo)
            if not picked:
                continue
            gla, vac = picked
            w = part.get(activo)
            if w is None:
                continue
            num += max(0.0, vac) * _TRI_VACANCIA_NUM_OVERRIDE.get(activo, w)
            den += gla * w
        picked_pt = _pick_pt(periodo)
        if picked_pt:
            gla, vac = picked_pt
            w = part.get(_TRI_PT_PARTICIPACION_KEY)
            if w is not None:
                num += max(0.0, vac) * w
                den += gla * w
        for activo in _TRI_VACANCIA_ACTIVOS_SIMPLE:
            picked = _pick_simple(activo, periodo)
            if not picked:
                continue
            gla, vac = picked
            w = part.get(activo)
            if w is None:
                continue
            num += max(0.0, vac) * w
            den += gla * w
        out[periodo] = round(100.0 * num / den, 2) if den else None

    # La histórica manda donde exista (2017-06 a 2026-06); el cálculo en
    # vivo desde rent roll solo rellena los meses posteriores.
    out.update(historica)
    return out


def _fetch_ingresos_noi_vacancia(fondo_key: str) -> list[dict]:
    """Serie mensual para el chart "Evolución Ingresos, NOI y Vacancia" de la
    página 2 (eje derecho en %, igual que el fact sheet de referencia).
    Apo/PT: [{periodo, ingresos_uf, noi_uf, vacancia_oficinas_pct,
    vacancia_locales_pct}] — vacancia por tipo desde
    v_vacancia_{apoquindo,pt}_consolidado_tipo (dedup: prioriza fuente
    'rent_roll' sobre 'manual' cuando ambas existen para el mismo período).
    m2_gla se usa por período cuando viene poblado (caso PT); si no (caso
    Apo, donde solo el snapshot rent_roll más reciente lo trae) se cae al
    último m2_gla conocido para ese tipo, asumiendo que la superficie de un
    edificio no cambia mes a mes.
    TRI: [{periodo, ingresos_uf, noi_uf, vacancia_pct}] — una sola línea de
    vacancia consolidada del fondo completo (ver _fetch_vacancia_tri), no
    por tipo de activo (TRI no desglosa oficinas/locales a nivel fondo)."""
    from tools.db.connection import get_conn

    conn = get_conn()

    if fondo_key == "TRI":
        ingresos = {
            r["periodo"]: r["valor"]
            for r in conn.execute(
                "SELECT periodo, valor FROM derived_kpi WHERE entidad_tipo='fondo' "
                "AND entidad_key='TRI' AND kpi='ingresos_mes'"
            ).fetchall()
        }
        noi = {
            r["periodo"]: r["valor"]
            for r in conn.execute(
                "SELECT periodo, valor FROM derived_kpi WHERE entidad_tipo='fondo' "
                "AND entidad_key='TRI' AND kpi='noi_mes'"
            ).fetchall()
        }
        vacancia = _fetch_vacancia_tri(conn)
        periodos = sorted(set(ingresos) & set(noi))
        return [
            {
                "periodo": p,
                "ingresos_uf": round(ingresos[p], 1),
                "noi_uf": round(noi[p], 1),
                "vacancia_pct": vacancia.get(p),
            }
            for p in periodos
        ]

    view = _VACANCIA_TIPO_VIEW.get(fondo_key)
    if not view:
        return []
    ingresos = {
        r["periodo"]: r["valor"]
        for r in conn.execute(
            "SELECT periodo, valor FROM derived_kpi WHERE entidad_tipo='fondo' "
            "AND entidad_key=? AND kpi='ingresos_mes'",
            (fondo_key,),
        ).fetchall()
    }
    noi = {
        r["periodo"]: r["valor"]
        for r in conn.execute(
            "SELECT periodo, valor FROM derived_kpi WHERE entidad_tipo='fondo' "
            "AND entidad_key=? AND kpi='noi_mes'",
            (fondo_key,),
        ).fetchall()
    }
    vac = {}  # periodo -> {tipo: {fuente: m2_vacantes}}
    gla_periodo = {}  # (periodo, tipo) -> m2_gla
    gla_ultimo = {}  # tipo -> último m2_gla conocido (fallback)
    for r in conn.execute(
        f"SELECT periodo, tipo_unidad, m2_vacantes, m2_gla, fuente "
        f"FROM {view} WHERE tipo_unidad IN ('Oficinas', 'Locales Comerciales') "
        f"ORDER BY periodo"
    ).fetchall():
        if r["m2_vacantes"] is not None:
            vac.setdefault(r["periodo"], {}).setdefault(r["tipo_unidad"], {})[r["fuente"]] = r["m2_vacantes"]
        if r["m2_gla"]:
            gla_periodo[(r["periodo"], r["tipo_unidad"])] = r["m2_gla"]
            gla_ultimo[r["tipo_unidad"]] = r["m2_gla"]

    def _vac_pct(periodo: str, tipo: str):
        fuentes = vac.get(periodo, {}).get(tipo)
        gla = gla_periodo.get((periodo, tipo), gla_ultimo.get(tipo))
        if not fuentes or not gla:
            return None
        m2_vac = max(0.0, fuentes.get("rent_roll", fuentes.get("manual")))
        return round(100.0 * m2_vac / gla, 2)

    periodos = sorted(set(ingresos) & set(noi))
    return [
        {
            "periodo": p,
            "ingresos_uf": round(ingresos[p], 1),
            "noi_uf": round(noi[p], 1),
            "vacancia_oficinas_pct": _vac_pct(p, "Oficinas"),
            "vacancia_locales_pct": _vac_pct(p, "Locales Comerciales"),
        }
        for p in periodos
    ]


# Componentes de TRI reutilizados de scripts/consolidate_{ingresos,noi}_tri.py
# (misma metodología, misma tabla de participaciones/vigencias) — cada
# componente ya está persistido en derived_kpi como serie mensual 100%
# (entidad_tipo='activo', kpi='ingresos_mensual'/'noi_mensual'); acá solo se
# pondera por participación efectiva y se agrupa por tipo de activo para las
# tablas "Ingresos/NOI Anual por Tipo de Activo" de la página 2.
_TRI_TIPO_ACTIVO_COMPONENTES = {
    "Apo3001": "Oficinas",
    "Apoquindo": "Oficinas",
    "PT": "Oficinas",
    "Mall Curicó": "Comercial",
    "Viña Centro": "Comercial",
    "Strip Machalí": "Comercial",
    "Sucden": "Industrial",
    "INMOSA": "Residencias",
}
_TRI_COMPONENTES_PART = {
    "Apo3001": "Apo3001",
    "Apoquindo": "Apo4501",
    "INMOSA": "INMOSA",
    "Mall Curicó": "Mall Curicó",
    "PT": "Torre A",
    "Sucden": "Sucden",
    "Viña Centro": "Viña Centro",
    "Strip Machalí": "Strip Machalí",
}
_TRI_PARTICIPACION_OVERRIDE = {"Apo3001": 1.0}
_TRI_VIGENCIA_DESDE_OVERRIDE = {
    "Mall Curicó": "2020-01",
    "Apo3001": "2020-01",
    "Apoquindo": "2019-01",
}


def _fetch_tablas_anuales_tri(fondo_key: str) -> dict:
    """{"ingresos": {tipo: {año|"U12M": valor_uf}}, "noi": {...}, "years": [...]}
    para las tablas "Ingresos/NOI Anual por Tipo de Activo (UF)" de la página 2
    de TRI. Reusa los componentes/participaciones/vigencias ya validados en
    consolidate_ingresos_tri.py / consolidate_noi_tri.py (kpis ingresos_mensual
    / noi_mensual por activo, 100%, entidad_tipo='activo')."""
    if fondo_key != "TRI":
        return {}
    from tools.db.connection import get_conn

    conn = get_conn()
    part = {
        r["activo_key"]: r["participacion_efectiva"]
        for r in conn.execute(
            "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo WHERE fondo_key='TRI'"
        ).fetchall()
    }
    part.update(_TRI_PARTICIPACION_OVERRIDE)
    vigencia = {
        r["activo_key"]: r["vigente_hasta"]
        for r in conn.execute("SELECT activo_key, vigente_hasta FROM dim_activo WHERE fondo_key='TRI'").fetchall()
    }

    def _por_kpi(kpi: str) -> tuple[dict, dict, dict]:
        bucket_year: dict[str, dict[str, float]] = {}
        bucket_mes: dict[str, dict[str, float]] = {}
        meses_por_year: dict[str, set] = {}
        for comp, tipo in _TRI_TIPO_ACTIVO_COMPONENTES.items():
            part_key = _TRI_COMPONENTES_PART[comp]
            p = part.get(part_key)
            if p is None:
                continue
            desde = _TRI_VIGENCIA_DESDE_OVERRIDE.get(comp, "0000-00")
            hasta = vigencia.get(comp)
            for r in conn.execute(
                "SELECT periodo, valor FROM derived_kpi WHERE entidad_tipo='activo' AND entidad_key=? AND kpi=?",
                (comp, kpi),
            ).fetchall():
                periodo, valor = r["periodo"], r["valor"]
                if periodo < desde or (hasta and periodo > hasta):
                    continue
                ponderado = valor * p
                bucket_mes.setdefault(tipo, {})[periodo] = bucket_mes.setdefault(tipo, {}).get(periodo, 0.0) + ponderado
                year = periodo[:4]
                bucket_year.setdefault(tipo, {})[year] = bucket_year.setdefault(tipo, {}).get(year, 0.0) + ponderado
                meses_por_year.setdefault(year, set()).add(periodo)

        # U12M: 12 meses trailing desde el último periodo con dato en ALGÚN tipo.
        todos_periodos = sorted({p for serie in bucket_mes.values() for p in serie})
        # Solo años calendario completos (12 meses de dato) — excluye el año
        # en curso (parcial) y cualquier año de arranque parcial (ej. 2018).
        years_completos = {y for y, meses in meses_por_year.items() if len(meses) == 12}
        out = {
            tipo: {y: round(v) for y, v in years.items() if y in years_completos}
            for tipo, years in bucket_year.items()
        }
        # U12M rolling por cada periodo disponible (no solo el último), para
        # que el selector de mes de la UI pueda elegir el U12M correspondiente
        # al mes visualizado en vez de quedar fijo en el último dato cargado.
        u12m_por_periodo: dict[str, dict[str, float]] = {}
        for periodo in todos_periodos:
            y, m = int(periodo[:4]), int(periodo[5:7])
            periodos_u12m = []
            for _ in range(12):
                periodos_u12m.append(f"{y}-{m:02d}")
                m -= 1
                if m == 0:
                    m, y = 12, y - 1
            for tipo, serie in bucket_mes.items():
                u12m_por_periodo.setdefault(tipo, {})[periodo] = round(sum(serie.get(p, 0.0) for p in periodos_u12m))
        return out, years_completos, u12m_por_periodo

    ingresos, years_ing, u12m_ingresos = _por_kpi("ingresos_mensual")
    noi, years_noi, u12m_noi = _por_kpi("noi_mensual")
    years = sorted(years_ing & years_noi)
    return {
        "ingresos": ingresos,
        "noi": noi,
        "years": years,
        "u12m_ingresos": u12m_ingresos,
        "u12m_noi": u12m_noi,
    }


def _fetch_plano_pt(fondo_key: str) -> dict:
    """{periodo: {unidad: {vacante, arrendatario, renta_uf, m2}}} para el
    overlay del "Plano Local 100" de la página 4 de PT — ver
    FONDOS_CFG["PT"]["page4"]["plano"] y
    tools/db/rent_roll_stats.py::get_plano_locales."""
    if fondo_key != "PT":
        return {}
    from tools.db.rent_roll_stats import get_plano_locales, _periodos_disponibles

    plano = FONDOS_CFG["PT"]["page4"]["plano"]
    edificio = plano["edificio"]
    unidades = [loc["unidad"] for piso in plano["pisos"] for loc in piso["locales"]]
    out = {}
    for periodo in _periodos_disponibles("PT"):
        tabla = get_plano_locales("PT", periodo, edificio, unidades)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


def _fetch_gla_apo(fondo_key: str) -> dict:
    """{edificio: m2} para el donut "GLA (m²)" de la página 3 de Apo (layout
    "edificio") — ver tools/db/rent_roll_stats.py::get_gla_edificios. Estático
    (calculado con el rent roll más reciente disponible): la superficie de un
    edificio no cambia mes a mes, a diferencia de ingresos_edificios que sí
    varía por período."""
    if fondo_key != "Apo":
        return {}
    from tools.db.rent_roll_stats import get_gla_edificios

    edificios = FONDOS_CFG["Apo"]["page3"]["edificios"]
    return get_gla_edificios("Apoquindo", edificios) or {}


def _fetch_vacancia_apo(fondo_key: str) -> dict:
    """{periodo: {"Edificio|||Fila": {pct_actual, pct_anterior, variacion}}}
    para el grid de vacancia por edificio de la página 3 de Apo (ver
    FONDOS_CFG["Apo"]["page3"]["vacancia_edificios"]). Ver
    tools/db/rent_roll_stats.py::get_vacancia_edificios."""
    if fondo_key != "Apo":
        return {}
    from tools.db.rent_roll_stats import get_vacancia_edificios, get_vacancia_fondo, _periodos_disponibles

    edificios_filas = {
        ed["nombre"]: ed["rows"]
        for ed in FONDOS_CFG["Apo"]["page3"]["vacancia_edificios"]
    }
    out = {}
    for periodo in _periodos_disponibles("Apoquindo"):
        tabla = get_vacancia_edificios("Apoquindo", periodo, edificios_filas)
        if tabla is None:
            continue
        fila = {f"{ed}|||{r}": val for (ed, r), val in tabla.items()}
        fondo = get_vacancia_fondo("Apoquindo", periodo)
        if fondo is not None:
            fila["Fondo"] = fondo
        out[periodo] = fila
    return out


def _fetch_ltv_fondo(fondo_key: str) -> float | None:
    """Último LTV del fondo (derived_kpi, entidad_tipo='fondo'), para la fila
    "Financiamiento" de Aspectos Relevantes (página 3 de Apo)."""
    from tools.db.connection import get_conn

    conn = get_conn()
    row = conn.execute(
        "SELECT valor FROM derived_kpi WHERE entidad_tipo='fondo' AND entidad_key=? "
        "AND kpi='ltv' ORDER BY periodo DESC LIMIT 1",
        (fondo_key,),
    ).fetchone()
    return row["valor"] if row else None


def _fetch_status_oficinas_apo(fondo_key: str) -> dict:
    """{periodo: {edificio: {pisos, ocupacion_pct}}} para el gráfico "Status
    Actual Oficinas por Activo" de la página 3 de Apo (ver
    FONDOS_CFG["Apo"]["page3"]["status_oficinas"]). Ver
    tools/db/rent_roll_stats.py::get_status_oficinas."""
    if fondo_key != "Apo":
        return {}
    from tools.db.rent_roll_stats import get_status_oficinas, _periodos_disponibles

    edificios = [n for n, _ in FONDOS_CFG["Apo"]["page3"]["status_oficinas"]]
    out = {}
    for periodo in _periodos_disponibles("Apoquindo"):
        tabla = get_status_oficinas("Apoquindo", periodo, edificios)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


def _fetch_status_locales_apo(fondo_key: str) -> dict:
    """{periodo: {edificio: {locales, ocupacion_pct}}} para el gráfico
    "Status Actual Locales por Activo" de la página 3 de Apo (ver
    FONDOS_CFG["Apo"]["page3"]["status_locales"]). Ver
    tools/db/rent_roll_stats.py::get_status_locales."""
    if fondo_key != "Apo":
        return {}
    from tools.db.rent_roll_stats import get_status_locales, _periodos_disponibles

    edificios = [n for n, _ in FONDOS_CFG["Apo"]["page3"]["status_locales"]]
    out = {}
    for periodo in _periodos_disponibles("Apoquindo"):
        tabla = get_status_locales("Apoquindo", periodo, edificios)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


def _fetch_perf_data(fondo_key: str) -> dict:
    """Tabla "Resumen Performance Activos" de la página 2 (rent roll), por
    período — ver tools/db/rent_roll_stats.py. PT y Apo agrupan por
    sociedad/edificio (ver _GRUPOS_TIPOS_POR_FONDO); TRI consolida a nivel
    fondo paraguas por activo/subfondo (ver get_perf_table_tri /
    _GRUPOS_PERF_TRI — una columna por grupo, participación efectiva de TRI
    escala m² y UF, confirmado con el usuario 2026-08-10)."""
    if fondo_key == "TRI":
        from tools.db.rent_roll_stats import get_perf_table_tri, periodos_disponibles_tri

        out = {}
        for periodo in periodos_disponibles_tri():
            tabla = get_perf_table_tri(periodo)
            if tabla is None:
                continue
            celdas = {f"{grupo}|||{tipo}": val for (grupo, tipo), val in tabla.items()}
            out[periodo] = celdas
        return out

    activo_key_logico = {"PT": "PT", "Apo": "Apoquindo"}.get(fondo_key)
    if activo_key_logico is None:
        return {}
    from tools.db.rent_roll_stats import get_perf_table, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles(activo_key_logico):
        tabla = get_perf_table(activo_key_logico, periodo)
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


def _fetch_rubro_arrendatario(fondo_key: str) -> dict:
    """{periodo: {rubro: renta_uf}} para el gráfico "Composición por Rubro del
    Arrendatario" de la página 2 — ver tools/db/rent_roll_stats.py::get_rubro_arrendatario
    (top-N por monto + "Otro", sin lista curada de rubros). TRI consolida a
    nivel fondo paraguas (mismo criterio que perfil de vencimiento, ver
    get_rubro_arrendatario_tri)."""
    if fondo_key == "TRI":
        from tools.db.rent_roll_stats import get_rubro_arrendatario_tri, periodos_disponibles_tri

        out = {}
        for periodo in periodos_disponibles_tri():
            tabla = get_rubro_arrendatario_tri(periodo)
            if tabla is not None:
                out[periodo] = tabla
        return out

    activo_key_logico = {"PT": "PT", "Apo": "Apoquindo"}.get(fondo_key)
    if activo_key_logico is None:
        return {}
    from tools.db.rent_roll_stats import get_rubro_arrendatario, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles(activo_key_logico):
        tabla = get_rubro_arrendatario(activo_key_logico, periodo)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


def _fetch_ingresos_arrendatario(fondo_key: str) -> dict:
    """{periodo: {arrendatario: renta_uf}} para el donut "Ingresos (UF/mes)"
    de la página 3 (layout "tenant") — ver
    tools/db/rent_roll_stats.py::get_ingresos_arrendatario. Solo fondos con
    page3.donut_arrendatario=True (hoy: PT)."""
    if not (FONDOS_CFG.get(fondo_key, {}).get("page3") or {}).get("donut_arrendatario"):
        return {}
    activo_key_logico = {"PT": "PT"}.get(fondo_key)
    if not activo_key_logico:
        return {}
    from tools.db.rent_roll_stats import get_ingresos_arrendatario, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles(activo_key_logico):
        tabla = get_ingresos_arrendatario(activo_key_logico, periodo)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


def _fetch_gla_arrendatario(fondo_key: str) -> dict:
    """{periodo: {arrendatario: m2}} para el donut "GLA (m²)" de la página 3
    (layout "tenant") — ver tools/db/rent_roll_stats.py::get_m2_arrendatario.
    Solo fondos con page3.donut_arrendatario=True (hoy: PT)."""
    if not (FONDOS_CFG.get(fondo_key, {}).get("page3") or {}).get("donut_arrendatario"):
        return {}
    activo_key_logico = {"PT": "PT"}.get(fondo_key)
    if not activo_key_logico:
        return {}
    from tools.db.rent_roll_stats import get_m2_arrendatario, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles(activo_key_logico):
        tabla = get_m2_arrendatario(activo_key_logico, periodo)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


def _fetch_perfil_vencimiento(fondo_key: str) -> dict:
    """{periodo: {"por_anio": {edificio: {anio: uf}}, "anios": [...],
    "plazo_medio_anios": float}} para el gráfico "Perfil de Vencimiento de
    Contratos" de la página 2 — ver tools/db/rent_roll_stats.py. PT/Apo
    agrupan por edificio/sociedad (get_perfil_vencimiento); TRI consolida a
    nivel fondo paraguas por categoría de activo (get_perfil_vencimiento_tri:
    Oficinas=PT+Apo+Apo3001, Activos Comerciales=Viña+Curicó,
    Residencias=INMOSA, Bodegas=Sucden — confirmado con el usuario
    2026-08-05)."""
    if fondo_key == "TRI":
        from tools.db.rent_roll_stats import (
            get_perfil_vencimiento_tri, periodos_disponibles_tri,
        )

        out = {}
        for periodo in periodos_disponibles_tri():
            tabla = get_perfil_vencimiento_tri(periodo)
            if tabla is not None:
                out[periodo] = tabla
        return out

    activo_key_logico = {"PT": "PT", "Apo": "Apoquindo"}.get(fondo_key)
    edificios = (FONDOS_CFG.get(fondo_key, {}).get("page2") or {}).get("perfil_vencimiento_edificios")
    if not activo_key_logico or not edificios:
        return {}
    from tools.db.rent_roll_stats import get_perfil_vencimiento, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles(activo_key_logico):
        tabla = get_perfil_vencimiento(activo_key_logico, periodo, edificios)
        if tabla is None:
            continue
        out[periodo] = tabla
    return out


def _fetch_tipo_activo(fondo_key: str) -> dict:
    """{periodo: {tipo: renta_uf}} para el donut "Composición por Tipo de
    Activo" de la página 2 — ver tools/db/rent_roll_stats.py::get_tipo_activo.
    Mismo alcance que _fetch_perf_data (PT y Apo; TRI en placeholder)."""
    activo_key_logico = {"PT": "PT", "Apo": "Apoquindo"}.get(fondo_key)
    if activo_key_logico is None:
        return {}
    from tools.db.rent_roll_stats import get_tipo_activo, _periodos_disponibles

    out = {}
    for periodo in _periodos_disponibles(activo_key_logico):
        tabla = get_tipo_activo(activo_key_logico, periodo)
        if tabla is None:
            continue
        out[periodo] = tabla
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
  body.pdf-export #sidebar,
  body.pdf-export .tc-fab,
  body.pdf-export .tc-fab-label,
  body.pdf-export .tc-panel,
  body.pdf-export #btn-unit-balance,
  body.pdf-export #btn-unit-gastos,
  body.pdf-export #btn-unit-dfn { display: none !important; }
  body.pdf-export #main-content { margin-left: 0 !important; }
  /* Cada .page debe caber en una sola página impresa (A4 landscape) — sin
     esto Chromium corta el contenido más alto que una página física en 2. */
  body.pdf-export .page { page-break-after: always; break-after: page; margin: 0 auto; }
  body.pdf-export .page:last-of-type { page-break-after: auto; break-after: auto; }
  .selectors {
    display: flex; flex-direction: column; gap: 0;
    padding: 0 18px; background: transparent;
    border-left: none; margin: 0;
  }
  .selectors .field { display:flex; flex-direction:column; gap:8px; padding: 16px 0; border-bottom: 1px solid #ECECEC; }
  .selectors .field-label {
    font-size: 10px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; color: #8A9992;
    display: flex; align-items: center; gap: 6px;
  }
  .selectors .field-label::before {
    content: ""; width: 3px; height: 11px; border-radius: 2px;
    background: var(--green); display: inline-block;
  }
  .selectors .fund-btns {
    display: flex; gap: 3px; background: #F0F2F1; border-radius: 8px; padding: 3px;
  }
  .selectors .year-btns, .selectors .q-btns { display:flex; gap:4px; }
  .selectors .fund-btn {
    flex: 1; padding: 7px 10px; border: none;
    background: transparent; cursor: pointer; font-weight: 600;
    color: #5b6b63; border-radius: 6px;
    transition: background-color 150ms ease, color 150ms ease, box-shadow 150ms ease;
    font-size: 12px;
  }
  .selectors .fund-btn:hover:not(.active) { background: rgba(0,178,122,0.1); color: var(--green); }
  .selectors .fund-btn.active { background: var(--green); color:#fff; box-shadow: 0 2px 6px rgba(0,178,122,0.35); }
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
    display: flex; gap: 8px; align-items: flex-start; flex-direction: column;
    padding: 16px 0;
  }
  .period-nav-group:not(:last-child) {
    border-bottom: 1px solid #ECECEC;
  }
  .period-nav-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    color: #8A9992; letter-spacing: 1px; white-space: nowrap;
    display: flex; align-items: center; gap: 6px;
  }
  .period-nav-label::before {
    content: ""; width: 3px; height: 11px; border-radius: 2px;
    background: var(--green); display: inline-block;
  }
  .period-nav-controls {
    display: flex; gap: 6px; align-items: center; width: 100%;
    background: #F7F9F8; border: 1px solid #EAEAEA; border-radius: 8px;
    padding: 4px;
  }
  .nav-arrow {
    background: transparent; border: none;
    color: var(--green); cursor: pointer; font-weight: 700;
    padding: 4px 6px; border-radius: 6px; font-size: 13px;
    min-width: 30px; min-height: 30px; display: flex; align-items: center;
    justify-content: center; transition: background-color 150ms ease, color 150ms ease;
    flex-shrink: 0;
  }
  .nav-arrow:hover:not(:disabled) { background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .nav-arrow:disabled { color: #c8c8c8; cursor: not-allowed; }
  .period-display {
    flex: 1; text-align: center;
    font-weight: 600; color: var(--text); cursor: pointer;
    padding: 5px 6px; border-radius: 6px;
    transition: background-color 150ms ease;
    position: relative;
  }
  .period-display:hover { background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .period-dropdown {
    position: fixed; background: #fff; border: 1px solid #ccc;
    border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
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
  .cols-page3-bodegas { grid-template-columns: 1fr 1.2fr; }
  .cols-page3-lower { grid-template-columns: 1fr 34%; align-items: start; }
  /* align-items: stretch (default) para que los dos chart-box de GLA/Ingresos
     por arrendatario (PT) siempre queden del mismo alto — el de la fila
     (determinado por el contenido más alto de los dos, top-N dinámico, ver
     rent_roll_stats.py::_top_n_por_clave) sin cortar contenido; el tercer
     hijo (Aspectos Relevantes) usa align-self:start para no estirarse con
     ellos. */
  .cols-page3-top { grid-template-columns: 1fr 1fr 1fr; }
  .cols-page3-top > :nth-child(3) { align-self: start; }
  .cols-page3-mid { grid-template-columns: 2fr 1fr; align-items: stretch; }
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

  /* Tabla "Análisis de Mercado - Oficinas" (página 3 TRI, #tbl-mercado3):
     lámina compacta tipo Excel — sin zebra, columnas centradas, bandas grises
     verticales en Clase/Absorción/Renta, separador punteado verde antes de
     cada fila total "Santiago". Ver spec de referencia JLL abril 2026. */
  #tbl-mercado3 { table-layout: fixed; }
  #tbl-mercado3 col.col-comuna { width: 18%; }
  #tbl-mercado3 col.col-clase { width: 9%; }
  #tbl-mercado3 col.col-inventario { width: 15%; }
  #tbl-mercado3 col.col-absorcion { width: 17%; }
  #tbl-mercado3 col.col-vacancia { width: 13%; }
  #tbl-mercado3 col.col-renta { width: 14%; }
  #tbl-mercado3 col.col-construccion { width: 14%; }
  #tbl-mercado3 th, #tbl-mercado3 td {
    padding: 3px 6px; font-size: 11px; line-height: 1.2;
    text-align: center; border-bottom: none;
  }
  #tbl-mercado3 th:first-child, #tbl-mercado3 td:first-child { text-align: left; }
  #tbl-mercado3 th { font-size: 10.5px; border-bottom: 2px solid var(--green); }
  #tbl-mercado3 tbody tr { background: none; }
  #tbl-mercado3 tbody tr:nth-child(even) { background: none; }
  #tbl-mercado3 tbody tr:hover { background: #EAF7F0; }
  #tbl-mercado3 tbody td { border-bottom: 1px solid #E9E9E9; }
  #tbl-mercado3 tbody tr:last-child td { border-bottom: none; }
  #tbl-mercado3 td:nth-child(2), #tbl-mercado3 td:nth-child(4), #tbl-mercado3 td:nth-child(6),
  #tbl-mercado3 th:nth-child(2), #tbl-mercado3 th:nth-child(4), #tbl-mercado3 th:nth-child(6) {
    background: #EDEDED;
  }
  #tbl-mercado3 td:nth-child(2), #tbl-mercado3 th:nth-child(2) { background: #D9D9D9; }
  #tbl-mercado3 tbody tr.row-total, #tbl-mercado3 tbody tr.row-total:nth-child(even) {
    background: none; font-weight: 400; color: #1a1a1a;
  }
  #tbl-mercado3 tbody tr.row-total td:nth-child(2),
  #tbl-mercado3 tbody tr.row-total td:nth-child(4),
  #tbl-mercado3 tbody tr.row-total td:nth-child(6) { background: #EDEDED; }
  #tbl-mercado3 tbody tr.row-total td:nth-child(2) { background: #D9D9D9; }
  #tbl-mercado3 tbody tr.row-total td { font-weight: 700; border-top: 2px dashed var(--green); border-bottom: none; }
  #tbl-mercado3 tbody tr.row-spacer td { border: none; padding: 2px 0; background: none; }
  .page3-mercado-cols { display: grid; grid-template-columns: 26% 1fr; gap: 14px; align-items: start; }
  .page3-mercado-cols .comentarios { padding-top: 2px; }
  .comentarios ul { list-style: none; padding-left: 0; margin: 0; }
  .comentarios li {
    position: relative; padding-left: 16px; margin-bottom: 8px;
    font-size: 11px; line-height: 1.35;
  }
  .comentarios li::before {
    content: ""; position: absolute; left: 0; top: 5px;
    width: 6px; height: 6px; border-radius: 50%; background: var(--green-bright, #00C878);
  }
  .comentarios-bodegas { margin: 2px 0 8px; }
  .comentarios-bodegas ul { display: flex; gap: 24px; }
  .comentarios-bodegas li { flex: 1; margin-bottom: 0; }

  /* Sección Bodegas (página 3 TRI): chart combinado 48% + tabla 48%. */
  .page3-bodegas-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
  /* El SVG del chart no trae width/height propios (solo viewBox) — sin esta
     regla el navegador lo renderiza a su tamaño intrínseco (~300x150) en vez
     de llenar la card. min-height:0 evita que .chart-box (min-height:220px)
     agregue espacio vacío extra: la card queda del alto real del gráfico. */
  .chart-box-bodegas { min-height: 0; }
  #tbl-bodegas { table-layout: fixed; }
  #tbl-bodegas col.col-zona { width: 16%; }
  #tbl-bodegas col.col-produccion { width: 21%; }
  #tbl-bodegas col.col-inv-final { width: 22%; }
  #tbl-bodegas col.col-vacancia { width: 21%; }
  #tbl-bodegas col.col-arriendo { width: 20%; }
  #tbl-bodegas th, #tbl-bodegas td {
    padding: 4px 6px; font-size: 11px; height: 27px;
    text-align: center; border-bottom: 1px solid #E9E9E9;
    border-right: 1px solid #E9E9E9;
  }
  #tbl-bodegas th:last-child, #tbl-bodegas td:last-child { border-right: none; }
  #tbl-bodegas th:first-child, #tbl-bodegas td:first-child { text-align: left; }
  #tbl-bodegas th { background: none; border-bottom: 2px solid var(--green); }
  #tbl-bodegas tbody tr { background: none; }
  #tbl-bodegas tbody tr:nth-child(even) { background: none; }
  #tbl-bodegas tbody tr:hover { background: #EAF7F0; }
  #tbl-bodegas tbody tr:last-child td { border-bottom: none; }
  #tbl-bodegas tbody tr.row-total, #tbl-bodegas tbody tr.row-total:nth-child(even) {
    background: #fff; font-weight: 700; color: #1a1a1a;
  }
  #tbl-bodegas tbody tr.row-total td { border-top: 2px dashed var(--green); border-bottom: none; }

  /* Página 4 TRI: tabla "Indicadores Activos" (tasación/deuda/LTV) */
  #tbl-indicadores { table-layout: fixed; }
  #tbl-indicadores col.col-part { width: 14%; }
  #tbl-indicadores col.col-activo { width: 27%; }
  #tbl-indicadores col.col-valor { width: 15%; }
  #tbl-indicadores col.col-fecha { width: 15%; }
  #tbl-indicadores col.col-deuda { width: 15%; }
  #tbl-indicadores col.col-ltv { width: 14%; }
  #tbl-indicadores th, #tbl-indicadores td {
    padding: 3px 6px; font-size: 9px; height: 22px;
    text-align: center; border-bottom: 1px solid #E9E9E9; border-right: 1px solid #E9E9E9;
  }
  #tbl-indicadores th:last-child, #tbl-indicadores td:last-child { border-right: none; }
  #tbl-indicadores th:nth-child(2), #tbl-indicadores td:nth-child(2) { text-align: left; }
  #tbl-indicadores th { background: none; border-bottom: 2px solid var(--green); font-size: 9px; }
  #tbl-indicadores tbody tr { background: none; }
  #tbl-indicadores tbody tr:nth-child(even) { background: none; }
  #tbl-indicadores tbody tr:hover { background: #EAF7F0; }
  #tbl-indicadores td.fecha-tasacion { color: #0066CC; }
  #tbl-indicadores tbody tr.row-total, #tbl-indicadores tbody tr.row-total:nth-child(even) {
    background: var(--green-header); font-weight: 700;
  }
  #tbl-indicadores tbody tr.row-total td { border-right: none; }

  /* Página 4 TRI: sección Viña Centro (63% descripción/gráficos, 35% aspectos+foto) */
  .page4-vina-cols { display: grid; grid-template-columns: 63% 1fr; gap: 14px; align-items: start; }
  .vina-comentarios-box {
    border: 1.5px dashed #0C7E49; border-radius: 0; padding: 7px 8px;
    margin-top: 8px; min-height: 140px; font-size: 8px; line-height: 1.35;
  }
  #tbl-vina-aspectos.kv tr { border-bottom: 1px solid var(--green); }
  #foto-vina { aspect-ratio: unset; }

  /* Página 5 TRI: resúmenes PT / Apoquindo */
  .page5-cols { display: grid; grid-template-columns: 63% 1fr; gap: 14px; align-items: start; }
  .page5-tbl-aspectos.kv tr { border-bottom: 1px solid var(--green); }

  /* Página 6 TRI: INMOSSA / Mall Curicó */
  .page6-cols { display: grid; grid-template-columns: 64% 1fr; gap: 14px; align-items: start; }
  #tbl-residencias { width: 60%; border-collapse: collapse; margin-top: 6px; }
  #tbl-residencias th, #tbl-residencias td { font-size: 9px; padding: 2px 4px; text-align: center; }
  #tbl-residencias th:first-child, #tbl-residencias td:first-child { text-align: left; }
  #tbl-residencias tr.row-total td { font-weight: 700; border-top: 1px solid var(--green); }
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

  /* Modal de exportación PDF */
  .export-modal { max-width: 420px; }
  .export-modal h3 { display: flex; align-items: center; gap: 6px; }
  .export-field { margin: 0 0 14px; }
  .export-field-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.6px; text-transform: uppercase;
    color: #4a6b5c; margin-bottom: 6px;
  }
  .export-row { display: flex; gap: 12px; }
  .export-row .export-field { flex: 1; min-width: 0; }
  .export-fund-checks { display: flex; flex-wrap: wrap; gap: 8px; }
  .export-fund-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 12px; border: 1px solid var(--border); border-radius: 20px;
    font-size: 12px; font-weight: 600; cursor: pointer; user-select: none;
    background: #fff; color: var(--text); transition: background .15s, border-color .15s, color .15s;
  }
  .export-fund-chip:hover { border-color: var(--green); }
  .export-fund-chip.checked { background: var(--green); border-color: var(--green); color: #fff; }
  .export-fund-chip input { position: absolute; opacity: 0; width: 0; height: 0; pointer-events: none; }
  .export-select {
    width: 100%; padding: 7px 10px; border: 1px solid var(--border); border-radius: 5px;
    font-size: 12px; font-family: inherit; color: var(--text); background: #fff;
    appearance: none;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'><path d='M0 0l5 6 5-6z' fill='%23666'/></svg>");
    background-repeat: no-repeat; background-position: right 10px center; background-size: 10px;
  }
  .export-select:focus { outline: none; border-color: var(--green); }
  .export-status {
    min-height: 18px; font-size: 12px; margin-bottom: 10px;
    display: flex; align-items: center; gap: 6px; border-radius: 4px;
  }
  .export-status.ok { color: #1c7a3d; }
  .export-status.warn { color: #9a6b00; }
  .export-status.err { color: #b3261e; }
  .export-download-btn {
    width: 100%; padding: 10px; border: none; border-radius: 6px;
    background: var(--green); color: #fff; font-size: 13px; font-weight: 700;
    cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;
    transition: background .15s, opacity .15s;
  }
  .export-download-btn:hover:not(:disabled) { background: #1c7a3d; }
  .export-download-btn:disabled { opacity: .55; cursor: not-allowed; }
  @keyframes export-spin { to { transform: rotate(360deg); } }

  /* Modal exportación PDF: 3 vistas (form / loading / result) — solo una
     visible a la vez según [data-state] en .export-modal, así al descargar
     el pop-up completo se transforma y no se pueden tocar los parámetros. */
  .export-view { display: none; }
  .export-modal[data-state="form"] .export-view-form { display: block; }
  .export-modal[data-state="loading"] .export-view-loading,
  .export-modal[data-state="result"] .export-view-result {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    text-align: center; padding: 30px 10px 10px; min-height: 180px;
  }
  .export-spinner-big {
    width: 44px; height: 44px; border-radius: 50%;
    border: 4px solid var(--green-soft); border-top-color: var(--green);
    animation: export-spin .8s linear infinite; margin-bottom: 18px;
  }
  .export-loading-title { font-size: 14px; font-weight: 700; color: var(--text); }
  #export-loading-dots { display: inline-block; width: 1.4em; text-align: left; }
  .export-loading-sub { font-size: 11px; color: #666; margin-top: 6px; max-width: 280px; }
  .export-result-icon {
    width: 44px; height: 44px; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; font-size: 22px; margin-bottom: 14px;
  }
  .export-result-icon.ok { background: var(--green-soft); color: #1c7a3d; }
  .export-result-icon.warn { background: #fdf1d6; color: #9a6b00; }
  .export-result-icon.err { background: #fbe2e0; color: #b3261e; }
  .export-result-msg { font-size: 13px; color: var(--text); margin-bottom: 16px; max-width: 300px; }
  .export-secondary-btn {
    padding: 7px 18px; border: 1px solid var(--border); border-radius: 5px;
    background: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
    color: var(--text); transition: border-color .15s;
  }
  .export-secondary-btn:hover { border-color: var(--green); }

  /* Página 2: resumen de performance de activos + gráficos */
  .charts-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 10px 0 16px; }
  .chart-box-stack { display: flex; flex-direction: column; }
  .chart-box-stack .chart-title:not(:first-child) { margin-top: 10px; }
  .chart-box-stack > div[data-chart] { flex: 1; }
  .tabla-anual-tipo-activo { width: 100%; border-collapse: collapse; }
  .tabla-anual-tipo-activo td, .tabla-anual-tipo-activo th { padding: 2px 4px; font-size: 9px; text-align: right; }
  .tabla-anual-tipo-activo td:first-child, .tabla-anual-tipo-activo th:first-child { text-align: left; }
  .tabla-anual-tipo-activo thead th { border-bottom: 1px solid #33413b; font-weight: 700; }
  .tabla-anual-total { font-weight: 700; border-top: 1px dashed #ccc; }
  .chart-box {
    border: 1px dashed var(--border); border-radius: 6px; padding: 12px 14px;
    min-height: 220px; display: flex; flex-direction: column;
  }
  .chart-box .chart-title {
    font-weight: 700; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; color: #33413b; margin-bottom: 8px;
  }
  .chart-box > div[data-chart] { flex: 1; position: relative; }
  .hbar-chart { height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 4px; position: relative; }
  .hbar-row { display: flex; align-items: center; gap: 8px; }
  .hbar-row .hbar-label {
    flex: 0 0 108px; font-size: 10px; color: #46504D; text-align: right;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .hbar-row .hbar-track {
    flex: 1 1 auto; background: #EDF2EF; border-radius: 3px; height: 12px;
    overflow: hidden; cursor: default;
  }
  .hbar-row .hbar-fill { display: block; background: #05A978; height: 100%; border-radius: 0 3px 3px 0; transition: filter .1s; }
  .hbar-row.is-active .hbar-fill { filter: brightness(0.9); }
  .hbar-row.is-active .hbar-track { background: #E0E9E4; }
  .hbar-row .hbar-pct {
    flex: 0 0 34px; font-size: 10px; color: #33413b; font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .hbar-tooltip {
    position: absolute; z-index: 5; background: #263029; color: #fff;
    border-radius: 6px; padding: 6px 10px; font-size: 10px; line-height: 1.5;
    pointer-events: none; opacity: 0; transition: opacity .08s;
    box-shadow: 0 4px 12px rgba(0,0,0,0.18); white-space: nowrap;
    transform: translate(-50%, calc(-100% - 10px));
  }
  .hbar-tooltip.on { opacity: 1; }
  .hbar-tooltip .t-title { font-weight: 700; margin-bottom: 2px; }
  .hbar-tooltip .t-line { display: flex; justify-content: space-between; gap: 12px; color: #C9D3CD; }
  .hbar-tooltip .t-line b { color: #fff; font-weight: 600; margin-left: 8px; }
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
  .donut-wrap { flex: 1; display: flex; align-items: center; justify-content: center; gap: 20px; position: relative; }
  .donut { width: 150px; height: 150px; border-radius: 50%; position: relative; flex: none; }
  .donut::after { content: ""; position: absolute; inset: 36px; background: #fff; border-radius: 50%; }
  .donut-legend { font-size: 13px; }
  .donut-legend .row { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
  .donut-legend .dot { width: 12px; height: 12px; border-radius: 2px; display: inline-block; flex: none; }
  .donut-legend .row .lbl { color: var(--text); }
  .donut-legend .row .pct { color: #7a8a83; font-weight: 600; font-variant-numeric: tabular-nums; margin-left: auto; padding-left: 10px; }
  .donut-pct {
    position: absolute; transform: translate(-50%, -50%); font-size: 12px;
    font-weight: 700; white-space: nowrap; pointer-events: none; z-index: 3;
  }
  .donut-hit-layer {
    position: absolute; inset: 0; width: 100%; height: 100%; z-index: 2;
  }
  .donut-hit { cursor: default; }
  .donut-tooltip {
    position: absolute; min-width: 168px; pointer-events: none; opacity: 0;
    transform: translate(-50%, -108%); transition: opacity 120ms ease;
    background: rgba(255,255,255,0.97); border: 1px solid #D8E0DD;
    border-radius: 6px; box-shadow: 0 6px 18px rgba(25,45,38,0.16);
    padding: 8px 9px; font-size: 10px; color: #26352F; z-index: 4;
  }
  .donut-tooltip.on { opacity: 1; }
  .donut-tooltip .title { font-weight: 700; margin-bottom: 5px; color: #15221D; }
  .donut-tooltip .line { display: flex; justify-content: space-between; gap: 16px; margin: 2px 0; }
  .donut-tooltip .label { display: flex; align-items: center; gap: 5px; color: #52645D; }
  .donut-tooltip .dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
  .donut-tooltip .value { font-weight: 700; color: #25342F; }
  .donut-legend .row.is-active {
    color: #15221D; font-weight: 700;
  }

  /* Grafico "Resultados Parking (UF)" - SVG combo (barras apiladas + lineas), sin librerias */
  .parking-chart {
    position: relative; display: flex; flex-direction: column; height: 100%;
    padding-top: 2px;
  }
  .parking-chart svg {
    flex: 1; width: 100%; height: auto; overflow: visible;
    font-family: Arial, Helvetica, sans-serif;
  }
  .parking-legend {
    display: flex; flex-wrap: wrap; gap: 4px 16px; justify-content: center;
    font-size: 12px; color: #33413b; margin-top: 4px;
  }
  .parking-legend .row { display: flex; align-items: center; gap: 6px; }
  .parking-legend .swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; flex: none; }
  .parking-legend .swatch.line { height: 3px; border-radius: 3px; }
  .parking-tooltip {
    position: absolute; min-width: 168px; pointer-events: none; opacity: 0;
    transform: translate(-50%, -108%); transition: opacity 120ms ease;
    background: rgba(255,255,255,0.97); border: 1px solid #D8E0DD;
    border-radius: 6px; box-shadow: 0 6px 18px rgba(25,45,38,0.16);
    padding: 8px 9px; font-size: 10px; color: #26352F; z-index: 2;
  }
  .parking-tooltip.on { opacity: 1; }
  .parking-tooltip .title { font-weight: 700; margin-bottom: 5px; color: #15221D; }
  .parking-tooltip .line { display: flex; justify-content: space-between; gap: 16px; margin: 2px 0; }
  .parking-tooltip .label { display: flex; align-items: center; gap: 5px; color: #52645D; }
  .parking-tooltip .dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
  .parking-tooltip .value { font-weight: 700; color: #25342F; }

  /* Barras del gráfico "Perfil de Vencimiento de Contratos" */
  .vc-bar-seg { transition: filter 120ms ease; }
  .vc-col.is-active .vc-bar-seg { filter: brightness(0.88); }

  /* Barra de ocupación (reemplaza el treemap de la referencia — mismo dato, layout simplificado) */
  .occ-box { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 8px; padding: 8px 6px; }
  .occ-bar { background: #EDEDED; border-radius: 4px; height: 14px; overflow: hidden; }
  .occ-bar-fill { background: var(--green); height: 100%; }
  .occ-label { font-size: 11px; text-align: center; font-weight: 600; color: #33413b; margin-top: 6px; }
  /* Caja "Ocupación: X%" con borde verde tipo pill, igual a la foto de
     referencia (recuadro redondeado, centrado, debajo de cada gráfico). */
  .occ-pill {
    align-self: center; margin-top: 10px; padding: 6px 18px;
    border: 2px solid var(--green); border-radius: 6px;
    font-size: 13px; font-weight: 700; color: #1a1a1a; background: #fff;
  }
  .occ-pill.placeholder { border-color: #ccc; color: #999; font-weight: 400; }
  /* Status Actual Oficinas (renderStatusOficinas): pisos apilados, ancho
     proporcional al m² real de cada piso — misma idea que un perfil de
     edificio, ver foto de referencia adjunta por el usuario. */
  .status-viz { position: relative; flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 6px; min-height: 160px; }
  /* Contenedor con aspect-ratio fijado inline por edificio (ver
     APO_OFICINAS_LAYOUT en renderStatusOficinas) — la silueta (trapecio
     4501, rectángulo 4700 con la planta baja más ancha) es un layout FIJO
     calcado pixel a pixel de la foto de referencia del usuario, igual que
     APO_LOCALES_LAYOUT: cada piso es un div posicionado en absoluto, no un
     flujo de flexbox. */
  .status-building { position: relative; width: 100%; }
  .status-floor { position: absolute; box-sizing: border-box; border: 0.5px solid #000; display: flex; }
  .status-floor-occ { background: var(--green); }
  .status-floor-vac { background: #fff; }
  /* Status Actual Locales (renderStatusLocales): treemap, área proporcional
     al m² real de cada local. Etiqueta oculta bajo un umbral de tamaño para
     evitar el texto cortado/apilado que se ve en celdas angostas (ej. locales
     de 84-90 m² junto a uno de 1255 m²). */
  /* Proporción 216:333 medida directamente sobre la foto de referencia del
     usuario (contenedor principal del treemap de Apo4501) — las coordenadas
     fijas de APO_LOCALES_LAYOUT (ver renderStatusLocales) están calculadas
     sobre esa misma proporción, así que el aspect-ratio del contenedor real
     tiene que calzar para que no se deformen. */
  .status-treemap { position: relative; width: 100%; aspect-ratio: 216 / 333; }
  .status-local {
    position: absolute; box-sizing: border-box; border: 0.5px solid #000;
    font-size: 8px; color: #1a1a1a; display: flex; align-items: flex-end;
    justify-content: flex-start; padding: 2px; overflow: hidden;
  }
  .status-local-label {
    display: block; max-width: 100%; overflow: hidden;
    white-space: nowrap; text-overflow: ellipsis;
  }
  .status-local-occ { background: var(--green); }
  .status-local-vac { background: #fff; }
  /* Plano Local 100 (PT, página 4, renderPlanoPT): SVG con viewBox = las
     coordenadas ORIGINALES del plano (ver FONDOS_CFG["PT"]["page4"]
     ["plano"]) — la imagen (<image>) se estira a llenar ese viewBox y los
     <rect>/<polygon> de cada local usan esas mismas coordenadas tal cual,
     sin reescalar a mano; si se reemplaza el archivo de imagen por otra
     resolución (misma composición), sigue calzando solo. Relleno
     semi-transparente para no tapar el plano de fondo. */
  .plano-piso { position: relative; width: 100%; }
  .plano-piso svg { display: block; width: 100%; height: auto; }
  .plano-shape { stroke: #000; stroke-width: 1.5; vector-effect: non-scaling-stroke; cursor: default; }
  .plano-local-occ { fill: rgba(0,178,122,0.45); }
  .plano-local-vac { fill: rgba(120,120,120,0.55); }
  .plano-label { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; fill: #16241d; text-anchor: middle; pointer-events: none; }
  .plano-label .nombre { font-weight: 700; }
  .plano-label .sub { font-weight: 400; }
  /* Tooltip al pasar el cursor sobre un piso (renderStatusOficinas) o un
     local (renderStatusLocales) — mismo lenguaje visual que .donut-tooltip. */
  .status-tooltip {
    position: absolute; min-width: 150px; max-width: 240px; pointer-events: none; opacity: 0;
    transform: translate(-50%, -108%); transition: opacity 120ms ease;
    background: rgba(255,255,255,0.97); border: 1px solid #D8E0DD;
    border-radius: 6px; box-shadow: 0 6px 18px rgba(25,45,38,0.16);
    padding: 8px 9px; font-size: 10px; color: #26352F; z-index: 5;
  }
  .status-tooltip.on { opacity: 1; }
  .status-tooltip .title { font-weight: 700; margin-bottom: 5px; color: #15221D; }
  .status-tooltip .line { display: flex; justify-content: space-between; gap: 16px; margin: 2px 0; }
  .status-tooltip .label { color: #52645D; }
  .status-tooltip .value { font-weight: 700; color: #25342F; }
  .status-tooltip .unidad-row { border-top: 1px solid #EAEFEC; margin-top: 4px; padding-top: 4px; }

  /* Fotos de activos (página 3) — Apo (edificio): grilla original, sin cambios. */
  .fotos-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
  .foto-box { aspect-ratio: 403/669; border-radius: 6px; overflow: hidden; background: #F4F4F4;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 6px rgba(0,0,0,0.18); }
  .foto-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .foto-box .foto-placeholder { font-size: 10px; color: #999; text-align: center; padding: 8px; }
  .foto-caption { font-size: 10px; text-align: center; color: #666; margin-top: 3px; }

  /* PT (tenant): proporciones fijas por foto (no estirar a la altura de la
     columna hermana — eso las deformaba). Foto grande ~ratio nativo del
     complejo (890/690); las dos de abajo comparten el mismo ratio entre sí
     (grilla de fact sheet de referencia: ambas quedan del mismo tamaño) sin
     captions. Aislado con este selector para no afectar la grilla de Apo. */
  #page3-layout-tenant .fotos-grid { grid-template-rows: auto auto; height: auto; align-self: start; margin-top: 0; }
  #page3-layout-tenant .fotos-grid > div { display: flex; flex-direction: column; }
  #page3-layout-tenant .fotos-grid > div.foto-big { grid-column: 1 / -1; grid-row: 1; }
  #page3-layout-tenant .foto-box { aspect-ratio: unset; flex: unset; min-height: 0; width: 100%; }
  #page3-layout-tenant .fotos-grid > div.foto-big .foto-box { aspect-ratio: 890 / 690; }
  #page3-layout-tenant .fotos-grid > div:nth-child(2) .foto-box,
  #page3-layout-tenant .fotos-grid > div:nth-child(3) .foto-box { aspect-ratio: 0.7; }
  #page3-layout-tenant .foto-caption { display: none; }
  #tbl-perf-activos td:first-child, #tbl-perf-activos th:first-child { text-align: left; }
  #sidebar {
    position: fixed; left: 0; top: 0;
    width: 300px; height: 100vh;
    background: #fff; border-right: 1px solid #EAEAEA;
    box-shadow: 4px 0 24px rgba(0,0,0,0.05);
    overflow-y: auto; overflow-x: hidden; z-index: 200;
    padding: 0 0 16px;
    display: flex; flex-direction: column;
    scrollbar-width: thin; scrollbar-color: #d6d6d6 transparent;
  }
  #sidebar::-webkit-scrollbar { width: 6px; }
  #sidebar::-webkit-scrollbar-thumb { background: #d6d6d6; border-radius: 3px; }
  #sidebar-brand {
    display: flex; flex-direction: column; align-items: flex-start; gap: 6px;
    background: linear-gradient(135deg,#242424,#303030);
    color: #fff; padding: 22px 18px 18px;
    line-height: 1.2; position: sticky; top: 0; z-index: 1;
  }
  #sidebar-brand .brand-mark {
    flex-shrink: 0; height: 22px; width: auto; display: block;
  }
  #sidebar-brand span {
    font-size: 9px; font-weight: 700; letter-spacing: 1.2px;
    color: #9fd9c0; text-transform: uppercase; display: block;
  }
  #sidebar-footer {
    display: flex; flex-direction: column; gap: 6px;
    padding: 14px 18px 0; margin-top: auto;
  }
  #sidebar-footer .admin-toggle {
    float: none; margin: 0; align-self: stretch;
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; padding: 8px 10px; border-radius: 7px;
    font-weight: 600; letter-spacing: 0.2px;
  }
  #sidebar-footer .admin-toggle:hover { background: #E6F5EC; }
  #sidebar-footer .admin-toggle.on { background: var(--green); color: #fff; }
  #main-content { margin-left: 252px; }
</style>
</head>
<body>
<div id="sidebar">
  <div id="sidebar-brand">
    <img class="brand-mark" src="data:image/png;base64,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" alt="Toesca">
    <span>Fact Sheets</span>
  </div>
  <div class="selectors">
    <div class="field">
      <span class="field-label">Fondo</span>
      <div class="fund-btns" id="fund-btns"></div>
    </div>
    <div class="period-nav-group">
      <span class="period-nav-label">EEFF & Bursátil</span>
      <div class="period-nav-controls">
        <button class="nav-arrow" id="nav-prev-cb" onclick="navPeriod(-1, 'cb')" aria-label="Período anterior">‹</button>
        <span class="period-display" id="period-display-cb" onclick="togglePeriodDropdown('cb')"></span>
        <button class="nav-arrow" id="nav-next-cb" onclick="navPeriod(1, 'cb')" aria-label="Período siguiente">›</button>
      </div>
      <div class="period-dropdown" id="period-dropdown-cb" style="display:none;"></div>
    </div>
    <div class="period-nav-group">
      <span class="period-nav-label">Operacional</span>
      <div class="period-nav-controls">
        <button class="nav-arrow" id="nav-prev-op" onclick="navPeriod(-1, 'op')" aria-label="Período anterior">‹</button>
        <span class="period-display" id="period-display-op" onclick="togglePeriodDropdown('op')"></span>
        <button class="nav-arrow" id="nav-next-op" onclick="navPeriod(1, 'op')" aria-label="Período siguiente">›</button>
      </div>
      <div class="period-dropdown" id="period-dropdown-op" style="display:none;"></div>
    </div>
    <select id="sel-periodo-cb" style="display:none" aria-hidden="true"></select>
    <select id="sel-periodo-op" style="display:none" aria-hidden="true"></select>
  </div>
  <div id="sidebar-footer">
    <a href="http://localhost:8765/ingesta" target="_blank" rel="noopener" id="btn-ingesta" class="admin-toggle" style="text-decoration:none" title="Ingestar un nuevo EEFF a la base de datos (requiere tener ingesta.bat corriendo)">Ingesta FS</a>
    <button type="button" id="btn-admin" class="admin-toggle" title="Modo admin: click en cualquier número para ver cómo se calculó, y editar fechas de Noticias">✎ Admin</button>
    <button type="button" id="btn-export-pdf" class="admin-toggle" title="Exportar uno o varios fact sheets a PDF">⬇ Exportar PDF</button>
  </div>
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
              <td id="bal-liab-label-0">—</td><td id="bal-liab-value-0">—</td></tr>
          <tr><td>Otros Activos Corrientes</td><td id="bal-otros-ac">—</td>
              <td id="bal-liab-label-1">—</td><td id="bal-liab-value-1">—</td></tr>
          <tr><td>Propiedades de Inversión</td><td id="bal-pi">—</td>
              <td id="bal-liab-label-2">—</td><td id="bal-liab-value-2">—</td></tr>
          <tr><td>Otros Activos No Corrientes</td><td id="bal-otros-anc">—</td>
              <td id="bal-liab-label-3">—</td><td id="bal-liab-value-3">—</td></tr>
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

    <div id="page2-charts-container"></div>
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

    <!-- Layout "edificio" (Apo): tal como estaba antes de las iteraciones de
         layout hechas para PT. NO tocar esta sección al ajustar PT — ids
         propios (donut-gla, tbl-aspectos, grid-fotos, tbl-tasaciones, etc.),
         completamente independientes del layout "tenant" de abajo. -->
    <div id="page3-layout-edificio" class="hidden">
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
              <thead><tr><th></th><th>Valor Tasación</th><th>Fecha Tasación</th><th id="th-tasacion-deuda">Deuda</th><th>LTV</th></tr></thead>
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
          <!-- Cada chart-box trae su propio título completo ("Status Actual
               Oficinas/Locales {edificio}", ver statusBox() en fillStructure)
               replicando el layout de la foto de referencia del usuario —
               sin encabezado de sección compartido. -->
          <div class="charts-grid-2" id="grid-status-oficinas"></div>
          <div class="charts-grid-2" id="grid-status-locales" style="margin-top:10px"></div>
        </div>
      </div>
    </div>

    <!-- Layout "tenant" (PT): GLA/Ingresos/Aspectos Relevantes en 3 columnas,
         Aspectos del Mes ancho completo, Tasaciones+Parking a la izquierda /
         Fotos a la derecha. ids propios sufijo "-t", independientes del
         layout "edificio" de arriba. -->
    <div id="page3-layout-tenant" class="hidden">
      <div class="cols cols-page3-top">
        <div class="chart-box">
          <div class="chart-title">GLA (m²)</div>
          <div class="donut-wrap" id="donut-gla-t"></div>
        </div>
        <div class="chart-box">
          <div class="chart-title">Ingresos (UF/mes)</div>
          <div class="donut-wrap" id="donut-ingresos-t"></div>
        </div>
        <div>
          <div class="section-title">Aspectos Relevantes</div>
          <table class="kv" id="tbl-aspectos-t"></table>
        </div>
      </div>

      <div class="section-title">Aspectos del Mes</div>
      <div class="aspectos-mes-box" id="txt-aspectos-mes-t"></div>

      <div class="cols cols-page3-mid">
        <div>
          <div class="section-title">Tasaciones</div>
          <div style="overflow-x:auto">
            <table id="tbl-tasaciones-t">
              <thead><tr><th></th><th>Valor Tasación</th><th>Fecha Tasación</th><th id="th-tasacion-deuda-t">Deuda</th><th>LTV</th></tr></thead>
              <tbody id="tbl-tasaciones-tbody-t"></tbody>
            </table>
          </div>
          <div style="overflow-x:auto;margin-top:8px">
            <table id="tbl-tasaciones-comp-t">
              <thead><tr><th></th><th id="th-tasacion-prev-t"></th><th id="th-tasacion-actual-t"></th><th>Var % UF</th></tr></thead>
              <tbody id="tbl-tasaciones-comp-tbody-t"></tbody>
            </table>
          </div>

          <div class="section-title" style="margin-top:10px">Resultados Parking (UF)</div>
          <div id="chart-parking" style="height:260px"></div>
        </div>
        <div class="fotos-grid" id="grid-fotos-t"></div>
      </div>
    </div>

    <!-- Layout "mercado" (TRI): reporte de mercado de terceros — oficinas
         (tabla real desde raw_mercado_oficinas), bodegas y centros comerciales
         (solo estructura, sin fuente en DB todavía). ids propios sufijo "-m". -->
    <div id="page3-layout-mercado" class="hidden">
      <div class="section-title">Análisis de Mercado - Oficinas</div>
      <div class="page3-mercado-cols">
        <div class="comentarios">
          <ul>
            <li class="small placeholder" id="txt-mercado3-p1">Pendiente: párrafo de absorción (informe JLL) — actualización manual, no proviene de la DB.</li>
            <li class="small placeholder" id="txt-mercado3-p2">Pendiente: párrafo de concentración por comuna (informe JLL).</li>
          </ul>
        </div>
        <div style="overflow-x:auto">
          <table id="tbl-mercado3">
            <colgroup>
              <col class="col-comuna"><col class="col-clase"><col class="col-inventario">
              <col class="col-absorcion"><col class="col-vacancia"><col class="col-renta"><col class="col-construccion">
            </colgroup>
            <thead><tr>
              <th>Comuna</th><th>Clase</th><th>Inventario<br/>(m²)</th>
              <th>Absorción neta U12M<br/>(m²)</th><th>Vacancia<br/>(%)</th>
              <th>Renta<br/>(UF/m²)</th><th>Construcción<br/>(m²)</th>
            </tr></thead>
            <tbody id="tbl-mercado3-tbody"></tbody>
          </table>
        </div>
      </div>
      <div class="charts-grid-2" style="align-items:start">
        <div class="chart-box" style="min-height:0">
          <div class="chart-title">Evolución anual vacancia (%) Oficinas Las Condes</div>
          <div id="chart-vacancia-oficinas"></div>
        </div>
        <div class="chart-box" style="min-height:0">
          <div class="chart-title">Evolución anual rentas (UF/m²) Oficinas Las Condes</div>
          <div id="chart-rentas-oficinas"></div>
        </div>
      </div>

      <div class="section-title">Análisis de Mercado - Bodegas</div>
      <div class="comentarios comentarios-bodegas">
        <ul>
          <li class="small" id="txt-mercado3-bodegas-1"></li>
          <li class="small" id="txt-mercado3-bodegas-2"></li>
        </ul>
      </div>
      <div class="cols page3-bodegas-cols">
        <div class="chart-box chart-box-bodegas">
          <div class="chart-title">Evolución de la vacancia y canon de arriendo Bodegas</div>
          <div id="chart-bodegas" style="width:100%;aspect-ratio:600/205"></div>
        </div>
        <div style="overflow-x:auto">
          <table id="tbl-bodegas">
            <colgroup>
              <col class="col-zona"><col class="col-produccion"><col class="col-inv-final">
              <col class="col-vacancia"><col class="col-arriendo">
            </colgroup>
            <thead><tr><th>Zona</th><th>Producción<br/>(m²)</th><th>Inventario Final<br/>(m²)</th><th>Vacancia<br/>(%)</th><th>Arriendo<br/>(UF/m²)</th></tr></thead>
            <tbody id="tbl-bodegas-tbody"></tbody>
          </table>
        </div>
      </div>

      <div class="section-title">Análisis de Mercado - Centros Comerciales</div>
      <p class="small placeholder" id="txt-mercado3-comercio">Pendiente: párrafo de comercio (Cámara Nacional de Comercio) — sin fuente ingestada en la DB todavía.</p>
      <div style="overflow-x:auto">
        <table id="tbl-comercio">
          <thead><tr id="tbl-comercio-thead"></tr></thead>
          <tbody id="tbl-comercio-tbody"></tbody>
        </table>
      </div>
      <div class="chart-box" style="margin-top:10px">
        <div class="chart-title">Variaciones reales acumuladas Total Locales RM (CNC)</div>
        <div class="chart-placeholder" id="chart-comercio">Pendiente de datos</div>
      </div>

      <p class="small" style="margin-top:10px;color:#888">
        Fuentes: Jones Lang Lasalle (Panorama de Mercado de Oficinas), GPS Property (Reporte Global Mercado Bodegas),
        Colliers (Reporte Centros de Bodegaje), Cámara Nacional de Comercio, Servicios y Turismo.
      </p>
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
    <!-- Análisis de mercado de oficinas: solo si S.page4.submercado está definido
         (hoy Apo). PT no tiene esta sección en su PDF de referencia. -->
    <div id="page4-mercado" class="hidden">
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
    </div>

    <!-- Plano de planta: solo si S.page4.plano está definido (hoy PT — Plano
         Local 100, Piso -1 / Piso -2). Sin gráfico real disponible aún. -->
    <div id="page4-plano" class="hidden">
      <div class="section-title" id="plano-titulo">—</div>
      <div class="charts-grid-2" id="grid-plano"></div>
    </div>

    <!-- Indicadores Activos (TRI): tabla consolidada tasación/deuda/LTV,
         look-through fondo — ver S.page4.indicadores_rows y
         F.page4_indicadores (fetch_fondo). Solo visible si el fondo define
         indicadores_rows (hoy TRI). -->
    <div id="page4-indicadores" class="hidden">
      <div class="section-title">Indicadores Activos</div>
      <div style="overflow-x:auto">
        <table id="tbl-indicadores">
          <colgroup>
            <col class="col-part"><col class="col-activo"><col class="col-valor">
            <col class="col-fecha"><col class="col-deuda"><col class="col-ltv">
          </colgroup>
          <thead><tr>
            <th>Participación</th><th>Activo</th><th>Valor Tasación (UF)</th>
            <th>Fecha Tasación</th><th>Deuda**</th><th>LTV</th>
          </tr></thead>
          <tbody id="tbl-indicadores-tbody"></tbody>
        </table>
      </div>
    </div>

    <div class="section-title">Notas</div>
    <ol id="lst-notas" style="font-size:10px;color:#333;padding-left:16px;line-height:1.5"></ol>

    <!-- Centro Comercial Paseo Viña Centro (TRI): descripción + donuts GLA/
         Ingresos (sin fuente en DB, placeholder) + comentarios generales
         (editorial mensual, sin fuente todavía, placeholder) + aspectos
         relevantes (hechos estáticos del activo) + foto (pendiente de subir).
         Ver S.page4.vina_centro. -->
    <div id="page4-vina" class="hidden">
      <div class="section-title" id="vina-titulo">—</div>
      <div class="cols page4-vina-cols">
        <div>
          <p class="small" id="txt-vina-descripcion" style="text-align:justify"></p>
          <div class="charts-grid-2">
            <div class="chart-box">
              <div class="chart-title">GLA (m²)</div>
              <div class="chart-placeholder" id="chart-vina-gla">Pendiente de datos</div>
            </div>
            <div class="chart-box">
              <div class="chart-title">Ingresos (UF/mes)</div>
              <div class="chart-placeholder" id="chart-vina-ingresos">Pendiente de datos</div>
            </div>
          </div>
          <div class="vina-comentarios-box">
            <div class="small placeholder" id="txt-vina-comentarios">Pendiente: comentarios generales, vacancia, ventas acumuladas y resultados — actualización editorial mensual, sin fuente en la DB todavía.</div>
          </div>
        </div>
        <div>
          <div class="section-title" style="margin-top:0">Aspectos Relevantes</div>
          <table class="kv" id="tbl-vina-aspectos"><tbody></tbody></table>
          <div class="foto-box" id="foto-vina" style="margin-top:8px;height:170px">
            <div class="foto-placeholder">Pendiente: foto del Centro Comercial Paseo Viña Centro</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Página 5 (TRI): resúmenes de los subfondos PT y Apoquindo. Solo visible
     si S.page5 está definido (hoy TRI) — ver page5-pending para el resto. -->
<div class="page" id="page5">
  <header>
    <div>
      <h1 id="hdr5-nombre">—</h1>
      <h2 id="hdr5-sub">—</h2>
    </div>
  </header>
  <div class="month-bar"><span id="month-bar5">—</span></div>

  <div id="page5-pending" class="hidden">
    <p class="small placeholder" style="margin-top:16px">
      Página 5 aún no definida para este fondo.
    </p>
  </div>

  <div id="page5-body" class="hidden">
    <template id="tpl-page5-section">
      <div class="section-title page5-titulo"></div>
      <div class="cols page5-cols">
        <div>
          <p class="small page5-descripcion" style="text-align:justify"></p>
          <div class="charts-grid-2">
            <div class="chart-box">
              <div class="chart-title">GLA (m²)</div>
              <div class="donut-wrap page5-donut-gla"></div>
            </div>
            <div class="chart-box">
              <div class="chart-title">Ingresos (UF/mes)</div>
              <div class="donut-wrap page5-donut-ingresos"></div>
            </div>
          </div>
          <p class="small page5-parrafo-remuneracion" style="text-align:justify;margin-top:8px"></p>
          <p class="small page5-parrafo-masinfo" style="text-align:justify;margin-top:8px"></p>
        </div>
        <div>
          <div class="section-title" style="margin-top:0">Aspectos Relevantes</div>
          <table class="kv page5-tbl-aspectos"><tbody></tbody></table>
          <div class="page5-fotos" style="margin-top:7px"></div>
        </div>
      </div>
    </template>
    <div id="page5-section-pt"></div>
    <div id="page5-section-apo" style="margin-top:34px"></div>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Página 6 (TRI): INMOSSA (residencias adulto mayor) + Mall Curicó. Solo
     visible si S.page6 está definido (hoy TRI). -->
<div class="page" id="page6">
  <header>
    <div>
      <h1 id="hdr6-nombre">—</h1>
      <h2 id="hdr6-sub">—</h2>
    </div>
  </header>
  <div class="month-bar"><span id="month-bar6">—</span></div>

  <div id="page6-pending" class="hidden">
    <p class="small placeholder" style="margin-top:16px">Página 6 aún no definida para este fondo.</p>
  </div>

  <div id="page6-body" class="hidden">
    <!-- INMOSSA: sin donuts (arriendo triple-net a un solo operador, sin rent
         roll unitario) — tabla de residencias + ocupación histórica (placeholder,
         sin fuente en DB) + comentario del mes (placeholder). -->
    <div class="section-title" id="inmossa-titulo">—</div>
    <div class="cols page6-cols">
      <div>
        <p class="small" id="txt-inmossa-descripcion" style="text-align:justify"></p>
        <table id="tbl-residencias">
          <colgroup><col style="width:52%"><col style="width:25%"><col style="width:23%"></colgroup>
          <thead><tr><th>Hogar</th><th>Comienzo</th><th>Camas</th></tr></thead>
          <tbody id="tbl-residencias-tbody"></tbody>
        </table>
        <div class="chart-box" style="margin-top:8px">
          <div class="chart-title">Ocupación (2018–2026)</div>
          <div class="chart-placeholder" id="chart-ocupacion-inmossa">Pendiente: histórico de ocupación por residencia — sin fuente en la DB todavía.</div>
        </div>
        <div class="vina-comentarios-box" style="min-height:auto">
          <div class="small placeholder" id="txt-inmossa-comentario">Pendiente: comentario del mes — actualización editorial, sin fuente en la DB todavía.</div>
        </div>
      </div>
      <div>
        <div class="section-title" style="margin-top:0">Aspectos Relevantes</div>
        <table class="kv" id="tbl-inmossa-aspectos"><tbody></tbody></table>
        <div class="section-title" style="margin-top:10px">Ubicación Residencias</div>
        <div class="chart-placeholder" id="mapa-residencias" style="height:165px">Pendiente: mapa esquemático de ubicaciones — sin fuente en la DB todavía.</div>
      </div>
    </div>

    <div class="section-title" id="curico-titulo" style="margin-top:16px">—</div>
    <div class="cols page6-cols">
      <div>
        <p class="small" id="txt-curico-descripcion" style="text-align:justify"></p>
        <div class="charts-grid-2">
          <div class="chart-box">
            <div class="chart-title">GLA (m²)</div>
            <div class="donut-wrap" id="donut-curico-gla"></div>
          </div>
          <div class="chart-box">
            <div class="chart-title">Ingresos (UF/mes)</div>
            <div class="donut-wrap" id="donut-curico-ingresos"></div>
          </div>
        </div>
        <div class="vina-comentarios-box">
          <div class="small placeholder" id="txt-curico-comentarios">Pendiente: comentarios generales, vacancia, ventas acumuladas y resultados — actualización editorial mensual, sin fuente en la DB todavía.</div>
        </div>
      </div>
      <div>
        <div class="section-title" style="margin-top:0">Aspectos Relevantes</div>
        <table class="kv" id="tbl-curico-aspectos"><tbody></tbody></table>
        <div class="foto-box" id="foto-curico" style="margin-top:6px;aspect-ratio:216/126">
          <div class="foto-placeholder">Pendiente: foto del Centro Comercial Paseo Curicó</div>
        </div>
      </div>
    </div>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Página 7 (TRI): Edificio Apoquindo 3001 + Bodegas Sucden Chile. Solo
     visible si S.page7 está definido (hoy TRI). -->
<div class="page" id="page7">
  <header>
    <div>
      <h1 id="hdr7-nombre">—</h1>
      <h2 id="hdr7-sub">—</h2>
    </div>
  </header>
  <div class="month-bar"><span id="month-bar7">—</span></div>

  <div id="page7-pending" class="hidden">
    <p class="small placeholder" style="margin-top:16px">Página 7 aún no definida para este fondo.</p>
  </div>

  <div id="page7-body" class="hidden">
    <template id="tpl-page7-section">
      <div class="section-title page7-titulo"></div>
      <div class="cols page6-cols">
        <div>
          <p class="small page7-p1" style="text-align:justify"></p>
          <p class="small page7-p2" style="text-align:justify;margin-top:4px"></p>
          <div class="charts-grid-2">
            <div class="chart-box">
              <div class="chart-title">GLA (m²)</div>
              <div class="donut-wrap page7-donut-gla"></div>
            </div>
            <div class="chart-box">
              <div class="chart-title">Ingresos (UF/mes)</div>
              <div class="donut-wrap page7-donut-ingresos"></div>
            </div>
          </div>
          <div class="vina-comentarios-box">
            <div class="small placeholder page7-comentarios">Pendiente: comentario del mes — actualización editorial, sin fuente en la DB todavía.</div>
          </div>
        </div>
        <div>
          <div class="section-title" style="margin-top:0">Aspectos Relevantes</div>
          <table class="kv page7-tbl-aspectos"><tbody></tbody></table>
          <div class="foto-box page7-foto" style="margin-top:6px">
            <div class="foto-placeholder">Pendiente: foto</div>
          </div>
        </div>
      </div>
    </template>
    <div id="page7-section-apo3001"></div>
    <div id="page7-section-sucden" style="margin-top:16px"></div>
  </div>

  <p class="small" style="text-align:center;margin-top:20px;color:#888">
    Apoquindo 3885, Piso 22, Las Condes · Tel. +562 26462000 · www.toesca.com
  </p>
</div>

<!-- Página 8 (TRI, última): Notas metodológicas (i)-(x) + nota final. Sin
     footer/número de página (ver spec de referencia) — solo visible si
     S.page8 está definido. -->
<div class="page" id="page8">
  <div class="month-bar" style="text-align:right"><span id="month-bar8">—</span></div>

  <div id="page8-pending" class="hidden">
    <p class="small placeholder" style="margin-top:16px">Página 8 aún no definida para este fondo.</p>
  </div>

  <div id="page8-body" class="hidden">
    <div class="section-title">Notas</div>
    <ol id="lst-notas-8" style="font-size:10px;font-style:italic;color:#000;padding-left:18px;line-height:1.9"></ol>
    <p class="small" id="txt-nota-final-8" style="font-style:italic;margin-top:10px"></p>
  </div>
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

<div id="export-modal-bg" class="trace-modal-bg export-modal-bg" aria-hidden="true">
  <div class="trace-modal export-modal" id="export-modal" data-state="form" role="dialog" aria-modal="true" aria-labelledby="export-title">
    <button type="button" class="trace-close" id="export-close" aria-label="Cerrar">×</button>

    <div class="export-view export-view-form">
      <h3 id="export-title">⬇ Exportar a PDF</h3>
      <div class="trace-sub">Elige uno o más fondos y el período a exportar. Se descarga un .zip con un PDF por fondo.</div>

      <div class="export-field">
        <div class="export-field-label">Fondos</div>
        <div id="export-fund-checks" class="export-fund-checks"></div>
      </div>

      <div class="export-row">
        <div class="export-field">
          <div class="export-field-label">Período operacional</div>
          <select id="export-sel-op" class="export-select"></select>
        </div>
        <div class="export-field">
          <div class="export-field-label">Período EEFF</div>
          <select id="export-sel-cb" class="export-select"></select>
        </div>
      </div>

      <div id="export-status" class="export-status"></div>
      <button type="button" id="export-download-btn" class="export-download-btn">
        <span class="export-btn-label">Descargar</span>
      </button>
    </div>

    <div class="export-view export-view-loading">
      <div class="export-spinner-big" aria-hidden="true"></div>
      <div class="export-loading-title">Generando<span id="export-loading-dots"></span></div>
      <div class="export-loading-sub" id="export-loading-sub">Esto puede tardar hasta un minuto por fondo.</div>
    </div>

    <div class="export-view export-view-result">
      <div class="export-result-icon" id="export-result-icon"></div>
      <div class="export-result-msg" id="export-result-msg"></div>
      <button type="button" class="export-secondary-btn" id="export-retry-btn">Volver</button>
    </div>
  </div>
</div>

<script>
(function(){
  // Mantiene el sidebar y el margen del contenido con tamaño de pantalla constante
  // sin importar el zoom nativo del navegador (Ctrl +/-), que escala devicePixelRatio.
  var baseDPR = window.devicePixelRatio || 1;
  var SIDEBAR_W = 300, MAIN_ML = 252;
  function applyZoomLock(){
    var ratio = (window.devicePixelRatio || 1) / baseDPR;
    if (!ratio || !isFinite(ratio) || ratio <= 0) ratio = 1;
    var sidebar = document.getElementById("sidebar");
    var main = document.getElementById("main-content");
    if (sidebar){
      // Ancho fijo real + reescala uniforme (contenido incluido) para
      // cancelar el zoom del navegador y que quede pixel-idéntico siempre.
      sidebar.style.width = SIDEBAR_W + "px";
      sidebar.style.height = (window.innerHeight * ratio) + "px";
      sidebar.style.transformOrigin = "top left";
      sidebar.style.transform = "scale(" + (1 / ratio) + ")";
    }
    if (main){
      main.style.marginLeft = (MAIN_ML / ratio) + "px";
    }
  }
  window.addEventListener("resize", applyZoomLock);
  applyZoomLock();
})();

const FUNDS = __DATA_JSON__;
const KPI_META = __KPI_META_JSON__;
const MESES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
const MESES_ABR = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

function mesEspanol(p){ if(!p) return ""; const [y,m]=p.split("-"); return MESES[parseInt(m,10)-1]+" "+y; }
function slug(s){ return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"").replace(/[^a-z0-9]+/g,"-"); }
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
// ---- Sincronización de trimestre entre selector operacional (mensual) y contable/bursátil (trimestral) ----
// No deben poder mostrarse dos períodos de trimestres distintos al mismo tiempo.
function quarterId(p){
  const [y,m] = p.split("-");
  return parseInt(y,10)*10 + Math.ceil(parseInt(m,10)/3);
}
function quarterEndPeriodo(p){
  const [y,m] = p.split("-");
  const endMonth = Math.ceil(parseInt(m,10)/3)*3;
  return y+"-"+String(endMonth).padStart(2,"0");
}
function quarterStartPeriodo(p){
  const [y,m] = p.split("-");
  const startMonth = Math.ceil(parseInt(m,10)/3)*3-2;
  return y+"-"+String(startMonth).padStart(2,"0");
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

function fmtMonthLabel(p){
  const [y, m] = p.split("-");
  const meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  return meses[parseInt(m, 10) - 1] + " " + y;
}

function refreshExportPeriodos(){
  const checked = Array.from(document.querySelectorAll("#export-fund-checks input:checked")).map(i => i.value);
  document.querySelectorAll(".export-fund-chip").forEach(chip => {
    chip.classList.toggle("checked", chip.querySelector("input").checked);
  });

  const opSel = document.getElementById("export-sel-op");
  const cbSel = document.getElementById("export-sel-cb");
  const opPrev = opSel.value;
  const cbPrev = cbSel.value;

  const opSet = new Set();
  const cbSet = new Set();
  checked.forEach(f => {
    Object.keys(FUNDS[f].fondo_kpi || {}).forEach(p => opSet.add(p));
    Object.keys(FUNDS[f].contable || {})
      .filter(p => ["03","06","09","12"].includes(p.slice(-2)))
      .forEach(p => cbSet.add(p));
  });

  const opList = Array.from(opSet).sort();
  const cbList = Array.from(cbSet).sort();

  opSel.innerHTML = opList.map(p => `<option value="${p}">${fmtMonthLabel(p)}</option>`).join("");
  cbSel.innerHTML = cbList.map(p => `<option value="${p}">${fmtQ(p)}</option>`).join("");

  if (opList.includes(opPrev)) opSel.value = opPrev; else if (opList.length) opSel.value = opList[opList.length - 1];
  if (cbList.includes(cbPrev)) cbSel.value = cbPrev; else if (cbList.length) cbSel.value = cbList[cbList.length - 1];

  document.getElementById("export-download-btn").disabled = checked.length === 0;
}

function setExportStatus(kind, html){
  const status = document.getElementById("export-status");
  status.className = "export-status" + (kind ? " " + kind : "");
  status.innerHTML = html || "";
}

let exportDotsTimer = null;
function startExportDots(){
  const el = document.getElementById("export-loading-dots");
  let n = 0;
  el.textContent = "";
  exportDotsTimer = setInterval(() => {
    n = (n + 1) % 4;
    el.textContent = ".".repeat(n);
  }, 450);
}
function stopExportDots(){
  if (exportDotsTimer) { clearInterval(exportDotsTimer); exportDotsTimer = null; }
}

function setExportView(state){
  document.getElementById("export-modal").dataset.state = state;
  if (state === "loading") startExportDots(); else stopExportDots();
}

let exportAbortController = null;

function openExportModal(){
  const wrap = document.getElementById("export-fund-checks");
  wrap.innerHTML = Object.keys(FUNDS).map(f => `
    <label class="export-fund-chip${f === currentFund ? " checked" : ""}">
      <input type="checkbox" value="${f}" ${f === currentFund ? "checked" : ""}> ${f}
    </label>
  `).join("");
  wrap.querySelectorAll("input").forEach(i => i.addEventListener("change", refreshExportPeriodos));
  refreshExportPeriodos();
  setExportStatus(null, "");
  setExportView("form");
  document.getElementById("export-modal-bg").classList.add("open");
}

function closeExportModal(){
  if (exportAbortController) { exportAbortController.abort(); exportAbortController = null; }
  document.getElementById("export-modal-bg").classList.remove("open");
}

function backToExportForm(){
  setExportView("form");
}

async function onDescargarPdf(){
  const fondos = Array.from(document.querySelectorAll("#export-fund-checks input:checked")).map(i => i.value);
  if (!fondos.length) return;
  const periodo_op = document.getElementById("export-sel-op").value;
  const periodo_cb = document.getElementById("export-sel-cb").value;

  document.getElementById("export-loading-sub").textContent = fondos.length > 1
    ? `Generando ${fondos.length} PDFs… puede tardar hasta un minuto por fondo.`
    : "Esto puede tardar hasta un minuto.";
  setExportView("loading");

  exportAbortController = new AbortController();
  try {
    const headers = {"Content-Type": "application/json"};
    if (window.INGESTA_TOKEN) headers["X-Ingesta-Token"] = window.INGESTA_TOKEN;
    const resp = await fetch("/api/export-pdf", {
      method: "POST",
      headers,
      body: JSON.stringify({ fondos, periodo_cb, periodo_op }),
      signal: exportAbortController.signal,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      document.getElementById("export-result-icon").className = "export-result-icon err";
      document.getElementById("export-result-icon").textContent = "✕";
      document.getElementById("export-result-msg").textContent = err.error || resp.statusText;
      setExportView("result");
      return;
    }
    const okCount = parseInt(resp.headers.get("X-Export-Ok") || fondos.length, 10);
    const errCount = parseInt(resp.headers.get("X-Export-Errors") || "0", 10);

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `factsheets_${periodo_op}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    if (errCount > 0) {
      document.getElementById("export-result-icon").className = "export-result-icon warn";
      document.getElementById("export-result-icon").textContent = "⚠";
      document.getElementById("export-result-msg").textContent =
        `Descargado con ${okCount} de ${okCount + errCount} fondos (revisa errores.txt en el zip).`;
      setExportView("result");
    } else {
      document.getElementById("export-result-icon").className = "export-result-icon ok";
      document.getElementById("export-result-icon").textContent = "✓";
      document.getElementById("export-result-msg").textContent =
        `Descarga lista (${okCount} PDF${okCount === 1 ? "" : "s"}).`;
      setExportView("result");
      setTimeout(closeExportModal, 1400);
    }
  } catch (exc) {
    if (exc.name === "AbortError") return;
    document.getElementById("export-result-icon").className = "export-result-icon err";
    document.getElementById("export-result-icon").textContent = "✕";
    document.getElementById("export-result-msg").textContent = "Error inesperado: " + exc;
    setExportView("result");
  } finally {
    exportAbortController = null;
  }
}

function fmtCLP(v){ if(v==null||isNaN(v)) return "—"; return "$"+Math.round(v).toLocaleString("es-CL"); }
function fmtMiles(v){ if(v==null||isNaN(v)) return "—"; return Math.round(v/1000).toLocaleString("es-CL"); }
function fmtPct(v,d=1){ if(v==null||isNaN(v)) return "—"; return (v*100).toFixed(d).replace(".",",")+"%"; }
function fmtNum(v,d=1){ if(v==null||isNaN(v)) return "—"; return Number(v).toFixed(d).replace(".",","); }
function fmtEnteroMiles(v){ if(v==null||isNaN(v)) return "—"; return Math.round(v).toLocaleString("es-CL"); }
function fmtFechaCorta(iso){ if(!iso) return ""; const p=iso.split("-"); return p[2]+"-"+p[1]+"-"+p[0]; }
function fmtTrimestre(iso){ if(!iso) return ""; const [y,m]=iso.split("-"); return `${Math.ceil(Number(m)/3)}Q${y.slice(2)}`; }
function fmtMesAno(periodo){ if(!periodo) return ""; const [y,m]=periodo.split("-"); return `${m}-${y.slice(2)}`; }

// Del diccionario {periodo: valor} (años "YYYY" o meses "YYYY-MM", comparables
// como string), devuelve la entrada con el período más reciente <= target.
function latestAtOrBefore(dict, target){
  if (!dict || !target) return null;
  const keys = Object.keys(dict).filter(k => k <= target).sort();
  if (!keys.length) return null;
  const k = keys[keys.length - 1];
  return { periodo: k, value: dict[k] };
}

// Página 3 — tabla de Tasaciones (edificio/tenant): recalcula año de
// tasación y mes de deuda vigentes según el período operacional seleccionado
// (usadoOp) — "último dato disponible <= usadoOp", así en 2026 sigue
// mostrando la tasación 2025 mientras no exista una más nueva.
function fillTasaciones(F, p3, usadoOp, tbodyId, deudaTheadId, compTheadPrevId, compTheadActualId, compTbodyId){
  const td = F.tasaciones;
  const edificios = p3.tasaciones_edificios;
  const n = edificios.length;
  const selectedYear = usadoOp ? usadoOp.slice(0, 4) : null;

  const perEdificio = {};
  edificios.forEach(nombre => {
    const e = td && td.edificios[nombre];
    const years = e && e.years ? Object.keys(e.years).sort() : [];
    const atOrBefore = selectedYear ? years.filter(y => y <= selectedYear) : years;
    const actualYear = atOrBefore.length ? atOrBefore[atOrBefore.length - 1] : null;
    const priorYears = actualYear ? years.filter(y => y < actualYear) : [];
    const prevYear = priorYears.length ? priorYears[priorYears.length - 1] : null;
    perEdificio[nombre] = {
      actual: actualYear ? { periodo: actualYear, ...e.years[actualYear] } : null,
      prev: prevYear ? { periodo: prevYear, ...e.years[prevYear] } : null,
    };
  });

  const actualYears = edificios.map(nombre => perEdificio[nombre].actual && perEdificio[nombre].actual.periodo).filter(Boolean).sort();
  const fundActualYear = actualYears.length ? actualYears[actualYears.length - 1] : null;
  const prevYears = edificios.map(nombre => perEdificio[nombre].prev && perEdificio[nombre].prev.periodo).filter(Boolean).sort();
  const fundPrevYear = prevYears.length ? prevYears[prevYears.length - 1] : null;

  let totalValorActual = 0, totalValorPrev = 0, anyActual = false, anyPrev = false;
  edificios.forEach(nombre => {
    const a = perEdificio[nombre].actual, p = perEdificio[nombre].prev;
    if (a) { totalValorActual += a.valor_uf || 0; anyActual = true; }
    if (p) { totalValorPrev += p.valor_uf || 0; anyPrev = true; }
  });
  const totalVarPct = (anyActual && anyPrev && totalValorPrev) ? (totalValorActual - totalValorPrev) / totalValorPrev : null;

  const deudaFondo = usadoOp ? latestAtOrBefore(td && td.deuda_fondo_por_mes, usadoOp) : null;
  const deudaTotal = deudaFondo ? deudaFondo.value : null;
  const totalLtv = (deudaTotal != null && totalValorActual) ? deudaTotal / totalValorActual : null;

  document.getElementById(deudaTheadId).textContent =
    deudaFondo ? `Deuda (${fmtMesAno(deudaFondo.periodo)})` : "Deuda";
  const deudaCell = deudaTotal != null ? fmtEnteroMiles(deudaTotal) : "—";
  const ltvCell = totalLtv != null ? fmtPct(totalLtv) : "—";

  const porActivo = !!(td && td.deuda_por_activo);
  const rowSnapshot = (nombre, i) => {
    const a = perEdificio[nombre].actual;
    const valor = a ? fmtEnteroMiles(a.valor_uf) : "—";
    const fecha = a && a.fecha ? fmtTrimestre(a.fecha) : "—";
    if (porActivo) {
      const e = td && td.edificios[nombre];
      const deudaEdEntry = usadoOp ? latestAtOrBefore(e && e.deuda_por_mes, usadoOp) : null;
      const deudaEdVal = deudaEdEntry ? deudaEdEntry.value : null;
      const ltvEd = (deudaEdVal != null && a && a.valor_uf) ? deudaEdVal / a.valor_uf : null;
      return `<tr><td>${nombre}</td><td>${valor}</td><td>${fecha}</td><td>${deudaEdVal != null ? fmtEnteroMiles(deudaEdVal) : "—"}</td><td>${ltvEd != null ? fmtPct(ltvEd) : "—"}</td></tr>`;
    }
    const merged = i === 0
      ? `<td rowspan="${n}">${deudaCell}</td><td rowspan="${n}">${ltvCell}</td>`
      : "";
    return `<tr><td>${nombre}</td><td>${valor}</td><td>${fecha}</td>${merged}</tr>`;
  };
  const totalSnapshot =
    `<tr class="row-total"><td>${p3.tasaciones_total_nombre}</td><td>${anyActual ? fmtEnteroMiles(totalValorActual) : "—"}</td><td></td>`
    + `<td>${deudaCell}</td><td>${ltvCell}</td></tr>`;
  document.getElementById(tbodyId).innerHTML =
    edificios.map(rowSnapshot).join("") + totalSnapshot;

  document.getElementById(compTheadPrevId).textContent =
    fundPrevYear ? `Tasación ${fundPrevYear}` : p3.tasaciones_periodo[0];
  document.getElementById(compTheadActualId).textContent =
    fundActualYear ? `Tasación ${fundActualYear}` : p3.tasaciones_periodo[1];

  const placeholderRow3 = (nombre) =>
    `<tr><td>${nombre}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`;
  const rowComp = (nombre) => {
    const a = perEdificio[nombre].actual, p = perEdificio[nombre].prev;
    if (!a) return placeholderRow3(nombre);
    const prevVal = p ? fmtEnteroMiles(p.valor_uf) : "—";
    // fact_tasacion.variacion_pct viene del archivo fuente y a veces no está
    // informado (ver Boulevard 2025) aunque sí tengamos valor_uf de ambos
    // años — se recalcula acá como fallback en vez de dejarlo en "—".
    const varPct = a.variacion_pct != null
      ? a.variacion_pct
      : (p && p.valor_uf ? (a.valor_uf - p.valor_uf) / p.valor_uf : null);
    return `<tr><td>${nombre}</td><td>${prevVal}</td><td>${fmtEnteroMiles(a.valor_uf)}</td><td>${varPct != null ? fmtPct(varPct) : "—"}</td></tr>`;
  };
  const totalComp = anyActual
    ? `<tr class="row-total"><td>${p3.tasaciones_total_nombre}</td><td>${anyPrev ? fmtEnteroMiles(totalValorPrev) : "—"}</td><td>${fmtEnteroMiles(totalValorActual)}</td><td>${totalVarPct != null ? fmtPct(totalVarPct) : "—"}</td></tr>`
    : placeholderRow3(p3.tasaciones_total_nombre);
  document.getElementById(compTbodyId).innerHTML =
    [...edificios.map(rowComp), totalComp].join("");
}
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
  const nuevo = unitState[tabla]==="uf" ? "clp" : "uf";
  for (const t of Object.keys(unitState)) {
    unitState[t] = nuevo;
    localStorage.setItem("factsheet_unit_"+t, nuevo);
  }
  if (typeof currentFund !== "undefined" && currentFund) render();
}

// ---- Aspectos del mes (PT, página 3): texto libre editable por admin,
// persistido en localStorage por fondo+período+fila. Si no hay override, se
// usa el texto autogenerado (Vacancia del Fondo / Parking / Resultados) o
// "Pendiente." (ej. Otros Locales, que no tiene fuente automática). ----
const ASPECTOS_MES_STORE_KEY = "factsheet_aspectos_mes_overrides";
function loadAspectosMesOverrides(){
  try { return JSON.parse(localStorage.getItem(ASPECTOS_MES_STORE_KEY) || "{}"); }
  catch(e){ return {}; }
}
function saveAspectosMesOverride(fondo, periodo, slug, value){
  const store = loadAspectosMesOverrides();
  store[fondo] = store[fondo] || {};
  store[fondo][periodo] = store[fondo][periodo] || {};
  if (value && value.trim() !== "") store[fondo][periodo][slug] = value.trim();
  else delete store[fondo][periodo][slug];
  localStorage.setItem(ASPECTOS_MES_STORE_KEY, JSON.stringify(store));
}
function getAspectosMesOverride(fondo, periodo, slug){
  const store = loadAspectosMesOverrides();
  return (store[fondo] && store[fondo][periodo] && store[fondo][periodo][slug]) || null;
}
// autoTexts: {slug: textoAutogenerado|null}. Actualiza cada <span> de
// txt-aspectos-mes-t con override > autogenerado > "Pendiente.", y habilita
// edición libre cuando body.admin está activo. El guardado NO es automático
// al perder foco (blur no es confiable acá: cualquier re-render — cambio de
// período/fondo, resize, etc. — puede pisar el texto tipeado antes de que el
// blur alcance a persistirlo) — requiere click explícito en el botón
// "Confirmar" que aparece junto al texto en modo admin.
function updateAspectosMesTexts(containerId, fondo, periodo, autoTexts){
  const container = document.getElementById(containerId);
  if (!container) return;
  const isAdmin = document.body.classList.contains("admin");
  container.querySelectorAll("span[id]").forEach(span => {
    const slug = span.id.slice(containerId.length + 1);
    const override = periodo ? getAspectosMesOverride(fondo, periodo, slug) : null;
    const auto = autoTexts ? autoTexts[slug] : null;
    const final = override != null ? override : auto;

    let btn = span.nextElementSibling;
    if (!btn || !btn.classList || !btn.classList.contains("aspecto-mes-confirm")){
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "aspecto-mes-confirm";
      btn.textContent = "Confirmar";
      btn.style.cssText = "margin-left:6px;font-size:10px;padding:1px 6px;cursor:pointer;vertical-align:middle;display:none;";
      span.insertAdjacentElement("afterend", btn);
      btn.addEventListener("click", () => {
        const p = span.dataset.periodo;
        const f = span.dataset.fondo;
        if (!p || !f) return;
        saveAspectosMesOverride(f, p, slug, span.textContent);
        const original = btn.textContent;
        btn.textContent = "✓ Guardado";
        setTimeout(() => { btn.textContent = original; }, 1200);
        span.classList.remove("placeholder");
      });
    }

    // Solo pisar el texto en pantalla si el span no está siendo editado ahora
    // mismo (evita que un re-render por otro motivo borre lo que el usuario
    // está tipeando antes de que alcance a apretar "Confirmar").
    if (document.activeElement !== span) {
      span.textContent = final != null ? final : "Pendiente.";
      span.classList.toggle("placeholder", final == null);
    }
    span.contentEditable = isAdmin && periodo ? "true" : "false";
    btn.style.display = isAdmin && periodo ? "inline-block" : "none";
    span.dataset.periodo = periodo || "";
    span.dataset.fondo = fondo || "";
  });
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
  sel.dataset.prevValue = initial;

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

  // Sincroniza el selector contrario para que nunca queden dos trimestres distintos
  // seleccionados a la vez: op -> siguiente trimestre; cb -> primer mes (adelante) o
  // último mes (atrás) del trimestre elegido.
  window["syncPeriodSelectors"] = function(changedSuffix, oldVal, newVal){
    if (!oldVal || !newVal || oldVal === newVal) return;
    const counterpartSuffix = changedSuffix === "op" ? "cb" : "op";
    const cSel = document.getElementById("sel-periodo-" + counterpartSuffix);
    if (!cSel || !cSel.options.length) return;
    const cOpts = Array.from(cSel.options).map(o => o.value).sort();

    function pickClosest(target){
      if (cOpts.includes(target)) return target;
      const atOrBefore = cOpts.filter(o => o <= target);
      return atOrBefore.length ? atOrBefore[atOrBefore.length - 1] : cOpts[0];
    }

    let target;
    if (changedSuffix === "op") {
      target = quarterEndPeriodo(newVal);
    } else {
      if (quarterId(newVal) === quarterId(oldVal)) return;
      const forward = quarterId(newVal) > quarterId(oldVal);
      target = forward ? quarterStartPeriodo(newVal) : newVal;
    }

    if (quarterId(target) === quarterId(cSel.value)) return;

    const chosen = pickClosest(target);
    if (chosen === cSel.value) return;
    cSel.value = chosen;
    cSel.dispatchEvent(new Event("change"));
  };

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".period-nav-group") && !e.target.closest(".period-dropdown")){
      hidePeriodDropdown();
    }
  });

  sel.addEventListener("change", () => {
    const oldVal = sel.dataset.prevValue;
    const newVal = sel.value;
    sel.dataset.prevValue = newVal;
    updateDisplay();
    if (!window.__syncingPeriodNav) {
      window.__syncingPeriodNav = true;
      try { window.syncPeriodSelectors(suffix, oldVal, newVal); } finally { window.__syncingPeriodNav = false; }
    }
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
    const mercadoMode = p3.modo === "mercado";
    const edificioMode = !mercadoMode && !!p3.edificios;
    const tenantMode = !mercadoMode && !edificioMode;
    document.getElementById("page3-titulo").textContent = p3.titulo;
    document.getElementById("page3-layout-edificio").classList.toggle("hidden", !edificioMode);
    document.getElementById("page3-layout-tenant").classList.toggle("hidden", !tenantMode);
    document.getElementById("page3-layout-mercado").classList.toggle("hidden", !mercadoMode);

    const donutPending = (containerId) => {
      document.getElementById(containerId).innerHTML =
        `<div class="chart-placeholder" style="width:100%">Pendiente de datos</div>`;
    };
    const fillFotos = (containerId, fotosList) => {
      document.getElementById(containerId).innerHTML =
        fotosList.map(({caption, src}, i) => {
          const body = src
            ? `<img src="${src}" alt="${caption}">`
            : `<div class="foto-placeholder">📷<br>${caption}<br>(sin foto)</div>`;
          const cls = i === 0 ? " foto-big" : "";
          return `<div class="${cls.trim()}"><div class="foto-box">${body}</div><div class="foto-caption">${caption}</div></div>`;
        }).join("");
    };
    const _aspSlug = (k) => k.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
    const fillAspectos = (containerId) => {
      document.getElementById(containerId).innerHTML =
        p3.aspectos.map(([k,v]) => v == null
          ? `<tr><td>${k}</td><td class="placeholder" id="${containerId}-${_aspSlug(k)}">—</td></tr>`
          : `<tr><td>${k}</td><td>${v}</td></tr>`
        ).join("");
    };
    const fillAspectosMes = (containerId) => {
      document.getElementById(containerId).innerHTML =
        p3.aspectos_mes.map(([k]) =>
          `<p><b>${k}:</b> <span class="placeholder" id="${containerId}-${_aspSlug(k)}">Pendiente.</span></p>`
        ).join("");
    };
    // Tasaciones (valores reales, dependientes del período) se llenan en
    // render(), que corre justo después y sí tiene acceso al período
    // seleccionado (usadoOp) — ver fillTasaciones() a nivel de módulo.

    if (edificioMode) {
      // Layout Apo — sin cambios respecto al original.
      fillAspectos("tbl-aspectos");
      fillFotos("grid-fotos", p3.edificios.map(n => ({ caption: n, src: p3.fotos[n] })));
      donutPending("donut-gla"); // donut-ingresos lo llena render() con dato real si existe
      fillAspectosMes("txt-aspectos-mes");

      // El contenido real (forma del edificio por piso / treemap de locales)
      // depende del período operacional (usadoOp), así que solo se deja acá
      // el cascarón — se rellena en render(), ver renderStatusOficinas /
      // renderStatusLocales más abajo.
      const statusBox = (nombre, slot, titulo) => `
        <div class="chart-box">
          <div class="chart-title">${titulo} ${nombre}</div>
          <div class="status-viz placeholder" id="status-${slot}-${slug(nombre)}">Pendiente de datos</div>
          <div class="occ-pill placeholder" id="status-${slot}-${slug(nombre)}-label">Ocupación: —</div>
        </div>`;
      document.getElementById("grid-status-oficinas").innerHTML =
        p3.status_oficinas.map(([n]) => statusBox(n, "of", "Status Actual Oficinas")).join("");
      document.getElementById("grid-status-locales").innerHTML =
        p3.status_locales.map(([n]) => statusBox(n, "loc", "Status Actual Locales")).join("");

      const [pAnt, pAct] = p3.vacancia_periodo;
      document.getElementById("vacancia-periodo-label").textContent = `(${pAnt} → ${pAct})`;
      // Datos reales (por período operacional) se rellenan en render(), ver
      // bloque "Página 3 Apo: tabla de vacancia por edificio" más abajo —
      // acá solo dejamos la estructura con placeholders para el primer paint.
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
    } else if (tenantMode) {
      // Layout PT (tenant): ids propios sufijo "-t", separados del layout Apo.
      fillAspectos("tbl-aspectos-t");
      fillFotos("grid-fotos-t", p3.fotos_list || []);
      donutPending("donut-gla-t");
      donutPending("donut-ingresos-t");
      fillAspectosMes("txt-aspectos-mes-t");
    }
    // Layout "mercado" (TRI): la tabla/párrafos se rellenan en render(), que
    // corre después de switchFund() y tiene acceso al período seleccionado.
  }

  // Página 4 — notas metodológicas + análisis de mercado (headers solo, datos después de pc/usadoOp)
  document.getElementById("hdr4-nombre").textContent = S.nombre;
  document.getElementById("hdr4-sub").textContent = S.sub;
  const hasPage4 = !!S.page4;
  document.getElementById("page4-pending").classList.toggle("hidden", hasPage4);
  document.getElementById("page4-body").classList.toggle("hidden", !hasPage4);

  // Página 5 — resúmenes de subfondos PT/Apoquindo (hoy solo TRI). Se
  // construye una sola vez acá (clonando <template id="tpl-page5-section">);
  // render() más abajo solo rellena los donuts, que sí dependen del período.
  document.getElementById("hdr5-nombre").textContent = S.nombre;
  document.getElementById("hdr5-sub").textContent = S.sub;
  const hasPage5 = !!S.page5;
  document.getElementById("page5-pending").classList.toggle("hidden", hasPage5);
  document.getElementById("page5-body").classList.toggle("hidden", !hasPage5);
  if (hasPage5) {
    const buildPage5Section = (containerId, sec) => {
      const tpl = document.getElementById("tpl-page5-section");
      const frag = tpl.content.cloneNode(true);
      frag.querySelector(".page5-titulo").textContent = sec.titulo;
      frag.querySelector(".page5-descripcion").textContent = sec.descripcion;
      frag.querySelector(".page5-parrafo-remuneracion").textContent = sec.parrafo_remuneracion;
      const masInfo = frag.querySelector(".page5-parrafo-masinfo");
      masInfo.innerHTML = sec.parrafo_mas_info.replace("Más información", "<strong>Más información</strong>");
      frag.querySelector(".page5-tbl-aspectos tbody").innerHTML =
        sec.aspectos.map(([k, v]) => `<tr><td>${k}</td><td${v === null ? ' class="placeholder page5-aspecto-pendiente" data-key="'+k+'"' : ""}>${v === null ? "—" : v}</td></tr>`).join("");
      const fotos = frag.querySelector(".page5-fotos");
      if (sec.foto_4501 && sec.foto_4700) {
        fotos.innerHTML = `
          <div class="fotos-grid">
            <div class="foto-box"><img src="${sec.foto_4501}"></div>
            <div class="foto-box"><img src="${sec.foto_4700}"></div>
          </div>`;
      } else if (sec.foto) {
        fotos.innerHTML = `<div class="foto-box"><img src="${sec.foto}"></div>`;
      } else {
        fotos.innerHTML = `<div class="foto-box"><div class="foto-placeholder">Pendiente: foto por reemplazar</div></div>`;
      }
      document.getElementById(containerId).innerHTML = "";
      document.getElementById(containerId).appendChild(frag);
    };
    buildPage5Section("page5-section-pt", S.page5.pt);
    buildPage5Section("page5-section-apo", S.page5.apo);
  }

  // Página 6 — INMOSSA + Mall Curicó (headers/estático acá; donuts y
  // superficie/vacancia reales de Curicó se rellenan en render(), ver F.page6).
  document.getElementById("hdr6-nombre").textContent = S.nombre;
  document.getElementById("hdr6-sub").textContent = S.sub;
  const hasPage6 = !!S.page6;
  document.getElementById("page6-pending").classList.toggle("hidden", hasPage6);
  document.getElementById("page6-body").classList.toggle("hidden", !hasPage6);
  if (hasPage6) {
    const inm = S.page6.inmossa;
    document.getElementById("inmossa-titulo").textContent = inm.titulo;
    document.getElementById("txt-inmossa-descripcion").textContent = inm.descripcion;
    document.getElementById("tbl-residencias-tbody").innerHTML =
      inm.residencias.map(([h, c, camas]) => `<tr><td>${h}</td><td>${c}</td><td>${camas}</td></tr>`).join("") +
      `<tr class="row-total"><td>Sub total</td><td></td><td>${inm.residencias_subtotal}</td></tr>`;
    document.getElementById("tbl-inmossa-aspectos").querySelector("tbody").innerHTML =
      inm.aspectos.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");

    const cur = S.page6.curico;
    document.getElementById("curico-titulo").textContent = cur.titulo;
    document.getElementById("txt-curico-descripcion").textContent = cur.descripcion;
    document.getElementById("tbl-curico-aspectos").querySelector("tbody").innerHTML =
      cur.aspectos.map(([k, v]) => `<tr><td>${k}</td><td${v === null ? ' class="placeholder page6-curico-pendiente" data-key="'+k+'"' : ""}>${v === null ? "—" : v}</td></tr>`).join("");
  }

  // Página 7 — Apoquindo 3001 + Bodegas Sucden Chile (headers/estático acá;
  // donuts y superficie/vacancia reales se rellenan en render(), ver F.page7).
  document.getElementById("hdr7-nombre").textContent = S.nombre;
  document.getElementById("hdr7-sub").textContent = S.sub;
  const hasPage7 = !!S.page7;
  document.getElementById("page7-pending").classList.toggle("hidden", hasPage7);
  document.getElementById("page7-body").classList.toggle("hidden", !hasPage7);
  if (hasPage7) {
    const buildPage7Section = (containerId, sec, fotoAspect) => {
      const tpl = document.getElementById("tpl-page7-section");
      const frag = tpl.content.cloneNode(true);
      frag.querySelector(".page7-titulo").textContent = sec.titulo;
      frag.querySelector(".page7-p1").textContent = sec.descripcion_p1;
      frag.querySelector(".page7-p2").textContent = sec.descripcion_p2;
      frag.querySelector(".page7-tbl-aspectos tbody").innerHTML =
        sec.aspectos.map(([k, v]) => `<tr><td>${k}</td><td${v === null ? ' class="placeholder page7-aspecto-pendiente" data-key="'+k+'"' : ""}>${v === null ? "—" : v}</td></tr>`).join("");
      frag.querySelector(".page7-foto").style.aspectRatio = fotoAspect;
      document.getElementById(containerId).innerHTML = "";
      document.getElementById(containerId).appendChild(frag);
    };
    buildPage7Section("page7-section-apo3001", S.page7.apo3001, "158/236");
    buildPage7Section("page7-section-sucden", S.page7.sucden, "252/139");
  }

  // Página 8 (última) — Notas metodológicas. Estático salvo los data-slot
  // fecha-cb/fecha-op/mes-op dentro de S.page8.notas, que ya rellena el
  // mismo mecanismo document-wide usado por la página 4 (ver fillNotasFechas
  // más abajo en render()).
  const hasPage8 = !!S.page8;
  document.getElementById("page8-pending").classList.toggle("hidden", hasPage8);
  document.getElementById("page8-body").classList.toggle("hidden", !hasPage8);
  if (hasPage8) {
    document.getElementById("lst-notas-8").innerHTML = S.page8.notas.map(n => `<li>${n}</li>`).join("");
    document.getElementById("txt-nota-final-8").textContent = S.page8.nota_final;
  }

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
// renta_mensual_uf, renta_uf_vacante, renta_uf_gracia, pct_vacancia_uf,
// absorcion_3m, absorcion_12m} más "__grand_total__|||Total" para la columna
// Total final. Renta en gracia se calcula en _renta_gracia_calculada (ver
// tools/db/ingest_rent_roll_validated.py): Renta Esperada Ponderada si el
// contrato aún no empieza a pagar, si no 0 (no es la columna JLL cruda).
// % vacancia (UF) = renta vacante / (renta mensual + vacante + en gracia).
// Renta en descuento queda en placeholder: no hay columna equivalente en el
// rent roll. Renta mensual/vacante de Bodegas y Estacionamientos de Inmob.
// Boulevard PT SpA llega como el string RENTA_PENDIENTE (tools/db/
// rent_roll_stats.py) porque depende de facturación real, no de la tasa del
// rent roll; % vacancia (UF) se propaga como PENDIENTE en ese caso.
const PERF_ROW_METRIC = {
  "m² útiles": "m2_utiles", "m² vacantes": "m2_vacantes",
  "% vacancia (m²)": "pct_vacancia_m2", "Renta mensual (UF)": "renta_mensual_uf",
  "Renta vacante (UF)": "renta_uf_vacante", "Renta en gracia (UF)": "renta_uf_gracia",
  "% vacancia (UF)": "pct_vacancia_uf",
};
const PERF_ROW_PCT = new Set(["% vacancia (m²)", "% vacancia (UF)"]);
const PERF_ROW_ABSORCION = {
  "Absorción bruta m² 3M": ["absorcion_3m", "bruta_m2"], "Absorción bruta UF 3M": ["absorcion_3m", "bruta_uf"],
  "Absorción neta m² 3M": ["absorcion_3m", "neta_m2"], "Absorción neta UF 3M": ["absorcion_3m", "neta_uf"],
  "Absorción bruta m² 12M": ["absorcion_12m", "bruta_m2"], "Absorción bruta UF 12M": ["absorcion_12m", "bruta_uf"],
  "Absorción neta m² 12M": ["absorcion_12m", "neta_m2"], "Absorción neta UF 12M": ["absorcion_12m", "neta_uf"],
};

function fmtPerfCell(v, esPct){
  if (v === "PENDIENTE") return "Pendiente";
  if (v === null || v === undefined) return "—";
  const s = Number(v).toLocaleString('es-CL', {maximumFractionDigits: 1});
  return esPct ? s + "%" : s;
}

// Página 2 — bloques de gráficos/tablas de "Resumen Performance Activos del
// Fondo", ensamblados dinámicamente según S.page2.charts_layout (lista de
// filas, cada fila una lista de claves de PAGE2_CHART_BOXES). Así cada fondo
// puede tener su propio orden/composición sin duplicar el HTML — ver imagen
// de referencia FS TRI abril 2026 (orden NOI/RCSD arriba, tablas anuales +
// donut rubro al medio, perfil vencimiento + recaudación abajo), distinto del
// orden validado para PT (rubro + tipo activo arriba).
const PAGE2_CHART_BOXES = {
  rubro: `<div class="chart-box">
    <div class="chart-title" id="chart-title-rubro">Composición por Rubro del Arrendatario (UF/mes)</div>
    <div id="chart-rubro" data-chart="rubro-arrendatario">
      <div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>
    </div>
  </div>`,
  tipo_activo: `<div class="chart-box">
    <div class="chart-title" id="chart-title-tipo">Composición por Tipo de Activo (UF/mes)</div>
    <div class="donut-wrap" id="donut-tipo-activo" data-chart="tipo-activo">
      <div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>
    </div>
  </div>`,
  noi_rcsd: `<div class="chart-box">
    <div class="chart-title">Evolución NOI y Ratio de Cobertura de Servicio de Deuda</div>
    <div id="chart-noi-rcsd" data-chart="noi-rcsd">
      <div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>
    </div>
  </div>`,
  ingresos_noi_vacancia: `<div class="chart-box">
    <div class="chart-title">Evolución Ingresos, NOI y Vacancia (%)</div>
    <div id="chart-ingresos-noi-vacancia" data-chart="ingresos-noi-vacancia">
      <div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>
    </div>
  </div>`,
  perfil_vencimiento: `<div class="chart-box">
    <div class="chart-title">Perfil de Vencimiento de Contratos (%)
      <span class="small" style="float:right;font-weight:400;text-transform:none">Plazo medio contratos: <b id="fld-plazo-medio">—</b></span>
    </div>
    <div id="chart-perfil-vencimiento" data-chart="perfil-vencimiento-contratos">
      <div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>
    </div>
  </div>`,
  recaudacion: `<div class="chart-box">
    <div class="chart-title">Recaudación Consolidada U12M
      <span class="small" style="float:right;font-weight:400;text-transform:none">Morosidad promedio: <b id="fld-morosidad">—</b></span>
    </div>
    <div class="chart-placeholder" data-chart="recaudacion-consolidada">Pendiente de datos</div>
  </div>`,
  // Tablas anuales por tipo de activo (fila 2019-2025 + U12M) — pendientes de
  // wire a la DB (no hay fuente consolidada de ingresos/NOI históricos por
  // tipo de activo a nivel fondo todavía). Estructura visual únicamente.
  tablas_anuales: `<div class="chart-box chart-box-stack">
    <div class="chart-title">Ingresos Anuales por Tipo de Activo (UF)</div>
    <div id="tabla-ingresos-anual-tipo-activo" data-chart="ingresos-anual-tipo-activo">
      <div class="chart-placeholder" style="width:100%">Pendiente de datos</div>
    </div>
    <div class="chart-title">NOI Anual por Tipo de Activo (UF)</div>
    <div id="tabla-noi-anual-tipo-activo" data-chart="noi-anual-tipo-activo">
      <div class="chart-placeholder" style="width:100%">Pendiente de datos</div>
    </div>
  </div>`,
};

// Tablas "Ingresos/NOI Anual por Tipo de Activo (UF)" de la página 2 de TRI
// — ver F.tablas_anuales_tri (build_factsheet.py::_fetch_tablas_anuales_tri).
// dataYears: {tipo: {año: valor_uf}}, u12mPorPeriodo: {tipo: {periodo: valor_uf}}
// (rolling, uno por cada mes disponible) — la columna U12M mostrada se resuelve
// al mes seleccionado (usadoOp), no al último dato cargado en la DB.
function renderTablaAnualTipoActivo(containerId, dataYears, u12mPorPeriodo, years, order, usadoOp){
  const el = document.getElementById(containerId);
  if(!el) return;
  if(!dataYears || !years || !years.length){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%">Pendiente de datos</div>`;
    return;
  }
  const periodosDisponibles = [...new Set(
    Object.values(u12mPorPeriodo || {}).flatMap(m => Object.keys(m))
  )].sort();
  const elegibles = periodosDisponibles.filter(p => p <= usadoOp);
  const periodoU12m = elegibles.length ? elegibles[elegibles.length - 1] : periodosDisponibles[periodosDisponibles.length - 1];
  const data = {};
  order.forEach(t => {
    if(!dataYears[t] && !(u12mPorPeriodo[t] || {})[periodoU12m]) return;
    data[t] = { ...(dataYears[t] || {}) };
    if(periodoU12m != null) data[t]["U12M"] = (u12mPorPeriodo[t] || {})[periodoU12m];
  });
  const cols = [...years, "U12M"];
  const tipos = order.filter(t => data[t]);
  const totalRow = cols.map(c => tipos.reduce((s, t) => s + (data[t][c] || 0), 0));
  el.innerHTML = `<table class="tabla-anual-tipo-activo">
    <thead><tr><th></th>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead>
    <tbody>
      ${tipos.map(t => `<tr><td>${t}</td>${cols.map(c => `<td>${fmtEnteroMiles(data[t][c])}</td>`).join("")}</tr>`).join("")}
      <tr class="tabla-anual-total"><td>Total</td>${totalRow.map(v => `<td>${fmtEnteroMiles(v)}</td>`).join("")}</tr>
    </tbody>
  </table>`;
}

const PAGE2_LAYOUT_DEFAULT = [
  ["rubro", "tipo_activo"],
  ["noi_rcsd", "ingresos_noi_vacancia"],
  ["perfil_vencimiento", "recaudacion"],
];

function renderPage2ChartsLayout(layoutRows){
  const rows = layoutRows && layoutRows.length ? layoutRows : PAGE2_LAYOUT_DEFAULT;
  document.getElementById("page2-charts-container").innerHTML = rows.map(row => {
    return `<div class="charts-grid-2">${row.map(k => PAGE2_CHART_BOXES[k] || "").join("")}</div>`;
  }).join("");
}

// Donut chart (conic-gradient) — data: [[label, pct], ...], pct suma 100.
const DONUT_COLORS = ["#00B27A", "#C8ECD8", "#7FCDA0", "#E0E0E0"];
function renderDonut(containerId, data, options = {}){
  let acc = 0;
  const stops = data.map(([, pct], i) => {
    const start = acc; acc += pct;
    return `${DONUT_COLORS[i % DONUT_COLORS.length]} ${start}% ${acc}%`;
  }).join(", ");
  // Etiquetas de % centradas en el anillo (radio medio), en el ángulo medio de
  // cada segmento. Anillo grueso (inset 36px sobre donut de 150px -> banda de
  // 39px) para que el texto no toque ni el hueco central ni el borde exterior.
  let accLabel = 0;
  const R = 75, RING_R = 60;
  // Etiquetas selectivas: bajo ~6% el arco es demasiado angosto para un
  // número sin chocar con el vecino — esos segmentos quedan solo en la
  // leyenda + tooltip (ver dataviz: "selective direct labels").
  const LABEL_MIN_PCT = 6;
  const labels = data.map(([, pct], i) => {
    const mid = accLabel + pct / 2; accLabel += pct;
    if (pct < LABEL_MIN_PCT) return "";
    const angle = (mid / 100) * 2 * Math.PI;
    const x = R + RING_R * Math.sin(angle);
    const y = R - RING_R * Math.cos(angle);
    const color = DONUT_COLORS[i % DONUT_COLORS.length];
    const claro = color === "#E0E0E0" || color === "#C8ECD8";
    return `<span class="donut-pct" style="left:${x}px; top:${y}px; color:${claro ? "#33413b" : "#fff"}">${pct}%</span>`;
  }).join("");
  let accHit = 0;
  const polar = (radius, pct) => {
    const angle = (pct / 100) * 2 * Math.PI;
    return [R + radius * Math.sin(angle), R - radius * Math.cos(angle)];
  };
  const hitPaths = data.map(([, pct], i) => {
    const start = accHit, end = accHit + pct; accHit = end;
    if (pct <= 0) return "";
    const outerR = 75, innerR = 36;
    const [x1, y1] = polar(outerR, start);
    const [x2, y2] = polar(outerR, end);
    const [x3, y3] = polar(innerR, end);
    const [x4, y4] = polar(innerR, start);
    const large = pct > 50 ? 1 : 0;
    return `<path class="donut-hit" data-i="${i}" d="M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${outerR} ${outerR} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} L ${x3.toFixed(2)} ${y3.toFixed(2)} A ${innerR} ${innerR} 0 ${large} 0 ${x4.toFixed(2)} ${y4.toFixed(2)} Z" fill="transparent" pointer-events="all"/>`;
  }).join("");
  const legend = data.map(([label, pct], i) =>
    `<div class="row" data-i="${i}"><span class="dot" style="background:${DONUT_COLORS[i % DONUT_COLORS.length]}"></span>` +
    `<span class="lbl">${label}</span><span class="pct">${pct}%</span></div>`
  ).join("");
  document.getElementById(containerId).innerHTML =
    `<div class="donut" style="background:conic-gradient(${stops})">${labels}<svg class="donut-hit-layer" viewBox="0 0 150 150" aria-hidden="true">${hitPaths}</svg></div><div class="donut-legend">${legend}</div><div class="donut-tooltip" aria-hidden="true"></div>`;

  const el = document.getElementById(containerId);
  const tooltip = el.querySelector(".donut-tooltip");
  const legendRows = el.querySelectorAll(".donut-legend .row");
  const hasTooltip = data.some(d => d[2] && (d[2].value !== undefined || d[2].tooltip !== undefined));
  if (!hasTooltip) return;

  const htmlLine = (label, value, color) =>
    `<div class="line"><span class="label"><span class="dot" style="background:${color}"></span>${label}</span><span class="value">${value}</span></div>`;
  const positionTooltip = (event) => {
    const r = el.getBoundingClientRect();
    const left = Math.max(92, Math.min(el.clientWidth - 92, event.clientX - r.left));
    const top = Math.max(72, event.clientY - r.top - 8);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  };
  const showTooltip = (i, event) => {
    const [label, pct, meta = {}] = data[i];
    const color = DONUT_COLORS[i % DONUT_COLORS.length];
    const value = meta.value !== undefined ? `${fmtEnteroMiles(meta.value)} ${meta.unit || "UF"}` : (meta.tooltip || "");
    tooltip.innerHTML =
      `<div class="title">${options.tooltipTitle || "Detalle"}</div>` +
      htmlLine(label, value, color) +
      htmlLine("Participación", `${pct}%`, color);
    positionTooltip(event);
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    legendRows.forEach((row, idx) => row.classList.toggle("is-active", idx === i));
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    legendRows.forEach(row => row.classList.remove("is-active"));
  };
  el.querySelectorAll(".donut-hit").forEach(hit => {
    const i = Number(hit.dataset.i);
    hit.addEventListener("mouseenter", (event) => showTooltip(i, event));
    hit.addEventListener("mousemove", (event) => showTooltip(i, event));
    hit.addEventListener("mouseleave", hideTooltip);
  });
  legendRows.forEach(row => {
    const i = Number(row.dataset.i);
    row.addEventListener("mouseenter", (event) => showTooltip(i, event));
    row.addEventListener("mousemove", (event) => showTooltip(i, event));
    row.addEventListener("mouseleave", hideTooltip);
  });
}

// "Composición por Rubro del Arrendatario" / "por Tipo de Activo" - barras
// horizontales de una sola serie, ordenadas ascendente (mayor abajo, como el
// fact sheet de referencia). data: {categoria: valor_uf}.
function renderBarChartHorizontal(containerId, data){
  const el = document.getElementById(containerId);
  const entries = Object.entries(data || {}).filter(([, v]) => v > 0);
  if (!entries.length){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  entries.sort((a, b) => a[1] - b[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const max = Math.max(...entries.map(([, v]) => v));
  const rows = entries.map(([label, v], i) => {
    const pct = total ? Math.round(v / total * 1000) / 10 : 0;
    const width = max ? Math.max(2, v / max * 100) : 0;
    return `<div class="hbar-row" data-i="${i}">` +
      `<span class="hbar-label">${label}</span>` +
      `<span class="hbar-track"><span class="hbar-fill" style="width:${width.toFixed(1)}%"></span></span>` +
      `<span class="hbar-pct">${pct}%</span>` +
      `</div>`;
  }).join("");
  el.innerHTML = `<div class="hbar-chart">${rows}</div><div class="hbar-tooltip" aria-hidden="true"></div>`;

  const tooltip = el.querySelector(".hbar-tooltip");
  const rowEls = el.querySelectorAll(".hbar-row");
  const showTooltip = (i, event) => {
    const [label, v] = entries[i];
    const pct = total ? Math.round(v / total * 1000) / 10 : 0;
    tooltip.innerHTML =
      `<div class="t-title">${label}</div>` +
      `<div class="t-line">Renta mensual<b>${fmtEnteroMiles(v)} UF</b></div>` +
      `<div class="t-line">Participación<b>${pct}%</b></div>`;
    const r = el.getBoundingClientRect();
    tooltip.style.left = `${event.clientX - r.left}px`;
    tooltip.style.top = `${event.clientY - r.top}px`;
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    rowEls.forEach((row, idx) => row.classList.toggle("is-active", idx === i));
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    rowEls.forEach(row => row.classList.remove("is-active"));
  };
  rowEls.forEach(row => {
    const i = Number(row.dataset.i);
    row.addEventListener("mouseenter", (event) => showTooltip(i, event));
    row.addEventListener("mousemove", (event) => showTooltip(i, event));
    row.addEventListener("mouseleave", hideTooltip);
  });
}

// Donut "Composición por Tipo de Activo" (UF/mes) - reusa renderDonut con un
// orden de categorías fijo (`order`, ver FONDOS_CFG[fondo]["page2"]["tipo_activo"])
// para que el color siga siempre a la misma categoría, nunca a su posición/rank.
function renderTipoActivoDonut(containerId, counts, order){
  const el = document.getElementById(containerId);
  if (!counts){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  const total = order.reduce((s, k) => s + (counts[k] || 0), 0);
  const data = order.map(k => {
    const v = counts[k] || 0;
    const pct = total ? Math.round(v / total * 1000) / 10 : 0;
    return [k, pct, { value: v, unit: "UF" }];
  });
  renderDonut(containerId, data, { tooltipTitle: "Renta mensual por tipo de activo" });
}

// "Perfil de Vencimiento de Contratos" (UF/mes) - barras verticales apiladas
// por edificio, una barra por año de vencimiento. data: {por_anio, anios}
// (ver tools/db/rent_roll_stats.py::get_perfil_vencimiento). Colores fijos
// por edificio (mismos que el resto de las páginas Apo: verde = 4501, gris
// oscuro = 4700), no por posición/rank.
const PERFIL_VENC_COLORS = {
  "Apoquindo 4501": "#05A978", "Apoquindo 4700": "#46504D",
  "Torre A S.A.": "#05A978", "Inmob. Boulevard PT SpA": "#46504D",
  // TRI consolidado por categoría (ver FONDOS_CFG.TRI.page2.perfil_vencimiento_edificios
  // y tools/db/rent_roll_stats.py::get_perfil_vencimiento_tri).
  "Oficinas": "#05A978", "Activos Comerciales": "#8C948F",
  "Residencias": "#1F2A26", "Bodegas": "#8FE3C7",
};
function renderStackedBarChart(containerId, data, edificios){
  const el = document.getElementById(containerId);
  if (!data){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  const { por_anio, anios } = data;
  // Eje Y en % de la renta mensual total del portafolio (no UF absolutas) —
  // igual al fact sheet de referencia. El UF sigue disponible en el tooltip.
  const totalesUf = anios.map(a => edificios.reduce((s, ed) => s + ((por_anio[ed] || {})[a] || 0), 0));
  const granTotalUf = totalesUf.reduce((s, v) => s + v, 0);
  const pctOf = v => granTotalUf ? (v / granTotalUf) * 100 : 0;
  const totales = totalesUf.map(pctOf);
  const max = Math.max(1, ...totales);
  const W = 900, H = 280, padL = 78, padR = 16, padT = 18, padB = 46;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = anios.length;
  const bw = Math.max(6, (plotW / n) * 0.55);
  const x = i => padL + (i + 0.5) * (plotW / n);
  const yMax = Math.ceil(max / 5) * 5 || max;
  const y = v => padT + plotH - (v / yMax) * plotH;

  const nGrid = 5;
  let gridLines = "", yLabels = "";
  for (let g = 0; g <= nGrid; g++){
    const v = yMax * g / nGrid;
    const yy = padT + plotH - plotH * g / nGrid;
    gridLines += `<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="${g===0?'#AEBBB5':'#E8EEEB'}" stroke-width="${g===0?1.2:1}"/>`;
    yLabels += `<text x="${padL-8}" y="${yy+5}" font-size="20" text-anchor="end" fill="#6D7C75">${Math.round(v)}%</text>`;
  }

  const RX = Math.min(4, bw / 4);
  const bars = anios.map((a, i) => {
    let acc = 0;
    const xb = x(i) - bw / 2;
    const presentes = edificios.filter(ed => ((por_anio[ed] || {})[a] || 0) > 0);
    const segs = edificios.map(ed => {
      const v = pctOf((por_anio[ed] || {})[a] || 0);
      if (!v) return "";
      const yTop = y(acc + v), yBot = y(acc);
      const esUltimo = ed === presentes[presentes.length - 1];
      acc += v;
      // Solo el segmento superior de la pila lleva esquinas redondeadas —
      // simulado con dos rects (uno recto detrás, uno redondeado encima)
      // porque SVG <rect> no soporta radios "solo arriba".
      if (esUltimo && (yBot - yTop) > RX) {
        const hFlat = (yBot - yTop) - RX;
        return `<rect class="vc-bar-seg" x="${xb.toFixed(1)}" y="${(yTop+RX).toFixed(1)}" width="${bw.toFixed(1)}" height="${hFlat.toFixed(1)}" fill="${PERFIL_VENC_COLORS[ed] || '#999'}"/>` +
               `<rect class="vc-bar-seg" x="${xb.toFixed(1)}" y="${yTop.toFixed(1)}" width="${bw.toFixed(1)}" height="${(RX*2).toFixed(1)}" rx="${RX}" fill="${PERFIL_VENC_COLORS[ed] || '#999'}"/>`;
      }
      return `<rect class="vc-bar-seg" x="${xb.toFixed(1)}" y="${yTop.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0,yBot-yTop).toFixed(1)}" fill="${PERFIL_VENC_COLORS[ed] || '#999'}"/>`;
    }).join("");
    return `<g class="vc-col" data-i="${i}">${segs}</g>`;
  }).join("");

  const xLabels = anios.map((a, i) =>
    `<text x="${x(i).toFixed(1)}" y="${H-8}" font-size="20" text-anchor="middle" fill="#6D7C75">${a}</text>`
  ).join("");

  const hoverRects = anios.map((a, i) =>
    `<rect class="vc-hit" data-i="${i}" x="${(x(i)-(plotW/n)/2).toFixed(1)}" y="${padT}" width="${(plotW/n).toFixed(1)}" height="${plotH}" fill="transparent" pointer-events="all"/>`
  ).join("");

  const legend = edificios.map(ed =>
    `<span style="display:inline-flex;align-items:center;gap:4px;margin:0 10px;font-size:11px;color:#6D7C75">` +
    `<span style="width:10px;height:10px;border-radius:2px;display:inline-block;background:${PERFIL_VENC_COLORS[ed] || '#999'}"></span>${ed}</span>`
  ).join("");

  el.innerHTML = `
    <div class="parking-chart">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Perfil de vencimiento de contratos por edificio">
        ${gridLines}
        ${bars}
        ${yLabels}${xLabels}
        ${hoverRects}
      </svg>
      <div class="parking-tooltip" aria-hidden="true"></div>
      <div class="chart-legend" style="text-align:center;margin-top:4px">${legend}</div>
    </div>`;

  const wrap = el.querySelector(".parking-chart");
  const svg = el.querySelector("svg");
  const tooltip = el.querySelector(".parking-tooltip");
  const cols = el.querySelectorAll(".vc-col");
  const toPx = (vx, vy) => {
    const s = svg.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return { left: s.left - w.left + (vx / W) * s.width, top: s.top - w.top + (vy / H) * s.height };
  };
  const htmlLine = (label, value, color) =>
    `<div class="line"><span class="label"><span class="dot" style="background:${color}"></span>${label}</span><span class="value">${value}</span></div>`;
  const showTooltip = (i) => {
    const a = anios[i];
    const lines = edificios
      .map(ed => [ed, (por_anio[ed] || {})[a] || 0])
      .filter(([, v]) => v > 0)
      .map(([ed, v]) => htmlLine(ed, `${pctOf(v).toFixed(1)}% (${Math.round(v).toLocaleString('es-CL')} UF)`, PERFIL_VENC_COLORS[ed] || '#999'))
      .join("");
    if (!lines) { tooltip.classList.remove("on"); return; }
    tooltip.innerHTML = `<div class="title">${a}</div>${lines}`;
    const p = toPx(x(i), y(totales[i]));
    tooltip.style.left = `${Math.max(88, Math.min(wrap.clientWidth - 88, p.left))}px`;
    tooltip.style.top = `${Math.max(74, p.top - 8)}px`;
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    cols.forEach(c => c.classList.toggle("is-active", Number(c.dataset.i) === i));
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    cols.forEach(c => c.classList.remove("is-active"));
  };
  el.querySelectorAll(".vc-hit").forEach(hit => {
    const i = Number(hit.dataset.i);
    hit.addEventListener("mouseenter", () => showTooltip(i));
    hit.addEventListener("mousemove", () => showTooltip(i));
    hit.addEventListener("mouseleave", hideTooltip);
  });
}

// "Resultados Parking (UF)" - barras apiladas + lineas de resultado y ocupación.
function renderParkingChart(containerId, rows){
  const el = document.getElementById(containerId);
  if (!rows || !rows.length){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  const C = {
    abonados: "#46504D",
    variables: "#05A978",
    resultado: "#2C6FB3",
    ocupacion: "#D49B28",
    grid: "#E8EEEB",
    axis: "#AEBBB5",
    text: "#6D7C75"
  };
  const W = 900, H = 280, padL = 52, padR = 48, padT = 18, padB = 34;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = rows.length;
  const x = i => padL + (i + 0.5) * (plotW / n);
  const bw = Math.max(3, (plotW / n) * 0.50);

  const maxUf = Math.max(1, ...rows.map(r => (r.abonados_uf||0) + (r.variables_uf||0)), ...rows.map(r => r.resultado_uf||0));
  const yMax = Math.ceil(maxUf / 500) * 500;
  const maxOcc = Math.max(0.1, ...rows.map(r => r.ocupacion||0));
  const yMaxPct = Math.min(1, Math.ceil(maxOcc / 0.1) * 0.1 + 0.1);
  const yUf = v => padT + plotH - (v / yMax) * plotH;
  const yPct = v => padT + plotH - (v / yMaxPct) * plotH;

  const nGrid = 5;
  let gridLines = "", yLabelsL = "", yLabelsR = "";
  for (let g = 0; g <= nGrid; g++){
    const vUf = yMax * g / nGrid, vPct = yMaxPct * g / nGrid;
    const y = padT + plotH - plotH * g / nGrid;
    const strong = g === 0;
    gridLines += `<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="${strong ? C.axis : C.grid}" stroke-width="${strong ? 1.2 : 1}"/>`;
    yLabelsL += `<text x="${padL-8}" y="${y+3}" font-size="10" text-anchor="end" fill="${C.text}">${vUf.toLocaleString('es-CL')}</text>`;
    yLabelsR += `<text x="${W-padR+8}" y="${y+3}" font-size="10" text-anchor="start" fill="${C.text}">${Math.round(vPct*100)}%</text>`;
  }
  const axisLabels =
    `<text x="${padL}" y="10" font-size="10" font-weight="700" text-anchor="start" fill="${C.text}">UF</text>` +
    `<text x="${W-padR}" y="10" font-size="10" font-weight="700" text-anchor="end" fill="${C.text}">Ocup.</text>`;

  const bars = rows.map((r,i) => {
    const abon = r.abonados_uf||0, vari = r.variables_uf||0;
    const xb = x(i) - bw/2;
    const yAbonTop = yUf(abon), yBase = yUf(0), yVariTop = yUf(abon+vari);
    return `<rect x="${xb.toFixed(1)}" y="${yAbonTop.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0,yBase-yAbonTop).toFixed(1)}" rx="2" fill="${C.abonados}"/>` +
           `<rect x="${xb.toFixed(1)}" y="${yVariTop.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0,yAbonTop-yVariTop).toFixed(1)}" rx="2" fill="${C.variables}"/>`;
  }).join("");

  const path = (fn) => rows.map((r,i) => `${i===0?'M':'L'}${x(i).toFixed(1)},${fn(r).toFixed(1)}`).join(" ");
  const lineRes = path(r => yUf(r.resultado_uf||0));
  const lineOcc = path(r => yPct(r.ocupacion||0));

  const monthLabels = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun", 7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic"};
  const pxPerMonth = plotW / n;
  const tickInterval = pxPerMonth >= 42 ? 1 : (pxPerMonth >= 28 ? 2 : 3);
  const xLabels = rows.map((r,i) => {
    const [y,m] = r.periodo.split("-");
    const mm = parseInt(m,10);
    const quarterMonth = [3, 6, 9, 12].includes(mm);
    const showTick = tickInterval === 3 ? quarterMonth : (i % tickInterval === 0);
    if (!showTick) return "";
    const xx = x(i);
    const label = `${monthLabels[mm]}-${y.slice(2)}`;
    return `<line x1="${xx}" y1="${padT+plotH}" x2="${xx}" y2="${padT+plotH+4}" stroke="${C.axis}" stroke-width="1"/>` +
           `<text x="${xx}" y="${H-11}" font-size="10" text-anchor="middle" fill="${C.text}">${label}</text>`;
  }).join("");
  const hitW = plotW / n;
  const hoverRects = rows.map((r,i) =>
    `<rect class="parking-hit" data-i="${i}" x="${(x(i)-hitW/2).toFixed(1)}" y="${padT}" width="${hitW.toFixed(1)}" height="${plotH}" fill="transparent" pointer-events="all"/>`
  ).join("");

  el.innerHTML = `
    <div class="parking-chart">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Resultados mensuales del parking en UF y ocupación">
        ${gridLines}
        ${axisLabels}
        ${bars}
        <path d="${lineRes}" fill="none" stroke="${C.resultado}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
        <path d="${lineOcc}" fill="none" stroke="${C.ocupacion}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
        <line class="parking-guide" x1="0" x2="0" y1="${padT}" y2="${padT+plotH}" stroke="#26352F" stroke-width="1" stroke-dasharray="3 4" opacity="0"/>
        <circle class="parking-marker parking-marker-res" cx="0" cy="0" r="4.2" fill="#fff" stroke="${C.resultado}" stroke-width="2" opacity="0"/>
        <circle class="parking-marker parking-marker-occ" cx="0" cy="0" r="4.2" fill="#fff" stroke="${C.ocupacion}" stroke-width="2" opacity="0"/>
        ${yLabelsL}${yLabelsR}${xLabels}
        ${hoverRects}
      </svg>
      <div class="parking-tooltip" aria-hidden="true"></div>
      <div class="parking-legend">
        <div class="row"><span class="swatch" style="background:${C.abonados}"></span>Ingresos Abonados</div>
        <div class="row"><span class="swatch" style="background:${C.variables}"></span>Ingresos Variables</div>
        <div class="row"><span class="swatch line" style="background:${C.resultado}"></span>Resultados UF</div>
        <div class="row"><span class="swatch line" style="background:${C.ocupacion}"></span>Ocupación</div>
      </div>
    </div>`;

  const svg = el.querySelector("svg");
  const wrap = el.querySelector(".parking-chart");
  const tooltip = el.querySelector(".parking-tooltip");
  const guide = el.querySelector(".parking-guide");
  const markerRes = el.querySelector(".parking-marker-res");
  const markerOcc = el.querySelector(".parking-marker-occ");
  const toPx = (vx, vy) => {
    const s = svg.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return {
      left: s.left - w.left + (vx / W) * s.width,
      top: s.top - w.top + (vy / H) * s.height
    };
  };
  const htmlLine = (label, value, color) =>
    `<div class="line"><span class="label"><span class="dot" style="background:${color}"></span>${label}</span><span class="value">${value}</span></div>`;
  const showTooltip = (i) => {
    const r = rows[i], xx = x(i);
    const stack = (r.abonados_uf||0) + (r.variables_uf||0);
    const resY = yUf(r.resultado_uf||0), occY = yPct(r.ocupacion||0);
    const p = toPx(xx, Math.min(yUf(stack), resY, occY));
    const [year, month] = r.periodo.split("-");
    const periodo = `${MESES[parseInt(month,10)-1]} ${year}`;
    tooltip.innerHTML =
      `<div class="title">${periodo}</div>` +
      htmlLine("Abonados", `${fmtEnteroMiles(r.abonados_uf)} UF`, C.abonados) +
      htmlLine("Variables", `${fmtEnteroMiles(r.variables_uf)} UF`, C.variables) +
      htmlLine("Resultado", `${fmtEnteroMiles(r.resultado_uf)} UF`, C.resultado) +
      htmlLine("Ocupación", fmtPct(r.ocupacion), C.ocupacion);
    tooltip.style.left = `${Math.max(88, Math.min(wrap.clientWidth - 88, p.left))}px`;
    tooltip.style.top = `${Math.max(74, p.top - 8)}px`;
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    guide.setAttribute("x1", xx);
    guide.setAttribute("x2", xx);
    guide.setAttribute("opacity", "0.42");
    markerRes.setAttribute("cx", xx);
    markerRes.setAttribute("cy", resY);
    markerRes.setAttribute("opacity", "1");
    markerOcc.setAttribute("cx", xx);
    markerOcc.setAttribute("cy", occY);
    markerOcc.setAttribute("opacity", "1");
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    guide.setAttribute("opacity", "0");
    markerRes.setAttribute("opacity", "0");
    markerOcc.setAttribute("opacity", "0");
  };
  el.querySelectorAll(".parking-hit").forEach(hit => {
    const i = Number(hit.dataset.i);
    hit.addEventListener("mouseenter", () => showTooltip(i));
    hit.addEventListener("mousemove", () => showTooltip(i));
    hit.addEventListener("mouseleave", hideTooltip);
  });
}

function renderNoiRcsdChart(containerId, rows, rcsdAxisMax){
  const el = document.getElementById(containerId);
  if (!rows || !rows.length){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  const C = { cuota: "#5B6560", noi: "#05A978", rcsd: "#1B2A25", grid: "#E8EEEB", axis: "#AEBBB5", text: "#6D7C75" };
  const W = 900, H = 280, padL = 52, padR = 48, padT = 18, padB = 34;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = rows.length;
  const x = i => padL + (i + 0.5) * (plotW / n);

  const maxUf = Math.max(1, ...rows.map(r => r.noi_uf || 0));
  const yMax = Math.ceil(maxUf / 2500) * 2500;
  const rcsdVals = rows.map(r => r.rcsd).filter(v => v != null);
  const maxRcsd = Math.max(0.5, ...rcsdVals);
  const yMaxR = rcsdAxisMax || (Math.ceil(maxRcsd / 0.5) * 0.5);
  const yUf = v => padT + plotH - (Math.min(v, yMax) / yMax) * plotH;
  const yR = v => padT + plotH - (Math.min(v, yMaxR) / yMaxR) * plotH;

  const nGrid = 5;
  let gridLines = "", yLabelsL = "", yLabelsR = "";
  for (let g = 0; g <= nGrid; g++){
    const vUf = yMax * g / nGrid, vR = yMaxR * g / nGrid;
    const y = padT + plotH - plotH * g / nGrid;
    const strong = g === 0;
    gridLines += `<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="${strong ? C.axis : C.grid}" stroke-width="${strong ? 1.2 : 1}"/>`;
    yLabelsL += `<text x="${padL-8}" y="${y+5}" font-size="20" text-anchor="end" fill="${C.text}">${Math.round(vUf).toLocaleString('es-CL')}</text>`;
    yLabelsR += `<text x="${W-padR+8}" y="${y+5}" font-size="20" text-anchor="start" fill="${C.text}">${vR.toFixed(1)}x</text>`;
  }
  const axisLabels =
    `<text x="${padL}" y="12" font-size="18" font-weight="700" text-anchor="start" fill="${C.text}">UF</text>` +
    `<text x="${W-padR}" y="12" font-size="18" font-weight="700" text-anchor="end" fill="${C.text}">RCSD</text>`;

  const ptsCuota = rows.map((r,i) => `${x(i).toFixed(1)},${yUf(r.cuota_uf || 0).toFixed(1)}`);
  const ptsNoi = rows.map((r,i) => `${x(i).toFixed(1)},${yUf(Math.max(r.cuota_uf || 0, r.noi_uf || 0)).toFixed(1)}`);
  const yBase0 = yUf(0).toFixed(1);
  const areaCuota = `M${x(0).toFixed(1)},${yBase0} L${ptsCuota.join(' L')} L${x(n-1).toFixed(1)},${yBase0} Z`;
  const areaNoi = `M${ptsCuota.join(' L')} L${[...ptsNoi].reverse().join(' L')} Z`;
  const bars =
    `<path d="${areaCuota}" fill="${C.cuota}"/>` +
    `<path d="${areaNoi}" fill="${C.noi}"/>` +
    `<path d="M${ptsCuota.join(' L')}" fill="none" stroke="${C.cuota}" stroke-width="1.4" stroke-linejoin="round"/>` +
    `<path d="M${ptsNoi.join(' L')}" fill="none" stroke="${C.noi}" stroke-width="1.4" stroke-linejoin="round"/>`;

  let lineRcsd = "", started = false;
  rows.forEach((r,i) => {
    if (r.rcsd == null) { started = false; return; }
    lineRcsd += `${started ? 'L' : 'M'}${x(i).toFixed(1)},${yR(r.rcsd).toFixed(1)} `;
    started = true;
  });

  const monthLabels = {1:"ene",2:"feb",3:"mar",4:"abr",5:"may",6:"jun",7:"jul",8:"ago",9:"sept",10:"oct",11:"nov",12:"dic"};
  const pxPerMonth = plotW / n;
  const tickInterval = pxPerMonth >= 42 ? 4 : (pxPerMonth >= 20 ? 8 : 12);
  const xLabels = rows.map((r,i) => {
    const [y,m] = r.periodo.split("-");
    if (i % tickInterval !== 0) return "";
    const xx = x(i);
    const label = `${monthLabels[parseInt(m,10)]}-${y.slice(2)}`;
    return `<line x1="${xx}" y1="${padT+plotH}" x2="${xx}" y2="${padT+plotH+4}" stroke="${C.axis}" stroke-width="1"/>` +
           `<text x="${xx}" y="${H-6}" font-size="18" text-anchor="middle" fill="${C.text}">${label}</text>`;
  }).join("");
  const hitW = plotW / n;
  const hoverRects = rows.map((r,i) =>
    `<rect class="parking-hit" data-i="${i}" x="${(x(i)-hitW/2).toFixed(1)}" y="${padT}" width="${hitW.toFixed(1)}" height="${plotH}" fill="transparent" pointer-events="all"/>`
  ).join("");

  el.innerHTML = `
    <div class="parking-chart">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Evolución NOI y RCSD">
        ${gridLines}
        ${axisLabels}
        ${bars}
        <path d="${lineRcsd}" fill="none" stroke="${C.rcsd}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
        <line class="parking-guide" x1="0" x2="0" y1="${padT}" y2="${padT+plotH}" stroke="#26352F" stroke-width="1" stroke-dasharray="3 4" opacity="0"/>
        <circle class="parking-marker parking-marker-res" cx="0" cy="0" r="4.2" fill="#fff" stroke="${C.rcsd}" stroke-width="2" opacity="0"/>
        ${yLabelsL}${yLabelsR}${xLabels}
        ${hoverRects}
      </svg>
      <div class="parking-tooltip" aria-hidden="true"></div>
      <div class="parking-legend">
        <div class="row"><span class="swatch" style="background:${C.cuota}"></span>Cuota Financiamiento (UF)</div>
        <div class="row"><span class="swatch" style="background:${C.noi}"></span>NOI (UF)</div>
        <div class="row"><span class="swatch line" style="background:${C.rcsd}"></span>RCSD</div>
      </div>
    </div>`;

  const svg = el.querySelector("svg");
  const wrap = el.querySelector(".parking-chart");
  const tooltip = el.querySelector(".parking-tooltip");
  const guide = el.querySelector(".parking-guide");
  const marker = el.querySelector(".parking-marker-res");
  const toPx = (vx, vy) => {
    const s = svg.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return { left: s.left - w.left + (vx / W) * s.width, top: s.top - w.top + (vy / H) * s.height };
  };
  const htmlLine = (label, value, color) =>
    `<div class="line"><span class="label"><span class="dot" style="background:${color}"></span>${label}</span><span class="value">${value}</span></div>`;
  const showTooltip = (i) => {
    const r = rows[i], xx = x(i);
    const p = toPx(xx, yUf(r.noi_uf || 0));
    const [year, month] = r.periodo.split("-");
    const periodo = `${MESES[parseInt(month,10)-1]} ${year}`;
    tooltip.innerHTML =
      `<div class="title">${periodo}</div>` +
      htmlLine("NOI", `${fmtEnteroMiles(r.noi_uf)} UF`, C.noi) +
      htmlLine("Cuota", `${fmtEnteroMiles(r.cuota_uf)} UF`, C.cuota) +
      htmlLine("RCSD", r.rcsd != null ? `${r.rcsd.toFixed(2)}x` : "—", C.rcsd);
    tooltip.style.left = `${Math.max(88, Math.min(wrap.clientWidth - 88, p.left))}px`;
    tooltip.style.top = `${Math.max(74, p.top - 8)}px`;
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    guide.setAttribute("x1", xx);
    guide.setAttribute("x2", xx);
    guide.setAttribute("opacity", "0.42");
    if (r.rcsd != null) {
      marker.setAttribute("cx", xx);
      marker.setAttribute("cy", yR(r.rcsd));
      marker.setAttribute("opacity", "1");
    } else {
      marker.setAttribute("opacity", "0");
    }
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    guide.setAttribute("opacity", "0");
    marker.setAttribute("opacity", "0");
  };
  el.querySelectorAll(".parking-hit").forEach(hit => {
    const i = Number(hit.dataset.i);
    hit.addEventListener("mouseenter", () => showTooltip(i));
    hit.addEventListener("mousemove", () => showTooltip(i));
    hit.addEventListener("mouseleave", hideTooltip);
  });
}

function renderIngresosNoiVacanciaChart(containerId, rows){
  const el = document.getElementById(containerId);
  if (!rows || !rows.length){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  const single = rows.some(r => r.vacancia_pct !== undefined);
  const C = { ingresos: "#3BB878", noi: "#5B6560", oficinas: "#A6E4D0", locales: "#1B2A25", vacancia: "#1B2A25", grid: "#E8EEEB", axis: "#AEBBB5", text: "#6D7C75" };
  const W = 900, H = 280, padL = 52, padR = 56, padT = 18, padB = 34;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = rows.length;
  const x = i => padL + (i + 0.5) * (plotW / n);

  const maxUf = Math.max(1, ...rows.map(r => r.ingresos_uf || 0));
  const yMax = Math.ceil(maxUf / 2500) * 2500;
  const vacVals = single
    ? rows.map(r => r.vacancia_pct).filter(v => v != null)
    : rows.flatMap(r => [r.vacancia_oficinas_pct, r.vacancia_locales_pct]).filter(v => v != null);
  const maxVac = Math.max(10, ...vacVals);
  const yMaxV = Math.ceil(maxVac / 10) * 10;
  const yUf = v => padT + plotH - (Math.min(v, yMax) / yMax) * plotH;
  const yV = v => padT + plotH - (Math.min(v, yMaxV) / yMaxV) * plotH;

  const nGrid = 5;
  let gridLines = "", yLabelsL = "", yLabelsR = "";
  for (let g = 0; g <= nGrid; g++){
    const vUf = yMax * g / nGrid, vV = yMaxV * g / nGrid;
    const y = padT + plotH - plotH * g / nGrid;
    const strong = g === 0;
    gridLines += `<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="${strong ? C.axis : C.grid}" stroke-width="${strong ? 1.2 : 1}"/>`;
    yLabelsL += `<text x="${padL-8}" y="${y+5}" font-size="20" text-anchor="end" fill="${C.text}">${Math.round(vUf).toLocaleString('es-CL')}</text>`;
    yLabelsR += `<text x="${W-padR+8}" y="${y+5}" font-size="20" text-anchor="start" fill="${C.text}">${Math.round(vV)}%</text>`;
  }
  const axisLabels =
    `<text x="${padL}" y="12" font-size="18" font-weight="700" text-anchor="start" fill="${C.text}">UF</text>` +
    `<text x="${W-padR}" y="12" font-size="18" font-weight="700" text-anchor="end" fill="${C.text}">%</text>`;

  const ptsNoi = rows.map((r,i) => `${x(i).toFixed(1)},${yUf(r.noi_uf || 0).toFixed(1)}`);
  const ptsIngresos = rows.map((r,i) => `${x(i).toFixed(1)},${yUf(Math.max(r.noi_uf || 0, r.ingresos_uf || 0)).toFixed(1)}`);
  const yBase0 = yUf(0).toFixed(1);
  const areaNoi = `M${x(0).toFixed(1)},${yBase0} L${ptsNoi.join(' L')} L${x(n-1).toFixed(1)},${yBase0} Z`;
  const areaIngresos = `M${ptsNoi.join(' L')} L${[...ptsIngresos].reverse().join(' L')} Z`;
  const areas =
    `<path d="${areaNoi}" fill="${C.noi}"/>` +
    `<path d="${areaIngresos}" fill="${C.ingresos}"/>` +
    `<path d="M${ptsNoi.join(' L')}" fill="none" stroke="${C.noi}" stroke-width="1.4" stroke-linejoin="round"/>` +
    `<path d="M${ptsIngresos.join(' L')}" fill="none" stroke="${C.ingresos}" stroke-width="1.4" stroke-linejoin="round"/>`;

  const buildLine = (key, yFn) => {
    let path = "", started = false;
    rows.forEach((r,i) => {
      const v = r[key];
      if (v == null) { started = false; return; }
      path += `${started ? 'L' : 'M'}${x(i).toFixed(1)},${yFn(v).toFixed(1)} `;
      started = true;
    });
    return path;
  };
  const lineVacancia = single ? buildLine("vacancia_pct", yV) : "";
  const lineOficinas = single ? "" : buildLine("vacancia_oficinas_pct", yV);
  const lineLocales = single ? "" : buildLine("vacancia_locales_pct", yV);

  const monthLabels = {1:"ene",2:"feb",3:"mar",4:"abr",5:"may",6:"jun",7:"jul",8:"ago",9:"sept",10:"oct",11:"nov",12:"dic"};
  const pxPerMonth = plotW / n;
  const tickInterval = pxPerMonth >= 42 ? 4 : (pxPerMonth >= 20 ? 8 : 12);
  const xLabels = rows.map((r,i) => {
    const [y,m] = r.periodo.split("-");
    if (i % tickInterval !== 0) return "";
    const xx = x(i);
    const label = `${monthLabels[parseInt(m,10)]}-${y.slice(2)}`;
    return `<line x1="${xx}" y1="${padT+plotH}" x2="${xx}" y2="${padT+plotH+4}" stroke="${C.axis}" stroke-width="1"/>` +
           `<text x="${xx}" y="${H-6}" font-size="18" text-anchor="middle" fill="${C.text}">${label}</text>`;
  }).join("");
  const hitW = plotW / n;
  const hoverRects = rows.map((r,i) =>
    `<rect class="parking-hit" data-i="${i}" x="${(x(i)-hitW/2).toFixed(1)}" y="${padT}" width="${hitW.toFixed(1)}" height="${plotH}" fill="transparent" pointer-events="all"/>`
  ).join("");

  el.innerHTML = `
    <div class="parking-chart">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Evolución Ingresos, NOI y Vacancia">
        ${gridLines}
        ${axisLabels}
        ${areas}
        ${single
          ? `<path d="${lineVacancia}" fill="none" stroke="${C.vacancia}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>`
          : `<path d="${lineOficinas}" fill="none" stroke="${C.oficinas}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
        <path d="${lineLocales}" fill="none" stroke="${C.locales}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>`}
        <line class="parking-guide" x1="0" x2="0" y1="${padT}" y2="${padT+plotH}" stroke="#26352F" stroke-width="1" stroke-dasharray="3 4" opacity="0"/>
        ${yLabelsL}${yLabelsR}${xLabels}
        ${hoverRects}
      </svg>
      <div class="parking-tooltip" aria-hidden="true"></div>
      <div class="parking-legend">
        <div class="row"><span class="swatch" style="background:${C.ingresos}"></span>Ingresos (UF)</div>
        <div class="row"><span class="swatch" style="background:${C.noi}"></span>NOI (UF)</div>
        ${single
          ? `<div class="row"><span class="swatch line" style="background:${C.vacancia}"></span>Vacancia (%)</div>`
          : `<div class="row"><span class="swatch line" style="background:${C.oficinas}"></span>Vacancia (%) Oficinas</div>
        <div class="row"><span class="swatch line" style="background:${C.locales}"></span>Vacancia (%) Locales</div>`}
      </div>
    </div>`;

  const svg = el.querySelector("svg");
  const wrap = el.querySelector(".parking-chart");
  const tooltip = el.querySelector(".parking-tooltip");
  const guide = el.querySelector(".parking-guide");
  const toPx = (vx, vy) => {
    const s = svg.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return { left: s.left - w.left + (vx / W) * s.width, top: s.top - w.top + (vy / H) * s.height };
  };
  const htmlLine = (label, value, color) =>
    `<div class="line"><span class="label"><span class="dot" style="background:${color}"></span>${label}</span><span class="value">${value}</span></div>`;
  const showTooltip = (i) => {
    const r = rows[i], xx = x(i);
    const p = toPx(xx, yUf(r.ingresos_uf || 0));
    const [year, month] = r.periodo.split("-");
    const periodo = `${MESES[parseInt(month,10)-1]} ${year}`;
    tooltip.innerHTML =
      `<div class="title">${periodo}</div>` +
      htmlLine("Ingresos", `${fmtEnteroMiles(r.ingresos_uf)} UF`, C.ingresos) +
      htmlLine("NOI", `${fmtEnteroMiles(r.noi_uf)} UF`, C.noi) +
      (single
        ? htmlLine("Vacancia", r.vacancia_pct != null ? `${r.vacancia_pct.toFixed(1)}%` : "—", C.vacancia)
        : htmlLine("Vac. Oficinas", r.vacancia_oficinas_pct != null ? `${r.vacancia_oficinas_pct.toFixed(1)}%` : "—", C.oficinas) +
          htmlLine("Vac. Locales", r.vacancia_locales_pct != null ? `${r.vacancia_locales_pct.toFixed(1)}%` : "—", C.locales));
    tooltip.style.left = `${Math.max(88, Math.min(wrap.clientWidth - 88, p.left))}px`;
    tooltip.style.top = `${Math.max(74, p.top - 8)}px`;
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    guide.setAttribute("x1", xx);
    guide.setAttribute("x2", xx);
    guide.setAttribute("opacity", "0.42");
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    guide.setAttribute("opacity", "0");
  };
  el.querySelectorAll(".parking-hit").forEach(hit => {
    const i = Number(hit.dataset.i);
    hit.addEventListener("mouseenter", () => showTooltip(i));
    hit.addEventListener("mousemove", () => showTooltip(i));
    hit.addEventListener("mouseleave", hideTooltip);
  });
}

// Gráfico combinado "Evolución vacancia y canon de arriendo Bodegas" (página 3
// TRI): barras UF/m² (eje izq.) + línea vacancia con etiquetas de % en cada
// punto (eje der.). Datos estáticos (informe GPS Property), ver S.page3.bodegas.
function renderBodegasChart(containerId, evolucion){
  const el = document.getElementById(containerId);
  const labels = evolucion.semestres, ufVals = evolucion.uf_m2, vacVals = evolucion.vacancia_pct;
  if (!labels || !labels.length){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  const C = { bar: "#20C878", vac: "#595959", grid: "#D0D0D0", text: "#333" };
  // Geometría explícita (no auto-scaling): viewBox 600x250 ≈ 2.4:1, igual
  // proporción horizontal/baja del informe GPS Property de referencia.
  // Doble eje Y: UF/m2 a la izquierda (barras), Vacancia a la derecha (línea) —
  // cada uno con su propio domain/ticks fijo, sin relación entre sí.
  const W = 600, H = 205, padL = 58, padR = 42, padT = 38, padB = 48;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = labels.length;
  const x = i => padL + (i + 0.5) * (plotW / n);
  const bw = Math.min(9, (plotW / n) * 0.42);

  // Las barras no parten de 0 — arrancan del piso del eje (0.09), para
  // reproducir las alturas relativas del informe de referencia.
  const yMin = 0.09, yMax = 0.19;
  const yUf = v => padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  // Eje derecho independiente — domain propio, no relacionado al de UF/m2.
  const vMin = -1, vMax = 14;
  const yVac = v => padT + plotH - ((v - vMin) / (vMax - vMin)) * plotH;

  const ufTicks = [0.110, 0.130, 0.150, 0.170, 0.190];
  const vacTicks = [-1, 4, 9, 14];
  let gridLines = "", yLabelsL = "";
  ufTicks.forEach(v => {
    const y = yUf(v);
    gridLines += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W-padR}" y2="${y.toFixed(1)}" stroke="${C.grid}" stroke-width="1"/>`;
    yLabelsL += `<text x="${padL-6}" y="${(y+3).toFixed(1)}" font-size="10" text-anchor="end" fill="${C.text}">${v.toFixed(3)}</text>`;
  });
  let yLabelsR = "";
  vacTicks.forEach(v => {
    const y = yVac(v);
    yLabelsR += `<text x="${W-padR+6}" y="${(y+3).toFixed(1)}" font-size="10" text-anchor="start" fill="${C.text}">${v}%</text>`;
  });

  const bars = labels.map((_, i) => {
    const v = ufVals[i];
    const xb = x(i) - bw/2, yTop = yUf(v), yBase = yUf(yMin);
    return `<rect x="${xb.toFixed(1)}" y="${yTop.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(0, yBase - yTop).toFixed(1)}" fill="${C.bar}"/>`;
  }).join("");

  const linePts = labels.map((_, i) => `${x(i).toFixed(1)},${yVac(vacVals[i]).toFixed(1)}`);
  const linePath = `M${linePts.join(" L")}`; // segmentos rectos, sin suavizado
  const markers = labels.map((_, i) =>
    `<circle cx="${x(i).toFixed(1)}" cy="${yVac(vacVals[i]).toFixed(1)}" r="3" fill="#fff" stroke="${C.vac}" stroke-width="1.6"/>`
  ).join("");

  // El label de cada punto sigue la línea (offset fijo sobre el punto) en
  // vez de quedar todos a la misma altura — así reproduce el perfil de la
  // referencia. Se acerca un poco más cuando el punto está muy abajo (valores
  // bajos de vacancia) para no acercarse demasiado al eje X.
  const vacLabels = labels.map((_, i) => {
    const py = yVac(vacVals[i]);
    const offset = py > padT + plotH - 14 ? 7 : 9;
    return `<text x="${x(i).toFixed(1)}" y="${(py-offset).toFixed(1)}" font-size="10" text-anchor="middle" fill="#000">${Math.round(vacVals[i])}%</text>`;
  }).join("");

  const xLabels = labels.map((lab, i) =>
    `<text x="${x(i).toFixed(1)}" y="${padT+plotH+12}" font-size="9" text-anchor="end" fill="${C.text}" transform="rotate(-45 ${x(i).toFixed(1)} ${padT+plotH+12})">${lab}</text>`
  ).join("");

  const axisTitleL = `<text x="12" y="${padT+plotH/2}" font-size="10" font-weight="700" text-anchor="middle" fill="${C.text}" transform="rotate(-90 12 ${padT+plotH/2})">UF/m²</text>`;
  const axisTitleR = `<text x="${W-10}" y="${padT+plotH/2}" font-size="10" font-weight="700" text-anchor="middle" fill="${C.text}" transform="rotate(-90 ${W-10} ${padT+plotH/2})">Vacancia (%)</text>`;

  const hitW = plotW / n;
  const hoverRects = labels.map((_, i) =>
    `<rect class="parking-hit" data-i="${i}" x="${(x(i)-hitW/2).toFixed(1)}" y="${padT}" width="${hitW.toFixed(1)}" height="${plotH}" fill="transparent" pointer-events="all"/>`
  ).join("");

  el.innerHTML = `
    <div class="parking-chart">
      <div style="display:flex;justify-content:center;align-items:center;gap:14px;font-size:11px;margin-bottom:2px">
        <span><span style="display:inline-block;width:9px;height:9px;background:${C.bar};margin-right:3px;vertical-align:middle"></span>UF/m2</span>
        <span><span style="display:inline-block;width:12px;height:2px;background:${C.vac};margin-right:3px;vertical-align:middle"></span>Vacancia</span>
      </div>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Evolución vacancia y canon de arriendo Bodegas">
        ${gridLines}
        ${bars}
        <path d="${linePath}" fill="none" stroke="${C.vac}" stroke-width="3" stroke-linejoin="miter" stroke-linecap="round"/>
        ${markers}${vacLabels}
        <line class="parking-guide" x1="0" x2="0" y1="${padT}" y2="${padT+plotH}" stroke="#26352F" stroke-width="1" stroke-dasharray="3 4" opacity="0"/>
        ${yLabelsL}${yLabelsR}${xLabels}${axisTitleL}${axisTitleR}
        ${hoverRects}
      </svg>
      <div class="parking-tooltip" aria-hidden="true"></div>
    </div>`;

  const svg = el.querySelector("svg");
  const wrap = el.querySelector(".parking-chart");
  const tooltip = el.querySelector(".parking-tooltip");
  const guide = el.querySelector(".parking-guide");
  const toPx = (vx, vy) => {
    const s = svg.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return { left: s.left - w.left + (vx / W) * s.width, top: s.top - w.top + (vy / H) * s.height };
  };
  const htmlLine = (label, value, color) =>
    `<div class="line"><span class="label"><span class="dot" style="background:${color}"></span>${label}</span><span class="value">${value}</span></div>`;
  const showTooltip = (i) => {
    const xx = x(i);
    const p = toPx(xx, padT);
    tooltip.innerHTML =
      `<div class="title">${labels[i]}</div>` +
      htmlLine("UF/m2", ufVals[i].toLocaleString("es-CL", {minimumFractionDigits: 3, maximumFractionDigits: 3}), C.bar) +
      htmlLine("Vacancia", `${vacVals[i]}%`, C.vac);
    tooltip.style.left = `${Math.max(88, Math.min(wrap.clientWidth - 88, p.left))}px`;
    tooltip.style.top = `${Math.max(24, p.top - 8)}px`;
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    guide.setAttribute("x1", xx);
    guide.setAttribute("x2", xx);
    guide.setAttribute("opacity", "0.42");
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    guide.setAttribute("opacity", "0");
  };
  el.querySelectorAll(".parking-hit").forEach(hit => {
    const i = Number(hit.dataset.i);
    hit.addEventListener("mouseenter", () => showTooltip(i));
    hit.addEventListener("mousemove", () => showTooltip(i));
    hit.addEventListener("mouseleave", hideTooltip);
  });
}

// Gráfico "Evolución anual vacancia/renta Oficinas Las Condes" (página 3 TRI):
// dos líneas (Clase A / Clase B) sobre eje X trimestral agrupado por año.
// data = {quarters, years, seriesA, seriesB}; fmt = "pct" | "uf".
function renderOficinasEvolucionChart(containerId, data, fmt, title){
  const el = document.getElementById(containerId);
  const labels = data.quarters, seriesA = data.seriesA, seriesB = data.seriesB;
  if (!labels || !labels.length){
    el.innerHTML = `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    return;
  }
  const C = { a: "#1B6E5C", b: "#20C878", grid: "#D0D0D0", text: "#333" };
  const W = 900, H = 260, padL = 50, padR = 14, padT = 22, padB = 60;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = labels.length;
  const x = i => padL + (n === 1 ? plotW / 2 : (i * plotW) / (n - 1));

  const allVals = seriesA.concat(seriesB);
  const rawMax = Math.max(...allVals), rawMin = Math.min(0, Math.min(...allVals));
  const step = fmt === "pct" ? 0.02 : 0.05;
  const yMax = Math.ceil(rawMax / step) * step + step;
  const yMin = 0;
  const y = v => padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  const nTicks = 5;
  let gridLines = "", yLabels = "";
  for (let i = 0; i <= nTicks; i++){
    const v = yMin + (yMax - yMin) * (i / nTicks);
    const yy = y(v);
    gridLines += `<line x1="${padL}" y1="${yy.toFixed(1)}" x2="${W-padR}" y2="${yy.toFixed(1)}" stroke="${C.grid}" stroke-width="1"/>`;
    const label = fmt === "pct" ? (v * 100).toLocaleString("es-CL", {maximumFractionDigits: 0}) + "%"
      : v.toLocaleString("es-CL", {minimumFractionDigits: 2, maximumFractionDigits: 2});
    yLabels += `<text x="${padL-8}" y="${(yy+4).toFixed(1)}" font-size="16" text-anchor="end" fill="${C.text}">${label}</text>`;
  }

  const linePath = (vals, color) => {
    const pts = labels.map((_, i) => `${x(i).toFixed(1)},${y(vals[i]).toFixed(1)}`);
    const markers = labels.map((_, i) =>
      `<circle cx="${x(i).toFixed(1)}" cy="${y(vals[i]).toFixed(1)}" r="3.2" fill="#fff" stroke="${color}" stroke-width="2"/>`
    ).join("");
    return `<path d="M${pts.join(" L")}" fill="none" stroke="${color}" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"/>${markers}`;
  };

  // Etiquetas X: fila de trimestre (1Q/2Q/3Q/4Q) + fila de año centrada bajo cada grupo de 4.
  const xQ = labels.map((lab, i) =>
    `<text x="${x(i).toFixed(1)}" y="${padT+plotH+16}" font-size="13" text-anchor="middle" fill="${C.text}">${lab}</text>`
  ).join("");
  let xYears = "", qi = 0;
  const yearPerQuarter = new Array(labels.length);
  (data.years || []).forEach(yr => {
    const qsThisYear = labels.slice(qi).findIndex((_, k) => qi + k + 1 < labels.length && labels[qi + k + 1] === "1Q");
    const count = qsThisYear === -1 ? labels.length - qi : qsThisYear + 1;
    const cx = (x(qi) + x(qi + count - 1)) / 2;
    xYears += `<text x="${cx.toFixed(1)}" y="${padT+plotH+34}" font-size="15" font-weight="700" text-anchor="middle" fill="${C.text}">${yr}</text>`;
    for (let k = 0; k < count; k++) yearPerQuarter[qi + k] = yr;
    qi += count;
  });
  const axisBox = `<line x1="${padL}" y1="${padT+plotH}" x2="${W-padR}" y2="${padT+plotH}" stroke="${C.grid}" stroke-width="1"/>`;

  const hitW = plotW / Math.max(1, n - 1);
  const hoverRects = labels.map((_, i) =>
    `<rect class="parking-hit" data-i="${i}" x="${(x(i)-hitW/2).toFixed(1)}" y="${padT}" width="${hitW.toFixed(1)}" height="${plotH}" fill="transparent" pointer-events="all"/>`
  ).join("");

  const fmtVal = v => v == null ? "—" : (fmt === "pct"
    ? (v * 100).toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%"
    : v.toLocaleString("es-CL", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " UF/m²");

  el.innerHTML = `
    <div class="parking-chart">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Evolución ${title} Oficinas Las Condes">
        ${gridLines}${axisBox}
        ${linePath(seriesA, C.a)}
        ${linePath(seriesB, C.b)}
        <line class="parking-guide" x1="0" x2="0" y1="${padT}" y2="${padT+plotH}" stroke="#26352F" stroke-width="1" stroke-dasharray="3 4" opacity="0"/>
        ${yLabels}${xQ}${xYears}
        ${hoverRects}
      </svg>
      <div class="parking-tooltip" aria-hidden="true"></div>
      <div class="parking-legend">
        <div class="row"><span class="swatch line" style="background:${C.a}"></span>${title} A</div>
        <div class="row"><span class="swatch line" style="background:${C.b}"></span>${title} B</div>
      </div>
    </div>`;

  const svg = el.querySelector("svg");
  const wrap = el.querySelector(".parking-chart");
  const tooltip = el.querySelector(".parking-tooltip");
  const guide = el.querySelector(".parking-guide");
  const toPx = (vx, vy) => {
    const s = svg.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return { left: s.left - w.left + (vx / W) * s.width, top: s.top - w.top + (vy / H) * s.height };
  };
  const htmlLine = (label, value, color) =>
    `<div class="line"><span class="label"><span class="dot" style="background:${color}"></span>${label}</span><span class="value">${value}</span></div>`;
  const showTooltip = (i) => {
    const xx = x(i);
    const p = toPx(xx, padT);
    tooltip.innerHTML =
      `<div class="title">${labels[i]} ${yearPerQuarter[i] || ""}</div>` +
      htmlLine(`${title} A`, fmtVal(seriesA[i]), C.a) +
      htmlLine(`${title} B`, fmtVal(seriesB[i]), C.b);
    tooltip.style.left = `${Math.max(88, Math.min(wrap.clientWidth - 88, p.left))}px`;
    tooltip.style.top = `${Math.max(24, p.top - 8)}px`;
    tooltip.classList.add("on");
    tooltip.setAttribute("aria-hidden", "false");
    guide.setAttribute("x1", xx);
    guide.setAttribute("x2", xx);
    guide.setAttribute("opacity", "0.42");
  };
  const hideTooltip = () => {
    tooltip.classList.remove("on");
    tooltip.setAttribute("aria-hidden", "true");
    guide.setAttribute("opacity", "0");
  };
  el.querySelectorAll(".parking-hit").forEach(hit => {
    const i = Number(hit.dataset.i);
    hit.addEventListener("mouseenter", () => showTooltip(i));
    hit.addEventListener("mousemove", () => showTooltip(i));
    hit.addEventListener("mouseleave", hideTooltip);
  });
}

function renderPerfActivosHeader(p2, perfData){
  const groups = p2.perf_groups;
  const totalCols = groups.reduce((n,g) => n + g.cols.length, 0);
  document.getElementById("tbl-perf-activos-thead1").innerHTML =
    "<th></th>" + groups.map(g => `<th colspan="${g.cols.length}">${g.label}</th>`).join("") + "<th>Total</th>";
  document.getElementById("tbl-perf-activos-thead2").innerHTML =
    "<th></th>" + groups.map(g => g.cols.map(c => `<th>${c}</th>`).join("")).join("") + "<th></th>";

  const perfTd = (v, esPct) => `<td${v === "PENDIENTE" ? ' class="placeholder"' : ""}>${fmtPerfCell(v, esPct)}</td>`;

  const tbody = document.getElementById("tbl-perf-activos-tbody");
  tbody.innerHTML = p2.perf_rows.map(row => {
    const metric = PERF_ROW_METRIC[row];
    const esPct = PERF_ROW_PCT.has(row);
    let cells = "";
    if (metric && perfData) {
      groups.forEach(g => {
        g.cols.forEach(col => {
          const d = perfData[`${g.label}|||${col}`];
          cells += perfTd(d ? d[metric] : null, esPct);
        });
      });
      const gt = perfData["__grand_total__|||Total"];
      cells += perfTd(gt ? gt[metric] : null, esPct);
    } else if (PERF_ROW_ABSORCION[row] && perfData) {
      const [bucket, key] = PERF_ROW_ABSORCION[row];
      groups.forEach(g => {
        g.cols.forEach(col => {
          const d = perfData[`${g.label}|||${col}`];
          cells += perfTd(d && d[bucket] ? d[bucket][key] : null, false);
        });
      });
      const gt = perfData["__grand_total__|||Total"];
      cells += perfTd(gt && gt[bucket] ? gt[bucket][key] : null, false);
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

  document.getElementById("month-bar").textContent = mesEspanol(usadoOp).toUpperCase();

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
  const liabItems = [
    {label: "Préstamos Bancarios", key: "ESF.prestamos"},
    {label: "Pasivos por Impuestos Diferidos", key: "ESF.pasivos_impuestos_diferidos"},
    {label: "Otros Pasivos", key: "ESF.otros_pasivos"},
    {label: "Patrimonio", key: "ESF.patrimonio_neto"},
  ].filter(it => bal[it.key]);
  for (let i=0; i<4; i++){
    const labelEl = document.getElementById("bal-liab-label-"+i);
    const valueEl = document.getElementById("bal-liab-value-"+i);
    const it = liabItems[i];
    if (it){
      labelEl.style.visibility = "";
      valueEl.style.visibility = "";
      labelEl.textContent = it.label;
      valueEl.textContent = fmtMontoClp(bal[it.key], pc, F, "balance");
      attachTrace(valueEl, it.key, {fondo: currentFund, periodo: pc, raw_value: bal[it.key]});
    } else {
      labelEl.style.visibility = "hidden";
      valueEl.style.visibility = "hidden";
      labelEl.textContent = "—";
      valueEl.textContent = "—";
    }
  }
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
  document.getElementById("month-bar2").textContent = mesEspanol(usadoOp).toUpperCase();
  if (S.page2) {
    renderPage2ChartsLayout(S.page2.charts_layout);
    const perfPeriodo = (F.perf_data || {})[usadoOp] ? usadoOp : null;
    document.getElementById("perf-fecha").textContent = perfPeriodo
      ? "(al " + mesEspanol(perfPeriodo) + ")"
      : "(sin rent roll para " + mesEspanol(usadoOp) + ")";
    renderPerfActivosHeader(S.page2, perfPeriodo ? F.perf_data[perfPeriodo] : null);
    // Los boxes de gráficos se arman según S.page2.charts_layout (ver
    // renderPage2ChartsLayout arriba) — no todos los fondos incluyen todos
    // los ids (ej. TRI no tiene "tipo_activo"), por eso cada bloque chequea
    // que su elemento exista antes de renderizar.
    if (document.getElementById("chart-rubro")) {
      const rubroPeriodo = (F.rubro_arrendatario || {})[usadoOp] ? usadoOp : null;
      renderBarChartHorizontal("chart-rubro", rubroPeriodo ? F.rubro_arrendatario[rubroPeriodo] : null);
    }
    if (document.getElementById("donut-tipo-activo")) {
      const tipoPeriodo = (F.tipo_activo || {})[usadoOp] ? usadoOp : null;
      renderTipoActivoDonut("donut-tipo-activo", tipoPeriodo ? F.tipo_activo[tipoPeriodo] : null, S.page2.tipo_activo);
    }
    if (document.getElementById("tabla-ingresos-anual-tipo-activo")) {
      const ta = F.tablas_anuales_tri || {};
      renderTablaAnualTipoActivo("tabla-ingresos-anual-tipo-activo", ta.ingresos, ta.u12m_ingresos || {}, ta.years, S.page2.tipo_activo, usadoOp);
      renderTablaAnualTipoActivo("tabla-noi-anual-tipo-activo", ta.noi, ta.u12m_noi || {}, ta.years, S.page2.tipo_activo, usadoOp);
    }
    if (document.getElementById("chart-perfil-vencimiento")) {
      if (S.page2.perfil_vencimiento_edificios) {
        const vencPeriodo = (F.perfil_vencimiento || {})[usadoOp] ? usadoOp : null;
        const vencData = vencPeriodo ? F.perfil_vencimiento[vencPeriodo] : null;
        renderStackedBarChart("chart-perfil-vencimiento", vencData, S.page2.perfil_vencimiento_edificios);
        document.getElementById("fld-plazo-medio").textContent =
          vencData && vencData.plazo_medio_anios != null ? fmtNum(vencData.plazo_medio_anios, 1) + " años" : "—";
      } else {
        // Fondos sin desglose por edificio (PT, TRI): este gráfico es Apo-specific.
        // Resetear a placeholder explícitamente — si no, al cambiar de fondo en el
        // selector (SPA sin reload) queda pegado el último SVG renderizado para Apo.
        document.getElementById("chart-perfil-vencimiento").innerHTML =
          `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
        document.getElementById("fld-plazo-medio").textContent = "—";
      }
    }
  }

  // Página 3 / 4 — mismo mes de referencia que página 2 (no tienen datos por período aún)
  const mesRef = mesEspanol(usadoOp).toUpperCase();
  document.getElementById("month-bar3").textContent = mesRef;
  document.getElementById("month-bar4").textContent = mesRef;
  document.getElementById("month-bar5").textContent = mesRef;
  document.getElementById("month-bar6").textContent = mesRef;
  document.getElementById("month-bar7").textContent = mesRef;
  document.getElementById("month-bar8").textContent = mesRef;

  // Página 3 Apo: donut de ingresos UF/mes por edificio, solo si hay dato real
  // para el período operacional exacto (usadoOp) — nunca mostrar el del mes
  // anterior/siguiente, para no dejar "pegado" un gráfico de otro período.
  if (S.page3 && S.page3.edificios) {
    const ingresosPorPeriodo = F.ingresos_edificios || {};
    const ingresosData = usadoOp ? ingresosPorPeriodo[usadoOp] : null;
    const edificiosConDato = ingresosData ? S.page3.edificios.filter(n => ingresosData[n] != null) : [];
    if (edificiosConDato.length === S.page3.edificios.length) {
      const total = edificiosConDato.reduce((s, n) => s + ingresosData[n], 0);
      const donutData = edificiosConDato.map(n => [
        n,
        total ? Math.round(ingresosData[n] / total * 1000) / 10 : 0,
        { value: ingresosData[n], unit: "UF" }
      ]);
      renderDonut("donut-ingresos", donutData, { tooltipTitle: `Ingresos ${mesEspanol(usadoOp)}` });
    } else {
      document.getElementById("donut-ingresos").innerHTML =
        `<div class="chart-placeholder" style="width:100%">Pendiente de datos</div>`;
    }
  }

  // Página 3 Apo: donut de GLA m² por edificio — a diferencia del de
  // ingresos, la superficie de un edificio no cambia mes a mes: F.gla_edificios
  // es un único snapshot estático (ver _fetch_gla_apo en build_factsheet.py),
  // no depende de usadoOp.
  if (S.page3 && S.page3.edificios) {
    const glaData = F.gla_edificios || {};
    const edificiosConDato = S.page3.edificios.filter(n => glaData[n] != null);
    if (edificiosConDato.length === S.page3.edificios.length) {
      const total = edificiosConDato.reduce((s, n) => s + glaData[n], 0);
      const donutData = edificiosConDato.map(n => [
        n,
        total ? Math.round(glaData[n] / total * 1000) / 10 : 0,
        { value: glaData[n], unit: "m²" }
      ]);
      renderDonut("donut-gla", donutData, { tooltipTitle: "GLA" });
    } else {
      document.getElementById("donut-gla").innerHTML =
        `<div class="chart-placeholder" style="width:100%">Pendiente de datos</div>`;
    }
  }

  // Tooltip compartido por renderStatusOficinas/renderStatusLocales — mismo
  // patrón que renderDonut (positionTooltip/show/hide sobre un
  // .status-tooltip creado dentro del contenedor .status-viz, que ya es
  // position:relative).
  const _statusTooltip = (el) => {
    let tt = el.querySelector(".status-tooltip");
    if (!tt) {
      tt = document.createElement("div");
      tt.className = "status-tooltip";
      tt.setAttribute("aria-hidden", "true");
      el.appendChild(tt);
    }
    const position = (event) => {
      const r = el.getBoundingClientRect();
      const left = Math.max(80, Math.min(el.clientWidth - 80, event.clientX - r.left));
      const top = Math.max(60, event.clientY - r.top - 8);
      tt.style.left = `${left}px`;
      tt.style.top = `${top}px`;
    };
    const show = (html, event) => {
      tt.innerHTML = html;
      position(event);
      tt.classList.add("on");
      tt.setAttribute("aria-hidden", "false");
    };
    const hide = () => {
      tt.classList.remove("on");
      tt.setAttribute("aria-hidden", "true");
    };
    return { show, move: position, hide };
  };
  // raw_rent_roll_line.renta_uf ya es una TASA (UF/m²/mes), no un monto total
  // (ver tools/db/ingest_rent_roll_validated.py::_monto_mensual_uf) — no
  // hay que dividir por m² de nuevo.
  const _ufM2Mes = (rentaUf) => (rentaUf || 0).toLocaleString("es-CL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const _fmtM2 = (m2) => m2.toLocaleString("es-CL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  // Página 3 Apo: "Status Actual Oficinas por Activo" — silueta del edificio
  // FIJA (posición/ancho/alto de cada piso, calcada pixel a pixel de la foto
  // de referencia del usuario, igual que APO_LOCALES_LAYOUT), color = %
  // ocupado del piso ese período (usadoOp). Dato viene de F.status_oficinas
  // (tools/db/rent_roll_stats.py::get_status_oficinas). Tooltip por piso:
  // arrendatario(s), UF/m²/mes y m² de cada unidad del piso.
  //
  // Cada entrada es [x%, y%, w%, h%] dentro de un contenedor con el aspect
  // ratio del edificio (medido en la foto), indexado por posición (piso más
  // alto primero, igual que el orden de datos.pisos) — no por número de
  // piso, porque las filas de la foto no traen esa etiqueta. Antes el ancho
  // se calculaba en vivo como m2_piso/max(m2); ahora es fijo (decisión
  // explícita del usuario 2026-07-30: la forma no cambia con el rent roll).
  const APO_OFICINAS_LAYOUT = {
    "Apoquindo 4501": {
      // y/h uniformes (100/18 c/u) en vez de los y medidos pixel a pixel —
      // esos traían un jitter de redondeo de ±1px entre filas (16 vs 17px)
      // que se notaba como pisos de alto ligeramente distinto.
      aspecto: [235, 303],
      filas: [
        [0.00, 0.00, 100.00, 5.56], [1.28, 5.56, 97.45, 5.56], [2.55, 11.11, 94.89, 5.56],
        [3.83, 16.67, 92.34, 5.56], [5.53, 22.22, 88.94, 5.56], [6.81, 27.78, 86.38, 5.56],
        [8.09, 33.33, 83.83, 5.56], [9.36, 38.89, 81.28, 5.56], [10.64, 44.44, 78.72, 5.56],
        [11.91, 50.00, 76.17, 5.56], [13.19, 55.56, 73.62, 5.56], [14.47, 61.11, 71.06, 5.56],
        [15.74, 66.67, 68.51, 5.56], [17.02, 72.22, 65.96, 5.56], [18.30, 77.78, 63.40, 5.56],
        [19.57, 83.33, 60.85, 5.56], [20.85, 88.89, 58.30, 5.56], [22.13, 94.44, 55.74, 5.56],
      ],
    },
    "Apoquindo 4700": {
      // Ancho del contenedor = ancho real de la fila más ancha (planta baja,
      // 246px) y todo desplazado +35px respecto a la medición original del
      // usuario — esa fila partía en x=-35 (fuera del card a la izquierda);
      // así queda centrada y sin desbordar. Alto uniforme (100/16) en vez
      // del 19px/20px medido (la planta baja medía 1px más) — todos los
      // pisos deben verse del mismo alto.
      aspecto: [246, 298],
      filas: [
        [14.23, 0.00, 71.14, 6.25], [14.23, 6.25, 71.14, 6.25], [14.23, 12.50, 71.14, 6.25],
        [14.23, 18.75, 71.14, 6.25], [14.23, 25.00, 71.14, 6.25], [14.23, 31.25, 71.14, 6.25],
        [14.23, 37.50, 71.14, 6.25], [14.23, 43.75, 71.14, 6.25], [14.23, 50.00, 71.14, 6.25],
        [14.23, 56.25, 71.14, 6.25], [14.23, 62.50, 71.14, 6.25], [14.23, 68.75, 71.14, 6.25],
        [14.23, 75.00, 71.14, 6.25], [14.23, 81.25, 71.14, 6.25], [14.23, 87.50, 71.14, 6.25],
        [0.00, 93.75, 100.00, 6.25],
      ],
    },
  };
  const renderStatusOficinas = (nombre, datos) => {
    const el = document.getElementById(`status-of-${slug(nombre)}`);
    const label = document.getElementById(`status-of-${slug(nombre)}-label`);
    if (!el || !label) return;
    const layout = APO_OFICINAS_LAYOUT[nombre];
    if (!datos || !datos.pisos || !datos.pisos.length || !layout) {
      el.className = "status-viz placeholder";
      el.textContent = "Pendiente de datos";
      label.className = "occ-pill placeholder";
      label.textContent = "Ocupación: —";
      return;
    }
    const [aw, ah] = layout.aspecto;
    el.className = "status-viz";
    el.innerHTML = `<div class="status-building" style="aspect-ratio:${aw}/${ah}">${datos.pisos.map((p, i) => {
      const fila = layout.filas[i];
      if (!fila) return "";
      const [x, y, w, h] = fila;
      return `<div class="status-floor" data-i="${i}" style="left:${x}%;top:${y}%;width:${w}%;height:${h}%">` +
        `<div class="status-floor-occ" style="width:${p.ocupado_pct}%"></div>` +
        `<div class="status-floor-vac" style="width:${100 - p.ocupado_pct}%"></div></div>`;
    }).join("")}</div>`;
    label.className = "occ-pill";
    label.textContent = `Ocupación: ${datos.ocupacion_pct.toLocaleString("es-CL", {minimumFractionDigits: 1, maximumFractionDigits: 1})}%`;

    const tt = _statusTooltip(el);
    // Varias unidades del mismo piso suelen estar a nombre del mismo
    // arrendatario (ej. 4 oficinas contiguas arrendadas como una sola) — se
    // agrupan por arrendatario sumando m² (y ponderando la tasa UF/m²/mes
    // por m², ya que renta_uf es una tasa, no un monto) en vez de listar
    // cada unidad por separado.
    const agruparPorArrendatario = (unidades) => {
      const grupos = new Map();
      (unidades || []).forEach(u => {
        const key = u.vacante ? "__vacante__" : u.arrendatario;
        if (!grupos.has(key)) grupos.set(key, { vacante: u.vacante, arrendatario: u.arrendatario, m2: 0, montoUf: 0 });
        const g = grupos.get(key);
        g.m2 += u.m2;
        g.montoUf += (u.renta_uf || 0) * u.m2;
      });
      return [...grupos.values()];
    };
    const unidadLine = (u) => `<div class="line unidad-row"><span class="label">${u.vacante ? "Vacante" : "Arrendatario"}</span>` +
        `<span class="value">${u.vacante ? "" : u.arrendatario}</span></div>` +
      (u.vacante ? "" :
        `<div class="line"><span class="label">UF/m²/mes</span><span class="value">${_ufM2Mes(u.m2 ? u.montoUf / u.m2 : 0)}</span></div>`) +
      `<div class="line"><span class="label">m²</span><span class="value">${_fmtM2(u.m2)}</span></div>`;
    el.querySelectorAll(".status-floor").forEach(floorEl => {
      const p = datos.pisos[Number(floorEl.dataset.i)];
      const html = `<div class="title">Piso ${p.piso} — ${p.ocupado_pct}% ocupado</div>` +
        `<div class="line"><span class="label">m² totales</span><span class="value">${_fmtM2(p.m2)}</span></div>` +
        agruparPorArrendatario(p.unidades).map(unidadLine).join("");
      floorEl.addEventListener("mouseenter", (e) => tt.show(html, e));
      floorEl.addEventListener("mousemove", (e) => tt.move(e));
      floorEl.addEventListener("mouseleave", tt.hide);
    });
  };
  if (S.page3 && S.page3.status_oficinas) {
    const porPeriodo = usadoOp ? (F.status_oficinas || {})[usadoOp] : null;
    S.page3.status_oficinas.forEach(([nombre]) => renderStatusOficinas(nombre, porPeriodo ? porPeriodo[nombre] : null));
  }

  // Página 3 Apo: "Status Actual Locales por Activo" — layout FIJO por
  // edificio (calcado a mano de la foto de referencia del usuario, ver
  // APO_LOCALES_LAYOUT), no un treemap calculado: un squarify automático
  // arma una agrupación matemáticamente válida pero no necesariamente igual
  // a la de la foto (qué local queda pegado a cuál). Coordenadas en % fijas
  // por unidad — si el rent roll agrega/quita un local en estos edificios,
  // hay que actualizar este dict a mano (decisión explícita del usuario
  // 2026-07-30: la forma/organización de los edificios no cambia).
  const APO_LOCALES_LAYOUT = {
    "Apoquindo 4501": {
      "ex bodyline (4a,4b,4c,4d y 6)": [0, 0, 66.2, 54.4],
      "2D": [66.2, 0, 33.8, 54.4],
      "1E": [0, 54.4, 36.6, 27.0],
      "5": [0, 81.4, 36.6, 18.6],
      "1B": [36.6, 54.4, 34.7, 19.5],
      "4E": [71.3, 54.4, 28.7, 19.5],
      "2B (ex los castaños)": [36.6, 73.9, 19.4, 26.1],
      "2C": [56.0, 73.9, 17.6, 26.1],
      "1C": [73.6, 73.9, 13.4, 18.6],
      "1A": [73.6, 92.5, 13.4, 7.5],
      "1D": [87.0, 73.9, 13.0, 18.6],
      "2A #2": [87.0, 92.5, 13.0, 7.5],
    },
    "Apoquindo 4700": {
      "3": [0, 0, 100, 52.4],
      "1 #2": [0, 52.4, 80.3, 47.6],
      "2 #2": [80.3, 52.4, 19.7, 47.6],
    },
  };
  const renderStatusLocales = (nombre, datos) => {
    const el = document.getElementById(`status-loc-${slug(nombre)}`);
    const label = document.getElementById(`status-loc-${slug(nombre)}-label`);
    if (!el || !label) return;
    const layout = APO_LOCALES_LAYOUT[nombre];
    if (!datos || !datos.locales || !datos.locales.length || !layout) {
      el.className = "status-viz placeholder";
      el.textContent = "Pendiente de datos";
      label.className = "occ-label placeholder";
      label.textContent = "Ocupación: —";
      return;
    }
    // Locales sin coordenada en el layout fijo (unidad nueva en el rent
    // roll, no contemplada en la foto) se listan aparte en vez de perderse
    // silenciosamente.
    const conLayout = datos.locales.filter(l => layout[l.unidad]);
    const sinLayout = datos.locales.filter(l => !layout[l.unidad]);
    el.className = "status-viz";
    el.innerHTML = `<div class="status-treemap">${conLayout.map((l, i) => {
      const [x, y, w, h] = layout[l.unidad];
      const cls = l.vacante ? "status-local-vac" : "status-local-occ";
      return `<div class="status-local ${cls}" data-i="${i}" style="left:${x}%;top:${y}%;width:${w}%;height:${h}%">` +
        `<span class="status-local-label">${l.m2} m²</span></div>`;
    }).join("")}</div>${sinLayout.length ? `<p class="small placeholder">Sin layout definido: ${sinLayout.map(l => l.unidad).join(", ")}</p>` : ""}`;
    label.className = "occ-pill";
    label.textContent = `Ocupación: ${datos.ocupacion_pct.toLocaleString("es-CL", {minimumFractionDigits: 1, maximumFractionDigits: 1})}%`;

    // Si el texto no cabe en la celda (overflow real medido en el DOM, no un
    // umbral estimado), se oculta en vez de cortarse — pedido explícito del
    // usuario 2026-07-30.
    el.querySelectorAll(".status-local-label").forEach(span => {
      if (span.scrollWidth > span.clientWidth + 0.5 || span.scrollHeight > span.clientHeight + 0.5) {
        span.style.display = "none";
      }
    });

    const tt = _statusTooltip(el);
    el.querySelectorAll(".status-local").forEach(localEl => {
      const l = conLayout[Number(localEl.dataset.i)];
      const html = `<div class="title">${l.vacante ? "Vacante" : "Ocupado"}</div>` +
        (l.vacante ? "" :
          `<div class="line"><span class="label">Arrendatario</span><span class="value">${l.arrendatario}</span></div>` +
          `<div class="line"><span class="label">UF/m²/mes</span><span class="value">${_ufM2Mes(l.renta_uf)}</span></div>`) +
        `<div class="line"><span class="label">m² totales</span><span class="value">${_fmtM2(l.m2)}</span></div>`;
      localEl.addEventListener("mouseenter", (e) => tt.show(html, e));
      localEl.addEventListener("mousemove", (e) => tt.move(e));
      localEl.addEventListener("mouseleave", tt.hide);
    });
  };
  if (S.page3 && S.page3.status_locales) {
    const porPeriodo = usadoOp ? (F.status_locales || {})[usadoOp] : null;
    S.page3.status_locales.forEach(([nombre]) => renderStatusLocales(nombre, porPeriodo ? porPeriodo[nombre] : null));
  }

  // Página 3 PT (tenant): donuts de ingresos UF/mes y GLA m² por
  // arrendatario, con dato real del período operacional exacto (usadoOp), si
  // no placeholder. Top-N + "Otros" ya viene resuelto desde Python (ver
  // tools/db/rent_roll_stats.py::_top_n_arrendatario) — acá solo se arma el
  // donut respetando el orden (mayor a menor) que trae el dict.
  const donutArrendatario = (containerId, porPeriodo, tooltipTitle) => {
    const data = usadoOp ? (porPeriodo || {})[usadoOp] : null;
    if (data && Object.keys(data).length) {
      const total = Object.values(data).reduce((s, v) => s + v, 0);
      const donutData = Object.entries(data).map(([n, v]) => [
        n,
        total ? Math.round(v / total * 1000) / 10 : 0,
        { value: v, unit: tooltipTitle.unit },
      ]);
      renderDonut(containerId, donutData, { tooltipTitle: `${tooltipTitle.label} ${mesEspanol(usadoOp)}` });
    } else {
      document.getElementById(containerId).innerHTML =
        `<div class="chart-placeholder" style="width:100%">Pendiente de datos</div>`;
    }
  };
  if (S.page3 && S.page3.donut_arrendatario) {
    donutArrendatario("donut-ingresos-t", F.ingresos_arrendatario, { label: "Ingresos", unit: "UF" });
    donutArrendatario("donut-gla-t", F.gla_arrendatario, { label: "GLA", unit: "m²" });

    // Aspectos Relevantes (tabla tenant, ver tbl-aspectos-t): Superficie
    // Arrendable y Vacancia (m²) del fondo completo, misma fuente que la
    // tabla "Resumen Performance Activos" (F.perf_data, columna
    // "__grand_total__|||Total" de get_perf_table).
    const gtAsp = usadoOp && F.perf_data && F.perf_data[usadoOp]
      ? F.perf_data[usadoOp]["__grand_total__|||Total"] : null;
    const elSupT = document.getElementById("tbl-aspectos-t-superficie-arrendable");
    if (elSupT) elSupT.textContent = gtAsp && gtAsp.m2_utiles != null
      ? Math.round(gtAsp.m2_utiles).toLocaleString("es-CL") + " m2" : "—";
    const elVacT = document.getElementById("tbl-aspectos-t-vacancia-m");
    if (elVacT) elVacT.textContent = gtAsp && gtAsp.pct_vacancia_m2 != null
      ? gtAsp.pct_vacancia_m2.toLocaleString("es-CL", {maximumFractionDigits: 2}) + "%" : "—";

    // "Aspectos del mes" (fila "Vacancia del Fondo" / "Parking" / "Resultados"):
    // texto autogenerado por fila, con override editable en modo admin (ver
    // updateAspectosMesTexts / ASPECTOS_MES_STORE_KEY). "Otros Locales" (y
    // cualquier fila sin lógica acá) queda sin auto: solo override manual.
    const autoTexts = {};

    // Vacancia del Fondo — a partir de F.vacancia_pt_tipo (mes actual vs mes
    // anterior, por tipo de activo). Solo la parte cuantitativa (%, oficinas,
    // locales comerciales); eventos cualitativos (nuevos contratos,
    // colocaciones) no están en la DB — se agregan a mano vía override.
    {
      const vacTipo = usadoOp && F.vacancia_pt_tipo ? F.vacancia_pt_tipo[usadoOp] : null;
      const oficinas = vacTipo ? vacTipo["Oficinas"] : null;
      const locales = vacTipo ? vacTipo["Locales Comerciales"] : null;
      if (oficinas && locales && oficinas.pct_actual != null && locales.pct_actual != null && gtAsp && gtAsp.pct_vacancia_m2 != null) {
        const pctFondo = gtAsp.pct_vacancia_m2;
        const fmtPct = (v) => v.toLocaleString("es-CL", {maximumFractionDigits: 1});
        // Variación del % del fondo entre mes actual y anterior (misma fuente
        // que gtAsp, pero necesitamos el dato del período anterior — ver
        // F.perf_data, que también trae "__grand_total__|||Total" por período).
        const [ay, am] = usadoOp.split("-").map(Number);
        const prevDate = new Date(ay, am - 2, 1); // am es 1-indexed; -2 => mes anterior 0-indexed
        const periodoAnterior = `${prevDate.getFullYear()}-${String(prevDate.getMonth() + 1).padStart(2, "0")}`;
        const gtAspAnterior = periodoAnterior && F.perf_data && F.perf_data[periodoAnterior]
          ? F.perf_data[periodoAnterior]["__grand_total__|||Total"] : null;
        let evolucion;
        if (gtAspAnterior && gtAspAnterior.pct_vacancia_m2 != null) {
          const delta = pctFondo - gtAspAnterior.pct_vacancia_m2;
          evolucion = Math.abs(delta) < 0.05
            ? `no presentó variaciones y se mantuvo en ${fmtPct(pctFondo)}%`
            : `${delta > 0 ? "aumentó" : "disminuyó"} a ${fmtPct(pctFondo)}% (${delta > 0 ? "+" : ""}${fmtPct(delta)} pp)`;
        } else {
          evolucion = `se ubicó en ${fmtPct(pctFondo)}%`;
        }
        autoTexts["vacancia-del-fondo"] = `Durante ${mesEspanol(usadoOp)}, la vacancia del Fondo ${evolucion}, ` +
          `compuesta por ${fmtPct(oficinas.pct_actual)}% en oficinas y ${fmtPct(locales.pct_actual)}% en locales comerciales.`;
      }
    }

    // Parking — variación acumulada (ene->mes actual) del resultado neto UF y
    // del total de tickets vs. mismo rango 2024. Ver F.parking_desempeno /
    // _fetch_parking_desempeno en build_factsheet.py.
    {
      const pd = usadoOp && F.parking_desempeno ? F.parking_desempeno[usadoOp] : null;
      if (pd && pd.resultado_pct != null && pd.tickets_pct != null) {
        const fmtSigned = (v) => (v > 0 ? "+" : "") + v.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%";
        const tono = (pd.resultado_pct >= 0 && pd.tickets_pct >= 0) ? "muy positivo"
          : (pd.resultado_pct < 0 && pd.tickets_pct < 0) ? "negativo" : "mixto";
        autoTexts["parking"] = `El desempeño de los estacionamientos ha sido ${tono}: variación acumulada vs 2024 ` +
          `${fmtSigned(pd.resultado_pct)} en resultados y ${fmtSigned(pd.tickets_pct)} en tickets.`;
      }
    }

    // Resultados — variación % del NOI U12M vs U12M del mismo mes del año
    // anterior. Ver F.noi_u12m_yoy / _fetch_noi_u12m_yoy_pt.
    {
      const pct = usadoOp && F.noi_u12m_yoy ? F.noi_u12m_yoy[usadoOp] : null;
      if (pct != null) {
        const [yy, mm] = usadoOp.split("-");
        const mesAbrevLabel = `${MESES_ABR[parseInt(mm, 10) - 1]}-${yy.slice(2)}`;
        autoTexts["resultados"] = `El NOI de los U12M de ${mesAbrevLabel} vs ${parseInt(yy, 10) - 1} fue un ` +
          `${Math.abs(pct).toLocaleString("es-CL", {maximumFractionDigits: 1})}% ${pct >= 0 ? "mayor" : "menor"}.`;
      }
    }

    updateAspectosMesTexts("txt-aspectos-mes-t", currentFund, usadoOp, autoTexts);
  }

  // Página 3 Apo: tabla de vacancia por edificio (Locales/Oficinas/Edificio) —
  // depende del período operacional (usadoOp). F.vacancia_apo viene de
  // tools/db/rent_roll_stats.py::get_vacancia_edificios vía
  // scripts/build_factsheet.py::_fetch_vacancia_apo, que usa
  // tools/db/rent_roll_source.py (DB si el rent roll fue ingestado y
  // validado; si no, el Excel borrador no verificado como fallback — mismos
  // datos, cero cambios acá cuando se ingeste el rent roll bueno).
  if (S.page3 && S.page3.vacancia_edificios) {
    const vacPorPeriodo = F.vacancia_apo || {};
    const vacData = usadoOp ? vacPorPeriodo[usadoOp] : null;
    document.getElementById("vacancia-periodo-label").textContent = vacData
      ? `(al ${mesEspanol(usadoOp)})`
      : `(sin rent roll para ${mesEspanol(usadoOp)})`;
    const fmtPP = (v) => v == null ? null : (v > 0 ? "+" : "") + v.toLocaleString("es-CL", {maximumFractionDigits: 2}) + " pp";
    const fmtPctVac = (v) => v == null ? null : v.toLocaleString("es-CL", {maximumFractionDigits: 2}) + "%";
    const celdaVac = (texto) => texto == null
      ? '<td class="placeholder">—</td>'
      : `<td>${texto}</td>`;
    const vacanciaBox = (ed) => `
      <div class="subtable-box">
        <div class="subtable-title">${ed.nombre}</div>
        <table>
          <thead><tr><th></th><th>Mes anterior</th><th>Mes actual</th><th>Variación</th></tr></thead>
          <tbody>${ed.rows.map(r => {
            const d = vacData ? vacData[`${ed.nombre}|||${r}`] : null;
            return `<tr><td>${r}</td>` +
              celdaVac(d ? fmtPctVac(d.pct_anterior) : null) +
              celdaVac(d ? fmtPctVac(d.pct_actual) : null) +
              celdaVac(d ? fmtPP(d.variacion) : null) +
              `</tr>`;
          }).join("")}</tbody>
        </table>
      </div>`;
    document.getElementById("grid-vacancia").innerHTML = S.page3.vacancia_edificios.map(vacanciaBox).join("");
    const dFondo = vacData ? vacData["Fondo"] : null;
    document.getElementById("txt-vacancia-fondo").textContent = dFondo && dFondo.pct_actual != null
      ? fmtPctVac(dFondo.pct_actual)
      : "—";
    const elVacM2 = document.getElementById("tbl-aspectos-vacancia-m");
    if (elVacM2) elVacM2.textContent = dFondo && dFondo.pct_actual != null ? fmtPctVac(dFondo.pct_actual) : "—";
  }

  const elSup = document.getElementById("tbl-aspectos-superficie-arrendable");
  if (elSup && F.gla_edificios) {
    const total = Object.values(F.gla_edificios).reduce((a, b) => a + b, 0);
    elSup.textContent = total ? Math.round(total).toLocaleString("es-CL") + " m2" : "—";
  }
  const elFin = document.getElementById("tbl-aspectos-financiamiento");
  if (elFin) {
    elFin.textContent = F.ltv_fondo != null
      ? "LTV de " + (F.ltv_fondo * 100).toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%"
      : "—";
  }

  // Página 3 Apo/PT: tabla de Tasaciones — depende del período seleccionado
  // (usadoOp), se recalcula en cada render() en vez de una sola vez al
  // cambiar de fondo.
  if (S.page3 && S.page3.tasaciones_edificios) {
    if (S.page3.edificios) {
      fillTasaciones(F, S.page3, usadoOp, "tbl-tasaciones-tbody", "th-tasacion-deuda", "th-tasacion-prev", "th-tasacion-actual", "tbl-tasaciones-comp-tbody");
    } else {
      fillTasaciones(F, S.page3, usadoOp, "tbl-tasaciones-tbody-t", "th-tasacion-deuda-t", "th-tasacion-prev-t", "th-tasacion-actual-t", "tbl-tasaciones-comp-tbody-t");
    }
  }

  // Página 3 PT: parking debe seguir el selector operacional. Se muestran
  // solo los meses disponibles hasta el período seleccionado.
  if (S.page3 && S.page3.parking) {
    const parkingRows = (F.parking || []).filter(r => !usadoOp || r.periodo <= usadoOp);
    renderParkingChart("chart-parking", parkingRows);
  }

  if (document.getElementById("chart-noi-rcsd")) {
    const noiRcsdRows = (F.noi_rcsd || []).filter(r => !usadoOp || r.periodo <= usadoOp);
    const rcsdAxisMax = currentFund === "Apo" ? 3.5 : null;
    renderNoiRcsdChart("chart-noi-rcsd", noiRcsdRows, rcsdAxisMax);
  }

  if (document.getElementById("chart-ingresos-noi-vacancia")) {
    const invRows = (F.ingresos_noi_vacancia || []).filter(r => !usadoOp || r.periodo <= usadoOp);
    renderIngresosNoiVacanciaChart("chart-ingresos-noi-vacancia", invRows);
  }

  // Página 3 TRI: tabla de mercado de oficinas — misma fuente que la del
  // Análisis de Mercado de Apo (raw_mercado_oficinas), reutilizada acá con
  // párrafos propios (absorción/concentración) en vez de vacancia/canon.
  // Bodegas y centros comerciales no tienen fuente en la DB todavía: solo
  // estructura, valores en placeholder.
  if (S.page3 && S.page3.modo === "mercado") {
    const quarterEndOfM = (periodo) => {
      const [y, m] = periodo.split("-").map(Number);
      const qEndMonth = Math.ceil(m / 3) * 3;
      return y + "-" + String(qEndMonth).padStart(2, "0");
    };
    const mercadoPeriodoM = usadoOp ? quarterEndOfM(usadoOp) : null;
    const mercadoRowsM = (F.mercado && F.mercado[mercadoPeriodoM]) || S.page3.mercado_rows || [];
    const findRowM = (rows, comuna, clase) =>
      (rows || []).find(r => r.comuna === comuna && r.clase === clase && r.vacancia_pct !== undefined) || null;
    const fmtNumM = (v, dec) => (v === null || v === undefined) ? null :
      v.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    const celdaM = (v, esPct) => {
      if (v === null || v === undefined) return '<td class="placeholder">—</td>';
      const texto = esPct ? v.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%"
        : v.toLocaleString("es-CL", {maximumFractionDigits: 2});
      return `<td>${texto}</td>`;
    };

    const p1 = document.getElementById("txt-mercado3-p1");
    const p2 = document.getElementById("txt-mercado3-p2");
    // El wording debe reflejar solo lo que la tabla muestra: filas totales
    // "Santiago" de Clase A y Clase B (la tabla ya no despliega la fila
    // agregada "Total" A+B — ver mercado_rows / filtro clase !== "Total").
    const totalA = findRowM(mercadoRowsM, "Santiago", "A");
    const totalB = findRowM(mercadoRowsM, "Santiago", "B");
    if (totalA || totalB) {
      const absA = totalA ? totalA.absorcion_u12m_m2 : null;
      const absB = totalB ? totalB.absorcion_u12m_m2 : null;
      const partes = [];
      if (absA !== null && absA !== undefined) partes.push(`Clase A por ${fmtNumM(absA, 0)} m²`);
      if (absB !== null && absB !== undefined) partes.push(`Clase B por ${fmtNumM(absB, 0)} m²`);
      p1.textContent = `El mercado de oficinas en Santiago presenta una absorción neta acumulada durante los ` +
        `últimos 12 meses de ${partes.join(" y ")}.`;
      p1.classList.remove("placeholder");

      const comunasA = mercadoRowsM.filter(r => r.clase === "A" && r.comuna !== "Santiago" && r.absorcion_u12m_m2 !== undefined);
      const comunasB = mercadoRowsM.filter(r => r.clase === "B" && r.comuna !== "Santiago" && r.absorcion_u12m_m2 !== undefined);
      const topN = (rows, n) => [...rows].sort((a, b) => (b.absorcion_u12m_m2 || 0) - (a.absorcion_u12m_m2 || 0)).slice(0, n).map(r => r.comuna);
      const topA = topN(comunasA, 2);
      const topB = topN(comunasB, 2);
      const fragA = topA.length ? `en Clase A, en la comuna de ${topA.join(" y ")}` : "";
      const fragB = topB.length ? `en Clase B, en la comuna de ${topB.join(" y ")}` : "";
      const frags = [fragA, fragB].filter(Boolean);
      if (frags.length) {
        p2.textContent = `Esta se concentra principalmente ${frags.join("; ")}.`;
        p2.classList.remove("placeholder");
      } else {
        p2.classList.add("placeholder");
      }
    } else {
      p1.textContent = "Pendiente: párrafo de absorción (informe JLL) — sin datos ingestados para este trimestre.";
      p1.classList.add("placeholder");
      p2.textContent = "Pendiente: párrafo de concentración por comuna (informe JLL).";
      p2.classList.add("placeholder");
    }

    const mercadoRowsAB = mercadoRowsM.filter(r => r.clase !== "Total");
    document.getElementById("tbl-mercado3-tbody").innerHTML = mercadoRowsAB.map((r, i) => {
      const cls = r.total ? ' class="row-total"' : '';
      const spacerBefore = (i > 0 && r.clase === "B" && mercadoRowsAB[i - 1].clase === "A")
        ? '<tr class="row-spacer"><td colspan="7">&nbsp;</td></tr>' : '';
      let rowHtml;
      if (r.inventario_m2 === undefined) {
        rowHtml = `<tr${cls}><td>${r.comuna}</td><td>${r.clase}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`;
      } else {
        rowHtml = `<tr${cls}><td>${r.comuna}</td><td>${r.clase}</td>` +
          celdaM(r.inventario_m2, false) + celdaM(r.absorcion_u12m_m2, false) +
          celdaM(r.vacancia_pct, true) + celdaM(r.renta_uf_m2, false) +
          celdaM(r.construccion_m2, false) + `</tr>`;
      }
      return spacerBefore + rowHtml;
    }).join("");

    // Evolución anual vacancia/renta Oficinas Las Condes (Clase A/B) — desde
    // raw_mercado_oficinas_evolucion, ver F.oficinas_evolucion.
    const of = F.oficinas_evolucion;
    if (of) {
      // Truncar la serie al trimestre que contiene la fecha operacional
      // seleccionada en los selectores — no mostrar trimestres futuros.
      const cutoff = usadoOp ? quarterEndOfM(usadoOp) : null;
      const idxs = of.periodos
        .map((p, i) => i)
        .filter(i => !cutoff || of.periodos[i] <= cutoff);
      const sliceBy = arr => idxs.map(i => arr[i]);
      const quartersF = sliceBy(of.quarters);
      const yearsF = [...new Set(idxs.map(i => Number(of.periodos[i].slice(0, 4))))];
      renderOficinasEvolucionChart("chart-vacancia-oficinas",
        { quarters: quartersF, years: yearsF, seriesA: sliceBy(of.vacancia_a), seriesB: sliceBy(of.vacancia_b) },
        "pct", "Vacancia");
      renderOficinasEvolucionChart("chart-rentas-oficinas",
        { quarters: quartersF, years: yearsF, seriesA: sliceBy(of.renta_a), seriesB: sliceBy(of.renta_b) },
        "uf", "Renta");
    }

    // Bodegas: raw_mercado_bodegas (snapshot por zona) + raw_mercado_bodegas_evolucion
    // (histórico semestral, ver F.mercado_bodegas / F.bodegas_evolucion).
    const bod = S.page3.bodegas;
    const semesterEndOfM = (periodo) => {
      const [y, m] = periodo.split("-").map(Number);
      return m <= 6 ? `${y}-06` : `${y}-12`;
    };
    const bodPeriodos = F.mercado_bodegas ? Object.keys(F.mercado_bodegas).sort() : [];
    const bodPeriodoSelector = usadoOp ? semesterEndOfM(usadoOp) : null;
    const bodPeriodoActual = bodPeriodos.length
      ? ([...bodPeriodos].reverse().find(p => !bodPeriodoSelector || p <= bodPeriodoSelector) || null)
      : null;
    const bodRows = bodPeriodoActual ? F.mercado_bodegas[bodPeriodoActual] : null;
    const bodP1 = document.getElementById("txt-mercado3-bodegas-1");
    const bodP2 = document.getElementById("txt-mercado3-bodegas-2");
    bodP1.textContent = "Pendiente: párrafo de vacancia/canon de arriendo (informe GPS Property) — sin fuente ingestada en la DB todavía.";
    bodP1.classList.add("placeholder");
    bodP2.textContent = "Pendiente: párrafo de producción y proyecciones (informe GPS Property).";
    bodP2.classList.add("placeholder");
    const fmtBod = (v, dec) => (v === null || v === undefined) ? null :
      v.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    const celdaBod = (v, esPct) => {
      if (v === null || v === undefined) return '<td class="placeholder">—</td>';
      const texto = esPct ? fmtBod(v, 1) + "%" : fmtBod(v, 0);
      return `<td>${texto}</td>`;
    };
    if (bodRows) {
      document.getElementById("tbl-bodegas-tbody").innerHTML = bodRows.map(r => {
        const cls = r.es_total ? ' class="row-total"' : '';
        return `<tr${cls}><td>${r.zona}</td>` +
          celdaBod(r.produccion_m2, false) + celdaBod(r.inventario_final_m2, false) +
          celdaBod(r.tasa_vacancia_pct, true) +
          `<td>${r.precio_uf_m2 !== null && r.precio_uf_m2 !== undefined ? r.precio_uf_m2.toLocaleString("es-CL", {minimumFractionDigits:3, maximumFractionDigits:3}) : '<span class="placeholder">—</span>'}</td>` +
          `</tr>`;
      }).join("");
    } else {
      document.getElementById("tbl-bodegas-tbody").innerHTML =
        bod.zonas.map(z => `<tr><td>${z}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`).join("")
        + `<tr class="row-total"><td>${bod.total_nombre}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`;
    }
    if (F.bodegas_evolucion) {
      // Truncar la serie semestral al semestre que contiene la fecha
      // operacional seleccionada — no mostrar semestres futuros.
      const bev = F.bodegas_evolucion;
      const bevIdxs = bev.periodos
        .map((p, i) => i)
        .filter(i => !bodPeriodoSelector || bev.periodos[i] <= bodPeriodoSelector);
      const bevSliceBy = arr => bevIdxs.map(i => arr[i]);
      renderBodegasChart("chart-bodegas", {
        semestres: bevSliceBy(bev.semestres),
        uf_m2: bevSliceBy(bev.uf_m2),
        vacancia_pct: bevSliceBy(bev.vacancia_pct),
      });
    } else {
      document.getElementById("chart-bodegas").innerHTML =
        `<div class="chart-placeholder" style="width:100%;height:100%">Pendiente de datos</div>`;
    }

    const cc = S.page3.centros_comerciales;
    document.getElementById("tbl-comercio-thead").innerHTML =
      "<th></th>" + cc.categorias.map(c => `<th>${c}</th>`).join("");
    document.getElementById("tbl-comercio-tbody").innerHTML =
      `<tr><td>${usadoOp ? mesEspanol(usadoOp) : "—"}</td>` +
      cc.categorias.map(() => '<td class="placeholder">—</td>').join("") + `</tr>`;
  }

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

    // Análisis de mercado de oficinas: solo si el fondo define submercado
    // (hoy Apo). PT no tiene esta sección en su PDF de referencia — en su
    // lugar muestra el plano de planta (ver bloque "page4-plano" más abajo).
    const hasMercado = !!S.page4.submercado;
    document.getElementById("page4-mercado").classList.toggle("hidden", !hasMercado);
    if (hasMercado) {
      document.getElementById("mercado-titulo").textContent =
        `Análisis de Mercado de Oficinas — Submercado ${S.page4.submercado}`;
      function celdaMercado(v, esPct) {
        if (v === null || v === undefined) return '<td class="placeholder">—</td>';
        const texto = esPct
          ? v.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%"
          : v.toLocaleString("es-CL", {maximumFractionDigits: 2});
        return `<td>${texto}</td>`;
      }
      // El informe JLL es trimestral: solo se muestra si el período operacional
      // seleccionado cae dentro del mismo trimestre calendario que el dato ingestado.
      const quarterEndOf = (periodo) => {
        const [y, m] = periodo.split("-").map(Number);
        const qEndMonth = Math.ceil(m / 3) * 3;
        return y + "-" + String(qEndMonth).padStart(2, "0");
      };
      const mercadoPeriodo = usadoOp ? quarterEndOf(usadoOp) : null;
      const mercadoRows = (F.mercado && F.mercado[mercadoPeriodo]) || S.page4.mercado_rows || [];

      // ---- Párrafos de vacancia / canon de arriendo: redactados desde la DB,
      // comparando el trimestre actual contra el inmediatamente anterior. ----
      function prevQuarterPeriodo(p) {
        const { year, q } = periodoToYQ(p);
        const prevQ = q === 1 ? 4 : q - 1;
        const prevYear = q === 1 ? parseInt(year, 10) - 1 : parseInt(year, 10);
        return prevYear + "-" + String(prevQ * 3).padStart(2, "0");
      }
      const ORDINAL_TRIMESTRE = { 1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto" };
      function findMercadoRow(rows, comunaPrefix, clase) {
        if (!rows) return null;
        return rows.find(r => r.comuna && r.comuna.startsWith(comunaPrefix) &&
          r.clase === clase && r.vacancia_pct !== undefined) || null;
      }
      function fmtMercadoNum(v, dec) {
        return (v === null || v === undefined) ? null :
          v.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
      }
      const p1El = document.getElementById("txt-mercado-p1");
      const p2El = document.getElementById("txt-mercado-p2");
      if (mercadoPeriodo) {
        const prevPeriodo = prevQuarterPeriodo(mercadoPeriodo);
        const prevRows = F.mercado && F.mercado[prevPeriodo];
        const submercado = S.page4.submercado;
        const totalAct = findMercadoRow(mercadoRows, submercado, "Total");
        const totalPrev = findMercadoRow(prevRows, submercado, "Total");
        const claseAAct = findMercadoRow(mercadoRows, submercado, "A");
        const claseAPrev = findMercadoRow(prevRows, submercado, "A");
        const claseBAct = findMercadoRow(mercadoRows, submercado, "B");
        const claseBPrev = findMercadoRow(prevRows, submercado, "B");

        if (totalAct) {
          const vAct = totalAct.vacancia_pct;
          const vPrev = totalPrev ? totalPrev.vacancia_pct : null;
          let verbo = "fue de";
          let comparativo = "";
          if (vPrev !== null && vPrev !== undefined) {
            if (vAct < vPrev) verbo = "disminuyó a";
            else if (vAct > vPrev) verbo = "aumentó a";
            else verbo = "se mantuvo en";
            comparativo = ` (${fmtQ(prevPeriodo)} ${fmtMercadoNum(vPrev, 1)}%)`;
          }
          p1El.textContent = `Respecto al submercado ${submercado}, donde se encuentran los edificios ` +
            `${S.page3.edificios.join(" y ")}, según el informe de JLL durante el ${fmtQ(mercadoPeriodo)} la vacancia ` +
            `${verbo} ${fmtMercadoNum(vAct, 1)}%${comparativo}.`;
          p1El.classList.remove("placeholder");
        } else {
          p1El.textContent = "Pendiente: párrafo de vacancia (informe JLL) — sin datos ingestados para este trimestre.";
          p1El.classList.add("placeholder");
        }

        const partesRenta = [];
        if (claseAAct) {
          const rAct = fmtMercadoNum(claseAAct.renta_uf_m2, 2);
          const rPrev = claseAPrev ? fmtMercadoNum(claseAPrev.renta_uf_m2, 2) : null;
          partesRenta.push(`de ${rAct} UF/m² ${rPrev ? `(${fmtQ(prevPeriodo)} ${rPrev} UF/m²) ` : ""}en oficinas clase A`);
        }
        if (claseBAct) {
          const rAct = fmtMercadoNum(claseBAct.renta_uf_m2, 2);
          const rPrev = claseBPrev ? fmtMercadoNum(claseBPrev.renta_uf_m2, 2) : null;
          partesRenta.push(`de ${rAct} UF/m² ${rPrev ? `(${fmtQ(prevPeriodo)} ${rPrev} UF/m²) ` : ""}en oficinas clase B`);
        }
        if (partesRenta.length) {
          const { q } = periodoToYQ(mercadoPeriodo);
          p2El.textContent = `Respecto al canon de arriendo promedio en ${submercado}, durante el ` +
            `${ORDINAL_TRIMESTRE[q]} trimestre fue ${partesRenta.join(" y ")}.`;
          p2El.classList.remove("placeholder");
        } else {
          p2El.textContent = "Pendiente: párrafo de canon de arriendo (informe JLL) — sin datos ingestados para este trimestre.";
          p2El.classList.add("placeholder");
        }
      }

      document.getElementById("tbl-mercado-tbody").innerHTML =
        mercadoRows.map(r => {
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

    // Plano de planta (PT, hoy Plano Local 100): SVG con viewBox = las
    // coordenadas originales del plano (ver FONDOS_CFG["PT"]["page4"]
    // ["plano"]) — la imagen se estira a llenar ese viewBox con <image> y
    // cada local es un <rect>/<polygon> con esas mismas coordenadas, sin
    // reescalar a mano (si el archivo de imagen cambia de resolución pero
    // mantiene la misma composición, sigue calzando). Color/tooltip
    // dependen del rent roll del período usadoOp; la silueta no.
    const hasPlano = !!S.page4.plano;
    document.getElementById("page4-plano").classList.toggle("hidden", !hasPlano);
    if (hasPlano) {
      const plano = S.page4.plano;
      document.getElementById("plano-titulo").textContent = plano.titulo;
      const datosPeriodo = usadoOp ? (F.plano_locales || {})[usadoOp] : null;
      const shapeSvg = (loc, i, cls) => {
        if (loc.poligono) {
          const pts = loc.poligono.map(([px, py]) => `${px},${py}`).join(" ");
          return `<polygon class="plano-shape ${cls}" data-i="${i}" points="${pts}"></polygon>`;
        }
        return `<rect class="plano-shape ${cls}" data-i="${i}" x="${loc.x}" y="${loc.y}" width="${loc.w}" height="${loc.h}"></rect>`;
      };
      const planoBbox = (loc) => {
        if (loc.poligono) {
          const xs = loc.poligono.map(p => p[0]), ys = loc.poligono.map(p => p[1]);
          const x = Math.min(...xs), y = Math.min(...ys);
          return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
        }
        return { x: loc.x, y: loc.y, w: loc.w, h: loc.h };
      };
      // Nombre/arrendatario/m² dentro de cada local — horizontal si entra;
      // si no, rotado 90° (igual que "100-2 DISPONIBLE" en el plano
      // original) para locales angostos (Relevé, Jiu Jitsu, Crossfit); si
      // ni así entra, se omite (el tooltip sigue disponible al pasar el
      // cursor).
      // Parte una línea larga (típicamente el arrendatario) en 2 si no
      // entra en maxChars, cortando en el espacio más cercano al medio —
      // sin esto, un nombre largo ("Santiago Businnes Center SpA") hacía
      // fallar el fit completo y se perdían arrendatario+m² igual en
      // locales grandes como 100-1/100-2.
      const wrapToWidth = (text, maxChars) => {
        if (text.length <= maxChars) return [text];
        const mid = Math.floor(text.length / 2);
        let idx = text.lastIndexOf(" ", mid);
        if (idx <= 0) idx = text.indexOf(" ", mid);
        if (idx <= 0) return [text];
        return [text.slice(0, idx), text.slice(idx + 1)];
      };
      const planoLabelSvg = (loc, d, vbH) => {
        const bbox = planoBbox(loc);
        // El centro del bounding box puede caer fuera del relleno en formas
        // cóncavas (ej. el retranqueo/L de 100-1 y el chevron de 100-2) —
        // loc.label_at fija un punto garantizado dentro del polígono, y
        // loc.label_box el espacio real disponible ahí (el bbox completo del
        // polígono puede ser mucho más grande que el hueco angosto real
        // donde va a caer el texto) — el resto usa el bbox tal cual.
        const [cx, cy] = loc.label_at || [bbox.x + bbox.w / 2, bbox.y + bbox.h / 2];
        const [availW, availH] = loc.label_box || [bbox.w, bbox.h];
        const fs = vbH * 0.019;
        // El nombre del local es siempre su código de unidad (100-9, no
        // "Smartfit") — el arrendatario real va en la línea de abajo y
        // puede cambiar; el código no.
        const nombre = loc.unidad;
        const sub = !d ? [] : d.vacante ? ["Vacante"] : [d.arrendatario, `${_fmtM2(d.m2)} m²`];
        const full = [nombre, ...sub];
        const charW = fs * 0.56, lineH = fs * 1.25;
        const wrapAll = (lines, maxChars) => lines.flatMap(l => wrapToWidth(String(l), maxChars));
        const fitsH = (lines) => {
          const maxChars = Math.max(4, Math.floor((availW - fs) / charW));
          const wrapped = wrapAll(lines, maxChars);
          return availH > lineH * wrapped.length + fs * 0.6 ? wrapped : null;
        };
        const fitsV = (lines) => {
          const maxChars = Math.max(4, Math.floor((availH - fs) / charW));
          const wrapped = wrapAll(lines, maxChars);
          return availW > lineH * wrapped.length + fs * 0.6 ? wrapped : null;
        };
        let mode = null, lines = null;
        // loc.orientation fuerza horizontal/vertical (salta la detección
        // automática) para formas donde el auto-fit elige mal.
        if (loc.orientation === "v") {
          if ((lines = fitsV(full))) { mode = "v"; }
          else if ((lines = fitsV([nombre]))) { mode = "v"; }
          else { mode = "v"; lines = [nombre]; }
        } else if (loc.orientation === "h") {
          if ((lines = fitsH(full))) { mode = "h"; }
          else if ((lines = fitsH([nombre]))) { mode = "h"; }
          else { mode = "h"; lines = [nombre]; }
        } else if ((lines = fitsH(full))) { mode = "h"; }
        else if ((lines = fitsH([nombre]))) { mode = "h"; }
        else if ((lines = fitsV(full))) { mode = "v"; }
        else if ((lines = fitsV([nombre]))) { mode = "v"; }
        else return "";
        const startY = cy - (lines.length - 1) * lineH / 2;
        const tspans = lines.map((l, li) =>
          `<tspan x="${cx}" y="${startY + li * lineH}" class="${li === 0 ? "nombre" : "sub"}">${l}</tspan>`
        ).join("");
        const rotate = mode === "v" ? ` transform="rotate(-90 ${cx} ${cy})"` : "";
        return `<text class="plano-label" font-size="${fs}"${rotate}>${tspans}</text>`;
      };
      document.getElementById("grid-plano").innerHTML = plano.pisos.map(piso => `
        <div class="chart-box">
          <div class="chart-title">${piso.nombre}</div>
          <div class="plano-piso" id="plano-${slug(piso.nombre)}">
            <svg viewBox="0 0 ${piso.viewbox_w} ${piso.viewbox_h}" preserveAspectRatio="xMidYMid meet">
              <image href="${piso.imagen}" x="0" y="0" width="${piso.viewbox_w}" height="${piso.viewbox_h}" preserveAspectRatio="none"></image>
              ${piso.locales.map((loc, i) => {
                const d = datosPeriodo ? datosPeriodo[loc.unidad] : null;
                const cls = !d ? "" : d.vacante ? "plano-local-vac" : "plano-local-occ";
                return shapeSvg(loc, i, cls) + planoLabelSvg(loc, d, piso.viewbox_h);
              }).join("")}
            </svg>
          </div>
        </div>`).join("");

      plano.pisos.forEach(piso => {
        const el = document.getElementById(`plano-${slug(piso.nombre)}`);
        if (!el) return;
        const tt = _statusTooltip(el);
        el.querySelectorAll(".plano-shape").forEach(shapeEl => {
          const loc = piso.locales[Number(shapeEl.dataset.i)];
          const d = datosPeriodo ? datosPeriodo[loc.unidad] : null;
          const html = !d
            ? `<div class="title">${loc.unidad}</div><div class="line"><span class="label">Sin dato</span></div>`
            : `<div class="title">${d.vacante ? "Vacante" : "Ocupado"}</div>` +
              (d.vacante ? "" :
                `<div class="line"><span class="label">Arrendatario</span><span class="value">${d.arrendatario}</span></div>` +
                `<div class="line"><span class="label">UF/m²/mes</span><span class="value">${_ufM2Mes(d.renta_uf)}</span></div>`) +
              `<div class="line"><span class="label">m² totales</span><span class="value">${_fmtM2(d.m2)}</span></div>`;
          shapeEl.addEventListener("mouseenter", (e) => tt.show(html, e));
          shapeEl.addEventListener("mousemove", (e) => tt.move(e));
          shapeEl.addEventListener("mouseleave", tt.hide);
        });
      });
    }

    // Indicadores Activos (TRI): tabla tasación/deuda/LTV consolidada — datos
    // ya vienen resueltos desde fetch_fondo() en F.page4_indicadores (no
    // depende del selector de período de la página, ver comentario en
    // build_factsheet.py::fetch_fondo).
    const hasIndicadores = !!S.page4.indicadores_rows;
    document.getElementById("page4-indicadores").classList.toggle("hidden", !hasIndicadores);
    if (hasIndicadores && F.page4_indicadores) {
      const pi = F.page4_indicadores;
      const fmtUf = (v) => v == null ? "—" : Math.round(v).toLocaleString("es-CL");
      const fmtLtv = (v) => v == null ? "—" : (v * 100).toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%";
      const fmtFechaQ = (fecha) => {
        if (!fecha) return "—";
        const [y, m] = fecha.split("-");
        const q = Math.ceil(parseInt(m, 10) / 3);
        return `${q}Q${y.slice(2)}`;
      };
      // Filas con deuda_shared_key comparten una única celda Deuda/LTV con
      // rowspan=2 (calculada sobre el valor combinado de ambos activos) — hoy
      // Apoquindo 4501/4700, ver page4.indicadores_rows en config.
      let rowsHtml = "";
      for (let i = 0; i < pi.rows.length; i++) {
        const r = pi.rows[i];
        const next = pi.rows[i + 1];
        const sharesWithNext = r.deuda_shared_key && next && next.deuda_shared_key === r.deuda_shared_key;
        rowsHtml += `<tr><td>${r.participacion}</td><td>${r.label}</td>` +
          `<td>${fmtUf(r.valor_uf)}</td><td class="fecha-tasacion">${fmtFechaQ(r.fecha)}</td>`;
        if (sharesWithNext) {
          const valorCombinado = (r.valor_uf || 0) + (next.valor_uf || 0);
          const ltvCombinado = r.deuda_uf != null && valorCombinado ? r.deuda_uf / valorCombinado : null;
          rowsHtml += `<td rowspan="2">${fmtUf(r.deuda_uf)}</td><td rowspan="2">${fmtLtv(ltvCombinado)}</td>`;
        } else if (!r.deuda_shared_key) {
          rowsHtml += `<td>${fmtUf(r.deuda_uf)}</td><td>${fmtLtv(r.ltv)}</td>`;
        }
        rowsHtml += `</tr>`;
      }
      rowsHtml += `<tr class="row-total"><td></td><td>${S.page4.total_nombre}</td>` +
        `<td>${fmtUf(pi.total_valor)}</td><td></td><td>${fmtUf(pi.total_deuda)}</td><td>${fmtLtv(pi.total_ltv)}</td></tr>`;
      document.getElementById("tbl-indicadores-tbody").innerHTML = rowsHtml;
    }

    // Centro Comercial Paseo Viña Centro (TRI): descripción + aspectos son
    // hechos estáticos del activo (ver S.page4.vina_centro); donuts GLA/
    // Ingresos y comentarios editoriales mensuales quedan en placeholder —
    // sin fuente en la DB todavía.
    const hasVina = !!S.page4.vina_centro;
    document.getElementById("page4-vina").classList.toggle("hidden", !hasVina);
    if (hasVina) {
      const vc = S.page4.vina_centro;
      document.getElementById("vina-titulo").textContent = vc.titulo;
      document.getElementById("txt-vina-descripcion").textContent = vc.descripcion;
      document.getElementById("tbl-vina-aspectos").querySelector("tbody").innerHTML =
        vc.aspectos.map(([k, v]) => `<tr><td>${k}</td><td${v === null ? ' class="placeholder"' : ""}>${v === null ? "Pendiente" : v}</td></tr>`).join("");
    }
  }

  // Página 5 (TRI): donuts GLA/Ingresos por subfondo + superficie/vacancia,
  // ya resueltos desde fetch_fondo() en F.page5 (no dependen del selector de
  // período — mismo criterio que F.page4_indicadores).
  if (S.page5 && F.page5) {
    const donutFromDict = (containerId, dict, unit, tooltipTitle) => {
      const el = document.getElementById(containerId);
      el.classList.remove("chart-placeholder");
      if (!dict || !Object.keys(dict).length) {
        el.classList.add("chart-placeholder");
        el.innerHTML = "Pendiente de datos";
        return;
      }
      const total = Object.values(dict).reduce((s, v) => s + v, 0);
      const donutData = Object.entries(dict).map(([n, v]) => [
        n, total ? Math.round(v / total * 1000) / 10 : 0, { value: v, unit },
      ]);
      renderDonut(containerId, donutData, { tooltipTitle });
    };
    // Página 5 PT: un arrendatario menos que en la página 3 propia de PT —
    // el más chico de los nombrados se pliega a "Otros" (que crece). Solo
    // afecta esta página; no toca el top-N real (rent_roll_stats._top_n_arrendatario)
    // que sigue sirviendo la página 3 de PT tal cual.
    const foldSmallestIntoOtros = (dict) => {
      if (!dict) return dict;
      const entries = Object.entries(dict).filter(([n]) => n !== "Otros");
      if (entries.length < 2) return dict;
      entries.sort((a, b) => a[1] - b[1]);
      const [smallName, smallVal] = entries[0];
      const out = {};
      for (const [n, v] of Object.entries(dict)) {
        if (n === smallName) continue;
        out[n] = v;
      }
      out["Otros"] = (out["Otros"] || 0) + smallVal;
      return out;
    };
    const fillSection = (rootId, data) => {
      const root = document.getElementById(rootId);
      const donutGla = root.querySelector(".page5-donut-gla");
      const donutIngresos = root.querySelector(".page5-donut-ingresos");
      donutGla.id = donutGla.id || `${rootId}-donut-gla`;
      donutIngresos.id = donutIngresos.id || `${rootId}-donut-ingresos`;
      const isPt = rootId === "page5-section-pt";
      const gla = isPt ? foldSmallestIntoOtros(data.gla_arrendatario) : data.gla_arrendatario;
      const ingresos = isPt ? foldSmallestIntoOtros(data.ingresos_arrendatario) : data.ingresos_arrendatario;
      donutFromDict(donutGla.id, gla || data.gla_edificios, "m²", "GLA");
      donutFromDict(donutIngresos.id, ingresos || data.ingresos_edificios, "UF", "Ingresos");
      root.querySelectorAll(".page5-aspecto-pendiente").forEach(td => {
        const key = td.dataset.key;
        if (key === "Superficie Arrendable" && data.superficie_arrendable != null) {
          td.textContent = Math.round(data.superficie_arrendable).toLocaleString("es-CL") + " m²";
          td.classList.remove("placeholder");
        } else if ((key === "Vacancia" || key === "Vacancia (m²)") && data.vacancia_pct != null) {
          td.textContent = data.vacancia_pct.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%";
          td.classList.remove("placeholder");
        }
      });
    };
    fillSection("page5-section-pt", F.page5.pt);
    fillSection("page5-section-apo", F.page5.apo);
  }

  // Página 6 (TRI): donuts GLA/Ingresos de Mall Curicó + superficie/vacancia
  // reales, ya resueltos desde fetch_fondo() en F.page6.curico (rent roll,
  // no depende del selector de período de la página — mismo criterio que
  // F.page4_indicadores / F.page5).
  if (S.page6 && F.page6) {
    const cur = F.page6.curico;
    const donutOrPlaceholder = (containerId, dict, unit, tooltipTitle) => {
      const el = document.getElementById(containerId);
      el.classList.remove("chart-placeholder");
      if (!dict || !Object.keys(dict).length) {
        el.classList.add("chart-placeholder");
        el.innerHTML = "Pendiente de datos";
        return;
      }
      const total = Object.values(dict).reduce((s, v) => s + v, 0);
      const donutData = Object.entries(dict).map(([n, v]) => [
        n, total ? Math.round(v / total * 1000) / 10 : 0, { value: v, unit },
      ]);
      renderDonut(containerId, donutData, { tooltipTitle });
    };
    donutOrPlaceholder("donut-curico-gla", cur.gla_arrendatario, "m²", "GLA");
    donutOrPlaceholder("donut-curico-ingresos", cur.ingresos_arrendatario, "UF", "Ingresos");
    document.querySelectorAll(".page6-curico-pendiente").forEach(td => {
      const key = td.dataset.key;
      if (key === "Superficie Arrendable" && cur.superficie_arrendable != null) {
        td.textContent = Math.round(cur.superficie_arrendable).toLocaleString("es-CL") + " m²";
        td.classList.remove("placeholder");
      } else if (key === "Vacancia (m²)" && cur.vacancia_pct != null) {
        td.textContent = cur.vacancia_pct.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%";
        td.classList.remove("placeholder");
      }
    });
  }

  // Página 7 (TRI): donuts GLA/Ingresos + superficie/vacancia reales de
  // Apoquindo 3001 y Bodegas Sucden Chile — ya resueltos desde fetch_fondo()
  // en F.page7 (rent roll, no depende del selector de período de la página).
  if (S.page7 && F.page7) {
    const donutOrPlaceholder7 = (containerId, dict, unit, tooltipTitle) => {
      const el = document.getElementById(containerId);
      el.classList.remove("chart-placeholder");
      if (!dict || !Object.keys(dict).length) {
        el.classList.add("chart-placeholder");
        el.innerHTML = "Pendiente de datos";
        return;
      }
      const total = Object.values(dict).reduce((s, v) => s + v, 0);
      const donutData = Object.entries(dict).map(([n, v]) => [
        n, total ? Math.round(v / total * 1000) / 10 : 0, { value: v, unit },
      ]);
      renderDonut(containerId, donutData, { tooltipTitle });
    };
    const fillPage7Section = (rootId, data) => {
      const root = document.getElementById(rootId);
      const donutGla = root.querySelector(".page7-donut-gla");
      const donutIngresos = root.querySelector(".page7-donut-ingresos");
      donutGla.id = donutGla.id || `${rootId}-donut-gla`;
      donutIngresos.id = donutIngresos.id || `${rootId}-donut-ingresos`;
      donutOrPlaceholder7(donutGla.id, data.gla_arrendatario, "m²", "GLA");
      donutOrPlaceholder7(donutIngresos.id, data.ingresos_arrendatario, "UF", "Ingresos");
      root.querySelectorAll(".page7-aspecto-pendiente").forEach(td => {
        const key = td.dataset.key;
        if (key === "Superficie Arrendable" && data.superficie_arrendable != null) {
          td.textContent = Math.round(data.superficie_arrendable).toLocaleString("es-CL") + " m²";
          td.classList.remove("placeholder");
        } else if (key === "Vacancia (m²)" && data.vacancia_pct != null) {
          td.textContent = data.vacancia_pct.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%";
          td.classList.remove("placeholder");
        }
      });
    };
    fillPage7Section("page7-section-apo3001", F.page7.apo3001);
    fillPage7Section("page7-section-sucden", F.page7.sucden);
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
  document.getElementById("btn-export-pdf").addEventListener("click", openExportModal);
  document.getElementById("export-close").addEventListener("click", closeExportModal);
  document.getElementById("export-modal-bg").addEventListener("click", (ev) => {
    if (ev.target.id === "export-modal-bg") closeExportModal();
  });
  document.getElementById("export-download-btn").addEventListener("click", onDescargarPdf);
  document.getElementById("export-retry-btn").addEventListener("click", backToExportForm);

  const __params = new URLSearchParams(location.search);
  const __pFondo = __params.get("fondo");
  const __pCb = __params.get("cb");
  const __pOp = __params.get("op");
  const __pdfMode = __params.get("pdfmode") === "1";

  if (__pdfMode) {
    document.body.classList.add("pdf-export");
    // El PDF exportado siempre se ve en UF, independiente de la preferencia
    // guardada en localStorage del navegador que lo genera.
    unitState.balance = "uf";
    unitState.gastos = "uf";
    unitState.dfn = "uf";
  }

  if (__pFondo && FUNDS[__pFondo]) {
    switchFund(__pFondo);
    let __missing = false;
    if (__pCb) {
      const selCb = document.getElementById("sel-periodo-cb");
      if (Array.from(selCb.options).some(o => o.value === __pCb)) {
        selCb.value = __pCb;
        selCb.dispatchEvent(new Event("change"));
      } else {
        __missing = true;
      }
    }
    if (__pOp) {
      const selOp = document.getElementById("sel-periodo-op");
      if (Array.from(selOp.options).some(o => o.value === __pOp)) {
        selOp.value = __pOp;
        selOp.dispatchEvent(new Event("change"));
      } else {
        __missing = true;
      }
    }
    window.__PDF_READY__ = __missing ? "no_data" : true;
  } else {
    switchFund("TRI");
    if (__pdfMode) window.__PDF_READY__ = "no_data";
  }
})();
</script>
</div><!-- #main-content -->
<script>__CHAT_BUBBLE_JS__</script>
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
    chat_bubble_js = CHAT_BUBBLE_JS.read_text(encoding="utf-8")
    html = (
        HTML_TEMPLATE
        .replace("__DATA_JSON__", json.dumps(all_data, ensure_ascii=False))
        .replace("__KPI_META_JSON__", json.dumps(meta_out, ensure_ascii=False))
        .replace("__CHAT_BUBBLE_JS__", chat_bubble_js)
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"OK -> {OUT}")
    for k, d in all_data.items():
        print(f"  {k}: contable={len(d['contable'])} bursatil={len(d['bursatil'])} balance={len(d['balance'])} kpi={len(d['fondo_kpi'])} divs={len(d['dividendos'])}")


if __name__ == "__main__":
    main()
