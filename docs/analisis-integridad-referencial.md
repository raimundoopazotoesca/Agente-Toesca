# Inventario de inconsistencias referenciales

**Fecha:** 2026-07-24 · **Estado:** análisis entregado, **saneamiento NO ejecutado**
**Base:** `memory/agente_toesca_v2.db` tras las migraciones 058–060.
**Premisa del usuario:** el tope de 2.478 en el invariante es una protección temporal, no un estado aceptable. El objetivo es **cero** inconsistencias reales.

---

## 1. Resumen

| Categoría | Filas | Estado |
|---|---:|---|
| **A. FK real violada** — `raw_eeff_line.ingest_run_id → ingest_run(id)` | **2.478** | causa identificada, reparación trivial y sin impacto en cifras |
| **B. Relación lógica sin FK** — `derived_kpi.entidad_key` sin respaldo en `dim_*` | **1.471** | no es violación de FK (no existe la restricción); depende de decisiones de modelado |
| **C. Datos legacy sin trazabilidad** — `file_hash` NULL | **2.484** | 2.478 son los mismos de (A); 6 son una corrección manual documentada |
| **D. Brecha latente** — `PROVEEDOR_ACTIVOS['jll']` apunta a activos inexistentes | 0 hoy | fallaría en la primera ingesta de rent roll JLL |

**El único grupo que hoy viola una FK declarada es (A).** Las demás categorías son relaciones que el esquema no fuerza.

---

## 2. Categoría A — `raw_eeff_line.ingest_run_id` (2.478 filas)

### Conteo y perfil

- **Una sola tabla, una sola FK:** `raw_eeff_line.ingest_run_id → ingest_run(id)`. Ninguna otra tabla tiene violaciones.
- **25 grupos**, de 100 filas cada uno (menos uno), todos del fondo **PT**.
- Períodos: **2021-06 → 2025-12**, un archivo por trimestre (`2025-12-31.json`, `2024-09-30.json`, …).
- Tipos en la columna: `integer` 33.371 · `text` **2.378** · `null` 1.044. Las 2.478 violaciones son los 2.378 de texto más 100 que son un entero (`76457586`) sin correspondencia.

### Causa — verificada, no inferida

Las tres comprobaciones que la fijan:

1. **Solape perfecto con `file_hash` NULL.** De las 2.478 filas huérfanas, **2.478 tienen `file_hash IS NULL`** y **0 tienen `file_hash`**. Correlación del 100%.
2. **El valor huérfano es un hash de 8 caracteres** en las 2.478 filas (`LENGTH = 8` uniforme): `'1756fcfb'`, `'3622f414'`, …
3. **No existe ningún `ingest_run` correspondiente**: no coincide con ningún `file_hash` de `ingest_run` (0 de 25 grupos), ni con el `file_hash` de la propia fila. Además `ingest_run` solo tiene registros desde **2026-05-25**, muy posterior a estas cargas.

**Conclusión:** un cargador escribió el hash del archivo en `ingest_run_id` y dejó `file_hash` vacío — las dos columnas quedaron cruzadas. No es corrupción de datos financieros: es metadata de linaje mal colocada.

### Consecuencia hoy

Estas 2.478 filas son **inalcanzables por `mark_superseded()`**, que busca por `file_hash`. Es decir: **no se pueden versionar ni corregir** por el mecanismo normal. Son, en la práctica, inmortales.

### Propuesta de corrección

Un solo `UPDATE`, reversible, que resuelve (A) y la mayor parte de (C) a la vez:

```sql
UPDATE raw_eeff_line
   SET file_hash     = CAST(ingest_run_id AS TEXT),
       ingest_run_id = NULL
 WHERE file_hash IS NULL
   AND ingest_run_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM ingest_run i WHERE i.id = raw_eeff_line.ingest_run_id);
```

- Mueve el hash a su columna correcta → las filas vuelven a ser versionables.
- `ingest_run_id = NULL` es lo honesto: la corrida no quedó registrada y no se puede reconstruir. NULL es válido para la FK.
- **Violaciones resultantes: 0.**

**Alternativa considerada y descartada:** crear `ingest_run` sintéticos por `source_file` para preservar el vínculo. Daría trazabilidad aparente a costa de inventar `started_at`, `ended_at` y `status` que nadie registró. Si quieres auditoría explícita, la variante honesta es crear **una** corrida por archivo con `tool='legacy_ingest_from_json'`, `status='ok'` y `started_at = NULL`, dejando constancia de que es una reconstrucción. **Decisión pendiente.**

### Impacto en cifras y outputs

**Ninguno.** Verificado:
- Las 2.478 filas conservan sus montos: 2.478 valores, suma `8.159.850.042.000` CLP — el `UPDATE` no toca `monto_clp`, `periodo`, `fondo_key` ni `cuenta_codigo`.
- Ninguna consulta de negocio filtra por `ingest_run_id`; todas usan `superseded_at IS NULL`.
- El factsheet no lee esa columna.
- Efecto secundario **positivo**: al recuperar `file_hash`, esos períodos pasan a ser corregibles con el botón de supersede (F0.9).

---

## 3. Categoría B — `derived_kpi.entidad_key` (1.471 filas, 14 claves)

`derived_kpi` **no tiene FK** sobre `entidad_key` (es polimórfica: apunta a `dim_fondo`, `dim_activo` o `dim_serie` según `entidad_tipo`). No hay violación de restricción, pero sí claves sin respaldo:

| entidad_key | filas | Qué es |
|---|---:|---|
| `PT` | 202 | el **fondo**, guardado como `entidad_tipo='activo'` |
| `Apoquindo` | 178 | agregado Apo4501+Apo4700 (ver `matriz-claves-ambiguas-apoquindo.md`) |
| `PT Bodegas`, `PT Locales`, `PT Oficinas`, `PT Boulevard`, `PT Torre A` | 98 c/u | **subdivisiones por tipo de superficie** dentro de PT |
| `SUCDEN`, `Machalí`, `Curicó`, `Apoquindo 3001`, `Apoquindo 4501`, `Apoquindo 4700` | 74–98 | mismos activos con **nomenclatura larga/mayúsculas** (`Sucden`, `Strip Machalí`, `Mall Curicó`, `Apo3001`…) |
| `Fondo Apoquindo` | 91 | agregado a nivel fondo Apo |

Tres problemas distintos, no uno:
1. **Agregados mal etiquetados como activo** (`PT`, `Apoquindo`, `Fondo Apoquindo`) → decidido en ROADMAP F1.9: pasan a `entidad_tipo='fondo'`.
2. **Variantes de nomenclatura** (`SUCDEN` vs `Sucden`, `Curicó` vs `Mall Curicó`) → mismo patrón que `APO`/`Apo`; se resuelven al recalcular con recetas versionadas.
3. **Subdivisiones de superficie de PT** (`PT Oficinas`, `PT Bodegas`, …) → **entidad nueva, no contemplada en el modelo**. No son activos ni fondos: son categorías dentro de un activo. Es el caso que justificaría `dim_grupo_activo` (o una dimensión de segmento), el mismo lugar donde caería el futuro subtotal "Centros Comerciales".

**No se propone corrección aquí**: depende de F1.9 y del recálculo con el pipeline canónico. Se documenta para que el conteo no se confunda con violaciones de FK.

**Recomendación de diseño (no ejecutar aún):** no añadir una FK a `derived_kpi.entidad_key` — es polimórfica y una FK única no puede expresarla. Lo correcto es un `CHECK` + un test de invariante que valide, por `entidad_tipo`, que la clave existe en la dimensión correspondiente. Ese test sí puede llegar a cero.

---

## 4. Categoría C — `file_hash` NULL (2.484 filas)

- **2.478** son las de la categoría A → se resuelven con el mismo `UPDATE`.
- **6 filas** son legítimas y están autodocumentadas en `source_file`:
  `'EEFF Apo 2020-12 (correccion manual desde foto usuario, 2026-07-09)'`.
  Son una carga manual sin archivo fuente. **Propuesta:** asignarles un `file_hash` sintético trazable (p. ej. `manual:apo-2020-12`), para que sean versionables sin fingir que provienen de un archivo. Requiere tu confirmación de que esa corrección manual sigue vigente.

Tras ambas correcciones, `file_hash` podría declararse `NOT NULL` (como ya lo declaraban las migraciones), cerrando la puerta a que vuelva a ocurrir.

---

## 5. Categoría D — brecha latente de rent roll JLL

`scripts/ingesta_server.py` mapea:

```python
PROVEEDOR_ACTIVOS = {"jll": ["PT", "Apoquindo", "Apo3001"], ...}
```

Pero `dim_activo` **no tiene** `PT` ni `Apoquindo` (los activos de PT son `Torre A`, `Boulevard`, `Parking PT`; los de Apo son `Apo4501` y `Apo4700`). Como `raw_rent_roll_line.activo_key` **sí** tiene FK a `dim_activo`, la primera ingesta de un rent roll JLL fallaría con `FOREIGN KEY constraint failed`.

Hoy no hay violaciones porque el rent roll cargado es solo de Tres Asociados (Viña Centro y Mall Curicó, 2026-05). Los seeds antiguos de las migraciones sí traían `PT` y `Apoquindo`; producción no.

**Es la misma pregunta de modelado que el agregado de Apoquindo**: ¿JLL entrega el rent roll a nivel de agregado (`PT`, `Apoquindo`) y por tanto esas entidades deben existir, o hay que desagregarlo a los activos reales al ingerir? **Decisión pendiente**, previa al backfill de rent roll (F1.6).

---

## 6. Plan propuesto (para aprobar)

| Paso | Acción | Riesgo | Resultado |
|---|---|---|---|
| 1 | `UPDATE` de la categoría A (con backup + dry-run + conteos) | bajo — solo columnas de linaje, cero impacto en cifras | violaciones de FK: **2.478 → 0** |
| 2 | `file_hash` sintético para las 6 filas manuales | bajo | `file_hash` NULL: 2.484 → 0 |
| 3 | Declarar `file_hash NOT NULL` en `raw_eeff_line` | bajo, tras 1 y 2 | impide la regresión |
| 4 | Bajar el tope del invariante de 2.478 a **0** | — | el invariante deja de ser una excusa |
| 5 | Test por `entidad_tipo` para `derived_kpi.entidad_key` | — | mide la categoría B sin confundirla con FKs |

Los pasos 1–4 son ejecutables ya y dejan la categoría A en cero. La B y la D quedan bloqueadas por decisiones de modelado (F1.9 y rent roll JLL).

## 7. Decisiones que requieren tu validación

1. **Corridas sintéticas**: ¿`ingest_run_id = NULL` (honesto) o crear `ingest_run` de reconstrucción marcadas como legacy?
2. **Las 6 filas manuales de Apo 2020-12**: ¿siguen vigentes? ¿se les asigna hash sintético o se resuelven de otra forma?
3. **Subdivisiones `PT Oficinas`/`PT Bodegas`/…**: ¿son una dimensión de segmento a modelar, o KPIs legacy a marcar obsoletos y recalcular?
4. **Rent roll JLL** (categoría D): ¿`PT` y `Apoquindo` deben existir como entidades, o el ingestor debe desagregar a los activos reales?
