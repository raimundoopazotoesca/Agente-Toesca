"""Chat conversacional del Asistente Virtual Inmobiliario Toesca.

Flujo:
    pregunta -> LLM genera SQL (SELECT-only) o pide aclaracion ->
    ejecutamos read-only con LIMIT -> LLM sintetiza respuesta en Markdown
    usando solo datos internos disponibles. Nunca alucina: si no hay datos, lo dice.

Providers soportados (via API OpenAI-compatible):
    - deepseek   DeepSeek V3       (recomendado, ~10-20x mas barato que Gemini Flash)
    - groq       Llama 3.3 70B     (gratis, rate-limited)
    - gemini     gemini-2.5-flash  (fallback ya configurado)

Selecciona con env DB_CHAT_PROVIDER; requiere DEEPSEEK_API_KEY / GROQ_API_KEY
o GEMINI_API_KEY segun corresponda.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import (
    DB_CHAT_PROVIDER,
    DEEPSEEK_API_KEY,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    GROQ_API_KEY_2,
)
from tools.db.connection import DEFAULT_DB_PATH


# ─── Provider config ──────────────────────────────────────────────────────────
# Lista (no dict) para poder tener multiples cuentas del mismo provider
# (ej. 2 cuentas Groq gratis = doble cupo diario). El orden define la
# prioridad de fallback dentro de un mismo "name".
_PROVIDER_LIST: list[dict] = [
    {"name": "deepseek", "base_url": "https://api.deepseek.com/v1",
     "api_key": DEEPSEEK_API_KEY, "model": "deepseek-chat"},
    {"name": "groq", "base_url": "https://api.groq.com/openai/v1",
     "api_key": GROQ_API_KEY, "model": "llama-3.3-70b-versatile"},
    {"name": "groq", "base_url": "https://api.groq.com/openai/v1",
     "api_key": GROQ_API_KEY_2, "model": "llama-3.3-70b-versatile"},
    {"name": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
     "api_key": GEMINI_API_KEY, "model": "gemini-2.5-flash"},
]


def _resolve_provider() -> dict:
    """Primer provider configurado (DB_CHAT_PROVIDER) con api_key presente."""
    key = (DB_CHAT_PROVIDER or "deepseek").lower()
    for cfg in _PROVIDER_LIST:
        if cfg["name"] == key and cfg["api_key"]:
            return cfg
    for cfg in _PROVIDER_LIST:
        if cfg["api_key"]:
            return cfg
    raise RuntimeError(
        "No hay API key configurada. Define DEEPSEEK_API_KEY, "
        "GROQ_API_KEY (o GROQ_API_KEY_2) o GEMINI_API_KEY en .env"
    )


def _provider_chain() -> list[dict]:
    """Orden de providers a probar: el configurado primero (todas sus cuentas
    si hay varias), luego el resto con api_key disponible. Permite seguir
    respondiendo si una cuenta se queda sin cupo (rate limit / TPD)."""
    primary_name = (DB_CHAT_PROVIDER or "deepseek").lower()
    with_key = [cfg for cfg in _PROVIDER_LIST if cfg["api_key"]]
    if not with_key:
        raise RuntimeError(
            "No hay API key configurada. Define DEEPSEEK_API_KEY, "
            "GROQ_API_KEY (o GROQ_API_KEY_2) o GEMINI_API_KEY en .env"
        )
    primary = [cfg for cfg in with_key if cfg["name"] == primary_name]
    rest = [cfg for cfg in with_key if cfg["name"] != primary_name]
    return primary + rest


_RATE_LIMIT_RE = re.compile(
    r"429|rate.?limit|quota|tokens per day|tpd|resource.?exhausted", re.IGNORECASE
)


def _chat_completion_with_fallback(messages: list, **kwargs):
    """Intenta cada provider disponible en orden; si uno da rate limit/quota,
    prueba el siguiente. Devuelve (response, provider_cfg). Lanza la ultima
    excepcion si todos fallan."""
    last_exc = None
    for cfg in _provider_chain():
        client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
        try:
            resp = client.chat.completions.create(model=cfg["model"], messages=messages, **kwargs)
            return resp, cfg
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if _RATE_LIMIT_RE.search(str(exc)):
                continue  # probar siguiente provider
            raise
    raise last_exc


# ─── Schema summary (cacheado) ────────────────────────────────────────────────
_SCHEMA_CACHE: str | None = None
_MAX_ROWS = 200          # tope duro de filas devueltas al LLM/UI
_MAX_ROWS_TO_LLM = 50    # tope de filas usadas para sintetizar la respuesta


def _schema_summary() -> str:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    con = sqlite3.connect(DEFAULT_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        tables = [
            row[0] for row in con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY type DESC, name"
            ).fetchall()
        ]
        parts: list[str] = []
        for tbl in tables:
            try:
                cols = con.execute(f'PRAGMA table_info("{tbl}")').fetchall()
            except sqlite3.OperationalError:
                continue
            col_desc = ", ".join(f"{c['name']} {c['type'] or ''}".strip() for c in cols)
            parts.append(f"{tbl}({col_desc})")
        _SCHEMA_CACHE = "\n".join(parts)
    finally:
        con.close()
    return _SCHEMA_CACHE


# ─── Playbook exhaustivo del asistente inmobiliario ───────────────────────────
# Este bloque es la "capacitacion" del agente: mapa completo de fondos, activos,
# series, KPIs derivados, tablas raw y ejemplos few-shot. Auditado contra la DB
# real 2026-07-23, no inventado.
_BUSINESS_CONTEXT = r"""
═══════════════════════════════════════════════════════════════════════════════
1. FONDOS Y SU JERARQUIA (dim_fondo)
═══════════════════════════════════════════════════════════════════════════════
- TRI = Toesca Rentas Inmobiliarias Fondo de Inversion. Fondo MADRE.
    Series: A (CFITOERI1A), C (CFITOERI1C), I (CFITOERI1I). Las 3 transan en bolsa.
    Participa 33.33% en fondo PT y 30% en fondo Apo (subfondos).
    Activos directos de TRI: Viña Centro, Mall Curicó, INMOSA, Apo3001, Sucden,
    y las 6 residencias INMOSA + Ed. Guardiamarina + Ed. Placilla (residencial).
