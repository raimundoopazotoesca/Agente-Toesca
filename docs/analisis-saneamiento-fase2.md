# Análisis previos al saneamiento — segunda tanda

**Fecha:** 2026-07-24 · **Estado:** análisis entregados, **nada ejecutado** de lo que aquí se propone
**Contexto:** complementa `docs/analisis-duplicados-dry-run.md` y `docs/analisis-integridad-referencial.md` con las clasificaciones adicionales solicitadas.

---

## 1. Las 10 filas de `raw_er_activo_line` — **no son duplicados**

Pediste el detalle antes de proponer precedencia. El detalle cambia la conclusión: **no hay nada que sanear.**

Los 10 grupos son un único caso, `file_hash=b098c8f9`, `source_row=29`, meses 2019-01 a 2019-10, y en cada uno las dos filas son:

| activo_key | cuenta | monto (UF) | nombre |
|---|---|---:|---|
| `Apo4501` | `APO_CONTRIB` | −997,09 | `Contribuciones (split 75% s/combinado, regla 2026-07-09)` |
| `Apo4700` | `APO_CONTRIB` | −332,36 | `Contribuciones (split 25% s/combinado, regla 2026-07-09)` |

Es un **reparto deliberado**: el archivo traía una sola fila con las contribuciones combinadas de Apoquindo y el ingestor la dividió 75/25 entre los dos edificios, dejando la regla escrita en el propio `cuenta_nombre`. Distinto `activo_key`, distinto monto, misma fila de origen — **por diseño**. Ratio verificado: 997,09 / 332,36 = 3,0 exacto.

### Consecuencia: la clave propuesta era incorrecta

| Clave candidata | Sobrantes |
|---|---|
| `(file_hash, source_row, periodo)` | **10** ← rechazaría el split legítimo |
| `(file_hash, source_row, periodo, activo_key)` | **0 — limpia** |
| `(file_hash, source_row, periodo, activo_key, cuenta_codigo)` | 0 — limpia |

**Propuesta:** aplicar `UNIQUE(file_hash, source_row, periodo, activo_key)` **sin saneamiento previo**, porque no hay filas que depurar. Es la mínima que expresa la realidad: una fila de planilla puede repartirse entre activos, pero no puede repetirse para el mismo activo, período y fila.

*(No la apliqué: implica cambiar la propuesta que ya te había presentado, y prefiero tu visto bueno sobre la clave nueva.)*

---

## 2. Caso 1 (346 grupos) — subdivisión solicitada

| Criterio | Grupos |
|---|---:|
| `source_row` **no nulo** | **0** |
| `source_row` **NULO** | **346** (100%) |
| Todas las filas con código canónico | **0** |
| Ninguna fila con código canónico | **346** (100%) |
| Sección identificable | **0** |
| **Subgrupo con identidad inequívoca (ejecutable automáticamente)** | **0** |

**Resultado: ningún grupo del caso 1 cumple los criterios para ejecución automática.** Los 346 tienen `source_row` NULL, ninguno tiene código canónico ni sección, así que la única evidencia de identidad sería el nombre — insuficiente, precisamente por los homónimos `'Otros'` y `'Total'`.

Aplicando tu regla ("los grupos con `source_row IS NULL` deben permanecer detenidos salvo que exista otra evidencia fuerte"), **los 346 quedan detenidos**.

---

## 3. Caso 2 — clasificación adicional

Recalculado con criterio estricto (mismos valores, más de un archivo o hash): **2.839 grupos, 8.609 filas**.

| Clasificación | Grupos |
|---|---:|
| Todas las filas con código canónico | **2** |
| Ninguna fila con código canónico | **2.837** |
| Con sección recuperable | 2 |
| **Archivos que son copia exacta** (mismo `file_hash`) | **0** |
| Archivos distintos que podrían ser versiones o documentos diferentes | **2.839** (todos) |

**Resultado:** ningún grupo proviene de una copia exacta del mismo archivo; todos son documentos distintos que *podrían* representar el mismo hecho o versiones diferentes. Solo **2** grupos tienen código canónico, y son exactamente los de Apo 2020-12 que dejaste en suspenso.

