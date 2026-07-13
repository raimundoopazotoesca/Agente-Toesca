# Plan de poblamiento operacional de los fondos

**Fecha inicio**: 2026-07-07
**Objetivo global**: alimentar `memory/agente_toesca_v2.db` con toda la información operacional histórica necesaria para reconstruir de punta a cabo el fact sheet mensual de cada fondo (PT, Apo, TRI), sin depender del CDG.
**Fondo piloto**: PT (Toesca Rentas Inmobiliarias PT).
**Ventana histórica objetivo**: desde inicio de cada fondo. PT: nov-2017 → hoy (94 meses).

---

## Contexto

- El fondo PT tiene dos activos subyacentes: **Torre A S.A.** (Torre A - Parque Titanium, 19.755 m²) e **Inmobiliaria Boulevard PT SpA** (Local 100, 7.663 m²).
- Administrador operacional de ambos activos: **JLL** (Jones Lang LaSalle).
- Estacionamientos administrados por **Saba**.
- Financiamiento: **Banco Security** (crédito por sociedad; el FS reciente lo etiqueta como "sindicado Scotiabank" — pendiente verificar si hubo refinanciamiento o cambio de acreedor).
- Se está negociando una **API directa con JLL** hacia su base de datos. Este plan define qué info pedir por esa vía.

---

## Estado actual DB (PT)

Verificado 2026-07-07 sobre `memory/agente_toesca_v2.db`.

| Bloque | Estado | Cobertura |
|---|---|---|
| `dim_activo` PT | ✓ | Torre A + Boulevard PT |
| `dim_credito` PT | ✓ | 2 créditos Security |
| `raw_saldo_deuda` PT | ✓ | 2017-10 → 2029-11 (292 filas, incluye proyección) |
| `fact_tasacion` PT | parcial | 2020-2025 (falta 2017-2019) |
| `raw_eeff_line` PT | ✓ | trimestral |
| `raw_valor_cuota` PT | ✓ | contable trimestral + bursátil mensual |
| `raw_dividendo` PT | ✓ | histórico completo |
| `raw_rent_roll_line` PT | **✗ vacío** | — |
| `raw_er_activo_line` PT | **✗ vacío** | — |
| Parking (tabla nueva) | **✗ no existe** | — |
| Cobranza (tabla nueva) | **✗ no existe** | — |
| Comentarios cualitativos | **✗ no existe** | — |

---

## Inventario de datos por bloque del fact sheet

### A. Rent Roll (base de páginas 2 y 3 del FS)

Alimenta: vacancia m² y UF, ingresos UF/mes por activo/tipo/rubro, absorción 3M/12M, plazo medio contratos, perfil de vencimientos, composición por rubro/arrendatario/tipo, GLA, tabla Resumen Performance.

**Campos por línea (contrato o unidad vacante)**:
- activo (Torre A / Boulevard)
- tipo unidad (Oficina / Local Comercial / Bodega / Estacionamiento)
- unidad (piso/número, ID estable)
- ID contrato (estable a través de renovaciones)
- arrendatario
- rubro (Banco, Deporte, Padel, Seguros, Construcción, Otro…)
- m² útiles
- estado (ocupada / vacante / en gracia / en descuento)
- renta base UF/mes
- gracia UF/mes
- descuento UF/mes
- fecha inicio contrato
- fecha término contrato
- fecha corte (fin de mes)

**Fuente principal**: RR JLL mensual `{AAMM} Rent Roll y NOI.xlsx` (histórico local) + futura API JLL.
**Tabla destino**: `raw_rent_roll_line` (esquema existente — extender `extra_json` si falta).

### B0. Facturación mensual por contrato (crítico — permite clasificación de ingresos)

Alimenta: composición de ingresos por arrendatario (donut página 3), composición por rubro en UF/mes (página 2), segmentación NOI por tipo de unidad, cruce facturación → recaudación → morosidad a nivel contrato.

**Sin este bloque el ER es solo contable — no podemos responder "cuánto ingresó Scotiabank" o "cuánto viene del rubro Banco".**

**Campos por contrato-mes**:
- ID contrato (FK a rent roll)
- ID unidad (FK a rent roll)
- Activo, arrendatario, rubro (redundantes, facilitan queries)
- Periodo (YYYY-MM)
- Facturación por concepto UF: arriendo base, gastos comunes, reajuste UF, penalizaciones, servicios, otros
- Facturación total UF

