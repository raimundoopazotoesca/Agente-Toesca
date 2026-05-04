# Balance Consolidado Rentas PT

## Resumen

Planilla trimestral que consolida los EEFF de las 3 entidades que componen el Fondo PT:
- **Toesca Rentas PT** (holding/fondo)
- **Inmobiliaria Boulevard** (propietaria de PT Locales/Bodegas)
- **Torre A S.A.** (propietaria de PT Oficinas)

## Ubicación de archivos

**Planillas vF (fuente para actualizar):**
```
SharePoint/Controles de Gestión/Renta Comercial/Balances Consolidados/{año}/{TQ}/
  {MM}.{YYYY}- Balance Consolidado Rentas PT vF.xlsx
```
Ruta local: `C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Controles de Gestión/Renta Comercial/Balances Consolidados/`

**EEFF Fondo PT (fuente de datos):**
```
SharePoint/Fondo Rentas PT/EEFF/{YYYY}/{TT}/
  EEFF {AAAAMM} Toesca FI Rentas PT Final.pdf
```
Ruta local: `C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondo Rentas PT/EEFF/`

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

## Pendiente

- [ ] Confirmar fuente EEFF Torre A (ubicación desconocida)
- [ ] Documentar mapeo Inmob Boulevard (similar pero con Propiedades de Inversión activas)
- [ ] Confirmar si hay EEFF trimestrales para Boulevard y Torre A (o solo anuales)
- [ ] Implementar herramienta `actualizar_balance_consolidado_pt`
