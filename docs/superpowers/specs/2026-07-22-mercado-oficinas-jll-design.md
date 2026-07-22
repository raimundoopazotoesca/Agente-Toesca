# Ingesta y consolidación de datos de mercado de oficinas (JLL) — Diseño

**Fecha:** 2026-07-22
**Estado:** Draft — aprobado por el usuario en brainstorming, pendiente de implementación
**Motivación:** La página 4 del fact sheet de Apoquindo tiene una tabla de "Análisis de Mercado de Oficinas" que hoy muestra placeholders (`—`) porque no existe fuente de datos en la DB. Los datos vienen de informes trimestrales de proveedores (JLL para esta tabla), en PDF, con la tabla ya armada — el usuario copia el texto y lo pega.

## Objetivo

Diseñar la arquitectura de datos y el flujo de ingesta para que la tabla de mercado de oficinas del fact sheet de Apoquindo se alimente desde la DB (`agente_toesca_v2.db`), reemplazando el hardcode actual en `scripts/build_factsheet.py`.

## Alcance

- **In-scope:** tabla `raw_mercado_oficinas`, parser del texto copy-paste de JLL, tab nuevo "Mercado" en la app de ingesta existente (`web/ingesta.html` + `scripts/ingesta_server.py`), consumo desde `build_factsheet.py`.
- **Out-of-scope:** los párrafos de texto libre de la página 4 (`txt-mercado-p1`, `txt-mercado-p2`) — se siguen editando a mano, son análisis cualitativo, no datos tabulares.
- **Out-of-scope:** otros proveedores de mercado (Colliers, CBRE, etc.) o tablas de mercado para PT/TRI — hoy solo Apo tiene esta página y solo JLL es la fuente. El diseño no cierra la puerta a agregarlos (columna `proveedor` ya existe), pero no se implementa ahora.
- **Out-of-scope:** proyecciones o series históricas más allá de lo que trae cada informe trimestral.

## Fuente de datos: formato exacto del copy-paste JLL

El usuario copia el texto de la tabla directamente del PDF. Formato observado (ver ejemplo real en el anexo): **una línea por valor**, sin tabs ni separadores explícitos.

**Bloque de encabezado** (10 líneas, se descartan al parsear):
```
Clase
Inventario (m²)
Absorción neta trimestral (m²)
Absorción neta últimos 12 meses (m²)
Vacancia (%)
Renta pedida promedio (UF/m²/mes)
Renta pedida promedio (USD/m²/mes)
Producción trimestral (m²)
Producción últimos 12 meses (m²)
En construcción [2026-2029](m²)
```

**Bloques de datos**: 18 bloques de 11 líneas cada uno (6 submercados × clase `Total`, más totalizador `Santiago` = 7; 3 submercados × clase `A` (Las Condes CBD, Providencia, Santiago Centro) más totalizador `Santiago` = 4; 6 submercados × clase `B` más totalizador `Santiago` = 7 → total 18 filas):
```
<submercado>
<clase>
<inventario_m2>
<absorcion_trim_m2>
<absorcion_u12m_m2>
<vacancia_pct>
<renta_uf_m2>
<renta_usd_m2>
<produccion_trim_m2>
<produccion_u12m_m2>
<construccion_m2>
```

Submercados conocidos: `Las Condes (CBD)`, `Providencia`, `Santiago Centro`, `Vitacura`, `Ciudad empresarial`, `Estoril`, y el totalizador `Santiago` (marcado `es_total=1`).

Clase A solo existe para Las Condes (CBD), Providencia, Santiago Centro (+ totalizador Santiago); Vitacura, Ciudad empresarial y Estoril no tienen inventario clase A separado.

## Decisiones de diseño

### D1 — Tabla wide `raw_mercado_oficinas`, no long

Una fila de la tabla JLL = una fila de la DB, con las 9 métricas como columnas. Alternativa considerada: formato long (una fila por métrica) — descartada porque va contra el principio de queries simples (requeriría pivot para reconstruir una fila) y la tabla JLL es estable en sus columnas desde hace años. Si JLL agrega una columna nueva, es un `ALTER TABLE ADD COLUMN` trivial.

### D2 — `vacancia_pct` en escala 0-100, no 0-1

Consistente con el formato de la fuente (`5,6%` → `5.6`), evita conversión mental al leer la DB directamente.

### D3 — Ingesta vía la app web existente, no vía chat

La app `http://localhost:8765/ingesta` ya tiene tabs "EEFF" y "Rent Roll" con el patrón validar→preview→confirmar. Se agrega un tercer tab "Mercado" siguiendo el mismo patrón, en vez de crear un flujo de ingesta por chat. Razón: consistencia con el flujo ya validado por el usuario, evita fricción de "¿en qué chat ingesto esto?".

### D4 — Idempotencia vía `file_hash` del texto pegado