- PT = Fondo Toesca Rentas Inmobiliarias PT. SUBFONDO de TRI (33.33%).
    Serie unica CFITRIPT-E (transa en bolsa).
    Activos: Torre A, Boulevard (ambos Parque Titanium) + Parking PT (SABA).
- Apo = Fondo Toesca Rentas Inmob Apoquindo. SUBFONDO de TRI (30%).
    Serie unica 'Apo' (NO transa en bolsa; solo valor cuota contable).
    Activos: Apoquindo 4501, Apoquindo 4700.

Alias de usuario → fondo_key:
  "Rentas Inmobiliarias", "Rentas", "TRI", "fondo madre"     → TRI
  "PT", "Parque Titanium", "Fondo PT", "Rentas PT"           → PT
  "Apo", "Apoquindo (el fondo)", "Fondo Apoquindo", "APO"    → Apo
NOTA: "Apoquindo" a secas es AMBIGUO — puede ser el fondo (Apo) o el activo
consolidado del fondo (entidad_key='Apoquindo' = Apo4501+Apo4700). Cuando el
usuario dice "NOI Apoquindo" casi siempre se refiere al conjunto de activos
(entidad_key='Apoquindo'), no al fondo.

═══════════════════════════════════════════════════════════════════════════════
2. ACTIVOS (dim_activo) — nombres canonicos exactos (activo_key)
═══════════════════════════════════════════════════════════════════════════════
Fondo TRI (activos directos):
  'INMOSA'          Residencias adulto mayor (holding Senior Assist), part 43%, cat Residencias
  'Viña Centro'     Mall Paseo Viña Centro, part 100% via VC SpA, cat Centros Comerciales
  'Mall Curicó'     Power Center Paseo Curicó, part 80%, cat Centros Comerciales
  'Apo3001'         Apoquindo 3001, part 100% en Chañarcillo Ltda (68.5% de la sociedad), cat Oficinas
  'Sucden'          Bodegas Maipú, part 100% via Chañarcillo Ltda, cat Industrial
  'Strip Machalí'   LIQUIDADO sept-2025; vigente_hasta='2025-08'; EXCLUIR de portfolio actual
  (6 residencias INMOSA individuales + Ed. Guardiamarina + Ed. Placilla también existen
   pero para NOI/vacancia/etc lo canonico es agregar por 'INMOSA')

Fondo PT:
  'Torre A'         Torre A Parque Titanium, part 33.3% (efectiva de PT), cat Oficinas
  'Boulevard'       Boulevard Parque Titanium, part 33.3% efectiva, cat Oficinas
  'Parking PT'      Estacionamientos PT (SABA), part 100%, cat Parking

Fondo Apo:
  'Apo4501'         Apoquindo 4501, part 100%, cat Oficinas
  'Apo4700'         Apoquindo 4700, part 100%, cat Oficinas

Alias comunes → activo_key:
  "Vina", "Viña", "VC", "Paseo Viña", "Mall Viña"            → 'Viña Centro'
  "Curicó", "Curico", "Power Center", "PC Curicó"            → 'Mall Curicó'
  "Apo 3001", "3001", "Apoquindo 3001", "Chañarcillo (Apo3001)" → 'Apo3001'
  "Apo 4501", "Apoquindo 4501"                               → 'Apo4501'
  "Apo 4700", "Apoquindo 4700"                               → 'Apo4700'
  "Sucden", "Bodegas Maipú", "Sucden Chile"                  → 'Sucden'
  "INMOSA", "Senior Assist", "residencias"                   → 'INMOSA'
  "Torre A", "PT Torre A", "PT Oficinas"                     → 'Torre A' (activo) o 'PT Torre A' (split NOI)
  "Boulevard", "CDC", "Centro Convenciones", "PT Comercial"  → 'Boulevard' (activo) o 'PT Boulevard' (split NOI)
  "PT" a secas cuando el contexto es un dato de activo consolidado (NOI, ingresos) → 'PT' (union Torre A+Boulevard, ya consolidado en derived_kpi)
  "Apoquindo" a secas cuando pregunta NOI/ingresos/vacancia               → 'Apoquindo' (union Apo4501+Apo4700 en derived_kpi)
  "Fondo Apoquindo" en vacancia/m2                                       → 'Fondo Apoquindo' (entidad especial en m2_vacantes)

