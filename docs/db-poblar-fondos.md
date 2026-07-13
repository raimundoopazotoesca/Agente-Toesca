# Guía: Poblar la DB por fondo (TRI, PT, Apoquindo)

**Archivo vivo** — actualizar cuando se agreguen nuevas fuentes o cambie el schema.
**Contexto**: `memory/agente_toesca_v2.db` es la DB canónica. El CDG Excel es entregable, no fuente.

---

## Arquitectura en 3 capas

```
PDFs / Excel proveedor
        │
        ▼
  raw_*          ← línea por línea del documento, idempotente por file_hash
  (raw_eeff_line, raw_valor_cuota_contable_line, raw_dividendo_line,
   raw_cuota_en_circulacion_line, raw_valor_cuota_bursatil_line)
        │
        ▼
  fact_*         ← valor único por (entidad, fecha): precios bursátiles, UF, dividendos con nemotécnico
  (fact_precio_cuota, fact_uf, fact_dividendo)
        │
        ▼
  derived_kpi    ← calculado: NOI, vacancia, valor cuota libro, TIR, rentabilidades
  (kpi TEXT, entidad_tipo TEXT, entidad_key TEXT, periodo TEXT, valor REAL, unidad TEXT, recipe TEXT)
```

**Regla de oro**: nunca leer el CDG completo (14 MB/87 hojas, ~12s). Usar siempre el CDG extract (`work/eeff_ingesta/TRI/cdg_extract.xlsx`, ~1 MB).

---

## Fondos y sus identificadores

| Fondo | `fondo_key` | Nemotécnico(s) | Serie |
|---|---|---|---|
| Parque Titanium | `PT` | `CFITRIPT-E` | Única |
| Rentas TRI (paraguas) | `TRI` | `CFITOERI1A`, `CFITOERI1C`, `CFITOERI1I` | A / C / I |
| Apoquindo | `Apo` | `Apo` (interno, no cotiza) | Única |

---

## Fuente 1 — CDG Extract (`cdg_extract.xlsx`)

**Ruta**: `work/eeff_ingesta/TRI/cdg_extract.xlsx`
**Hojas**: `A&R PT`, `A&R Rentas`, `A&R Apoquindo`

### Layout de cada hoja (mismo para las 3)

| Col (0-based) | Letra | Contenido |
|---|---|---|
| 0 | A | Año |
| 1 | B | Mes |
| 2 | C | Id (nro correlativo) |
| 3 | D | Fecha (datetime) |
| 4 | E | Detalle: `Aporte`, `VR Contable`, `VR Bursátil`, `Dividendo`, `Disminución` |
| 5 | F | Serie (None para PT y Apo; `A`/`C`/`I` para TRI) |
| 6 | G | Tipo (Aporte / Reparto) |
| 7 | H | Monto CLP total |
| 8 | I | Monto CLP / cuota |
| 9 | J | Cuotas en circulación |
| 10 | K | UF del día |
| 11 | L | Monto UF total |
| 12 | M | Monto UF / cuota ← el más importante |
| 13 | N | Libro Inicio (flujo TIR: positivo para distribuciones, negativo para Aportes) |

**Datos empiezan en fila 13 (1-based)**. Terminar cuando col A es None o < 2000.

### Qué se ingesta por fondo

| Detalle | PT | TRI | Apo | Tabla destino |
|---|---|---|---|---|
| `VR Contable` | ✓ | ✓ | ✓ | `raw_valor_cuota_contable_line` (tipo=`contable`) |
| Cuotas de `VR Contable` | ✓ | ✓ | ✓ | `raw_cuota_en_circulacion_line` |
| `Dividendo` | ✓ | ✓ | ✓ | `raw_dividendo_line` (tipo=`dividendo`) |
| `Disminución` | ✗ | ✗ | ✓ | `raw_dividendo_line` (tipo=`disminucion`) |
| `VR Bursátil` precio + patrimonio | ✓ | ✓ | ✗ | `raw_valor_cuota_bursatil_line` (col `patrimonio_bursatil_uf`) |

*TRI precio bursátil viene de LarrainVial datachart, no del extract.

### Comandos para correr el CDG extract

```bash
# PT
python -X utf8 -m tools.db.backfill ar_pt

# TRI (dividendos + cuotas + VR contable)
# → ya estaba implementado en backfill_dividendos y ingest_cdg_extract_tri
python -X utf8 -m tools.db.backfill dividendos

# Apoquindo ← recién implementado (2026-06-15)
python -X utf8 -m tools.db.backfill ar_apo
```