Mismo patrón que el resto de la DB: `UNIQUE(file_hash, source_row)`. Hash = sha256 del texto pegado completo. Re-pegar el mismo texto no duplica. Si JLL corrige el informe del mismo trimestre, el usuario re-pega el texto corregido (hash distinto) → se marca `superseded_at` en las filas viejas del mismo `periodo` y se insertan las nuevas.

### D5 — Periodo = último mes del trimestre del informe

Formato `YYYY-MM` estándar de la DB (ej. informe Q3 2025 → `periodo='2025-09'`). El usuario lo declara al ingestar (no se infiere del texto, JLL no lo incluye en la tabla).

## Schema

```sql
CREATE TABLE raw_mercado_oficinas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo             TEXT NOT NULL,        -- 'YYYY-MM', último mes del trimestre
    proveedor           TEXT NOT NULL,        -- 'JLL'
    submercado          TEXT NOT NULL,        -- 'Las Condes (CBD)', 'Providencia', etc.
    clase               TEXT NOT NULL,        -- 'Total', 'A', 'B'
    es_total            INTEGER DEFAULT 0,    -- 1 para filas 'Santiago' (agregado)
    inventario_m2       REAL,
    absorcion_trim_m2   REAL,
    absorcion_u12m_m2   REAL,
    vacancia_pct        REAL,                 -- 5.6, no 0.056
    renta_uf_m2         REAL,
    renta_usd_m2        REAL,
    produccion_trim_m2  REAL,
    produccion_u12m_m2  REAL,
    construccion_m2     REAL,
    file_hash           TEXT,
    source_row          INTEGER,
    ingest_run_id       INTEGER REFERENCES ingest_run(id),
    loaded_at           TEXT DEFAULT (datetime('now')),
    superseded_at       TEXT,
    UNIQUE(file_hash, source_row)
);
CREATE INDEX idx_mercado_periodo ON raw_mercado_oficinas(periodo);
CREATE INDEX idx_mercado_lookup ON raw_mercado_oficinas(periodo, submercado, clase)
    WHERE superseded_at IS NULL;
```

Volumen: 18 filas/trimestre × 4/año ≈ 72 filas/año. Tabla minúscula, sin necesidad de particionado ni agregados intermedios.

## Parser (`tools/db/ingest_mercado.py`)

```python
def parse_tabla_jll(texto: str) -> list[dict]:
    lines = [l.strip() for l in texto.strip().splitlines() if l.strip()]
    if lines[0] == "Clase":
        lines = lines[10:]
    if len(lines) % 11 != 0:
        raise ValueError(f"Se esperaban bloques de 11 líneas, quedaron {len(lines)}")
    filas = []
    for i in range(0, len(lines), 11):
        chunk = lines[i:i + 11]
        submercado, clase = chunk[0], chunk[1]
        valores = [_parse_num_cl(v) for v in chunk[2:11]]
        filas.append({
            "submercado": submercado,
            "clase": clase,
            "es_total": 1 if submercado == "Santiago" else 0,
            "inventario_m2": valores[0],
            "absorcion_trim_m2": valores[1],
            "absorcion_u12m_m2": valores[2],
            "vacancia_pct": valores[3],
            "renta_uf_m2": valores[4],
            "renta_usd_m2": valores[5],
            "produccion_trim_m2": valores[6],
            "produccion_u12m_m2": valores[7],
            "construccion_m2": valores[8],
        })
    return filas
```

`_parse_num_cl`: convierte formato chileno (`"1.733.422"` → `1733422.0`), porcentajes (`"5,6%"` → `5.6`), negativos (`"-7.786"` → `-7786.0`).

### Validaciones en `validate()`

- Exactamente 18 filas.
- Clases presentes: `Total`, `A`, `B`.
- Cada submercado conocido aparece con la combinación clase esperada (A solo en Las Condes CBD, Providencia, Santiago Centro).
- Rangos razonables: `vacancia_pct` entre 0 y 100; métricas de superficie ≥ 0 salvo absorción (puede ser negativa).
- Retorna `ValidationResult` con preview de las 18 filas + errors/warnings, mismo contrato que `ingest_eeff_validated.validate()`.

### `commit()`

Abre `ingest_run`, inserta filas con `INSERT OR IGNORE` (unique por `file_hash, source_row`), marca `superseded_at` en filas previas del mismo `periodo`+`proveedor` si el hash cambió, cierra `ingest_run`. Retorna resumen `{ok: True, filas_insertadas: N, periodo: ...}`.

## Endpoints nuevos (`scripts/ingesta_server.py`)

```
GET  /api/mercado/periodo_check?periodo=2025-09         → ¿ya ingestado? cuántas filas
POST /api/mercado/validate   {texto, periodo, proveedor} → preview + errors/warnings
POST /api/mercado/commit     {texto, periodo, proveedor} → persiste, retorna resumen
```

## Frontend (`web/ingesta.html`)