**Conclusión conjunta de §2 y §3: no hay nada ejecutable automáticamente en el saneamiento de duplicados de `raw_eeff_line`.** El 100% depende de completar el mapeo canónico y/o la sección. Tu decisión de no ejecutar el bloque de 6.383 evitó marcar como superseded ~8.600 filas cuya identidad no está demostrada.

---

## 4. Apo 2020-12 — comparación JSON vs corrección manual

| Cuenta | Corrección manual | JSON (`EEFF_APO_202103.json`) | Δ |
|---|---:|---:|---:|
| `ESF.total_activo_corriente` | 405.468.000 | 405.468.000 | **0** |
| `ESF.total_activo_no_corriente` | 41.937.890.000 | 41.937.890.000 | **0** |
| `ESF.total_activo` | **42.343.358.000** | *(ausente)* | — |

**Hallazgos:**

1. **La corrección manual no corrigió ningún valor.** Las dos cuentas que se solapan son idénticas al dígito. Los 2 "duplicados" son, por tanto, caso 2 (redundante), no una corrección.
2. **Lo que sí aportó fue la cuenta que faltaba:** `ESF.total_activo`, ausente en el JSON. Esa fila **no es duplicada** y es la contribución real de la carga manual.
3. **Cuadra contablemente:** 405.468.000 + 41.937.890.000 = 42.343.358.000, exacto.
4. **Coherente con la serie:** Apo `total_activo` va 45.621M (2020-09) → **42.343M (2020-12)** → 43.922M (2021-03). El valor encaja en la tendencia.
5. El JSON fuente es `EEFF_APO_202103.json`, es decir 2020-12 entró como **período comparativo** de un documento de 2021-03 — lo que explica que trajera los subtotales pero no el total.

**Imagen o fuente que respaldó la corrección:** el único rastro es el texto de `source_file`
(`'EEFF Apo 2020-12 (correccion manual desde foto usuario, 2026-07-09)'`). **La fotografía no está en el repositorio ni referenciada en ninguna parte.** No puedo aportarla.

**Impacto sobre estados y KPIs:** nulo hoy. Ninguna cuenta de gasto del factsheet está afectada y los valores solapados son idénticos, así que da igual cuál sobreviva. La única fila con efecto es `ESF.total_activo`, que es única y **debe conservarse**.

**Recomendación (para tu decisión):** dado que los valores coinciden, la precedencia es indiferente para las cifras. Lo pendiente no es elegir versión sino **confirmar que 42.343.358.000 es correcto**, ya que ese número solo existe por la carga manual y no tiene documento fuente verificable en el repo. Ambas versiones siguen vigentes, como pediste.

---

## 5. Plan incremental de mapeo canónico

### Cobertura actual (filas vivas de `raw_eeff_line`)

**Global: 5.307 de 29.130 = 18,2%.**

| Fondo | Mapeadas / total | % |
|---|---|---:|
| TRI | 2.578 / 10.207 | 25,3% |
| PT | 1.050 / 4.195 | 25,0% |
| **Apo** | 1.679 / 14.728 | **11,4%** |

| Año | Filas | % mapeado |
|---|---:|---:|
| 2017 | 909 | 39,2% |
| 2018 | 1.909 | 33,4% |
| 2019 | 2.616 | 27,4% |
| 2020 | 2.992 | 18,6% |
| 2021 | 3.656 | 13,8% |
| 2022 | 5.116 | **12,2%** |
| 2023 | 4.754 | 12,9% |
| 2024 | 4.346 | 14,4% |
| 2025 | 2.495 | 21,3% |
| 2026 | 337 | 41,8% |

| Sección | Filas |
|---|---:|
| (sin mapear) | 23.823 |
| ER | 2.458 |
| ESF | 1.685 |
| EFE | 1.013 |
| ECP | 151 |

