# Balance Consolidado Rentas Nuevo

## Estado de implementación

**Herramienta:** `actualizar_balance_consolidado_rentas_nuevo(mes, año)` en `tools/balance_consolidado_tools.py` (desde línea ~2079).
**Registro:** callable vía `actualizar_balance_consolidado_rentas_si_completo` (tool del agente).

### Qué está implementado ✓

- Finds vF, copia como vAgente en la misma carpeta (misma carpeta del vF, no WORK_DIR)
- Desplaza columnas D:K en hojas input + PT/Apo
- Escribe fecha (`datetime`) y estado en fila 2 col D y col B respectivamente
- **Balance Chañarcillo** → `Fondos/Rentas TRI/Sociedades/Chañarcillo/Analisis/YYYY/MM-AAAA*Ch*arcillo*.xlsx` hoja `Bce Tributario` → `CHANAR_BALANCE_MAP` (16 filas)
- **Balance Curicó** → `Fondos/Rentas TRI/Activos/Curicó/EEFF/YYYY/MM-AAAA*INFORME*CURIC*.xlsx` hoja `Acum MM-AAAA` → `CURICO_BALANCE_MAP` (16 filas) + `_apply_curico_impdif` (R31/R56 neto)
- **Balance Inmob VC** → `Fondos/Rentas TRI/Sociedades/Inmobiliaria VC/Analisis/YYYY/MM-AAAA*Inmobiliaria*VC*.xlsx` hoja `Bce Tributario` → `INMOB_VC_BALANCE_MAP` (11 filas)
- **Balance Viña Centro** → `Fondos/Rentas TRI/Activos/Viña Centro/EEFF/YYYY/*INFORME*EFF*VI*A*CENTRO*.xlsx` hoja `BALANCE ACUMULADO` → `VINA_BALANCE_MAP` (21 filas)
- **EERR Inmosa** → `Fondos/Rentas TRI/Activos/INMOSA/Contabilidad/YYYY/*Senior*Assist*.xlsx` (única hoja) → `INMOSA_SA_EERR_MAP` (31 filas, dot-notation)
- **EERR Inmob VC** → misma fuente que balance → `INMOB_VC_EERR_MAP` (26 filas, verificado Dec 2025). Nota: labels col B del planilla contienen el código de cuenta directamente (`4-2-01-02  INTERESES PAGARE`).
- **EERR Chañarcillo** → misma fuente que balance (`Bce Tributario`) → `CHANAR_EERR_MAP` (31 filas, verificado Dec 2025: resultado del período 470.785.569 calza con D119). **Atención:** los valores históricos de col D estaban desplazados una fila (label "5-1-01-12 ESTRUCTURACION" tenía valor de COMISIONES, etc.). El map usa el código del label, no el patrón histórico — los valores en filas 93-99 cambiarán respecto al histórico.
- **EERR Curicó** → misma fuente que balance (`Acum MM-AAAA`) → `CURICO_EERR_MAP` (57 filas, verificado Dec 2025: resultado del período -405.776.897 calza con D174). Fila 162 (`4-2-01-004`) duplica fila 94 en el planilla y queda en blanco — no se mapea.
- **EERR Viña Centro** → misma fuente que balance (`BALANCE ACUMULADO`) → `VINA_EERR_MAP` (73 filas, verificado Dec 2025). El histórico tenía un descuadre de 244.636.379 (visible en fila 194 "Resultado" del control) por label codes mal asignados. El map nuevo mapea por descripción/valor en vez de strictly por label code, eliminando ese descuadre — total `G - Pd` = 3.093.097.786 = D189 + D194. Filas re-mapeadas: 94, 97, 113, 119, 120, 123, 137 (ver constante en código).
- Copia PT: busca `*Rentas PT*vAgente*.xlsx` en misma carpeta que vF, luego en WORK_DIR. Copia `Resumen` → `Resumen PT`, `Consolidado Fondo PT` → `Consolidado Fondo PT`
- Copia Apoquindo: busca `*Apoquindo*vAgente*.xlsx`. Copia `Resumen` → `Resumen  Apoquindo` (2 espacios), `Consolidado Apoquindo` → `Consolidado Apoquindo`

### Qué falta ✗