**Fuente**: JLL (API futura). Puede que también aparezca en los reportes mensuales actuales — a validar.
**Tabla destino nueva**: `raw_facturacion_contrato_line` (activo_key, periodo, contrato_id, unidad_id, arrendatario, rubro, concepto, monto_uf, monto_clp, source_file, file_hash).

### B. ER mensual por activo (base de página 1 NOI/Ingresos U12M + gráficos evolución página 2)

Alimenta: NOI UF/mes, Ingresos UF/mes, U12M, cap rate implícito, evolución NOI+RCSD, evolución Ingresos/NOI/Vacancia.

**Campos por mes y activo**:
- ingresos por concepto (arriendo base, GC recuperados, otros)
- gastos operacionales por concepto (GC no recuperados, mantención, comisiones, seguros, contribuciones, servicios, otros)
- NOI = ingresos - gastos operacionales
- CLP y UF del mes

**Fuente**: hoja "NOI PT" del RR JLL + futura API JLL.
**Tabla destino**: `raw_er_activo_line` (esquema existente).

### B1. Gastos internos no reportados por JLL (contribuciones + seguros)

El ER que JLL entrega **no incluye contribuciones ni seguros** — Toesca los administra internamente. Ambos siguen fórmulas simples en base a UF (indexadas), lo que permite reconstruirlos mensualmente sin depender de fuente externa.

**Campos por mes y activo**:
- concepto (contribuciones / seguros)
- monto UF
- monto CLP (usando UF del mes)
- fórmula/parámetros usados (para trazabilidad)

**Fuente**: fórmulas internas Toesca + UF del período (ya en `fact_uf`).
**Tabla destino nueva**: `raw_gasto_interno_line` (activo_key, periodo, concepto, monto_uf, monto_clp, formula_ref, source_note, file_hash).
**Nota**: al calcular NOI consolidado y cap rate, sumar estos gastos a los de JLL para evitar sobreestimar NOI.

### C. Deuda (página 1 endeudamiento + página 2 gráfico RCSD)

Alimenta: LTV, LTC, Leverage, Duration (Macaulay), Tasa promedio, Deuda financiera neta, perfil de vencimientos (0-3 / 3-7 / 7-10 / >10 años), Cuota Financiamiento UF/mes, RCSD.

**Estado**: base ya en DB. Pendiente:
- Confirmar acreedor actual (Security vs Scotiabank sindicado).
- Validar tabla de desarrollo completa por crédito (fecha, saldo inicial, amortización, interés, cuota, saldo final).
- Registrar refinanciamientos si los hubo.

**Fuente**: Banco Security + contratos internos.

### D. Tasaciones (página 1 + página 3 tabla LTV por activo)

**Estado**: 2020-2025 en DB. Faltan 2017-2019.
**Fuente**: PDFs de tasación (usuario los tiene consolidados).
**Campos**: fecha, tasador, valor UF, m², UF/m², cap rate implícito, tasa descuento, notas.

### E. Parking (página 3 gráfico Resultados Parking, desde ene-2023)

Alimenta: Ingresos Abonados UF, Ingresos Variables UF, Resultados UF, Ocupación %, tickets.