Nuevo tab `"Mercado"` junto a `"EEFF"` y `"Rent Roll"`, mismo patrón visual: selector de periodo (`input[type=month]`), selector de proveedor (por ahora solo JLL), textarea para pegar el texto copiado, botón "Validar" → preview en tabla de las 18 filas con badges de warnings/errors, botón "Confirmar" → commit.

## Consumo desde `scripts/build_factsheet.py`

Reemplaza el `mercado_rows` hardcodeado en `FONDO_CONFIG["APO"]["page4"]` por una query data-driven, solo para el fondo Apo:

```python
if fondo_key == "APO":
    periodo_mercado = _ultimo_trimestre_cerrado(periodo)
    mercado_rows_db = cur.execute("""
        SELECT submercado, clase, inventario_m2, absorcion_u12m_m2,
               vacancia_pct, renta_uf_m2, construccion_m2, es_total
        FROM raw_mercado_oficinas
        WHERE periodo = ? AND proveedor = 'JLL' AND superseded_at IS NULL
        ORDER BY
            CASE clase WHEN 'Total' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 END,
            es_total, id
    """, (periodo_mercado,)).fetchall()
```

El fact sheet solo muestra 5 de las 9 columnas (inventario, absorción U12M, vacancia, renta UF, construcción) — las otras 4 quedan en la DB para uso futuro (dashboard, cross-check) pero no se renderizan en esta página.

### Manejo de trimestre sin datos

Si la query no retorna filas (informe del trimestre aún no ingestado), se mantiene el comportamiento actual: celdas con placeholder `—`, sin romper el render.

### Cambios en `factsheet.html`

El JS que hoy itera `S.page4.mercado_rows` (todo con `class="placeholder">—`) pasa a recibir los valores reales desde el backend, con formato:
- `inventario_m2`, `construccion_m2` → miles con punto (`1.733.422`)
- `vacancia_pct` → `5,6%`
- `renta_uf_m2` → `0,57`
- fila con `es_total=1` → clase `row-total` (ya existe en el CSS)

## Piezas a implementar

1. Migración `052_raw_mercado_oficinas.sql`
2. `tools/db/ingest_mercado.py` — `parse_tabla_jll`, `_parse_num_cl`, `validate`, `commit`
3. Endpoints `/api/mercado/*` en `scripts/ingesta_server.py`
4. Tab "Mercado" en `web/ingesta.html`
5. Query + render data-driven en `scripts/build_factsheet.py` + `factsheet.html`
6. Tests: parseo del bloque real (anexo), idempotencia (re-ingestar no duplica), validación de conteo de filas

## Anexo: texto real de ejemplo (Q3 2025, para tests)

```
Clase
Inventario (m²)
Absorción neta trimestral (m²)
Absorción neta últimos 12 meses (m²)
Vacancia (%)
Renta pedida promedio (UF/m²/mes)
Renta pedida promedio (USD/m²/mes)
Producción trimestral (m²)
Producción últimos 12 meses (m²)
En construcción [2026-2029](m²)
Las Condes (CBD)
Total
1.733.422
9.388
39.913
5,6%
0,57
24,63
7.013
36.704
104.187
Providencia
Total
552.223
8.283
36.890
10,7%
0,49
21,42
0
25.000
17.218
Santiago Centro
Total
373.249
-7.786
8.316
10,6%
0,34
14,82
0
0
0
Vitacura
Total
173.394
4.284
9.313
10,0%
0,50
21,57
0
0
0
Ciudad empresarial
Total
260.433
6.997
10.896
6,8%
0,24
10,39
0
0
0
Estoril
Total
69.242
1.372
2.648
18,5%
0,40
17,37
0
0
0
Santiago
Total
3.161.963
22.538
107.976
7,7%
0,47
20,63
7.013
61.704
121.405
Las Condes (CBD)
A
1.076.580
3.652
27.452
5,4%
0,62
26,85
0
29.691
99.400
Providencia
A
156.895
6.658
28.527
23,6%
0,52
22,78
0
25.000
10.800
Santiago Centro
A
81.180
-4.281
1.752
17,8%
0,34
14,93
0
0
0
Santiago
A
1.314.655
6.028
57.731
8,3%
0,55
23,89
0
54.691
110.200
Las Condes (CBD)
B
656.842
5.737
12.461
6,0%
0,49
21,39
7.013
7.013
4.787
Providencia
B
395.328
1.625
8.363
5,5%
0,44
19,12
0
0
6.418
Santiago Centro
B
292.069
-3.505
6.564
8,6%
0,34
14,76
0
0
0
Vitacura
B
173.394
4.284
9.313
10,0%
0,50
21,57
0
0
0
Ciudad empresarial
B
260.433
6.997
10.896
6,8%
0,24
10,39
0
0
0
Estoril
B
69.242
1.372
2.648
18,5%
0,40
17,37
0
0
0
Santiago
B
1.847.308
16.510
50.245
7,3%
0,41
17,98
7.013
7.013
11.205
```
