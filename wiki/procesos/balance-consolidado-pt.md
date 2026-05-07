# Balance Consolidado Rentas PT

## Resumen

Planilla trimestral que consolida los EEFF de las 3 entidades que componen el Fondo PT:
- **Toesca Rentas PT** (holding/fondo)
- **Inmobiliaria Boulevard** (propietaria de PT Locales/Bodegas)
- **Torre A S.A.** (propietaria de PT Oficinas)

## Ubicación de archivos

**Planillas vF (fuente para actualizar):**
```
SharePoint/Control de Gestión/Balances Consolidados/{año}/{TQ}/
  {MM}.{YYYY}- Balance Consolidado Rentas PT vF.xlsx
```
Ruta local: `C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Control de Gestión/Balances Consolidados/`

**EEFF Fondo PT (balance):**
```
SharePoint/Fondos/Rentas PT/EEFF/{YYYY}/{TT}/
  EEFF {AAAAMM} Toesca FI Rentas PT Final.pdf
```
Ruta local: `C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondos/Rentas PT/EEFF/`

**Boulevard (balance + EERR):**
```
SharePoint/Fondos/Rentas TRI/Sociedades/Boulevard/
  EEFF 31-12-{YYYY} Boulevard.pdf          ← balance sheet (anual)
  {MM}-{YYYY} - Análisis Inmobiliaria Boulevard PT.xlsx  ← EERR (hoja "EERR")
```
Ruta local: `C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondos/Rentas TRI/Sociedades/Boulevard/`

**Torre A (balance + EERR):**
```
SharePoint/Fondos/Rentas TRI/Sociedades/Torre A/
  EEFF 31-12-{YYYY} Torre A.pdf           ← usar si los períodos pasados indican EEFF
  {MM}-{YYYY} - Análisis Torre A.xlsx      ← balance (hoja "Estado de Situacion") + EERR (hoja "EERR")
```
Ruta local: `C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondos/Rentas TRI/Sociedades/Torre A/`
> Manda la regla general de períodos pasados: si se usó Análisis, usar Análisis; si se usó EEFF, usar EEFF.

## Hojas del archivo

| Hoja | Tipo | Descripción |
|---|---|---|
| `Fondo PT` | **Input** | EEFF del fondo holding (Toesca Rentas PT) |
| `Inmob Boulevard` | **Input** | EEFF de Inmobiliaria Boulevard |
| `Torre A` | **Input** | EEFF de Torre A S.A. |
| `Consolidado PT` | Output (no editar) | Consolidación de las 3 entidades |
| `Resumen PT` | Output (no editar) | Vista resumida |
| `Consolidado Fondo PT` | Output (no editar) | Consolidado a nivel fondo |
| `BC PT` | Output (no editar) | Balance simplificado → alimenta fact sheet |

## Regla global: cuentas duplicadas en balance (aplica a TODOS los balances consolidados)

Al leer cualquier fuente (EEFF o Análisis), puede aparecer una misma cuenta o monto en **ambos lados del balance** (activos y pasivos). Incluirlas inflaría el balance artificialmente sin representar valor real neto.

**Criterio de exclusión:**
- Si una cuenta activo y una cuenta pasivo tienen el **mismo monto exacto** y claramente representan la misma deuda/contrato visto desde dos lados → **excluir ambas del balance consolidado**
- El ejemplo más común: intereses diferidos que aparecen como activo y como pasivo por el mismo valor
- Pero aplica a cualquier tipo de cuenta duplicada, no solo intereses diferidos

**Consecuencia aceptada:**
```
Total Activos planilla ≠ Total Activos fuente
(diferencia = monto de las cuentas excluidas)
```
**Invariante que SIEMPRE debe cumplirse:**
```
Total Activos planilla = Total Pasivos + Patrimonio planilla
```

**Ante la duda:** no excluir por cuenta propia — consultar al usuario.

Esta regla aplica a **todas las hojas de todos los balances consolidados** (PT, Rentas, Apoquindo y cualquier futuro).