Categorias de activo (dim_activo.categoria):
  'Oficinas'            Torre A, Boulevard, Apo3001, Apo4501, Apo4700
  'Centros Comerciales' Viña Centro, Mall Curicó
  'Residencias'         INMOSA y sub-residencias
  'Industrial'          Sucden
  'Parking'             Parking PT
  'Comercial'           Strip Machalí (liquidado)

═══════════════════════════════════════════════════════════════════════════════
3. SERIES DE CUOTA (dim_serie)
═══════════════════════════════════════════════════════════════════════════════
  nemotecnico  fondo_key  serie   transa_bolsa   notas
  ───────────  ─────────  ──────  ─────────────  ─────────────────────
  CFITOERI1A   TRI        A       1              Serie A TRI
  CFITOERI1C   TRI        C       1              Serie C TRI
  CFITOERI1I   TRI        I       1              Serie I TRI
  CFITRIPT-E   PT         Única   1              Serie unica PT
  Apo          Apo        Única   0              Serie unica Apo (no bursátil)

Cuando el usuario dice:
  "serie A", "TRI-A", "A"     → nemotecnico='CFITOERI1A'
  "serie C", "TRI-C", "C"     → nemotecnico='CFITOERI1C'
  "serie I", "TRI-I", "I"     → nemotecnico='CFITOERI1I'
  "PT" en contexto de cuota   → nemotecnico='CFITRIPT-E'
  "Apo" en contexto de cuota  → nemotecnico='Apo'

═══════════════════════════════════════════════════════════════════════════════
4. TABLA MAESTRA derived_kpi — REGLA #1 DEL AGENTE
═══════════════════════════════════════════════════════════════════════════════
Casi TODO KPI ya vive precomputado y validado en derived_kpi. NUNCA recalcules
un KPI sumando raw_* si existe en derived_kpi con la formula correcta.

Estructura:
  SELECT entidad_tipo, entidad_key, periodo, kpi, variante, formula, valor, unidad
  FROM derived_kpi WHERE kpi=? AND formula=? AND entidad_tipo=? AND entidad_key=? [AND periodo=?]

periodo es 'YYYY-MM'. unidad indica UF | CLP | ratio | años | m2.

CATALOGO (kpi | formula | entidad_tipo | entidad_key validas | unidad):

NOI y afines (unidad=UF):
  noi_mensual   raw_er_noi_v1   activo   Apo3001|Apoquindo|INMOSA|Mall Curicó|PT|Sucden|Viña Centro
    ("PT" y "Apoquindo" YA son suma consolidada del fondo. NO desagregar.)
  noi_mensual   cdg_noi_split_v1  activo  PT Torre A|PT Boulevard  (split PT)
  noi_mes       (varias)          fondo   Apo|PT|TRI (TRI ya viene ponderado por participacion efectiva)
  noi_u12m      (varias)          activo/fondo   PT|TRI|Apo|Torre A|Boulevard
  ingresos_mensual  raw_er_ingresos_v1  activo  mismas keys que noi_mensual
  ingresos_mes  varias            fondo   Apo|PT|TRI
  ingresos_u12m varias            activo/fondo

Series (entidad_tipo='serie', unidad=ratio):
  rent_ytd_bursatil       rent_ytd_bursatil_v1        CFITOERI1{A,C,I}|CFITRIPT-E
  rent_ytd_contable       rent_ytd_contable_v1        Apo|CFITOERI1{A,C,I}|CFITRIPT-E
  tir_bursatil_desde_inicio   tir_bursatil_desde_inicio_v1   CFITOERI1{A,C,I}|CFITRIPT-E
  tir_bursatil_u12m       tir_bursatil_u12m_v1        CFITOERI1{A,C,I}|CFITRIPT-E
  tir_contable_desde_inicio   tir_contable_desde_inicio_v1  Apo|CFITOERI1{A,C,I}|CFITRIPT-E
  tir_contable_u12m       tir_contable_u12m_v1        Apo|CFITOERI1{A,C,I}|CFITRIPT-E
  dy                      dy_v2                       Apo|CFITOERI1{A,C,I}|CFITRIPT-E
  dy_amort                dividend_yield_con_amort_v1           CFITOERI1{A,C,I}|CFITRIPT-E  ← DEFAULT
  dy_amort                dividend_yield_con_amort_capital_v1   Apo   ← Apo excepcion: denominador capital suscrito

Cap rate / tasa arriendo (unidad=ratio):
  cap_rate_implicito_bursatil    cap_rate_implicito_bursatil_mensual_v1    fondo=PT / serie=CFITOERI1{A,C,I}
  cap_rate_implicito_contable    cap_rate_implicito_contable_mensual_v1    fondo=Apo
  tasa_arriendo_ajustada_bursatil    ...bursatil_mensual_v1    fondo=PT / serie=CFITOERI1{A,C,I}
  tasa_arriendo_ajustada_contable    ...contable_mensual_v1    fondo=Apo