**Código**: `tools/db/ingest_cdg_extract.py`
- `ingest_ar_pt(excel_path)` → persiste PT
- `ingest_ar_apo(excel_path)` → persiste Apo
- `ingest_cdg_extract_tri(excel_path)` → persiste TRI (función más antigua)

---

## Fuente 2 — EEFF PDFs → `raw_eeff_line`

Esta tabla contiene TODAS las cuentas contables de los estados financieros (ESF, ER, ECP, EFE, Notas).
**Una fila = una cuenta en un período.**

### Schema `raw_eeff_line`

```
fondo_key      TEXT   → 'PT', 'TRI', 'APO'
periodo        TEXT   → 'YYYY-MM-DD' (fecha de cierre del estado)
cuenta_codigo  TEXT   → código numérico o None
cuenta_nombre  TEXT   → nombre exacto de la cuenta
monto_clp      REAL   → monto en CLP (ya convertido si el PDF reporta M$)
monto_uf       REAL   → monto en UF si se reporta, None si no
source_file    TEXT   → nombre del PDF original
file_hash      TEXT   → SHA256 del PDF (idempotencia)
source_sheet   TEXT   → sección: 'ESF', 'ER', 'ECP', 'EFE', 'NOTA_1', etc.
ingest_run_id  INTEGER
```

### Proceso de ingesta EEFF (2 variantes)

#### Variante A — Gemini automático (PDFs en servidor)

```bash
# 1. Convertir PDF a Markdown con MarkItDown
python -m markitdown "ruta/al/EEFF.pdf" > work/eeff_ingesta/APO/md/EEFF_APO_202512.md
# (copiar también el PDF a work/eeff_ingesta/APO/pdf/)

# 2. Ingestar con Gemini
python -X utf8 scripts/ingest_eeff.py --fondo APO --file work/eeff_ingesta/APO/md/EEFF_APO_202512.md

# 3. Procesar todos los MD de un fondo de una vez
python -X utf8 scripts/ingest_eeff.py --fondo APO --all
```

El script detecta el PDF correspondiente al MD (mismo nombre, extensión .pdf).
Usa Gemini 2.5 Flash para extraer las líneas y las guarda en `raw_eeff_line`.
Guarda el JSON intermediario en `work/eeff_ingesta/APO/json/` para revisión.

#### Variante B — JSON manual (ChatGPT u otro LLM externo)

Cuando los PDFs no están disponibles en local o Gemini falla, se puede usar ChatGPT:

1. Abrir el PDF en ChatGPT y pedir la extracción usando el **prompt del sistema** de `scripts/ingest_eeff.py` (variable `SYSTEM_PROMPT`).
2. Guardar el JSON resultante en `work/eeff_ingesta/APO/json/EEFF_APO_YYYYMM.json`
3. Ingestar:
```bash
python scripts/ingest_from_json.py --fondo APO --json work/eeff_ingesta/APO/json/EEFF_APO_202512.json
```

### Prompt exacto para extraer EEFF con ChatGPT

```
Eres un experto en EEFF de fondos de inversión chilenos (CMF).
Recibirás el texto de un PDF de EEFF. Extrae TODAS las cuentas con sus montos.

Devuelve SOLO JSON válido con esta estructura:
{
  "periodos_reportados": ["YYYY-MM-DD"],
  "lineas": [
    {
      "section": "ESF|ER|ECP|EFE|NOTA_<n>|ANEXO_<letra>",
      "cuenta_codigo": "string opcional",
      "cuenta_nombre": "nombre exacto de la cuenta",
      "subgrupo": "Activo corriente, Pasivo no corriente, Patrimonio, etc.",
      "periodo": "YYYY-MM-DD",
      "monto_clp": número en pesos (si dice 'M$', multiplica por 1000; si dice 'MM$', por 1000000),
      "monto_uf": número en UF si se reporta, null si no
    }
  ]
}

Reglas:
- ESF = Estado de Situación Financiera
- ER = Estado de Resultados Integrales
- ECP = Estado de Cambios en el Patrimonio
- EFE = Estado de Flujos de Efectivo
- Una línea por (cuenta, periodo). Si el estado tiene 2 columnas (año actual + año anterior), genera 2 líneas.
- Para notas con tablas, incluir cada fila como section="NOTA_<n>"
- Negativos: paréntesis = negativo
- Omitir encabezados, índices y párrafos narrativos sin monto
```

### Cuentas clave que DEBEN aparecer en el JSON

Para que los KPIs derivados funcionen, necesitamos al menos:

**ESF (Balance)**:
- `Total Activos` / `Total de activos`
- `Inversiones en propiedades` / `Inversiones inmobiliarias` / `Propiedades de inversión`
- `Préstamos bancarios` / `Obligaciones con bancos`
- `Total Pasivos`
- `Total Patrimonio` / `Patrimonio neto`