---

## Regla general: ¿EEFF o Análisis?

Para cada sección (balance / EERR) de cada hoja, determinar la fuente mirando el mismo período del año anterior:

```
Para MM.YYYY → revisar MM.YYYY-1 en la planilla
Si TODOS los valores inputeados terminan en 000 → fuente es EEFF PDF (M$ × 1.000)
Si ALGÚN valor NO termina en 000       → fuente es Análisis xlsx (pesos directos)
```

**Por qué funciona:**
- EEFF reporta en M$ → al multiplicar ×1000 siempre quedan 3 ceros al final
- Análisis reporta en pesos exactos → los valores raramente terminan en 000

Aplica sección por sección dentro de la misma hoja (ej: en Inmob Boulevard el balance usa EEFF y el EERR usa Análisis — los valores del balance terminan en 000 y los del EERR no).

---

## Fuente fija por quarter

Derivado del histórico 2025 de la planilla `12.2025- Balance Consolidado Rentas PT vF.xlsx`. La herramienta usa esta tabla primero y deja la inferencia histórica como respaldo.

| Hoja | Sección | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|
| `Fondo PT` | Balance | EEFF | EEFF | EEFF | EEFF |
| `Fondo PT` | EERR | EEFF | EEFF | EEFF | EEFF |
| `Inmob Boulevard` | Balance | Análisis | Análisis | Análisis | EEFF |
| `Inmob Boulevard` | EERR | Análisis | Análisis | Análisis | Análisis |
| `Torre A` | Balance | Análisis | Análisis | Análisis | Análisis |
| `Torre A` | EERR | Análisis | Análisis | Análisis | Análisis |

---

## Procedimiento de actualización

### 1. Crear archivo del nuevo período

Copiar el último `vF` y renombrar con el nuevo período:
```
12.2025- Balance Consolidado Rentas PT vF.xlsx
→ copia → 03.2026- Balance Consolidado Rentas PT vAgente.xlsx
```
Al terminar de editar, el archivo resultante se llama `vAgente`.

### 2. Seleccionar el EEFF correcto

El EEFF es anual — se usa el EEFF del año fiscal que cierra en la fecha del período:

| Período planilla | EEFF a usar |
|---|---|
| 03.YYYY (1Q) | EEFF trimestral 1Q si existe, si no anual del año anterior |
| 06.YYYY (2Q) | EEFF trimestral 2Q si existe |
| 09.YYYY (3Q) | EEFF trimestral 3Q si existe |
| 12.YYYY (4Q) | EEFF anual de YYYY |

> El EEFF del 4T de Fondo PT está confirmado como anual: solo existe una versión por año (`EEFF {AAAAMM} Toesca FI Rentas PT Final.pdf` en carpeta `4T`).

### 3. Insertar nueva columna (CRÍTICO)

Las hojas output referencian siempre la columna D. Procedimiento:

```
ANTES:  D=4Q2025, E=3Q2025, F=2Q2025, G=1Q2025, H=4Q2024, I=3Q2024, J=2Q2024, K=1Q2024

Implementación en código: shift right K←J←I←H←G←F←E←D (sin insertar columna real)

DESPUÉS: D=NUEVO (1Q2026), E=4Q2025, F=3Q2025, G=2Q2025, H=1Q2025, I=4Q2024, J=3Q2024, K=2Q2024
```

Siempre hay 8 trimestres en D-K. El más antiguo (K anterior) se descarta.

### 4. Rellenar hoja Fondo PT

Estructura de la hoja:
- **Fila 2:** fechas en D-K (fecha fin del trimestre, ej. 2025-12-31)
- **Filas 5-70:** Balance (Activos, Pasivos, Patrimonio)
- **Filas 73-112:** Estado de Resultados (YTD acumulado)
- **Col C:** Índice de clasificación (ver tabla abajo)

#### Unidades

EEFF en M$ (miles de pesos) → planilla en pesos: multiplicar por 1.000.

#### Mapeo Balance (Fondo PT)

