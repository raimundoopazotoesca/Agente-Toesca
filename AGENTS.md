# AGENTS.md — Automation Agent (Toesca)

Eres un agente de código. Este proyecto mantiene `memory/agente_toesca_v2.db` (SQLite) como fuente única de datos de los fondos inmobiliarios Toesca (PT, TRI, Apoquindo).

**Guía detallada de poblar la DB por fondo**: `docs/db-poblar-fondos.md` ← leer antes de tocar cualquier script de ingesta.

---

## Contexto inmediato (tarea activa)

### Fondo Apoquindo — estado 2026-06-15

**Ya hecho:**
- `raw_valor_cuota_line` (fondo_key='Apo'): 28 filas, 2019-03 → 2025-12 (VR Contable trimestral)
- `raw_cuota_en_circulacion_line` (fondo_key='Apo'): 28 filas
- `raw_dividendo_line` (fondo_key='Apo'): 12 filas (6 dividendos + 6 disminuciones, 2019-12 → 2022-10)
- Fuente: `work/eeff_ingesta/TRI/cdg_extract.xlsx`, hoja `A&R Apoquindo`, función `ingest_ar_apo()`

**Pendiente:**
- `raw_eeff_line` (fondo_key='APO'): **0 filas** — los EEFF PDFs aún no están ingestados.

### PDF disponible hoy

```
C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\
  Fondos\Rentas Apoquindo\EEFF\2025\4T\
    Toesca Rentas Inmobiliarias Apoquindo 2025 12 con Opinión.pdf
```

Los PDFs 2019-2024 no están en local todavía — hay que conseguirlos o usar ChatGPT con ellos.

### Cómo ingestar el PDF 2025-12

```bash
# Paso 1: convertir a MD (MarkItDown está instalado: pip install markitdown[all])
python -m markitdown "C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondos/Rentas Apoquindo/EEFF/2025/4T/Toesca Rentas Inmobiliarias Apoquindo 2025 12 con Opinión.pdf" > work/eeff_ingesta/APO/md/EEFF_APO_202512.md

# Copiar PDF al directorio de trabajo (IMPORTANTE: el script lo necesita para el file_hash)
copy "C:/Users/raimundo.opazo/OneDrive - Toesca/Inmobiliario Toesca - Documentos/Fondos/Rentas Apoquindo/EEFF/2025/4T/Toesca Rentas Inmobiliarias Apoquindo 2025 12 con Opinión.pdf" work/eeff_ingesta/APO/pdf/EEFF_APO_202512.pdf

# Paso 2: extraer con Gemini y persistir en raw_eeff_line
python -X utf8 scripts/ingest_eeff.py --fondo APO --file work/eeff_ingesta/APO/md/EEFF_APO_202512.md
```

### Cómo ingestar PDFs históricos (vía JSON manual)

Si usas ChatGPT para extraer el PDF, guarda el JSON en:
`work/eeff_ingesta/APO/json/EEFF_APO_<YYYYMM>.json`

El JSON debe tener este formato (ver prompt exacto en `docs/db-poblar-fondos.md`):
```json
{
  "periodos_reportados": ["2024-12-31"],
  "lineas": [
    {"section": "ESF", "cuenta_nombre": "Total Activos", "periodo": "2024-12-31", "monto_clp": 123456789, "monto_uf": null},
    ...
  ]
}
```

Luego:
```bash
python scripts/ingest_from_json.py --fondo APO --json work/eeff_ingesta/APO/json/EEFF_APO_202412.json
```

---

## Reglas irrompibles

1. **DB = `memory/agente_toesca_v2.db`** (no la v1, ya eliminada).
2. **Nunca leer el CDG completo** (`*Control De Gestión*.xlsx`, 14 MB). Usar `work/eeff_ingesta/TRI/cdg_extract.xlsx`.
3. **Machalí EXCLUIDO** del portfolio. No ingesta, no cálculos.
4. **fondo_key**: `PT`, `TRI`, `Apo` (nunca "A&R PT", "Rentas Apoquindo", etc.).
5. **fondo_key en raw_eeff_line**: usar `APO` en mayúsculas (el script `ingest_eeff.py` pide `--fondo APO`).
6. **Idempotencia**: todos los inserts son seguros de repetir. Verificar siempre por `file_hash`.
7. **Siempre `python -X utf8`** para evitar problemas con consola cp1252 en Windows.

---

## Verificar estado rápido

```bash
python -X utf8 -c "
import sqlite3; conn = sqlite3.connect('memory/agente_toesca_v2.db')
for t,fk in [('raw_eeff_line','APO'),('raw_valor_cuota_line','Apo'),('raw_dividendo_line','Apo')]:
    r = conn.execute('SELECT COUNT(*), MIN(periodo if period is not null else fecha_pago), MAX(periodo if period is not null else fecha_pago) FROM '+t+' WHERE fondo_key=?',(fk,)).fetchone()
    print(t,'['+fk+']:', r)
conn.close()
"
# O más simple:
python -X utf8 -c "
import sqlite3; c=sqlite3.connect('memory/agente_toesca_v2.db')
print('EEFF APO:', c.execute(\"SELECT COUNT(*) FROM raw_eeff_line WHERE fondo_key='APO'\").fetchone()[0])
print('VR Contable Apo:', c.execute(\"SELECT COUNT(*), MIN(fecha), MAX(fecha) FROM raw_valor_cuota_line WHERE fondo_key='Apo'\").fetchone())
print('Dividendos Apo:', c.execute(\"SELECT tipo, COUNT(*) FROM raw_dividendo_line WHERE fondo_key='Apo' GROUP BY tipo\").fetchall())
"
```

---

## Stack técnico

- Python 3.11+, SQLite, openpyxl (read_only para archivos grandes), MarkItDown, Gemini 2.5 Flash
- `python -X utf8` siempre (Windows cp1252)
- No usar `ws.cell(row, col)` en modo read_only (O(n)); usar `iter_rows(values_only=True)` una vez
- Rutas con forward slashes o raw strings en Python (evitar `\U`, `\n`, etc.)

## Archivos clave

```
tools/db/backfill.py               ← orquestador de todos los backfills
tools/db/ingest_cdg_extract.py     ← ingest_ar_pt, ingest_ar_apo, ingest_cdg_extract_tri
scripts/ingest_eeff.py             ← EEFF PDFs → raw_eeff_line (usa Gemini)
scripts/ingest_from_json.py        ← JSON manual → raw_eeff_line
tools/db/migrations/               ← DDL de todas las tablas
docs/db-poblar-fondos.md           ← guía detallada de todo el proceso
```