**Campos por mes**:
- ingresos abonados UF
- ingresos variables UF (tickets)
- gastos operacionales parking UF
- resultado neto UF
- tickets vendidos (#)
- horas de estadía promedio
- ocupación % (definición FS: tiempo promedio estadía sobre 12h × 502 estacionamientos)
- estacionamientos operativos

**Fuente**: Saba (reporte mensual). Confirmar con JLL si ellos igual reportan.
**Tabla destino nueva**: `raw_parking_line`.

### F. Recaudación / morosidad (página 2 gráfico Recaudación Consolidada U12M)

Alimenta: Facturación UF, Recaudación UF, Recaudación con Plan de Pago UF, Morosidad UF, Morosidad promedio >30 días %.

**Campos por mes (por activo)**:
- facturación UF
- recaudación UF
- recaudación con plan de pago UF
- morosidad por tramo: 0-30, 30-60, 60-90, >90 días

**Fuente**: JLL (cobranza).
**Tabla destino nueva**: `raw_cobranza_line`.

### G. Otros indicadores (página 1)

Todos derivados: tasa arriendo UF/m², cap rate, ingresos/NOI mes y U12M. No requieren fuente adicional.

### H. Comentarios cualitativos (página 3 "Aspectos del mes")

Texto libre del gestor. Manual.
**Tabla destino nueva**: `raw_comentario_mensual` (fondo_key, activo_key, periodo, tema, texto).

### I. Fotos y planos

Estáticos, no requieren histórico.

---

## Fuentes por bloque

| Bloque | Fuente | Cobertura histórica esperada |
|---|---|---|
| A. Rent Roll | RR JLL mensual + API JLL futura | nov-2017 → hoy |
| B0. Facturación por contrato | JLL (API futura, validar si está en reportes actuales) | nov-2017 → hoy |
| B. ER activo (excluye contribuciones y seguros) | JLL (hoja "NOI PT") + API futura | nov-2017 → hoy |
| B1. Gastos internos (contribuciones + seguros) | Fórmulas internas Toesca + `fact_uf` | nov-2017 → hoy |
| C. Deuda | Banco Security + contratos | 2017-10 → 2029-11 |
| D. Tasaciones | Tasadores externos (PDFs internos) | 2017-2025 anual |
| E. Parking | Saba | 2023-01 → hoy |
| F. Cobranza | JLL | nov-2017 → hoy |
| H. Comentarios | Gestor Toesca | mensual |

---

## Prioridad de ejecución

1. **Rent Roll (A)** — desbloquea ~60% del FS. Empezar con los RR JLL locales que ya tenemos.
2. **ER Torre A + Boulevard (B)** — desbloquea página 1 NOI/Ingresos U12M y curva página 2.
3. **Tasaciones 2017-2019 (D)** — cerrar histórico desde archivos internos.
4. **Parking (E)** — desde Saba.
5. **Cobranza (F)** — vía JLL.
6. **Validar Deuda (C)** — confirmar acreedor y calendario completo.
7. **Comentarios (H)** — último, manual.

---

## Estrategia con la API JLL

Se pide a JLL exponer **4 endpoints** en su API:

1. **Rent Roll snapshot mensual** — todos los campos del bloque A, snapshot fin de mes, ID estable de contrato y unidad.
2. **ER mensual por activo** — ingresos y gastos operacionales desagregados por cuenta, en CLP y UF.
3. **Cobranza mensual** — facturación, recaudación (con y sin plan de pago), morosidad por tramos de días.
4. **Parking mensual** (solo si JLL lo administra o consolida; si no queda con Saba).

Formato: JSON. Histórico desde nov-2017. Frecuencia: mensual.

Preguntas abiertas para JLL están en el mail asociado (ver correo del 2026-07-07).

---

## Preguntas transversales

- **LTV política**: nota (v) del FS dice "Deuda / Valor Activos según tasación 2024". Confirmar si LTV siempre usa tasación del año calendario o última disponible.
- **Duration**: Macaulay sobre calendario de amortización — validar fórmula ya implementada vs FS.
- **Estacionamientos**: en tabla resumen página 2 se cuentan en unidades, no m². Ojo al agregarlos.

---

## Log de sesiones

### 2026-07-07 — Kickoff PT

- Revisión FS PT jul-2025 (4 páginas).
- Inventario completo de bloques operacionales.
- Verificación de estado DB (rent roll y ER activo vacíos; resto parcial o completo).
- Definición de fuentes por bloque.
- Redacción de mail a JLL con preguntas y solicitud formal de API.
- **Ajuste**: agregado bloque B0 "facturación por contrato" — necesario para clasificar ingresos por arrendatario/rubro. Sin este cruce el ER queda desconectado del rent roll y no se puede responder "cuánto ingresa de X arrendatario / X rubro". Mail actualizado con endpoint adicional.
- **Ajuste**: parking sale del scope JLL (fuente Saba directa, ya confirmado). Endpoint parking y pregunta correspondiente removidos del mail.
- **Ajuste**: agregado bloque B1 "gastos internos" — el ER de JLL no incluye contribuciones ni seguros. Ambos se calculan internamente con fórmulas UF. Nueva tabla destino `raw_gasto_interno_line`. Nota agregada en pregunta #8 del mail sobre cuentas del ER excluidas.
- Próximo paso: recibir RR JLL históricos del usuario, comenzar ingesta Torre A.
