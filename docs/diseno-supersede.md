# Diseño del supersede — reemplazo de datos ya ingestados

**Fecha:** 2026-07-24 · **Estado:** diseño entregado, **no implementado**
**Corresponde a:** ROADMAP F0.9
**Condición previa (tuya):** implementarlo cuando la semántica de versionado y reemplazo
esté completamente fijada. Este documento fija esa semántica primero.

---

## 1. El problema

Hoy, si un proveedor manda una versión corregida de un archivo ya ingestado, **no hay
forma de reemplazarlo desde la interfaz**. La ingesta bloquea duro el período
(`"No se puede reingestar un período ya cargado"`) y la única salida es ejecutar
`mark_superseded()` a mano desde Python o SQL. Es la operación más delicada del sistema
—invalida datos publicados— y es la única sin preview, sin confirmación y sin registro.

---

## 2. Unidad de reemplazo: el archivo, no la fila

**El supersede opera sobre `file_hash` (un archivo) o sobre `ingest_run_id` (una corrida),
nunca sobre filas sueltas.**

Razones:
- Es la semántica que ya usan los repos: `mark_superseded(conn, file_hash)` marca todas
  las filas de ese archivo.
- Una fila suelta no tiene sentido de negocio: un EEFF es un documento coherente; anular
  media docena de sus líneas deja un estado que no corresponde a ningún documento real.
- Evita exactamente el riesgo que detuvo el saneamiento de duplicados: marcar filas
  individuales cuya identidad no está demostrada.

**Corolario:** el análisis de duplicados (`docs/analisis-duplicados-dry-run.md`) y este
botón usan **la misma primitiva**. No hay una lógica para el histórico y otra para la web:
ambos llaman a la misma función, con el mismo registro de auditoría.

---

## 3. Semántica de versionado (fijada)

```
supersede(file_hash | ingest_run_id, motivo, usuario)
  → marca superseded_at = ahora en TODAS las filas vivas de ese origen
  → NO borra físicamente
  → registra quién, cuándo y por qué
  → marca stale los KPIs derivados de los períodos afectados
```

Reglas:

1. **Append-only.** Nunca se borra. `superseded_at` es un tombstone lógico; el dato queda
   auditable y el rollback es posible.
2. **Todo o nada por origen.** No se puede superseder parte de un archivo.
3. **Idempotente.** Superseder dos veces el mismo hash no cambia nada la segunda vez.
4. **Reversible.** `unsupersede` existe y también se audita, con el mismo protocolo.
5. **Motivo obligatorio.** Sin texto libre no vacío, no se ejecuta.
6. **No cascada silenciosa.** Superseder no re-ingesta nada: deja el período vacío y el
   panel de estado lo mostrará como pendiente. Reemplazar = superseder + ingerir, dos
   pasos explícitos.

### Interacción con las restricciones de unicidad

Los UNIQUE aplicados (migraciones 063–064) **no incluyen `superseded_at`** en
`raw_rent_roll_line`, `raw_flujo_line` ni `raw_er_activo_line`. Consecuencia: reingerir el
mismo archivo tras superseder **fallaría**, porque la fila superseded sigue ocupando la
clave.

Dos salidas, hay que elegir una:

| Opción | Cómo | Costo |
|---|---|---|
| **A** — incluir `superseded_at` en la clave | como ya hacen las tablas de parking: `UNIQUE(..., superseded_at)` | requiere recrear los índices; permite N versiones del mismo archivo |
| **B** — exigir que la versión corregida tenga otro `file_hash` | es lo normal: un archivo corregido tiene contenido distinto | si el proveedor manda el archivo **idéntico**, no se puede reingerir — pero tampoco tendría sentido |

**Recomendación: A**, por consistencia con las tablas de parking, que ya resolvieron esto
así. Es un cambio de índice, sin impacto en datos. **Decisión pendiente.**

---

## 4. Modelo de datos

Tabla nueva, mínima:

```sql
CREATE TABLE supersede_event (
    id             INTEGER PRIMARY KEY,
    tabla          TEXT NOT NULL,      -- raw_eeff_line, raw_rent_roll_line, …
    file_hash      TEXT,               -- uno de los dos, no ambos
    ingest_run_id  INTEGER REFERENCES ingest_run(id),
    filas_afectadas INTEGER NOT NULL,
    motivo         TEXT NOT NULL,
    usuario        TEXT NOT NULL,
    accion         TEXT NOT NULL CHECK (accion IN ('supersede','unsupersede')),
    periodos       TEXT,               -- JSON con los períodos tocados, para invalidar KPIs
    creado_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

No hace falta más: `superseded_at` en la fila dice *qué* está anulado; esta tabla dice
*quién, cuándo y por qué*. El par cubre la trazabilidad del Principio 3.

---

## 5. Flujo en la interfaz

Reutiliza el patrón validate → preview → confirmar que ya existe en toda la ingesta.

```
1. El usuario elige tipo de dato y período  (o pega un file_hash)
2. GET  /api/supersede/preview  → qué se va a anular, SIN tocar nada
3. El usuario escribe el motivo (obligatorio)
4. POST /api/supersede          → re-valida server-side y ejecuta en una transacción
5. La UI muestra el resultado y los KPIs marcados stale
```

### Contenido del preview (antes de confirmar)

- Archivo/corrida: `source_file`, `file_hash`, fecha de ingesta, herramienta.
- **Filas afectadas**, desglosadas por período y fondo/activo.
- **Suma de los montos** que se van a anular — para que se vea el peso de lo que se retira.
- **Qué queda después**: si el período se queda sin datos, decirlo explícitamente
  ("el período 2025-12 de PT quedará sin EEFF").
- **KPIs derivados afectados**, con su cantidad.
- Advertencia si el archivo tiene filas **ya** superseded (idempotencia).

### Confirmación

Botón deshabilitado hasta que haya motivo. Igual que en la ingesta, el `POST` **re-ejecuta
el preview server-side** y aborta si cambió respecto de lo mostrado — defensa en
profundidad: nunca confiar en que el cliente respetó el gate.

---

## 6. Recálculo / invalidación de KPIs

Superseder datos invalida los derivados que salieron de ellos. Hoy `derived_kpi` **no tiene
forma de expresar "obsoleto"** (es el mismo hueco que bloquea F1.9).

Mecanismo mínimo, coherente con lo ya aplicado:

```sql
ALTER TABLE derived_kpi ADD COLUMN stale_at TEXT;   -- previsto en F1.1
```

Al superseder: `stale_at = ahora` en los `derived_kpi` de las entidades y períodos
afectados. Las lecturas de negocio muestran el valor pero **marcado como desactualizado**;
el orquestador (F1.1) los recalcula en la siguiente corrida.

**Por qué marcar y no borrar:** borrar dejaría el factsheet sin número y sin explicación.
Marcar permite mostrar "12,3% (pendiente de recálculo)", que es honesto — coherente con la
regla de no convertir una ausencia en un cero.

**Dependencia:** este punto **requiere F1.1**. Sin orquestador, marcar stale deja KPIs
desactualizados sin nadie que los recalcule. Por eso el botón debe llegar **después o junto
con** el pipeline canónico, no antes.

---

## 7. Auditoría y rollback

- Toda ejecución deja fila en `supersede_event`.
- **Rollback:** `unsupersede` pone `superseded_at = NULL` en las filas del evento y registra
  la acción inversa. Posible porque no se borra nada.
- Límite: si tras superseder se ingirió un archivo nuevo para el mismo período, el
  `unsupersede` reviviría datos que ahora conviven con los nuevos. El preview del
  unsupersede debe detectarlo y **detenerse**, pidiendo resolver el conflicto a mano.

---

## 8. Tests exigidos antes de dar por implementado

1. Preview no modifica nada (conteos idénticos antes y después).
2. El commit re-valida server-side y aborta si cambió el estado.
3. Sin motivo → rechazo.
4. Idempotencia: superseder dos veces no cambia nada.
5. `unsupersede` restaura exactamente las mismas filas.
6. `unsupersede` se detiene si hay datos nuevos del mismo período.
7. Los KPIs de los períodos afectados quedan `stale`.
8. Requiere token, como todo `/api/*`.
9. El evento queda en `supersede_event` con usuario, motivo y filas.
10. **Misma primitiva que el saneamiento histórico**: un test que verifica que ambos
    caminos llaman a la misma función.

---

## 9. Qué NO incluir en la primera versión

- Supersede de filas individuales (rompe la semántica de §2).
- Supersede en cascada automática entre tablas.
- Reingesta automática tras superseder (dos pasos explícitos).
- Papelera con retención/purga: `superseded_at` ya cumple, y no hay presión de tamaño.

---

## 10. Decisiones que requieren tu validación

1. **Unicidad vs supersede** (§3): ¿opción A (incluir `superseded_at` en los índices únicos,
   como parking) u opción B (exigir hash distinto)? Recomiendo A.
2. **Orden**: el botón depende de `stale_at` y del orquestador (F1.1). ¿Se implementa junto
   con F1.1, o antes sin invalidación de KPIs (dejando el recálculo manual)?
3. **Alcance por tipo de dato**: ¿el botón cubre las 5 fuentes (EEFF, rent roll, mercado,
   balance, parking) desde el inicio, o solo EEFF y rent roll, que son las que más se
   corrigen?
4. **Quién puede superseder**: hoy no hay identidad de usuario (el token es compartido). El
   campo `usuario` quedaría en `"local"` hasta F2.1. ¿Aceptable para empezar?