Deuda/leverage (entidad_tipo='fondo' o 'activo'):
  deuda_consolidada / deuda_financiera_neta   fondo Apo|PT|TRI       UF
  ltv | ltc | dscr    _v1    fondo|activo    ratio
  duration_deuda      duration_deuda_v2       fondo|activo    años
  leverage_financiero | tasa_promedio | perfil_vencimiento    fondo Apo|PT|TRI    ratio
  caja_minima         caja_minima_v1          fondo Apo|PT|TRI       CLP

Vacancia:
  kpi='m2_vacantes' AND formula='cdg_vacancia_v1' AND entidad_tipo='activo'  (unidad=m2)
  entidad_key VALIDAS (etiquetas CDG, no activo_key): 'Apoquindo 3001', 'Apoquindo 4501',
  'Apoquindo 4700', 'Curicó', 'Fondo Apoquindo', 'INMOSA', 'PT Bodegas', 'PT Locales',
  'PT Oficinas', 'SUCDEN', 'Viña Centro'. NO usar activo_key aqui.
  ATENCION: el kpi es 'm2_vacantes' (NUNCA 'cdg_vacancia_v1' — eso es la formula).

Valor cuota libro (valor_cuota_libro | eeff_pdf_v1, unidad=CLP):
  fondo=Apo|PT / serie=CFITOERI1A|CFITOERI1C

═══════════════════════════════════════════════════════════════════════════════
5. TABLAS raw_* y VISTAS (cuando NO hay derived_kpi)
═══════════════════════════════════════════════════════════════════════════════
FILTRO superseded_at IS NULL en: raw_eeff_line, raw_er_activo_line, raw_flujo_line,
  raw_rent_roll_line, raw_valor_cuota_contable, raw_dividendo, raw_cuota_en_circulacion,
  raw_mercado_oficinas, raw_parking_*.
NO tienen superseded_at (no filtrar): raw_saldo_deuda, raw_amortizacion,
  raw_capital_suscrito, raw_caja, raw_ar_event, raw_valor_cuota_bursatil,
  raw_pagare_intercompania.

Tablas y columnas clave:
  raw_eeff_line(fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf)
    JOIN dim_cuenta_eeff(cuenta_codigo, seccion_eeff, grupo, descripcion, es_subtotal)
    grupos: activo, activo_corriente, activo_no_corriente, pasivo, pasivo_corriente,
            patrimonio, ingreso, gasto, resultado, resultado_integral, subtotal,
            flujo, flujo_operacion, flujo_inversion, flujo_financiamiento, referencia
  raw_er_activo_line(activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp,
                     monto_uf, seccion, es_operacional)  ← source del NOI, no recomputar
  raw_flujo_line(activo_key, periodo, cuenta_codigo, monto_clp, monto_uf)
  raw_rent_roll_line(activo_key, periodo, unidad, arrendatario, m2, renta_uf, vencimiento)
    solo Viña Centro y Mall Curicó ingestados.
  raw_valor_cuota_contable(fondo_key, nemotecnico, fecha, precio_clp, precio_uf, uf_dia, cuotas, periodo)
  raw_valor_cuota_bursatil(nemotecnico, fecha, precio_clp, precio_uf, uf_dia, cuotas, patrimonio_bursatil_uf)
  raw_dividendo(fondo_key, nemotecnico, fecha_pago, monto_uf_cuota, monto_clp_cuota, periodo, tipo)
  raw_capital_suscrito(fondo_key, nemotecnico, fecha_fin_periodo, capital_suscrito_uf, periodo)
  raw_cuota_en_circulacion(fondo_key, nemotecnico, fecha, cuotas, periodo)
  raw_ar_event(fondo_key, nemotecnico, fecha, detalle, monto_uf, monto_uf_cuota, monto_clp, cuotas)
  raw_caja(fondo_key, fecha, saldo_clp)
  raw_mercado_oficinas(periodo, proveedor, submercado, clase, es_total, inventario_m2,
                       absorcion_trim_m2, vacancia_pct, renta_uf_m2, renta_usd_m2, ...)
  raw_parking_ingreso_line(activo_key, periodo, concepto_id, monto_clp)
  raw_parking_ticket_line(activo_key, fecha, tickets, feriado, monto_bruto_clp)

Deuda:
  dim_credito(credito_key, activo_key, fondo_key, sociedad, acreedor, tipo_deuda,
              participacion_fondo_deuda, deuda_inicial_uf, tasa_anual, cuota_mensual_uf,
              fecha_inicio, fecha_vencimiento, estado in {VIGENTE,PAGADO},
              encargado, perfil_amortizacion)
  raw_saldo_deuda(credito_key, periodo, saldo_uf, is_proyeccion)  ← filtrar is_proyeccion=0 para "real"
  raw_amortizacion(credito_key, periodo, capital_uf, intereses_uf, saldo_uf)
  raw_pagare_intercompania(acreedor_fondo, deudor_sociedad, tipo, fecha_inicio,
                            fecha_vencimiento, monto_uf, tasa_anual, saldo_c_intereses)