El EEFF de Fondo PT es un fondo holding — la mayoría de sus activos son inversiones financieras.

| Fila | Cuenta planilla | Clas | Fuente EEFF | Nota EEFF |
|---|---|---|---|---|
| 7 | Efectivo y equivalente | 1 | Pág 6: "Efectivo y efectivo equivalente" | 21 |
| 12 | CxC por operaciones | 2 | Pág 6: ítem correspondiente | — |
| 22 | Act fin a costo amortizado NC | 10 | Pág 6: "Activos financieros a costo amortizado" NC | 9 |
| 24 | CxC entidades relacionadas | 11 | Nota 11 del EEFF | — |
| 25 | Inversiones método participación | 12 | Pág 6: "Inversiones valorizadas por el método de la participación" | 10 |
| 27 | Propiedades de Inversión | 3 | Pág 6: "Propiedades de Inversión" (= 0 para Fondo PT) | — |
| 31 | Activo por Impuesto Diferido | 4 | (= 0 para Fondo PT) | — |
| 42 | CxP por operaciones (corriente) | 8 | Nota 16 del EEFF: porción operaciones | 16 |
| 43 | Remuneraciones soc. admin. | 8 | Pág 7: "Remuneraciones sociedad administradora" | 31 |
| 44 | CxP entidades relacionadas corrientes | 14 | Nota 16 del EEFF: porción entidades relacionadas | 16 |
| 48 | Pasivos por impuestos corrientes | 7 | (= 0 para Fondo PT) | — |
| 52 | Préstamos LP | 5 | (= 0 para Fondo PT) | — |
| 55 | CxP entidades relacionadas NC | 13 | (= 0 para Fondo PT) | — |
| 56 | Pasivos por impuestos diferidos | 6 | (= 0 para Fondo PT) | — |
| 57 | Otros pasivos NC | 8 | Pág 7: "Otros pasivos" NC | 10 |
| 62 | Aportes | 9 | Estado Cambios Patrimonio: **saldo inicio** (antes de repartos) | — |
| 64 | Resultados acumulados | 9 | Pág 7: "Resultados acumulados" | — |
| 65 | Resultado del ejercicio | 9 | Pág 7: "Resultado del ejercicio" | — |
| 66 | Dividendos provisorios | 9 | Estado Cambios Patrimonio: "Repartos de patrimonio" (negativo) | — |

> **OJO con Aportes:** El EEFF muestra en Pág 7 el valor neto (después de repartos). El planilla usa el valor **bruto** (antes de repartos) de la tabla Estado de Cambios en Patrimonio, y separa los repartos en fila 66.

> **OJO con Nota 16 (CxP):** La suma de fila 42 + fila 44 debe ser igual al total de Nota 16 del EEFF.

#### Mapeo Estado de Resultados (Fondo PT)

EEFF pág 8 → filas 76-103 de la planilla. Mapeo 1:1, mismas líneas, mismos nombres.
Todos los valores son YTD acumulados (ej. 4Q2025 = año completo 2025).

| Fila | Cuenta planilla | Fuente EEFF pág 8 | Nota |
|---|---|---|---|
| 76 | Intereses y reajustes | "Intereses y reajustes" | 19 |
| 85 | Resultado inversiones método participación | "Resultado en inversiones valorizadas por el método de la participación" | 10 |
| 91 | Remuneración Comité Vigilancia | "Remuneración del Comité de Vigilancia" | 39 |
| 92 | Comisión de administración | "Comisión de administración" | 31 |
| 93 | Honorarios custodia | "Honorarios por custodia y administración" | 34 |
| 95 | Otros gastos de operación | "Otros gastos de operación" | 35 |

Los totales (filas 87, 96, 98, 100, 103) son fórmulas automáticas.

### 5. Validaciones obligatorias (deben cuadrar con EEFF)

