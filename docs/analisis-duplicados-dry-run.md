# Dry run de duplicados — `raw_eeff_line`

**Fecha:** 2026-07-24 · **Estado:** análisis entregado, **saneamiento NO ejecutado**
**Script:** `scripts/dry_run_duplicados.py` (no escribe nada; `--detalle` muestra ejemplos)
**Política aplicada:** la de tres casos definida por el usuario, con la prioridad
(1) ingesta validada y confirmada · (2) `ingest_run_id` válido · (3) fuente y hash identificables · (4) registro vigente · (5) reingesta explícita · (6) revisión humana si divergen sin precedencia demostrable.

---

## 1. Hallazgo previo que cambia el plan

**El `UNIQUE(file_hash, source_row)` que declaraban las migraciones es incorrecto para dos de las cuatro tablas raw.** No debe aplicarse tal cual.

| Tabla | `source_row` NULL | ¿Sirve `(file_hash, source_row)`? |
|---|---:|---|
| `raw_eeff_line` | 34.312 de 36.793 (**93%**) | **No: inútil.** SQLite trata cada NULL como distinto, así que la restricción no impediría casi nada |
| `raw_er_activo_line` | 8 de 10.448 | **No: dañino.** Una fila de la planilla genera una fila **por mes**: verificado un caso con `file_hash=50fc1923, source_row=4` → **104 filas**, una por período desde 2018-01. La restricción rechazaría datos válidos |
| `raw_flujo_line` | 0 de 46 | igual que el anterior (meses en columnas) |
| `raw_rent_roll_line` | 0 de 119 | **Sí**, es el único donde aplica bien |

**Claves correctas propuestas:**

| Tabla | Clave única real |
|---|---|
| `raw_eeff_line` | `(fondo_key, periodo, cuenta_codigo_canonical)` — solo cuando el canónico existe; ver §4 |
| `raw_er_activo_line` | `(file_hash, source_row, periodo)` — solo **10 filas** sobrantes hoy |
| `raw_flujo_line` | `(file_hash, source_row, periodo)` — **0** sobrantes, aplicable ya |
| `raw_rent_roll_line` | `(file_hash, source_row)` — **0** sobrantes, aplicable ya |

---

## 2. Resultado del dry run (`raw_eeff_line`)

Filas vivas analizadas: **29.130** · Grupos de clave de negocio: **18.862**

| Caso | Grupos | Filas |
|---|---:|---:|
| **1 — duplicado exacto** (mismo `file_hash`, misma `source_row`, mismos valores) | 346 | 742 |
| **2 — redundante** (misma clave y valores, distinto archivo) | 3.056 | 9.043 |
| **3 — valores distintos con precedencia demostrable** | 2 | 4 |
| **3 — AMBIGUO, detenido para revisión humana** | **1.098** | 4.981 |

**Si se ejecutara el saneamiento:**

| | |
|---|---:|
| Filas que quedarían vigentes | 22.745 |
| Filas que quedarían superseded | **6.385** |
| Grupos detenidos para revisión | 1.098 |
| Períodos afectados | 85 |

**Por fondo:**

| Fondo | Grupos | Filas superseded |
|---|---:|---:|
| Apo | 2.557 | 5.232 |
| TRI | 581 | 851 |
| PT | 266 | 302 |

Ninguna fila se borra: solo se marca `superseded_at`, reversible.

---

## 3. Impacto en cifras y outputs — **hoy es nulo**

Este es el resultado más importante para calibrar la urgencia.

Los duplicados están **casi exclusivamente en filas sin `cuenta_codigo_canonical`**, que ninguna consulta de negocio agrega:

- Filas vivas con código canónico: **5.307**; sin código: 23.823.
- Grupos duplicados **entre filas con código canónico: solo 2**.
- Cuentas de gasto que el factsheet suma (`ER.depreciaciones`, `ER.otros_gastos`, `ER.total_gastos_operacion`, …) con duplicados: **0**.

Los 2 únicos grupos con canónico duplicado son, ambos, `Apo 2020-12`:
`ESF.total_activo_corriente` y `ESF.total_activo_no_corriente`, con las fuentes
`EEFF_APO_202103.json` y `EEFF Apo 2020-12 (correccion manual desde foto usuario, 2026-07-09)`.
Es exactamente el **caso 3 legítimo** de tu política: una corrección deliberada y documentada. La regla de precedencia elige bien (gana la corrección manual, la anterior queda superseded), pero conviene que lo confirmes.