| Pendiente | Descripción | Dificultad |
|---|---|---|
| ~~**EERR Chañarcillo**~~ | ✓ Implementado Dec 2025 — 31 filas, totales calzan (resultado 470.785.569) | — |
| ~~**EERR Curicó**~~ | ✓ Implementado Dec 2025 — 57 filas, totales calzan (resultado -405.776.897) | — |
| ~~**EERR Inmob VC**~~ | ✓ Implementado — 26 filas, verificado Dec 2025 | — |
| ~~**EERR Viña Centro**~~ | ✓ Implementado Dec 2025 — 73 filas, mapeado por descripción corrige descuadre 244M del histórico | — |
| **Balance Inmosa Q1-Q3** | Mapear cuentas dot-notation del Senior Assist a filas 5-70 de la hoja Inmosa | Media |
| **Balance + EERR Fondo Rentas** | Parser PDF EEFF del fondo (M$ × 1000). Q1/Q4=EEFF, Q2/Q3=Analisis | Alta |
| **Balance + EERR Machalí** | Entidad nueva, fuente Q2/Q4=Analisis/EEFF, Q1/Q3 sin evidencia suficiente | Alta |
| **Bug `_copy_vals_sheet_rn`** | Falla con `MergedCell.value is read-only` al copiar Resumen PT/Apoquindo. Saltar celdas merged en la copia | Baja |

---

## Próxima sesión — orden de trabajo sugerido

**Estado actual (2026-05-12):** Balance + EERR de las 5 entidades core (Inmosa SA, Inmob VC, Chañarcillo, Curicó, Viña Centro) están implementados. Falta balance Q1-Q3 de Inmosa, todo Fondo Rentas y todo Machalí, y un bug menor en la copia de hojas PT/Apoquindo.

1. **Bug `_copy_vals_sheet_rn` (Baja)** — `tools/balance_consolidado_tools.py:2553`. Saltar celdas merged:
   ```python
   if isinstance(ws_dst.cell(...), MergedCell): continue
   ```
   Esto desbloquea la ejecución end-to-end de Rentas Nuevo.

2. **Balance Inmosa Q1-Q3 (Media)** — dot-notation Senior Assist → filas 5-70. Más laborioso porque cambia formato de códigos.

3. **Fondo Rentas / Machalí (Alta)** — requieren parser PDF + identificar fuentes Análisis para Q2/Q3. Dejar para el final.

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

**Atajo clave:** los labels en col B del planilla YA contienen el código de cuenta al inicio (`4-2-01-02  INTERESES PAGARE`). Solo hay que extraer el código y verificar contra el trial balance.

Pasos:
1. Abrir con openpyxl el planilla vF: `{SHAREPOINT_DIR}/Control de Gestión/Balances Consolidados/2025/4Q/12.2025- Balance Consolidado Rentas Nuevo vF.xlsx`
2. Abrir la hoja de la entidad (ej: `Chañarcillo`)
3. Leer col B filas 73 a 124 → extraer código de cuenta del inicio del label (regex `^[\d\-]+`)
4. Abrir el archivo fuente de la entidad (ej: `Fondos/Rentas TRI/Sociedades/Chañarcillo/Analisis/2025/12-2025 Análisis Chañarcillo.xlsx`, hoja `Bce Tributario`)
5. Usar `_read_trial_balance_rn` para leer el trial balance
6. Verificar que `G - Pd` del código coincide con el valor histórico en col D del planilla
7. Construir `CHANAR_EERR_MAP = {fila: [codigo], ...}`
8. En la función principal, reemplazar `lines.append("  EERR: TODO...")` con `_apply_eerr_sa_map_rn(ws_chanar, tb, col, CHANAR_EERR_MAP)`

**No crear función nueva** — `_apply_eerr_sa_map_rn` ya acepta `eerr_map` como parámetro opcional.

**Formato del trial balance Chañarcillo/Curicó/Inmob VC:** códigos dash-notation (`3-1-01-01`)
**Formato del trial balance Viña Centro:** mismos dash-notation, hoja `BALANCE ACUMULADO`
**Columna EERR en trial balance:** `Pd` (pérdida) y `G` (ganancia), índices 7 y 8 (0-based)
**Valor EERR = G - Pd** (positivo = ingreso, negativo = gasto)

### 3. Para implementar Balance Inmosa Q1-Q3

El archivo Senior Assist (`Fondos/Rentas TRI/Activos/INMOSA/Contabilidad/YYYY/*Senior*Assist*.xlsx`, única hoja) usa dot-notation (`1.1.1010.10.01`).
Headers (fila 10): Cuenta | Descripción | Debe | Haber | Deudor | Acreedor | **Activo** | **Pasivo** | Perdida | (col 10 = Ganancia)

Crear `INMOSA_SA_BALANCE_MAP = {fila: (tipo, [codigos_dot]),...}` donde filas son las del planilla (5-70 hoja Inmosa).
Verificar contra col D del vF histórico.

### 4. Para implementar Fondo Rentas

- Q1/Q4: EEFF PDF (M$ × 1000). Buscar en `{SHAREPOINT_DIR}/Fondos/Rentas TRI/EEFF/Fondo/{YYYY}/{Q}/...` con MarkItDown
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
