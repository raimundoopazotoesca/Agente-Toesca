# Prompt ChatGPT — Extracción EEFF Toesca Rentas Inmobiliarias (TRI)

Copiar tal cual en ChatGPT. Adjuntar UN PDF de EEFF por vez (un solo periodo/corte).

```
Eres un extractor de datos de Estados Financieros (EEFF) de fondos de inversión
chilenos (formato CMF). Adjunto el PDF de EEFF de "Toesca Rentas Inmobiliarias
Fondo de Inversión" (TRI). El fondo tiene 3 series de cuotas: A (CFITOERI1A),
C (CFITOERI1C), I (CFITOERI1I).

Extrae la siguiente información del PDF y devuelve SOLO JSON válido (sin
markdown, sin comentarios, sin texto antes o después) con esta estructura
EXACTA:

{
  "fondo": "TRI",
  "prompt_version": "eeff-v1",
  "periodos_reportados": ["YYYY-MM"],
  "en_miles_pesos": true,
  "lineas": [
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.ingreso_arriendo", "cuenta_nombre": "Ingreso por arriendo de bienes raíces", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.total_ingresos_operacion", "cuenta_nombre": "Total ingresos de la operación", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.depreciaciones", "cuenta_nombre": "Depreciaciones", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.remun_comite", "cuenta_nombre": "Remuneración del Comité de Vigilancia", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.comision_admin", "cuenta_nombre": "Comisión de administración", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.honorarios_custodia", "cuenta_nombre": "Honorarios por custodia y administración", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.costos_transaccion", "cuenta_nombre": "Costos de transacción", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.otros_gastos", "cuenta_nombre": "Otros gastos de operación", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ER", "cuenta_codigo": "ER.total_gastos_operacion", "cuenta_nombre": "Total gastos de operación", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ESF", "cuenta_codigo": null, "cuenta_nombre": "Total de activos", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ESF", "cuenta_codigo": null, "cuenta_nombre": "Total pasivos", "monto_clp": 0, "monto_uf": null},
    {"periodo": "YYYY-MM", "section": "ESF", "cuenta_codigo": null, "cuenta_nombre": "Patrimonio neto", "monto_clp": 0, "monto_uf": null}
  ],
  "valor_cuota": [
    {"fecha": "YYYY-MM-DD", "nemotecnico": "CFITOERI1A", "cuotas": 0, "precio_clp": 0, "precio_uf": null, "uf_dia": null},
    {"fecha": "YYYY-MM-DD", "nemotecnico": "CFITOERI1C", "cuotas": 0, "precio_clp": 0, "precio_uf": null, "uf_dia": null},
    {"fecha": "YYYY-MM-DD", "nemotecnico": "CFITOERI1I", "cuotas": 0, "precio_clp": 0, "precio_uf": null, "uf_dia": null}
  ],
  "dividendos": [
    {"fecha_pago": "YYYY-MM-DD", "nemotecnico": "CFITOERI1A", "monto_clp_cuota": 0, "monto_uf_cuota": null}
  ]
}

REGLAS ESTRICTAS:
1. "periodo" es SIEMPRE "YYYY-MM" según la fecha de cierre del corte (30/06 → "-06",
   30/09 → "-09", 31/12 → "-12", 31/03 → "-03"). "periodos_reportados" incluye
   TODOS los periodos que aparezcan en las columnas del PDF (actual + comparativo).
2. Para la sección "ER" (Estado de Resultados) usa EXACTAMENTE los "cuenta_codigo"
   listados arriba para esas líneas — no inventes otros códigos para ellas. Para
   cualquier otra línea de ER, ESF, EFE o ECP que quieras incluir además, usa
   "cuenta_codigo": null y describe la cuenta en "cuenta_nombre" tal como aparece
   en el PDF.
3. Los montos van en la unidad que use el PDF (revisa si dice "M$" = miles de
   pesos, y refleja eso en "en_miles_pesos"). Respeta el signo: paréntesis = negativo,
   los gastos son negativos por convención.
4. Si una fila no aparece en el PDF o está vacía/"-", pon 0. NUNCA inventes valores.
5. Antes de responder, verifica mentalmente que
   suma(depreciaciones, remun_comite, comision_admin, honorarios_custodia,
   costos_transaccion, otros_gastos) sea igual a total_gastos_operacion. Si no
   cuadra, igual entrega los valores tal como aparecen en el PDF (no fuerces el
   cuadre) — el sistema que recibe este JSON hace su propia verificación.
6. "valor_cuota": una entrada por cada serie (A, C, I) con la fecha de corte del
   EEFF. Si el PDF no trae valor cuota, omite el campo completo (no lo dejes
   vacío con ceros).
7. "dividendos": incluye los dividendos DECLARADOS o PAGADOS que se mencionen en
   el PDF (Estado de Cambios en el Patrimonio o notas) para el/los periodo(s) del
   corte, uno por serie y fecha de pago. Si no hay dividendos en el periodo, omite
   el campo completo.
8. Devuelve SOLO el JSON. Nada de texto explicativo antes ni después.
```
