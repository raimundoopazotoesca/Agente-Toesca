# Balance Consolidado Rentas Nuevo

## Estado de implementación

**Herramienta:** `actualizar_balance_consolidado_rentas_nuevo(mes, año)` en `tools/balance_consolidado_tools.py` (desde línea ~2079).
**Registro:** callable vía `actualizar_balance_consolidado_rentas_si_completo` (tool del agente).

### Qué está implementado ✓

- Finds vF, copia como vAgente en la misma carpeta (misma carpeta del vF, no WORK_DIR)
- Desplaza columnas D:K en hojas input + PT/Apo
- Escribe fecha (`datetime`) y estado en fila 2 col D y col B respectivamente
- **Balance Chañarcillo** → `RAW/MM-AAAA*Ch*arcillo*.xlsx` hoja `Bce Tributario` → `CHANAR_BALANCE_MAP` (16 filas)
- **Balance Curicó** → `Fondos/Rentas TRI/Activos/Curicó/EEFF/YYYY/MM-AAAA*INFORME*CURIC*.xlsx` hoja `Acum MM-AAAA` → `CURICO_BALANCE_MAP` (16 filas) + `_apply_curico_impdif` (R31/R56 neto)
- **Balance Inmob VC** → `RAW/MM-AAAA*Inmobiliaria*VC*.xlsx` hoja `Bce Tributario` → `INMOB_VC_BALANCE_MAP` (11 filas)
- **Balance Viña Centro** → `RAW/*INFORME*EFF*VI*A*CENTRO*.xlsx` hoja `BALANCE ACUMULADO` → `VINA_BALANCE_MAP` (21 filas)
- **EERR Inmosa** → `RAW/*Senior*Assist*.xlsx` (única hoja) → `INMOSA_SA_EERR_MAP` (31 filas, dot-notation)
- Copia PT: busca `*Rentas PT*vAgente*.xlsx` en misma carpeta que vF, luego en WORK_DIR. Copia `Resumen` → `Resumen PT`, `Consolidado Fondo PT` → `Consolidado Fondo PT`
- Copia Apoquindo: busca `*Apoquindo*vAgente*.xlsx`. Copia `Resumen` → `Resumen  Apoquindo` (2 espacios), `Consolidado Apoquindo` → `Consolidado Apoquindo`

### Qué falta ✗

| Pendiente | Descripción | Dificultad |
|---|---|---|
| **EERR Chañarcillo** | Mapear cuentas del trial balance a filas 73-124 de la hoja Chañarcillo | Media |
| **EERR Curicó** | Ídem para Curicó | Media |
| **EERR Inmob VC** | Ídem para Inmob VC (entidad chica, pocas líneas) | Baja |
| **EERR Viña Centro** | Ídem para Viña Centro | Media |
| **Balance Inmosa Q1-Q3** | Mapear cuentas dot-notation del Senior Assist a filas 5-70 de la hoja Inmosa | Media |
| **Balance + EERR Fondo Rentas** | Parser PDF EEFF del fondo (M$ × 1000). Q1/Q4=EEFF, Q2/Q3=Analisis | Alta |
| **Balance + EERR Machalí** | Entidad nueva, fuente Q2/Q4=Analisis/EEFF, Q1/Q3 sin evidencia suficiente | Alta |

---

## Instrucciones para retomar

### 1. Leer el contexto base

```
tools/balance_consolidado_tools.py  → función actualizar_balance_consolidado_rentas_nuevo
                                      constantes: CHANAR_BALANCE_MAP, CURICO_BALANCE_MAP, etc.
                                      helpers: _read_trial_balance_rn, _apply_balance_map_rn,
                                               _apply_eerr_sa_map_rn, _find_ws_rn
```

### 2. Para implementar un EERR map de una entidad