*Observación:* la cobertura **cae** hacia los años recientes (39% en 2017 vs 12% en 2022) y Apo es el fondo peor cubierto. No es un problema de antigüedad sino de qué documentos se ingirieron con mapeo.

### Long tail

**1.986 nombres distintos** sin mapear cubren las 23.823 filas. Concentración:

| Alcance | % de filas sin mapear que cubre |
|---|---:|
| top 20 nombres | 16,8% |
| top 50 | 27,3% |
| top 100 | 38,3% |
| top 200 | **52,6%** |

Los más frecuentes: `Total` (770), `Serie UNICA - Valor Cuota Libro` (329), `Serie UNICA - Patrimonio` (329), `Serie UNICA - Valor Cuota Mercado` (303), `Serie UNICA - Aportantes N°` (303), `Otros` (256).

**Dato relevante:** los `Serie UNICA - *` (1.264 filas) **no son cuentas contables**, son métricas de serie que ya viven en tablas propias (`raw_valor_cuota_contable`, `raw_valor_cuota_bursatil`, `v_serie_patrimonio`). No hay que mapearlas: hay que **decidir si se excluyen del mapeo** o se marcan con una sección `OTRO`/`SERIE`.

### Plan por etapas (propuesto, no ejecutado)

| Etapa | Alcance | Filas aprox. | Criterio |
|---|---|---:|---|
| **1** | Cuentas usadas por factsheet, KPIs y Asistente | ~600 | Ya mapeadas en su mayoría; auditar que las 7 cuentas de gasto del factsheet y las de `KPI_META` estén completas en los 3 fondos y todos los períodos |
| **2** | Top 50 nombres por frecuencia | ~6.500 | 27% del faltante con 50 decisiones |
| **3** | Cuentas necesarias para análisis financiero (ESF completo, ER completo por fondo) | ~8.000 | Habilita balance y resultado completos |
| **4** | Long tail histórico | resto | Por lotes, sin bloquear nada |

**Regla de mapeo (tuya, incorporada):** cada asignación se basa en **fuente y sección**, nunca en similitud de nombres. Operativamente: un nombre solo se mapea si se puede identificar el documento y la sección donde aparece; los homónimos (`'Otros'`, `'Total'`) **requieren la sección** para desambiguarse, así que dependen de poblar `seccion` (migración 062 ya la creó).

**Métrica de seguimiento propuesta:** un test/reporte que emita cobertura por fondo × año × sección, para ver el avance y detectar retrocesos. Puede vivir junto a `tools/db/coverage.py`.

---

## 6. Rent roll JLL — análisis parcial y honesto

**Limitación:** no hay ningún archivo JLL sincronizado en esta máquina (`Rent Rolls/JLL` no existe en el OneDrive local; tampoco hay ninguno en `work/` ni en el repo). **No puedo entregar la estructura real de los archivos**; lo que sigue sale del código y debe verificarse contra un archivo real en la máquina Windows.

### Campos que el lector ya extrae

`tools/rentroll_tools.py` lee estas columnas:

```
Activo1 · Activo2 · Detalle Activo · Arrendatario · Tipo Arrendatario
Renta Fija (UF/m2 /mes) · Area Arrendable (m2) · Fecha Inicio · Término del Contrato
```

### Mapeo actual y por qué es el problema

`_RR_ACTIVO_KEY` (`rentroll_tools.py:39`) mapea **`Activo1`**, que contiene el **nombre del fondo**, no el activo:

| `Activo1` (fondo) | → `activo_key` actual | ¿Existe en `dim_activo`? |
|---|---|---|
| `Fondo Rentas PT` | `PT` | **No** |
| `Fondo Rentas Apoquindo` | `Apoquindo` | **No** |
| `Apoquindo 3001` | `Apo3001` | Sí |
| `Paseo Viña Centro` | `Viña Centro` | Sí |
| `Mall Curicó` | `Mall Curicó` | Sí |

Las dos primeras son las entidades artificiales que pediste no crear.

### Pista concreta: `Activo2` ya se usa y probablemente tiene el activo real