**ER (Resultados)**:
- `Ingresos por arrendamiento` / `Rentas de arrendamiento`
- `Gastos de administración` / `Costos de administración`
- `Resultado del período` / `Ganancia (pérdida) del período`

**ECP (Cambios en Patrimonio)**:
- `Patrimonio al cierre del período`
- `Dividendos distribuidos` / `Distribuciones a partícipes`
- `Suscripciones de cuotas` / `Aportes de capital`

**EFE (Flujos de Efectivo)**:
- `Flujos de actividades operativas`
- `Flujos de actividades de inversión`
- `Flujos de actividades de financiamiento`

---

## Estado actual por fondo (2026-06-15)

### TRI ✅ Completo

| Tabla | Filas | Rango |
|---|---|---|
| `raw_valor_cuota_contable_line` (fondo_key='TRI') | 462 | 2017-12 → 2026-03 |
| `raw_dividendo_line` (fondo_key='TRI') | 167 | 2018-04 → 2025-12 |
| `raw_cuota_en_circulacion_line` (fondo_key='TRI') | 153 | — |
| `raw_eeff_line` (fondo_key='TRI') | ~1.000+ | — |
| `raw_valor_cuota_bursatil_line` (3 nemos) | 25/nemo | 2024-05 → 2026-05 |

### PT ✅ Completo (EEFF histórico parcial)

| Tabla | Filas | Rango | Notas |
|---|---|---|---|
| `raw_eeff_line` (fondo_key='PT') | 4.523 | 2017 → 2025-12 | PDFs 2017-2019 vía Gemini; 2020-2025 vía ChatGPT manual |
| `raw_valor_cuota_contable_line` (fondo_key='PT') | 33 | 2017-12 → 2025-12 | VR Contable trimestral del CDG extract |
| `raw_dividendo_line` (fondo_key='PT') | 27 | — | CDG extract |
| `raw_cuota_en_circulacion_line` (fondo_key='PT') | 33 | — | CDG extract |
| `raw_valor_cuota_bursatil_line` (incluye col `patrimonio_bursatil_uf`) | 506 | — | CDG extract + LarrainVial |

### Apoquindo 🟡 En progreso (2026-06-15)

| Tabla | Filas | Rango | Estado |
|---|---|---|---|
| `raw_valor_cuota_contable_line` (fondo_key='Apo') | **28** | 2019-03 → 2025-12 | ✅ CDG extract (trimestral) |
| `raw_cuota_en_circulacion_line` (fondo_key='Apo') | **28** | 2019-03 → 2025-12 | ✅ CDG extract |
| `raw_dividendo_line` (fondo_key='Apo') | **12** | 2019-12 → 2022-10 | ✅ 6 dividendos + 6 disminuciones |
| `raw_eeff_line` (fondo_key='APO') | **0** | — | ❌ **Pendiente** |
| `derived_kpi` dividendo_por_cuota Apo | 6 | 2019-12 → 2022-10 | ✅ (de backfill_dividendos anterior) |
| `derived_kpi` valor_cuota_libro Apo | 1 | 2025-12 | Parcial (solo último) |

#### Lo que falta para Apoquindo

1. **EEFF PDFs → `raw_eeff_line` (fondo_key='APO')**

   PDFs disponibles localmente:
   - `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Fondos\Rentas Apoquindo\EEFF\2025\4T\Toesca Rentas Inmobiliarias Apoquindo 2025 12 con Opinión.pdf`
   
   PDFs históricos 2019-2024: **hay que conseguirlos** (revisar SharePoint Fondos/Rentas Apoquindo o correos). Una vez disponibles, el flujo es idéntico al de PT.

2. **Flujo para el PDF disponible (2025-12)**:

```bash
# Paso 1: convertir a MD
python -m markitdown "C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondos/Rentas Apoquindo/EEFF/2025/4T/Toesca Rentas Inmobiliarias Apoquindo 2025 12 con Opinión.pdf" > work/eeff_ingesta/APO/md/EEFF_APO_202512.md

# Copiar el PDF al directorio de trabajo
copy "C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondos/Rentas Apoquindo/EEFF/2025/4T/Toesca Rentas Inmobiliarias Apoquindo 2025 12 con Opinión.pdf" work/eeff_ingesta/APO/pdf/EEFF_APO_202512.pdf

# Paso 2: ingestar con Gemini
python -X utf8 scripts/ingest_eeff.py --fondo APO --file work/eeff_ingesta/APO/md/EEFF_APO_202512.md
```