Pasos:
1. Abrir con openpyxl el planilla vF: `{SHAREPOINT_DIR}/Control de Gestión/Balances Consolidados/2025/4Q/12.2025- Balance Consolidado Rentas Nuevo vF.xlsx`
2. Abrir la hoja de la entidad (ej: `Chañarcillo`)
3. Leer col B filas 73 a 124 → son los labels de cada línea EERR
4. Abrir el archivo fuente de la entidad (ej: `RAW/12-2025 Análisis Chañarcillo.xlsx`, hoja `Bce Tributario`)
5. Usar `_read_trial_balance_rn` para leer el trial balance
6. Para cada label en col B del planilla, identificar el/los código(s) de cuenta del trial balance que corresponden
7. Verificar contra el valor histórico en col D (o E si D está vacía)
8. Construir un dict `CHANAR_EERR_MAP = {fila: [prefixes], ...}` similar a `INMOSA_SA_EERR_MAP`
9. Agregar función `_apply_eerr_chanar_rn(ws, tb, col)` que llame a `_apply_eerr_sa_map_rn`-style pero con el tipo correcto (G - Pd)

**Formato del trial balance Chañarcillo/Curicó/Inmob VC:** códigos dash-notation (`3-1-01-01`)
**Formato del trial balance Viña Centro:** mismos dash-notation, hoja `BALANCE ACUMULADO`
**Columna EERR en trial balance:** `Pd` (pérdida) y `G` (ganancia), índices 7 y 8 (0-based)
**Valor EERR = G - Pd** (positivo = ingreso, negativo = gasto)

### 3. Para implementar Balance Inmosa Q1-Q3

El archivo Senior Assist (`RAW/*Senior*Assist*.xlsx`, única hoja) usa dot-notation (`1.1.1010.10.01`).
Headers (fila 10): Cuenta | Descripción | Debe | Haber | Deudor | Acreedor | **Activo** | **Pasivo** | Perdida | (col 10 = Ganancia)

Crear `INMOSA_SA_BALANCE_MAP = {fila: (tipo, [codigos_dot]),...}` donde filas son las del planilla (5-70 hoja Inmosa).
Verificar contra col D del vF histórico.

### 4. Para implementar Fondo Rentas

- Q1/Q4: EEFF PDF (M$ × 1000). Buscar en `{SHAREPOINT_DIR}/Fondos/Rentas TRI/EEFF/YYYY/...` con MarkItDown
- Q2/Q3: Análisis xlsx (todavía sin identificar fuente exacta)
- El parser debe extraer balance y EERR. Ver `_parse_eeff_fondo_pt_pdf` como referencia

### 5. Integrar el EERR map en la función principal

Buscar el bloque de cada entidad en `actualizar_balance_consolidado_rentas_nuevo`:
```python
lines.append("  EERR: TODO (mapa filas pendiente)")
```
Reemplazar con la llamada al nuevo map/función.

---

## Fuente fija por quarter

| Hoja | Sección | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|
| `Inmosa` | Balance | Analisis | Analisis | Analisis | EEFF |
| `Inmosa` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Chañarcillo` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Chañarcillo` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Curicó` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Curicó` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Inmob VC` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Inmob VC` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Viña Centro` | Balance | Analisis | Analisis | Analisis | Analisis |
| `Viña Centro` | EERR | Analisis | Analisis | Analisis | Analisis |
| `Fondo Rentas` | Balance | EEFF | Analisis | Analisis | EEFF |
| `Fondo Rentas` | EERR | EEFF | EEFF | Analisis | EEFF |
| `Machalí` | Balance | Pendiente | Analisis | Pendiente | EEFF |
| `Machalí` | EERR | Pendiente | Analisis | Pendiente | Analisis |

## Notas críticas

- Las hojas **no tocar** (output): `Resumen`, `Consolidado Fondo Rentas ` (espacio final), `Resumen Viña`, `Consolidado Viña`
- Hojas con encoding corrupto en el xlsx: acceder siempre con `_find_ws_rn(wb, "Chañarcillo")` que hace matching normalizado
- `Curicó` hoja fuente: `Acum 12-2025` (no las hojas mensuales)
- `Viña Centro` fuente: hoja `BALANCE ACUMULADO` (no `BALANCE CLASIFICADO` — col S está incompleta)
- `Inmob VC` cuenta `1-1-02-06` tiene saldo Pasivo aunque su código es 1-x: se trata como P en el mapa
- `Curicó` ImpDif: `A(1-2-04-001) - P(2-2-06-010)` → R31 si >0, R56 si <0
- Senior Assist EERR: códigos dot-notation (`3.1.x`, `4.5.x`). Ingresos 3.x, Gastos 4.x. Valor = G - Pd
- Todas las columnas de datos (D:K) en filas 5-70 = balance, filas 73-124 = EERR