`_read_rr_locals` (`rentroll_tools.py:190`) hace `col_map.get("Activo2") or col_map.get("Activo1")` — es decir, **el código ya prefiere `Activo2` cuando existe**, para las validaciones. Si `Activo2` contiene el edificio (Torre A / Boulevard), esa es la columna correcta para el mapeo, y `Detalle Activo` sería el tercer nivel.

**Mapeo propuesto para PT** (a confirmar contra archivo real):

| `Activo2` esperado | `activo_key` real |
|---|---|
| Torre A | `Torre A` |
| Boulevard | `Boulevard` |
| Estacionamientos / Parking | `Parking PT` |

**Para Apoquindo:** los activos reales son `Apo4501` y `Apo4700`. Habría que ver si el rent roll los distingue (por dirección 4501/4700 o por edificio) o si entrega Apoquindo combinado — en cuyo caso hay que decidir cómo desagregar, igual que se hizo con las contribuciones (§1), o si el rent roll de Apoquindo no debe ingerirse por esta vía.

### Sobre `Apoquindo` y `Apo3001` en la configuración JLL

Tu sospecha de configuración legacy es razonable pero **no la puedo confirmar ni descartar**: hay evidencia en ambos sentidos.
- A favor de que sea legítimo: `CLAUDE.md` documenta que la hoja **"NOI PT"** del archivo JLL contiene datos de **PT, Apoquindo y Apo3001**, y `noi_tools` los procesaba juntos. O sea, JLL sí entrega los tres en el mismo libro.
- A favor de que sea legacy: el rent roll cargado hoy es solo de Tres Asociados, y `Apoquindo` como `activo_key` es la misma entidad ambigua que estamos eliminando.

**Verificación necesaria (en Windows):** abrir el último `{AAMM} Rent Roll y NOI.xlsx` y responder: ¿la hoja de rent roll incluye filas de Apoquindo y Apo3001, o solo de Parque Titanium? Eso zanja la pregunta con evidencia.

### Casos que no podrán asignarse automáticamente

- Filas cuyo `Activo2` esté vacío o no coincida con ningún `activo_key`.
- Unidades compartidas o servicios comunes que no pertenezcan a un edificio único.
- Apoquindo, si el archivo no distingue 4501 de 4700.

### Validación humana propuesta durante la ingesta

Reutilizar el patrón validate/commit que ya existe: en el preview, una tabla **"activos no asignados"** con las filas cuyo `activo_key` no se resolvió, su `Activo1/Activo2/Detalle Activo` y el arrendatario; el botón de confirmar se habilita solo si esa tabla está vacía o el usuario asigna cada caso explícitamente. Coherente con "no infieras el activo por el proveedor".

### Entregables pendientes de un archivo real

1. Estructura real (hojas, encabezados, fila de datos).
2. Contenido efectivo de `Activo1`, `Activo2` y `Detalle Activo`.
3. Tabla de mapeo definitiva hacia `dim_activo`.
4. Volumen de filas no asignables.

---

## 7. Decisiones que requieren tu validación

1. **`raw_er_activo_line`**: ¿apruebas `UNIQUE(file_hash, source_row, periodo, activo_key)`? No requiere saneamiento previo (0 sobrantes).
2. **Apo 2020-12**: los valores solapados son idénticos, así que la precedencia da igual; lo que falta es **confirmar que `total_activo` = 42.343.358.000 es correcto**, ya que solo existe por la carga manual y su foto no está en el repo. ¿La conservas como está?
3. **`Serie UNICA - *`** (1.264 filas): ¿se excluyen del mapeo canónico por no ser cuentas contables, o se les asigna una sección propia?
4. **Orden del mapeo canónico**: ¿confirmas las 4 etapas propuestas? La 2 (top 50 nombres) da el mejor retorno inmediato: 27% del faltante con 50 decisiones.
5. **Rent roll JLL**: ¿puedes verificar en Windows si el archivo incluye Apoquindo/Apo3001 y qué trae `Activo2`? Sin eso el mapeo definitivo queda bloqueado.