**Conclusión:** los duplicados **no distorsionan ninguna cifra publicada hoy**. Son un problema de higiene y de riesgo futuro: cualquier consulta nueva que agregue por `cuenta_nombre` en vez de por código canónico contaría de más. Eso permite hacer el saneamiento con calma y en el orden correcto, sin urgencia.

---

## 4. Los 1.098 casos ambiguos — la mitad son falsos positivos

De los 1.098 grupos detenidos, **537 (≈49%) provienen del mismo archivo con montos distintos**, y **los 537 carecen de `cuenta_codigo_canonical`**.

Ejemplo real:

```
('TRI', '2020-12', 'Otros')
  id=95   monto=0            src=12.20 Toesca Rentas Inmobiliarias.pdf
  id=188  monto=-38.435.000  src=12.20 Toesca Rentas Inmobiliarias.pdf
  id=268  monto=1.880.000    src=12.20 Toesca Rentas Inmobiliarias.pdf
```

Tres filas del **mismo PDF, mismo período**, con nombre `'Otros'` y montos distintos.
**No son duplicados**: son partidas diferentes que comparten un nombre genérico y aparecen en secciones distintas del estado financiero. Nombres genéricos más frecuentes: `Total` (147 grupos), `Otros` (102), y varias del tipo `Inmobiliaria Apoquindo S.A. - Total pasivos/gastos/activos`.

**Implicaciones:**

1. La clave de negocio `(fondo, periodo, nombre)` **no es válida** cuando falta el código canónico. Deduplicar por ella borraría datos reales.
2. El problema de fondo no es duplicación sino **mapeo de cuentas incompleto**: 23.823 filas vivas sin código canónico. Mientras eso siga así, no hay clave de negocio confiable para esas filas.
3. `raw_eeff_line` no tiene columna `seccion` (a diferencia de `raw_er_activo_line`), así que hoy **no hay forma de distinguir** dos `'Otros'` del mismo estado salvo por `source_row`, que es NULL en el 93% de los casos.

**Por eso el dry run los detiene en vez de resolverlos automáticamente**, tal como pediste.

---

## 5. Plan propuesto (por aprobar, en este orden)

| Paso | Acción | Alcance | Riesgo |
|---|---|---|---|
| 1 | Aplicar `UNIQUE(file_hash, source_row)` a **`raw_rent_roll_line`** y `(file_hash, source_row, periodo)` a **`raw_flujo_line`** | 0 filas sobrantes: aplicable de inmediato | nulo |
| 2 | Depurar las **10 filas** sobrantes de `raw_er_activo_line` y aplicar `(file_hash, source_row, periodo)` | 10 filas | bajo |
| 3 | Ejecutar casos **1 y 2** de `raw_eeff_line` (346 + 3.056 grupos → 6.383 filas superseded) | reversible, sin impacto en cifras | bajo |
| 4 | Confirmar los **2 grupos del caso 3** (corrección manual Apo 2020-12) | 2 filas | requiere tu confirmación |
| 5 | **Completar el mapeo canónico** de cuentas antes de tocar los 1.098 ambiguos | 23.823 filas sin canónico | es la tarea de fondo |
| 6 | Recién entonces, revisar los ambiguos con una clave de negocio válida | 1.098 grupos | — |
| 7 | Aplicar `UNIQUE` a `raw_eeff_line` sobre `(fondo_key, periodo, cuenta_codigo_canonical)` **parcial** (`WHERE cuenta_codigo_canonical IS NOT NULL AND superseded_at IS NULL`) | — | cierra la puerta a la regresión |

Los pasos 1–3 son ejecutables ya. El 5 es el que realmente resuelve el problema y es más grande que un saneamiento: es completar `eeff_cuenta_mapper`.

---

## 6. Decisiones que requieren tu validación

1. **Ejecutar los pasos 1–3** (casos 1 y 2, sin tocar ambiguos): ¿procedo?
2. **Los 2 grupos de Apo 2020-12**: ¿la corrección manual desde foto es la versión buena y la del `EEFF_APO_202103.json` debe quedar superseded?
3. **Mapeo canónico**: ¿es prioridad completarlo? Sin él, 23.823 filas (82% de las vivas) no tienen clave de negocio confiable y los 1.098 ambiguos no se pueden resolver.
4. **Columna `seccion` en `raw_eeff_line`**: ¿se agrega para poder distinguir partidas homónimas (`'Otros'` de activos vs de gastos)? `raw_er_activo_line` ya la tiene.
5. **`UNIQUE` parcial vs total** en `raw_eeff_line`: la parcial (solo filas con canónico y vigentes) permite convivir con el histórico sin mapear; la total exigiría terminar el paso 5 primero.