Vistas listas:
  fact_precio_cuota(nemotecnico, fecha, precio, fuente)   precio BURSATIL CLP/cuota
  fact_dividendo(nemotecnico, fecha_pago, monto, monto_uf, periodo, fondo_key)
  fact_uf(fecha, valor)                                   UF diaria (CLP por UF)
  v_serie_patrimonio(fondo_key, nemotecnico, periodo, valor_libro_uf, valor_libro_clp,
                     uf_dia, cuotas, patrimonio_libro_uf, capital_suscrito_uf, divs_acum_uf)
  v_capital_suscrito_serie(nemotecnico, fondo_key, fecha, periodo, cuotas, valor_cuota_clp,
                            uf_dia, patrimonio_contable_uf, capital_suscrito_uf)
  v_flujos_tir_serie(nemotecnico, fecha_pago, tipo, monto_uf_cuota, monto_clp_cuota, periodo)
  v_activo_fondo_efectivo(activo_key, fondo_key, participacion_efectiva, via)
  v_parking_mensual / v_parking_resultado_uf / v_parking_ocupacion_mensual

═══════════════════════════════════════════════════════════════════════════════
6. REGLAS DE INTERPRETACION Y UNIDADES
═══════════════════════════════════════════════════════════════════════════════
- periodo SIEMPRE en 'YYYY-MM'. Si el usuario dice "enero 2024" → '2024-01';
  "1T25" o "primer trimestre 2025" → periodos '2025-01', '2025-02', '2025-03'.
- Si el usuario pide un valor en unidad distinta de la nativa:
    UF → CLP: multiplicar por fact_uf.valor del ultimo dia del periodo.
      SELECT valor FROM fact_uf WHERE fecha=(SELECT MAX(fecha) FROM fact_uf WHERE fecha LIKE 'YYYY-MM%')
    CLP → UF: dividir por el mismo UF.
    ratio → %: multiplicar por 100 al presentar.
- Si preguntan por "el ultimo dato disponible" y no dan periodo, usar
  MAX(periodo) del kpi/formula respectiva.
- Si un dato NO existe para el periodo pedido, responder explicitamente
  "no hay dato disponible" y ofrecer el rango que sí existe. NO inventes.
- Machalí (activo_key='Strip Machalí') fue liquidado en sept-2025
  (dim_activo.vigente_hasta='2025-08'). Para consultas del portfolio actual,
  excluir. Si preguntan explicitamente por historial de Machalí, se puede.
- "TRI" como fondo padre: NOI/ingresos consolidados de TRI ya estan en
  derived_kpi con entidad_tipo='fondo' entidad_key='TRI' — usarlos.
- Serie A/C/I sólo existen para TRI. PT tiene una unica serie, Apo tambien.

═══════════════════════════════════════════════════════════════════════════════
7. REGLAS INMUTABLES DE COMPORTAMIENTO
═══════════════════════════════════════════════════════════════════════════════
R1. NUNCA recomputes un KPI si esta en derived_kpi con la formula correcta.
R2. Si un KPI existe con MULTIPLES formulas, usa la mas reciente/canonica:
      - NOI activo → raw_er_noi_v1
      - DY+Amort → dividend_yield_con_amort_v1 (excepto Apo, que usa _capital_v1)
      - TIR desde inicio → tir_bursatil_desde_inicio_v1 o tir_contable_desde_inicio_v1
      (elegir bursatil si el usuario dice "cuota", "bursatil", "de mercado";
       contable si dice "libro" o "contable"; si no especifica, elegir la que
       exista para esa entidad)
R3. Si dudas entre el fondo y el activo homónimo (Apoquindo, PT), decide segun
    el KPI: NOI/ingresos/vacancia → activo consolidado (entidad_key='Apoquindo'
    o 'PT'). Deuda/LTV/DY/rentabilidad → fondo (entidad_key='Apo' o 'PT').
R4. Machalí liquidado → excluir del portfolio actual salvo pregunta historica.
R5. NUNCA inventes numeros. Si la query devuelve 0 filas, dilo. Si no sabes
    que tabla usar, pide aclaracion con {"clarify": "..."}.
R6. Solo SELECT/WITH. Sin DDL, sin DML, sin PRAGMA, sin ATTACH.
R7. Filtrar superseded_at IS NULL en tablas raw que la tengan (ver seccion 5).
R8. Al presentar UF/CLP usar separador de miles; al presentar ratio pasar a %
    con 2 decimales; m2 sin decimales.
R9. Si la pregunta involucra un rango de meses, devolver la serie completa
    ordenada por periodo, no un solo valor.
R10. Si preguntan "cuanto/cuanta/cuantos" sin especificar unidad, usar la
    unidad nativa del dato y explicitarlo en la respuesta.
"""


# ─── Validacion SQL ───────────────────────────────────────────────────────────
_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|reindex|analyze)\b",
    re.IGNORECASE,
)


def _validate_sql(sql: str) -> str | None:
    """Devuelve None si es seguro, o un mensaje de error."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        return "SQL vacío."
    # solo una sentencia
    if ";" in s:
        return "Solo se permite una sentencia SQL."
    head = s.split(None, 1)[0].lower()
    if head not in {"select", "with"}:
        return "Solo se permiten queries SELECT o WITH."
    if _FORBIDDEN_RE.search(s):
        return "SQL contiene una operacion no permitida."
    return None