| Verificar | Planilla | EEFF |
|---|---|---|
| Total Activos | Fila 35, col D | Pág 6: "TOTAL ACTIVO" |
| Total Pasivo Corriente | Fila 49, col D | Pág 7: "TOTAL PASIVO CORRIENTE" |
| Total Pasivo No Corriente | Fila 59, col D | Pág 7: "TOTAL PASIVO NO CORRIENTE" |
| Total Patrimonio Neto | Fila 67, col D | Pág 7: "TOTAL PATRIMONIO NETO" |
| Pasivos + PAT | Fila 70, col D | Pág 7: "TOTAL PASIVO" (total general) |
| Resultado del ejercicio | Fila 103, col D | Pág 8: "RESULTADO DEL EJERCICIO" |

### 6. Guardar

Guardar el archivo como `{MM.YYYY}- Balance Consolidado Rentas PT vAgente.xlsx` en la misma carpeta donde estaba el vF.

## Verificación cruzada EEFF → planilla (ejemplo 4Q2025)

| Ítem | EEFF M$ | Planilla (÷1000) |
|---|---|---|
| Efectivo | 16.468 | 16.468.000 ✓ |
| Act fin costo amortizado NC | 27.347.233 | 27.347.233.000 ✓ |
| Inversiones método participación | 23.038.499 | 23.038.499.000 ✓ |
| Total Activo | 50.402.200 | 50.402.200.000 ✓ |
| Total Patrimonio | 22.480.192 | 22.480.192.000 ✓ |
| Resultado del ejercicio | 4.671.152 | 4.671.152.000 ✓ |

---

## Hoja Inmob Boulevard

### Fuentes de datos

| Sección | Fuente | Unidades |
|---|---|---|
| Balance | EEFF PDF Boulevard (págs 3-4) | M$ → × 1.000 → pesos |
| EERR | Análisis xlsx, hoja "EERR", col E | pesos (usar directo) |

> Boulevard solo tiene EEFF anual (un archivo por año). Para trimestres intermedios usar el Análisis xlsx que se actualiza mensualmente.

### Mapeo Balance (Inmob Boulevard)

| Fila | Cuenta planilla | Clas | Fuente EEFF / Nota |
|---|---|---|---|
| 7 | Efectivo | 1 | EEFF pág 3: "Efectivo y equivalentes al efectivo" (Nota 5) |
| 12 | CxC por operaciones | 2 | EEFF pág 3: "Deudores comerciales y otras cuentas por cobrar" (Nota 6) |
| 13 | CxC entidades relacionadas corrientes | 11 | EEFF pág 3: "Cuentas por cobrar entidades relacionadas corrientes" (Nota 8) |
| 23 | Otras CxC NC (CxC no corrientes por operaciones) | 2 | EEFF pág 3: "Otras cuentas por cobrar no corrientes" (Nota 6) |
| 27 | Propiedades de Inversión | 3 | EEFF pág 3: "Propiedades de inversión" (Nota 7) |
| 31 | Activo por Impuesto Diferido | 5 | EEFF pág 3: "Activos por impuestos diferidos" (Nota 11) |
| 40 | Préstamos corrientes | 6 | EEFF pág 4: "Otros pasivos financieros corrientes" (Nota 9) |
| 42 | CxP por operaciones | 8 | EEFF pág 4: "Cuentas comerciales y otras cuentas por pagar" (Nota 10) |
| 44 | CxP entidades relacionadas corrientes | 14 | EEFF pág 4: "Cuentas por pagar entidades relacionadas corrientes" (Nota 8) |
| 46 | Otras provisiones corrientes | 8 | EEFF pág 4: "Otras provisiones corrientes" (Nota 12) |
| 52 | Préstamos NC | 6 | EEFF pág 4: "Otros pasivos financieros no corrientes" (Nota 9) |
| 55 | CxP entidades relacionadas NC | 13 | EEFF pág 4: "Cuentas por pagar entidades relacionadas no corrientes" (Nota 8) |
| 62 | Aportes | 9 | EEFF pág 4 / cambios patrimonio: "Capital emitido" |
| 64 | Resultados acumulados | 9 | EEFF pág 4: "Resultados acumulados" |
| 65 | Resultado del ejercicio | 9 | EEFF pág 4: "Pérdida/Ganancia del ejercicio" |