3. **Para PDFs históricos (2019-2024) via ChatGPT**:
   - Subir el PDF a ChatGPT con el prompt de extracción (ver sección anterior)
   - Guardar JSON en `work/eeff_ingesta/APO/json/EEFF_APO_YYYYMM.json`
   - `python scripts/ingest_from_json.py --fondo APO --json work/eeff_ingesta/APO/json/EEFF_APO_YYYYMM.json`

---

## Verificar estado DB

```python
import sqlite3
conn = sqlite3.connect('memory/agente_toesca_v2.db')

# Estado completo por fondo
for fondo in ['PT', 'TRI', 'APO', 'Apo']:
    n = conn.execute(
        "SELECT COUNT(*), MIN(periodo), MAX(periodo) FROM raw_eeff_line WHERE fondo_key=?", (fondo,)
    ).fetchone()
    print(f"raw_eeff_line [{fondo}]: {n}")

# VR Contable
for fondo in ['PT', 'TRI', 'Apo']:
    n = conn.execute(
        "SELECT COUNT(*), MIN(fecha), MAX(fecha) FROM raw_valor_cuota_contable_line WHERE fondo_key=?", (fondo,)
    ).fetchone()
    print(f"raw_valor_cuota_contable_line [{fondo}]: {n}")

# Dividendos
for r in conn.execute(
    "SELECT fondo_key, tipo, COUNT(*), MIN(fecha_pago), MAX(fecha_pago) FROM raw_dividendo_line GROUP BY fondo_key, tipo"
).fetchall():
    print(f"raw_dividendo_line: {r}")

conn.close()
```

---

## Comandos backfill completo

```bash
# Solo Apoquindo (CDG extract — YA FUNCIONA)
python -X utf8 -m tools.db.backfill ar_apo

# Solo PT (CDG extract)
python -X utf8 -m tools.db.backfill ar_pt

# Solo EEFF de un fondo (Gemini, requiere MDs en work/eeff_ingesta/<FONDO>/md/)
python -X utf8 scripts/ingest_eeff.py --fondo APO --all

# Ingestar JSON manual (ChatGPT)
python scripts/ingest_from_json.py --fondo APO --json work/eeff_ingesta/APO/json/EEFF_APO_202412.json

# Todo lo demás (NOI, vacancia, UF, precios, rent roll, etc.)
python -X utf8 -m tools.db.backfill
```

---

## Idempotencia

Todos los scripts son seguros para correr N veces:
- `raw_valor_cuota_contable_line`: `UNIQUE(nemotecnico, fecha, tipo, file_hash)` → `INSERT OR IGNORE`
- `raw_cuota_en_circulacion_line`: `UNIQUE(nemotecnico, fecha, file_hash)` → `INSERT OR IGNORE`
- `raw_dividendo_line`: sin UNIQUE; guarda por `(fondo_key, file_hash)` antes de insertar
- `raw_eeff_line`: verifica `file_hash` antes de procesar el PDF

---

## Paths clave

```
work/eeff_ingesta/
  APO/
    pdf/   ← PDFs de EEFF Apoquindo (copia local)
    md/    ← conversión MarkItDown (.md) de cada PDF
    json/  ← JSON extraído por Gemini o ChatGPT (para auditoría + ingest_from_json.py)
  PT/
    pdf/   ← PDFs PT
    md/    ← MDs PT
    json/  ← JSONs PT
  TRI/
    cdg_extract.xlsx  ← CDG extract liviano (~1MB); fuente para PT, TRI, Apo

SharePoint (sincronizado local):
  C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\
    Fondos\Rentas Apoquindo\EEFF\  ← PDFs Apoquindo (solo 2025/4T disponible)
    Fondos\Rentas PT\EEFF\         ← PDFs PT históricos
    Fondos\Rentas TRI\EEFF\        ← PDFs TRI

DB:  memory/agente_toesca_v2.db
```

---

## Archivos de código relevantes

| Archivo | Función |
|---|---|
| `tools/db/backfill.py` | Punto de entrada para todos los backfills (`python -m tools.db.backfill <dominio>`) |
| `tools/db/ingest_cdg_extract.py` | `ingest_ar_pt`, `ingest_ar_apo`, `ingest_cdg_extract_tri` |
| `scripts/ingest_eeff.py` | Extracción de EEFF PDFs con Gemini → `raw_eeff_line` |
| `scripts/ingest_from_json.py` | Persistir JSON manual (ChatGPT) → `raw_eeff_line` |
| `tools/db/migrations/` | DDL de todas las tablas |
| `tools/db/repo_*.py` | Funciones de lectura de la DB (nunca SQL crudo fuera de aquí) |