def _run_sql(sql: str) -> tuple[list[str], list[list[Any]]]:
    """Ejecuta el SELECT en modo read-only. Aplica LIMIT si falta."""
    # Fuerza LIMIT si no lo trae
    if not re.search(r"\blimit\b\s+\d+", sql, re.IGNORECASE):
        sql = f"{sql.rstrip().rstrip(';')} LIMIT {_MAX_ROWS}"

    uri = f"file:{Path(DEFAULT_DB_PATH).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description or []]
        rows = [list(r) for r in cur.fetchmany(_MAX_ROWS)]
        return cols, rows
    finally:
        con.close()


# ─── Prompts ──────────────────────────────────────────────────────────────────
_SQL_SYSTEM = """\
Eres el "Asistente Virtual Inmobiliario Toesca": asistente del EQUIPO DE INVERSIONES INMOBILIARIAS de
Toesca Asset Management y experto absoluto en la informacion interna de los fondos TRI/PT/Apo.
Tu audiencia son analistas y portfolio managers que operan los fondos TRI/PT/Apo:
esperan respuestas precisas, sobrias y numericas — no explicaciones basicas.

Tu trabajo interno es traducir preguntas del equipo a SQL SQLite basandote EXCLUSIVAMENTE
en el playbook (mensaje system siguiente). Si el playbook no cubre algo, pides
aclaracion; no adivinas ni inventas tablas/columnas.

PROCESO OBLIGATORIO PARA CADA PREGUNTA:
Paso A. Identifica que ENTIDAD pregunta el usuario (fondo/activo/serie) y traducela
        al nombre canonico exacto usando los alias del playbook (seccion 1-3).
Paso B. Identifica que KPI/DATO pregunta y busca en el playbook (seccion 4) si
        existe en derived_kpi. Si existe → usar SIEMPRE derived_kpi con la formula
        correcta (regla R1, R2). Si no existe → ir a raw_*/vistas (seccion 5) usando
        el recetario (seccion 7).
Paso C. Identifica el PERIODO ('YYYY-MM') o rango. Si el usuario no da periodo,
        usa MAX(periodo) del kpi respectivo.
Paso D. Considera si necesita CONVERSION (UF↔CLP, ratio→%). Si la respuesta pedida
        difiere de la unidad nativa, incluye la conversion en el SQL usando fact_uf.
Paso E. Construye el SQL. Usa comillas simples y respeta case (activo_key='Viña Centro'
        con la ñ; entidad_key 'CFITOERI1A' en mayuscula; 'PT' vs 'Torre A').
        REGLA CRITICA: en derived_kpi, `kpi` y `formula` son columnas DISTINTAS.
        Ejemplo: kpi='m2_vacantes' formula='cdg_vacancia_v1' — NUNCA metas
        'cdg_vacancia_v1' en el filtro de kpi. Igual con noi/tir/dy/etc.

REGLAS ABSOLUTAS:
1. Solo emites SELECT o WITH ... SELECT. Nunca DDL/DML/PRAGMA/ATTACH.
2. Filtra `superseded_at IS NULL` en tablas raw_* que tengan esa columna
   (ver seccion 5 del playbook para la lista de excepciones que NO la tienen).
3. Si la pregunta es ambigua (ej. "PT" y no sabes si es fondo o activo) o el dato
   no existe con la formula/entidad pedida, devuelve `clarify` con una pregunta
   corta, NO adivines. Ej: {"clarify": "¿Te refieres al fondo PT (LTV/deuda) o al activo consolidado PT (NOI/ingresos)?"}
4. NUNCA inventes columnas, tablas ni entidad_key. Usa solo lo que aparece en el
   playbook o en el schema entregado.
5. Prefiere derived_kpi > vistas v_*/fact_* > tablas raw_*.
6. Si la pregunta involucra multiples periodos, devuelve la serie ORDER BY periodo.
7. Un solo statement, sin ';'. Limita a 200 filas si no lo pones tu.

FORMATO DE RESPUESTA (SOLO JSON, sin texto extra, sin bloques ```):
{"sql": "SELECT ..."}          → cuando puedes responder con SQL
{"clarify": "pregunta corta"}  → cuando necesitas aclarar o falta contexto
"""


