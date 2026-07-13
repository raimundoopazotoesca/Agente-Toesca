# AGENTS.md — Automation Agent (Toesca)

Eres un agente de código. Este proyecto mantiene `memory/agente_toesca_v2.db` (SQLite) como fuente única de datos de los fondos inmobiliarios Toesca (PT, TRI, Apoquindo).

**Memoria larga para Codex**: `CODEX.md` ← leer al inicio de sesiones largas o antes de continuar trabajo dejado por Claude.

**Guía detallada de poblar la DB por fondo**: `docs/db-poblar-fondos.md` ← leer antes de tocar cualquier script de ingesta.

---

## Contexto actual verificado por Codex (2026-07-13)

- La DB consultada reporta `schema_version=46`; existe migración 047 en repo, verificar antes de aplicar.
- `raw_eeff_line` ya tiene datos para `APO` (18.009 filas, 2019-03 → 2026-03). La instrucción antigua que decía `0 filas` está obsoleta.
- `raw_valor_cuota_contable` tiene `Apo` y `APO`; para Apoquindo usar filtros robustos (`UPPER(fondo_key)='APO'`) cuando corresponda.
- Tablas snapshot/evento ya no usan `_line` como tabla real (`raw_dividendo`, `raw_valor_cuota_contable`, etc.); existen vistas legacy con `_line`.
- Las ingestas ER recientes de Apo/PT guardan valores UF en `raw_er_activo_line.monto_clp` por convención heredada. No "corregir" sin revisar dependencias.
- Ultimos logs importantes están en `wiki/log.md` (2026-07-09 y 2026-07-13).

---

## Reglas irrompibles

1. **DB = `memory/agente_toesca_v2.db`** (no `memory/agente_toesca.db` ni v1).
2. **Nunca leer el CDG completo** (`*Control De Gestión*.xlsx`, 14 MB). Usar `work/eeff_ingesta/TRI/cdg_extract.xlsx`.
3. **Machalí EXCLUIDO** del portfolio. No ingesta, no cálculos.
4. **fondo_key**: `PT`, `TRI`, `Apo` (nunca "A&R PT", "Rentas Apoquindo", etc.).
5. **fondo_key en raw_eeff_line**: usar `APO` en mayúsculas para `scripts/ingest_eeff.py --fondo APO`; la DB también puede tener filas legacy `Apo`, verificar.
6. **Idempotencia**: todos los inserts son seguros de repetir. Verificar siempre por `file_hash`.
7. **Siempre `python -X utf8`** para evitar problemas con consola cp1252 en Windows.
8. **DB primero** para consultas de datos; abrir Excel solo si la DB no tiene cobertura o se está ingestado/verificando fuente.
9. **No inventar resultados**: si no se ejecutó una consulta/herramienta, no afirmar que se verificó.

---

## Verificar estado rápido

```bash
python -X utf8 -c "
import sqlite3; c=sqlite3.connect('memory/agente_toesca_v2.db')
print('schema_version:', c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0])
print('EEFF:', c.execute(\"SELECT fondo_key, COUNT(*), MIN(periodo), MAX(periodo) FROM raw_eeff_line GROUP BY fondo_key\").fetchall())
print('VR Contable:', c.execute(\"SELECT fondo_key, COUNT(*), MIN(fecha), MAX(fecha) FROM raw_valor_cuota_contable GROUP BY fondo_key\").fetchall())
print('Dividendos:', c.execute(\"SELECT fondo_key, tipo, COUNT(*), MIN(fecha_pago), MAX(fecha_pago) FROM raw_dividendo GROUP BY fondo_key,tipo\").fetchall())
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
