# Tab de ingesta: Amortización Extraordinaria — Design

**Fecha:** 2026-07-27
**Estado:** aprobado

## Contexto

Los créditos de los fondos (`dim_credito`, 15 registros VIGENTE/PAGADO) tienen su
cronograma completo de amortización en `raw_amortizacion` (credito_key + periodo →
capital_uf, intereses_uf, saldo_uf) y su saldo proyectado en `raw_saldo_deuda`
(credito_key + periodo → saldo_uf, is_proyeccion). Ambas tablas se pueblan
exclusivamente vía `tools/db/ingest_financing.py`, un script CLI que lee un Excel
maestro completo y hace `DELETE` + recarga total cada vez que corre. No existe
ningún canal web para actualizarlas incrementalmente.

Varios créditos tienen amortizaciones extraordinarias (bullet/prepago) ya
anticipadas en el campo libre `perfil_amortizacion` de `dim_credito` — ej.
`PT_TORREA_SECURITY`: *"Bullet c/amorts. nov-26/27/28 de UF 14.200 c/u"`. Cuando
uno de estos pagos ocurre (o cuando surge uno no anticipado), hoy no hay forma de
registrarlo en la DB hasta que alguien actualice el Excel maestro y se corra el
reload completo — que puede tardar meses. Mientras tanto, `raw_saldo_deuda`
sobrestima el saldo vigente y cualquier KPI de deuda/LTV que lo consuma queda
desactualizado.

**Objetivo de esta iteración:** una tab en `web/ingesta.html` para registrar el
*evento* de un pago extraordinario (crédito, fecha, monto) apenas se confirma,
sin depender del reload completo del Excel.

## Decisiones de alcance (confirmadas con el usuario)

1. Se registra un **evento puntual** (pago extra sobre un crédito existente), no
   un cronograma completo. Subir/reemplazar la tabla de amortización completa de
   un crédito individual queda fuera de esta iteración.
2. El evento se guarda en una **tabla nueva dedicada**
   (`raw_amortizacion_extraordinaria`), no se escribe directo en
   `raw_amortizacion` — para no chocar con el próximo wipe-and-reload de
   `ingest_financing.py`, que no sabe de este registro y lo pisaría.
3. Entrada por **formulario simple** (crédito + fecha + monto + nota), sin
   parseo de texto ni upload de archivo — es el tipo de dato más simple de todos
   los que ya existen en la app.
4. Al registrar el evento, se **recomputa `raw_saldo_deuda`** hacia adelante para
   ese crédito: resta `monto_uf` a todos los `saldo_uf` con `periodo >= periodo
   del evento` y `is_proyeccion=1`. Los períodos ya cerrados (histórico real) no
   se tocan.
5. **No se agrega a `tools/db/estado_ingesta.py`**: no es un dato periódico con
   "período pendiente/al día" — es un evento oportunista sin cadencia fija.

## Sección 1 — Esquema de datos

### Migración `tools/db/migrations/072_amortizacion_extraordinaria.sql`

```sql
CREATE TABLE raw_amortizacion_extraordinaria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    credito_key     TEXT NOT NULL REFERENCES dim_credito(credito_key),
    fecha           TEXT NOT NULL,        -- 'YYYY-MM-DD'
    periodo         TEXT NOT NULL,        -- 'YYYY-MM', derivado de fecha
    monto_uf        REAL NOT NULL,
    nota            TEXT,
    source_file     TEXT,                 -- NULL (no aplica, es formulario)
    file_hash       TEXT,                 -- NULL (idem)
    ingest_run_id   INTEGER REFERENCES ingest_run(id),
    loaded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_at   TEXT
);
```

`source_file`/`file_hash` se mantienen por consistencia con el resto de tablas
`raw_*` versionadas (permite un futuro "deshacer" vía `superseded_at`), aunque
queden NULL en este flujo — no hay archivo que hashear.

No se agrega `UNIQUE` estricto sobre `(credito_key, fecha)`: dos prepagos al
mismo crédito en la misma fecha son válidos (ej. dos tramos del mismo bullet).
La detección de duplicados es responsabilidad del usuario, asistida por el
historial que se muestra en la UI (ver Sección 3).

## Sección 2 — Backend

### Núcleo: `tools/db/ingest_amortizacion_extra.py`

- `listar_creditos(con) -> list[dict]`: `SELECT credito_key, acreedor, activo_key,
  fondo_key, estado FROM dim_credito WHERE estado='VIGENTE' ORDER BY fondo_key,
  activo_key`. Solo créditos vigentes — un `PAGADO` no puede recibir prepagos.
- `historial(con, credito_key) -> list[dict]`: eventos ya registrados
  (`superseded_at IS NULL`) para ese crédito, orden descendente por fecha.
- `commit(con, credito_key, fecha, monto_uf, nota) -> dict`:
  1. Valida: `credito_key` existe y `estado='VIGENTE'`; `monto_uf > 0`; `fecha`
     parseable ISO.
  2. Crea `ingest_run` (`tool='amortizacion_extraordinaria'`).
  3. Inserta en `raw_amortizacion_extraordinaria` (`periodo = fecha[:7]`).
  4. Llama a `_recomputar_saldo_proyectado(con, credito_key, periodo, monto_uf)`:
     `UPDATE raw_saldo_deuda SET saldo_uf = saldo_uf - :monto WHERE credito_key=:ck
     AND periodo >= :periodo AND is_proyeccion=1`.
  5. Retorna resumen: `{credito_key, periodo, monto_uf, periodos_ajustados: N}`.

Sin función `validate()` separada — al ser formulario estructurado (no texto
libre de proveedor externo) la validación se hace inline en `commit()`, igual
que valida cualquier form-POST del resto del backend.

### Endpoints en `scripts/ingesta_server.py`

```
GET  /api/amort_extra/creditos            → listar_creditos()
GET  /api/amort_extra/historial?credito_key=X → historial()
POST /api/amort_extra/commit              → body {credito_key, fecha, monto_uf, nota}
```

`commit` devuelve 400 con mensaje claro si la validación falla (mismo patrón que
`/api/balance/commit`, `/api/parking/commit`). Tras un commit exitoso, se llama
`_rebuild_factsheet()` igual que el resto de endpoints de commit, por
consistencia (aunque el factsheet no muestre este dato hoy, mantiene el patrón
uniforme de "todo commit exitoso dispara rebuild").

## Sección 3 — Frontend (`web/ingesta.html`)

Nueva tab `"Amort. Extraordinaria"` (`data-tab="amort-extra"`), siguiendo el
layout de las tabs simples (Parking, Balance):

- Dropdown de crédito (poblado desde `/api/amort_extra/creditos`, label =
  `"{acreedor} — {activo_key} ({fondo_key})"`).
- Input fecha (`YYYY-MM-DD`).
- Input monto UF.
- Textarea nota (opcional).
- Al seleccionar un crédito, se carga y muestra su historial
  (`/api/amort_extra/historial`) en una tabla debajo del form — da contexto
  para no duplicar un evento ya cargado.
- Botón "Registrar" → `POST /api/amort_extra/commit`. Éxito: refresca historial
  y limpia el form. Error: muestra el mensaje del backend.

Sin paso de "preview antes de confirmar" (a diferencia de EEFF/Mercado) — al ser
3 campos estructurados no hay ambigüedad que previsualizar.

## Fuera de alcance

- Reemplazar/subir el cronograma completo de amortización de un crédito
  (`raw_amortizacion`) vía web — sigue siendo `ingest_financing.py` con el Excel
  maestro completo.
- Entrada en `tools/db/estado_ingesta.py` / dashboard de pendientes — no aplica
  a un dato sin cadencia periódica.
- Ajustar `raw_amortizacion` (capital_uf/intereses_uf) al registrar el evento —
  solo se ajusta `raw_saldo_deuda` (saldo proyectado). El cronograma detallado
  mes a mes se sincroniza en el próximo reload completo del Excel maestro.
- Editar o eliminar eventos ya registrados desde la UI (si se necesita corregir
  uno, se hace directo en DB o en una iteración futura).

## Testing

- `tests/db/test_ingest_amortizacion_extra.py`:
  - `commit()` con crédito PAGADO → rechaza con error claro.
  - `commit()` con monto <= 0 → rechaza.
  - `commit()` válido → inserta 1 fila en `raw_amortizacion_extraordinaria` y
    ajusta solo los `saldo_uf` con `periodo >= periodo_evento AND
    is_proyeccion=1` para ese `credito_key` (verificar que períodos históricos e
    is_proyeccion=0 quedan intactos, y que otros créditos no se tocan).
  - `historial()` devuelve los eventos en orden descendente por fecha.
- Test de endpoint (`tests/test_ingesta_server_estado.py` o archivo nuevo):
  `POST /api/amort_extra/commit` sin `X-Ingesta-Token` → 401 (cubierto por el
  middleware existente, solo confirmar que la ruta nueva no quedó exenta).