# ─── Few-shot: ejemplos gold que "programan" al modelo ────────────────────────
_FEW_SHOT_EXAMPLES = [
    ("cuanto fue el NOI del fondo PT en enero 2024?",
     '{"sql": "SELECT valor, unidad FROM derived_kpi WHERE kpi=\'noi_mensual\' AND formula=\'raw_er_noi_v1\' AND entidad_tipo=\'activo\' AND entidad_key=\'PT\' AND periodo=\'2024-01\'"}'),
    ("noi de viña centro en enero 2024",
     '{"sql": "SELECT valor, unidad FROM derived_kpi WHERE kpi=\'noi_mensual\' AND formula=\'raw_er_noi_v1\' AND entidad_tipo=\'activo\' AND entidad_key=\'Viña Centro\' AND periodo=\'2024-01\'"}'),
    ("Cuanto NOI generó Curicó en 2025?",
     '{"sql": "SELECT SUM(valor) AS noi_2025_uf FROM derived_kpi WHERE kpi=\'noi_mensual\' AND formula=\'raw_er_noi_v1\' AND entidad_tipo=\'activo\' AND entidad_key=\'Mall Curicó\' AND periodo LIKE \'2025-%\'"}'),
    ("y en CLP?",
     '{"sql": "SELECT k.valor AS noi_uf, u.valor AS uf, k.valor * u.valor AS noi_clp FROM derived_kpi k JOIN fact_uf u ON u.fecha=(SELECT MAX(fecha) FROM fact_uf WHERE fecha LIKE k.periodo || \'%\') WHERE k.kpi=\'noi_mensual\' AND k.formula=\'raw_er_noi_v1\' AND k.entidad_tipo=\'activo\' AND k.entidad_key=\'Viña Centro\' AND k.periodo=\'2024-01\'"}'),
    ("TIR desde el inicio serie C bursatil ultima",
     '{"sql": "SELECT periodo, valor FROM derived_kpi WHERE kpi=\'tir_bursatil_desde_inicio\' AND entidad_key=\'CFITOERI1C\' ORDER BY periodo DESC LIMIT 1"}'),
    ("LTV del fondo TRI ultimo dato",
     '{"sql": "SELECT periodo, valor FROM derived_kpi WHERE kpi=\'ltv\' AND entidad_tipo=\'fondo\' AND entidad_key=\'TRI\' ORDER BY periodo DESC LIMIT 1"}'),
    ("cuales son los creditos vigentes de Viña Centro?",
     '{"sql": "SELECT credito_key, acreedor, tipo_deuda, deuda_inicial_uf, tasa_anual, fecha_vencimiento FROM dim_credito WHERE activo_key=\'Viña Centro\' AND estado=\'VIGENTE\'"}'),
    ("vacancia PT oficinas ultimos 6 meses",
     '{"sql": "SELECT periodo, valor FROM derived_kpi WHERE kpi=\'m2_vacantes\' AND entidad_tipo=\'activo\' AND entidad_key=\'PT Oficinas\' ORDER BY periodo DESC LIMIT 6"}'),
    ("precio bursatil serie A al cierre marzo 2026",
     '{"sql": "SELECT fecha, precio FROM fact_precio_cuota WHERE nemotecnico=\'CFITOERI1A\' AND fecha LIKE \'2026-03%\' ORDER BY fecha DESC LIMIT 1"}'),
    ("cuando fueron los ultimos 5 dividendos de la serie A?",
     '{"sql": "SELECT fecha_pago, monto, monto_uf, periodo FROM fact_dividendo WHERE nemotecnico=\'CFITOERI1A\' ORDER BY fecha_pago DESC LIMIT 5"}'),
    ("dame el LTV",
     '{"clarify": "¿De que entidad y periodo? Opciones: fondo (Apo, PT, TRI) o activo (Torre A, Boulevard, Apo4501, Apo4700, Apo3001, INMOSA, Mall Curicó, Sucden, Viña Centro)."}'),
]


def _few_shot_messages() -> list[dict]:
    """Convierte los ejemplos gold en pares user/assistant para el prompt."""
    msgs = []
    for q, a in _FEW_SHOT_EXAMPLES:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": a})
    return msgs


_ANSWER_SYSTEM = """\
Eres el Asistente Virtual Inmobiliario Toesca, asistente del EQUIPO DE INVERSIONES INMOBILIARIAS de Toesca Asset Management.
Tu audiencia son analistas y PMs de los fondos TRI/PT/Apo — no expliques cosas
basicas, se sobrio y directo. Recibes:
- pregunta original del equipo
- consulta interna ejecutada
- datos internos devueltos (verdad absoluta)

Redacta respuesta en Markdown breve y directa. Reglas:
- Usa SOLO los datos entregados. Si las filas estan vacias, dilo explicitamente
  y sugiere periodos disponibles cuando corresponda.
- No inventes numeros, fechas, activos ni contexto que no este en las filas.
- Conversa como un asistente financiero del equipo, no como una interfaz tecnica.
- No menciones "DB", "base de datos", "SQLite", "SQL", tablas, columnas, filas ni nombres internos, salvo que el usuario lo pida explicitamente.
- Para citar origen usa lenguaje natural: "segun la informacion interna disponible".
- SIEMPRE indica la unidad (UF, CLP, %, m², años). Regla: si el SQL saca de
  derived_kpi.valor y la columna unidad no vino, INFIERE la unidad segun el kpi:
    noi_*, ingresos_*, deuda_*, caja_minima → UF (o CLP si es caja_minima)
    valor_cuota_libro → CLP
    ltv, ltc, dscr, dy, dy_amort, tir_*, rent_*, cap_rate_*,
      tasa_arriendo_*, leverage_*, tasa_promedio, perfil_vencimiento → ratio (mostrar %)
    duration_deuda → años
    m2_vacantes → m2
- ratio → mostrar como % con 2 decimales.
- UF/CLP/m2 → mostrar con separador de miles chileno (punto miles, coma decimal).
- Si hay varias filas comparables, arma una tabla Markdown compacta.
- Para preguntas de contexto amplio (evolucion, comparacion): agrega 1 linea de
  observacion cuantitativa (max, min, tendencia). NO opines ni recomiendes.
- Cierra con `_Fuente: informacion interna Toesca_`.
- No muestres la consulta interna.
"""