### Mapeo EERR (Inmob Boulevard)

Fuente: Análisis xlsx, hoja "EERR", columna E. Copiar línea por línea a planilla filas 76-120.
Las cuentas usan códigos contables (`4-1-01-01`, `5-1-01-01`, etc.) que coinciden con los nombres en la planilla.
Validar: planilla fila 120 ("RESULTADO DEL PERIODO") = EERR análisis fila "RESULTADO DEL PERIODO".

---

## Hoja Torre A

### Fuentes de datos

| Sección | Fuente | Unidades |
|---|---|---|
| Balance | Según períodos pasados: Análisis xlsx o EEFF PDF | Análisis pesos directos / EEFF M$×1000 |
| EERR | Según períodos pasados: Análisis xlsx o EEFF PDF | Análisis pesos directos / EEFF M$×1000 |

> Para Torre A también manda el histórico: si la planilla venía desde EEFF, usar EEFF; si venía desde Análisis, usar Análisis.

### Regla de cuentas duplicadas (ver regla global abajo)

### Criterio general

Llenar los mismos índices de clasificación que se llenaron en períodos anteriores. Si aparece un ítem nuevo o dudoso, comparar contra el período anterior y omitir lo que hinche simétricamente el balance.

### Mapeo Balance (Torre A)

Los valores están en PESOS en el análisis (col C de "Estado de Situacion"). Usar directo sin multiplicar.

| Fila | Cuenta planilla | Clas | Fuente Análisis |
|---|---|---|---|
| 7 | Efectivo | 1 | "EFECTIVO Y EQUIVALENTE AL EFECTIVO" |
| 12 | CxC por operaciones | 2 | "CLIENTE" - "PROVISION INCOBRABLES" |
| 13 | CxC entidades relacionadas corrientes | 11 | "PRESTAMO POR COBRAR INMOB BOULEVARD PT" |
| 24 | CxC entidades relacionadas NC | 11 | "CUENTAS POR COBRAR EMPRESAS RELACIONADAS" (total) |
| 27 | Propiedades de Inversión | 3 | "PROPIEDADES DE INVERSION" |
| 31 | Activo por Impuesto Diferido | 5 | "ACTIVO POR IMPUESTO DIFERIDO" |
| 30 | Intereses Diferidos | — | **NO INCLUIR** (ver regla arriba) |
| 52 | Préstamos NC | 6 | Préstamos largo plazo |
| 56 | Pasivos por impuestos diferidos | 7 | "IMPUESTO DIFERIDO PASIVO" |

### Mapeo EERR (Torre A)

Mismo proceso que Boulevard: usar hoja "EERR" col E del Análisis xlsx.
Validar: planilla fila 114 ("RESULTADO DEL PERIODO") = EERR análisis fila "RESULTADO DEL PERIODO" = 4.543.723.954 (4Q2025).

---

## Resumen de fuentes por hoja

| Hoja | Balance fuente | EERR fuente | Unidades |
|---|---|---|---|
| Fondo PT | EEFF PDF págs 6-7 | EEFF PDF pág 8 | M$ × 1000 |
| Inmob Boulevard | EEFF PDF págs 3-4 | Análisis xlsx hoja "EERR" col E | Balance M$×1000 / EERR pesos |
| Torre A | Según períodos pasados: Análisis o EEFF | Según períodos pasados: Análisis o EEFF | Análisis pesos / EEFF M$×1000 |

---

## Estado herramienta

- [x] Implementada herramienta `actualizar_balance_consolidado_pt`.
- [x] La regla general "EEFF o Análisis" manda sobre los defaults por hoja.
- [x] Soporta Balance Boulevard desde Análisis xlsx cuando los períodos pasados indican pesos directos.
- [x] Soporta Torre A desde EEFF PDF cuando los períodos pasados indican EEFF.