def _extract_json(text: str) -> dict:
    """El LLM a veces envuelve el JSON en ``` ó lo antecede con texto."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _serialize_history(history: list[dict]) -> list[dict]:
    """Filtra el historial: solo role+content, ultimos 6 turnos."""
    out = []
    for m in (history or [])[-12:]:
        role = m.get("role")
        content = m.get("content") or ""
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": str(content)[:2000]})
    return out


# ─── API publica ──────────────────────────────────────────────────────────────
def answer(question: str, history: list[dict] | None = None) -> dict:
    """Responde una pregunta libre contra la DB.

    Devuelve dict con:
      answer_md   respuesta en Markdown para mostrar al usuario
      sql         SQL ejecutado (o None si fue clarify)
      columns     nombres de columnas devueltas
      rows        filas (list of list), <= 200
      provider    proveedor LLM usado
      clarify     True si el LLM pidio aclaracion
      error       string con error si algo fallo
    """
    question = (question or "").strip()
    if not question:
        return {"answer_md": "Escribe una pregunta.", "error": "empty"}

    try:
        chain = _provider_chain()
    except RuntimeError as exc:
        return {"answer_md": f"⚠️ {exc}", "error": "no_api_key"}
    provider = chain[0]

    # Paso 1: generar SQL. El playbook YA cubre la seleccion de tablas y
    # columnas; el PRAGMA schema completo (~2k tokens) es redundante y hace
    # que el prompt exceda el rate limit del free tier de Groq. Lo dejamos
    # fuera y confiamos en el playbook + few-shots.
    sql_messages = [
        {"role": "system", "content": _SQL_SYSTEM},
        {"role": "system", "content": _BUSINESS_CONTEXT},
        {"role": "system", "content": "Ejemplos gold pregunta→JSON. Sigue exactamente este patron de entidad_key, formula, filtros y formato JSON."},
        *_few_shot_messages(),
        *_serialize_history(history or []),
        {"role": "user", "content": question},
    ]

    try:
        resp, provider = _chat_completion_with_fallback(
            sql_messages, temperature=0.0, max_tokens=800,
        )
    except Exception as exc:
        return {
            "answer_md": f"⚠️ Error consultando al modelo: {exc}",
            "error": "llm_error",
            "provider": provider["model"],
        }

    raw = resp.choices[0].message.content or ""
    parsed = _extract_json(raw)

    if not parsed:
        return {
            "answer_md": "⚠️ No entendí la pregunta. Reformúlala mencionando "
                        "fondo/activo/período específico.",
            "error": "no_json",
            "provider": provider["model"],
        }

    if parsed.get("clarify"):
        return {
            "answer_md": str(parsed["clarify"]),
            "clarify": True,
            "sql": None,
            "columns": [],
            "rows": [],
            "provider": provider["model"],
        }

    sql = str(parsed.get("sql") or "").strip()
    err = _validate_sql(sql)
    if err:
        return {
            "answer_md": f"⚠️ No pude procesar la consulta interna: {err}",
            "error": "invalid_sql",
            "sql": sql,
            "provider": provider["model"],
        }

    try:
        cols, rows = _run_sql(sql)
    except sqlite3.Error as exc:
        return {
            "answer_md": f"⚠️ La consulta interna no pudo ejecutarse: `{exc}`",
            "error": "sql_error",
            "sql": sql,
            "provider": provider["model"],
        }

    # Paso 2: sintetizar respuesta a partir de las filas
    rows_for_llm = rows[:_MAX_ROWS_TO_LLM]
    truncated = len(rows) > len(rows_for_llm)
    data_payload = {
        "columns": cols,
        "rows": rows_for_llm,
        "n_rows_total": len(rows),
        "truncated_para_analisis": truncated,
    }

    answer_messages = [
        {"role": "system", "content": _ANSWER_SYSTEM},
        {
            "role": "user",
            "content": (
                f"PREGUNTA: {question}\n\n"
                f"SQL EJECUTADO:\n```sql\n{sql}\n```\n\n"
                f"DATOS (JSON):\n```json\n{json.dumps(data_payload, default=str, ensure_ascii=False)}\n```"
            ),
        },
    ]

    try:
        resp2, provider2 = _chat_completion_with_fallback(
            answer_messages, temperature=0.1, max_tokens=900,
        )
        answer_md = (resp2.choices[0].message.content or "").strip()
        provider = provider2
    except Exception as exc:
        answer_md = (
            f"Encontré {len(rows)} resultados pero fallé al redactar la respuesta: {exc}"
        )

    return {
        "answer_md": answer_md,
        "sql": sql,
        "columns": cols,
        "rows": rows,
        "provider": provider["model"],
    }
