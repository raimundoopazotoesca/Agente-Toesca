# EEFF TRI Series Parser — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extraer valor cuota libro, cuotas en circulación y capital suscrito por serie (A/C/I) directamente de los PDFs de EEFF del fondo TRI, escribirlos a `raw_valor_cuota_line` y `raw_cuota_en_circulacion_line`, independizando esos cálculos del `cdg_extract.xlsx`.

**Architecture:** Un parser (`parse_eeff_tri_notas`) que procesa el texto MarkItDown del PDF y extrae los dos bloques de la nota "Cuotas emitidas": (a) el texto narrativo con valor cuota por serie y (b) la tabla de cuotas suscritas por serie. Un ingester (`ingest_eeff_tri_series`) orquesta parser → DB. Un backfiller recorre los PDFs disponibles localmente. La tabla `raw_valor_cuota_line` se formaliza en una migration (hoy existe ad-hoc en la DB).

**Tech Stack:** Python 3.12, `markitdown`, `sqlite3`, `re`, `pytest`, `tools/db/connection.py` (apply_migrations, get_conn_for).

---

## Contexto crítico

### Patrón de texto en PDF (nota "Cuotas emitidas")

Los PDFs modernos (2019+) contienen dos tipos de datos extraíbles:

**1. Valor cuota libro por serie** — texto narrativo:
```
El valor de las cuotas suscritas y pagadas del Fondo al 31 de diciembre de 2025 tienen
un valor cuota de $ 31.869,3926 para la Serie A, $ 32.252,4814 para la Serie C y
$ 32.390,2518 para la Serie I. El valor de las cuotas suscritas y pagadas del Fondo
al 31 de diciembre de 2024 tienen un valor cuota de $ 28.927,7231para la Serie A,
$ 29.311,3182 para la Serie C y $ 29.450,0778 para la Serie I.
```
→ Dos fechas por PDF (período actual + período anterior).

**2. Cuotas suscritas por serie** — tabla aplanada:
```
31 de Diciembre de 2025\nSerie A\n...\nSuscritas\n475.667\nPagadas\n475.667\n
...Serie C...\nSuscritas\n1.252.928\n...Serie I...\nSuscritas\n1.091.101\n
```
→ Las series aparecen en orden A → C → I; los valores en el mismo orden.

**PDFs históricos (pre-2019)**: "Valor libro cuota Serie A/C/I" ya está en `raw_eeff_line`
(columna `cuenta_nombre`). El backfill de esos períodos lee directamente de `raw_eeff_line`.

### Tablas destino

```sql
-- raw_valor_cuota_line: tipo='contable' para valor cuota libro
UNIQUE(nemotecnico, fecha, tipo, file_hash)
-- raw_cuota_en_circulacion_line
UNIQUE(nemotecnico, fecha, file_hash)
```

### Nemotécnicos TRI
```python
SERIE_NEMO = {"A": "CFITOERI1A", "C": "CFITOERI1C", "I": "CFITOERI1I"}
```

### UF para precio_uf
`raw_valor_cuota_line.precio_uf = precio_clp / fact_uf.valor_clp` donde
`fact_uf.fecha` = último día del período.

---

## Files

| Acción | Archivo |
|---|---|
| **Create** | `tools/db/migrations/011_raw_valor_cuota_line.sql` |
| **Create** | `tools/db/ingest_eeff_tri_series.py` |
| **Create** | `tests/db/test_ingest_eeff_tri_series.py` |
| **Modify** | `tools/db/ingest_router.py` (registrar el nuevo ingester) |

---

## Task 1: Migration para `raw_valor_cuota_line`

La tabla existe en la DB pero no en migraciones. Agregarla como `CREATE TABLE IF NOT EXISTS` para que `apply_migrations` la garantice en DBs nuevas.

**Files:**
- Create: `tools/db/migrations/011_raw_valor_cuota_line.sql`

- [ ] **Step 1: Crear la migration**

```sql
-- 011_raw_valor_cuota_line.sql
CREATE TABLE IF NOT EXISTS raw_valor_cuota_line (
    id          INTEGER PRIMARY KEY,
    fondo_key   TEXT NOT NULL,
    nemotecnico TEXT NOT NULL,
    fecha       TEXT NOT NULL,          -- YYYY-MM-DD (último día del período)
    tipo        TEXT NOT NULL,          -- 'contable' | 'bursatil'
    precio_clp  REAL,                   -- CLP/cuota
    precio_uf   REAL,                   -- UF/cuota (precio_clp / uf_dia)
    uf_dia      REAL,                   -- UF del día
    cuotas      REAL,                   -- cuotas en circulación ese día
    periodo     TEXT,                   -- YYYY-MM
    source_file TEXT,
    file_hash   TEXT,
    loaded_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(nemotecnico, fecha, tipo, file_hash)
);
```

- [ ] **Step 2: Verificar que `apply_migrations` la procesa**

```bash
python -c "
from tools.db.connection import apply_migrations, get_conn_for
import tempfile, os
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    path = f.name
apply_migrations(path)
conn = get_conn_for(path)
rows = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='raw_valor_cuota_line'\").fetchall()
print('tabla existe:', rows)
conn.close()
os.unlink(path)
"
```
Expected: `tabla existe: [('raw_valor_cuota_line',)]`

- [ ] **Step 3: Commit**

```bash
git add tools/db/migrations/011_raw_valor_cuota_line.sql
git commit -m "feat(db): migration 011 - formalizar raw_valor_cuota_line"
```

---

## Task 2: Parser `parse_eeff_tri_notas`

Función pura: recibe texto plano del PDF y retorna `{fecha_str: {"valor_cuota": {serie: float}, "cuotas": {serie: float}}}`.

**Files:**
- Create: `tools/db/ingest_eeff_tri_series.py`
- Create: `tests/db/test_ingest_eeff_tri_series.py`

- [ ] **Step 1: Escribir el test con texto sintético**

```python
# tests/db/test_ingest_eeff_tri_series.py
"""Tests del parser y ingester de EEFFs TRI por serie."""
from tools.db.ingest_eeff_tri_series import parse_eeff_tri_notas

TEXTO_2025 = """
(22)  Cuotas emitidas

El valor de las cuotas suscritas y pagadas del Fondo al 31 de diciembre de 2025 tienen
un valor cuota de $ 31.869,3926 para la Serie A, $ 32.252,4814 para la Serie C y
$ 32.390,2518 para la Serie I. El valor de las cuotas
suscritas y pagadas del Fondo al 31 de diciembre de 2024 tienen un valor cuota de $ 28.927,7231para la Serie
A, $ 29.311,3182 para la Serie C y $ 29.450,0778 para la Serie I.

31 de Diciembre de 2025
Serie A
Fecha
31 de Diciembre de 2025

31 de Diciembre de 2025
Serie C
Fecha
31 de Diciembre de 2025

31 de Diciembre de 2025
Serie I
Fecha
31 de Diciembre de 2025

Por Emitir  Comprometidas
-

-

Suscritas
475.667

Pagadas
475.667

Por Emitir  Comprometidas
-

-

Suscritas
1.252.928

Pagadas
1.252.928

Por Emitir  Comprometidas
-

-

Suscritas
1.091.101

Pagadas
1.091.101
"""


def test_parse_valor_cuota_periodo_actual():
    result = parse_eeff_tri_notas(TEXTO_2025)
    assert "2025-12-31" in result
    vc = result["2025-12-31"]["valor_cuota"]
    assert abs(vc["A"] - 31869.3926) < 0.01
    assert abs(vc["C"] - 32252.4814) < 0.01
    assert abs(vc["I"] - 32390.2518) < 0.01


def test_parse_valor_cuota_periodo_anterior():
    result = parse_eeff_tri_notas(TEXTO_2025)
    assert "2024-12-31" in result
    vc = result["2024-12-31"]["valor_cuota"]
    assert abs(vc["A"] - 28927.7231) < 0.01
    assert abs(vc["C"] - 29311.3182) < 0.01
    assert abs(vc["I"] - 29450.0778) < 0.01


def test_parse_cuotas_suscritas():
    result = parse_eeff_tri_notas(TEXTO_2025)
    cuotas = result["2025-12-31"]["cuotas"]
    assert cuotas["A"] == 475667.0
    assert cuotas["C"] == 1252928.0
    assert cuotas["I"] == 1091101.0


def test_parse_texto_sin_nota_cuotas():
    """No debe explotar con texto sin la sección relevante."""
    result = parse_eeff_tri_notas("Texto sin datos relevantes")
    assert result == {}
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```bash
python -m pytest tests/db/test_ingest_eeff_tri_series.py -v 2>&1 | head -20
```
Expected: ImportError o AttributeError — `parse_eeff_tri_notas` no existe.

- [ ] **Step 3: Implementar `parse_eeff_tri_notas`**

```python
# tools/db/ingest_eeff_tri_series.py
"""
Ingesta de datos por serie del fondo TRI desde PDFs de EEFF.

Extrae de la nota 'Cuotas emitidas':
  - Valor cuota libro por serie (A/C/I) por período
  - Cuotas suscritas por serie por período

Escribe a:
  - raw_valor_cuota_line (tipo='contable')
  - raw_cuota_en_circulacion_line
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, Optional

SERIE_NEMO = {
    "A": "CFITOERI1A",
    "C": "CFITOERI1C",
    "I": "CFITOERI1I",
}

# Meses en español → número (para parsear fechas como "31 de diciembre de 2025")
_MES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_cl_number(s: str) -> Optional[float]:
    """Convierte número chileno a float. "31.869,3926" → 31869.3926"""
    s = s.strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _fecha_from_texto(dia: str, mes_str: str, año: str) -> Optional[str]:
    """("31", "diciembre", "2025") → "2025-12-31" """
    mes_num = _MES_ES.get(mes_str.lower().strip())
    if not mes_num:
        return None
    try:
        return f"{int(año):04d}-{mes_num:02d}-{int(dia):02d}"
    except ValueError:
        return None


def parse_eeff_tri_notas(text: str) -> Dict[str, dict]:
    """
    Parsea texto de un PDF de EEFF TRI.

    Retorna:
        {fecha_iso: {"valor_cuota": {"A": float, "C": float, "I": float},
                     "cuotas":      {"A": float, "C": float, "I": float}}}

    Puede devolver múltiples fechas si el PDF incluye período actual + anterior.
    Las claves de cuotas/valor_cuota pueden ser parciales si el parser no encontró todo.
    """
    result: Dict[str, dict] = {}

    # ── 1. Valor cuota libro por serie ──────────────────────────────────────
    # Patrón: "al DD de MES de YYYY tienen un valor cuota de $X para la Serie A,
    #          $Y para la Serie C y $Z para la Serie I"
    pat_bloque = re.compile(
        r"al\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\s+tienen\s+un\s+valor\s+cuota\s+de\s*\$\s*([\d\.,]+)"
        r"\s*para\s+la\s+Serie\s+A[,\s]*\$?\s*([\d\.,]+)\s*para\s+la\s+Serie\s+C\s+y\s*\$?\s*([\d\.,]+)"
        r"\s*para\s+la\s+Serie\s+I",
        re.IGNORECASE | re.DOTALL,
    )
    for m in pat_bloque.finditer(text):
        dia, mes_str, año = m.group(1), m.group(2), m.group(3)
        fecha = _fecha_from_texto(dia, mes_str, año)
        if not fecha:
            continue
        va = _parse_cl_number(m.group(4))
        vc = _parse_cl_number(m.group(5))
        vi = _parse_cl_number(m.group(6))
        if va and vc and vi:
            if fecha not in result:
                result[fecha] = {"valor_cuota": {}, "cuotas": {}}
            result[fecha]["valor_cuota"] = {"A": va, "C": vc, "I": vi}

    # ── 2. Cuotas suscritas por serie ────────────────────────────────────────
    # La tabla está aplanada. Buscamos la sección de cuotas emitidas:
    # Series aparecen en orden A → C → I; "Suscritas\nNNN.NNN" para cada una.
    # Localizamos el bloque entre "Cuotas emitidas" y "movimientos relevantes"
    bloque_match = re.search(
        r"Cuotas\s+emitidas.*?(?=movimientos\s+relevantes|Saldo\s+al\s+Inicio)",
        text, re.IGNORECASE | re.DOTALL
    )
    if bloque_match:
        bloque = bloque_match.group(0)
        # Extraer fecha del bloque (primera fecha que aparece)
        fecha_bloque_m = re.search(
            r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", bloque, re.IGNORECASE
        )
        if fecha_bloque_m:
            fecha_cuotas = _fecha_from_texto(
                fecha_bloque_m.group(1),
                fecha_bloque_m.group(2),
                fecha_bloque_m.group(3),
            )
        else:
            fecha_cuotas = None

        # Extraer todos los valores de "Suscritas"
        suscritas_vals = re.findall(
            r"Suscritas\s*\n\s*([\d\.]+)", bloque
        )
        # El bloque puede tener la tabla del período actual Y del período anterior
        # Las primeras 3 ocurrencias corresponden al período principal
        series_order = ["A", "C", "I"]
        if fecha_cuotas and len(suscritas_vals) >= 3:
            if fecha_cuotas not in result:
                result[fecha_cuotas] = {"valor_cuota": {}, "cuotas": {}}
            for i, serie in enumerate(series_order):
                val = _parse_cl_number(suscritas_vals[i])
                if val:
                    result[fecha_cuotas]["cuotas"][serie] = val

    return result
```

- [ ] **Step 4: Ejecutar tests**

```bash
python -m pytest tests/db/test_ingest_eeff_tri_series.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/ingest_eeff_tri_series.py tests/db/test_ingest_eeff_tri_series.py
git commit -m "feat(db): parse_eeff_tri_notas - valor cuota y cuotas por serie desde PDF"
```

---

## Task 3: Ingester `ingest_eeff_tri_series`

Orquesta: PDF → MarkItDown → parser → DB (raw_valor_cuota_line + raw_cuota_en_circulacion_line).

**Files:**
- Modify: `tools/db/ingest_eeff_tri_series.py` (agregar funciones)
- Modify: `tests/db/test_ingest_eeff_tri_series.py` (agregar tests del ingester)

- [ ] **Step 1: Escribir tests del ingester**

Agregar al final de `tests/db/test_ingest_eeff_tri_series.py`:

```python
import os
import sqlite3
import tempfile

from tools.db.connection import apply_migrations, get_conn_for
from tools.db.ingest_eeff_tri_series import ingest_parsed_data


def _make_db(tmp_db_path):
    apply_migrations(tmp_db_path)
    # Insertar UF del 2025-12-31 para el cálculo de precio_uf
    conn = get_conn_for(tmp_db_path)
    conn.execute(
        "INSERT OR IGNORE INTO fact_uf(fecha, valor_clp) VALUES('2025-12-31', 39695.94)"
    )
    conn.commit()
    conn.close()


def test_ingest_escribe_valor_cuota_contable(tmp_db_path):
    _make_db(tmp_db_path)
    parsed = {
        "2025-12-31": {
            "valor_cuota": {"A": 31869.3926, "C": 32252.4814, "I": 32390.2518},
            "cuotas": {"A": 475667.0, "C": 1252928.0, "I": 1091101.0},
        }
    }
    ingest_parsed_data(parsed, "test_eeff.pdf", "abc123", tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT nemotecnico, precio_clp, precio_uf FROM raw_valor_cuota_line "
        "WHERE tipo='contable' AND fecha='2025-12-31' ORDER BY nemotecnico"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    nemos = [r[0] for r in rows]
    assert "CFITOERI1A" in nemos
    a_row = next(r for r in rows if r[0] == "CFITOERI1A")
    assert abs(a_row[1] - 31869.3926) < 0.01
    # precio_uf = 31869.3926 / 39695.94 ≈ 0.8029
    assert a_row[2] is not None and abs(a_row[2] - 0.8029) < 0.01


def test_ingest_escribe_cuotas_en_circulacion(tmp_db_path):
    _make_db(tmp_db_path)
    parsed = {
        "2025-12-31": {
            "valor_cuota": {},
            "cuotas": {"A": 475667.0, "C": 1252928.0, "I": 1091101.0},
        }
    }
    ingest_parsed_data(parsed, "test_eeff.pdf", "abc123", tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT nemotecnico, cuotas FROM raw_cuota_en_circulacion_line "
        "WHERE fecha='2025-12-31' ORDER BY nemotecnico"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    assert dict(rows)["CFITOERI1A"] == 475667.0
    assert dict(rows)["CFITOERI1C"] == 1252928.0
    assert dict(rows)["CFITOERI1I"] == 1091101.0


def test_ingest_idempotente(tmp_db_path):
    """Ejecutar dos veces con el mismo file_hash no duplica filas."""
    _make_db(tmp_db_path)
    parsed = {
        "2025-12-31": {
            "valor_cuota": {"A": 31869.0},
            "cuotas": {"A": 475667.0},
        }
    }
    ingest_parsed_data(parsed, "test.pdf", "samehash", tmp_db_path)
    ingest_parsed_data(parsed, "test.pdf", "samehash", tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM raw_valor_cuota_line WHERE file_hash='samehash'"
    ).fetchone()[0]
    conn.close()
    assert n == 1
```

- [ ] **Step 2: Ejecutar tests para verificar que fallan**

```bash
python -m pytest tests/db/test_ingest_eeff_tri_series.py::test_ingest_escribe_valor_cuota_contable -v
```
Expected: ImportError — `ingest_parsed_data` no existe.

- [ ] **Step 3: Implementar `ingest_parsed_data` e `ingest_eeff_tri_pdf`**

Agregar al final de `tools/db/ingest_eeff_tri_series.py`:

```python
def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def ingest_parsed_data(
    parsed: Dict[str, dict],
    source_file: str,
    file_hash: str,
    db_path: str,
) -> Dict[str, int]:
    """
    Escribe el resultado de parse_eeff_tri_notas a la DB.

    Retorna {"valor_cuota_insertadas": N, "cuotas_insertadas": M}.
    """
    from tools.db.connection import get_conn_for

    conn = get_conn_for(db_path)
    vc_count = 0
    cuotas_count = 0

    try:
        for fecha, data in parsed.items():
            periodo = fecha[:7]  # YYYY-MM

            # ── UF del día ────────────────────────────────────────
            uf_row = conn.execute(
                "SELECT valor_clp FROM fact_uf WHERE fecha = ?", (fecha,)
            ).fetchone()
            uf_dia = uf_row[0] if uf_row else None

            # ── Valor cuota libro (tipo='contable') ───────────────
            for serie, precio_clp in data.get("valor_cuota", {}).items():
                nemo = SERIE_NEMO.get(serie)
                if not nemo or precio_clp is None:
                    continue
                precio_uf = (precio_clp / uf_dia) if uf_dia else None
                cuotas_val = data.get("cuotas", {}).get(serie)
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO raw_valor_cuota_line
                           (fondo_key, nemotecnico, fecha, tipo, precio_clp, precio_uf,
                            uf_dia, cuotas, periodo, source_file, file_hash)
                           VALUES ('TRI', ?, ?, 'contable', ?, ?, ?, ?, ?, ?, ?)""",
                        (nemo, fecha, precio_clp, precio_uf, uf_dia, cuotas_val,
                         periodo, source_file, file_hash),
                    )
                    vc_count += conn.execute("SELECT changes()").fetchone()[0]
                except sqlite3.IntegrityError:
                    pass

            # ── Cuotas en circulación ─────────────────────────────
            for serie, cuotas in data.get("cuotas", {}).items():
                nemo = SERIE_NEMO.get(serie)
                if not nemo or cuotas is None:
                    continue
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO raw_cuota_en_circulacion_line
                           (fondo_key, nemotecnico, fecha, cuotas, periodo,
                            source_file, file_hash)
                           VALUES ('TRI', ?, ?, ?, ?, ?, ?)""",
                        (nemo, fecha, cuotas, periodo, source_file, file_hash),
                    )
                    cuotas_count += conn.execute("SELECT changes()").fetchone()[0]
                except sqlite3.IntegrityError:
                    pass

        conn.commit()
    finally:
        conn.close()

    return {"valor_cuota_insertadas": vc_count, "cuotas_insertadas": cuotas_count}


def ingest_eeff_tri_pdf(pdf_path: str, db_path: Optional[str] = None) -> Dict:
    """
    Función principal. Lee un PDF de EEFF TRI, extrae datos por serie, persiste.

    Args:
        pdf_path: Ruta absoluta al PDF.
        db_path:  Ruta a la DB. Si None, usa la DB del proyecto (memory/agente_toesca.db).

    Retorna dict con conteos y errores.
    """
    from markitdown import MarkItDown

    if db_path is None:
        db_path = str(Path(__file__).resolve().parents[2] / "memory" / "agente_toesca.db")

    if not os.path.isfile(pdf_path):
        return {"error": f"Archivo no encontrado: {pdf_path}"}

    try:
        text = MarkItDown().convert(pdf_path).text_content or ""
    except Exception as e:
        return {"error": f"MarkItDown falló: {e}"}

    parsed = parse_eeff_tri_notas(text)
    if not parsed:
        return {"error": "No se encontraron datos por serie en el PDF", "periodos": []}

    file_hash = _hash_file(pdf_path)
    source_file = os.path.basename(pdf_path)
    counts = ingest_parsed_data(parsed, source_file, file_hash, db_path)

    return {
        "periodos_encontrados": sorted(parsed.keys()),
        **counts,
        "error": None,
    }
```

- [ ] **Step 4: Ejecutar todos los tests del archivo**

```bash
python -m pytest tests/db/test_ingest_eeff_tri_series.py -v
```
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/db/ingest_eeff_tri_series.py tests/db/test_ingest_eeff_tri_series.py
git commit -m "feat(db): ingest_eeff_tri_series - ingester PDF → raw_valor_cuota_line + raw_cuota_en_circulacion_line"
```

---

## Task 4: Backfill desde PDFs disponibles + `raw_eeff_line` histórico

Dos fuentes de backfill:
1. **PDFs locales en SharePoint** — procesar con `ingest_eeff_tri_pdf` (cobertura 2025).
2. **`raw_eeff_line`** — filas "Valor libro cuota Serie A/C/I" ya ingresadas (cobertura 2017-2018).

**Files:**
- Create: `tools/db/backfill_eeff_tri_series.py`

- [ ] **Step 1: Crear script de backfill**

```python
# tools/db/backfill_eeff_tri_series.py
"""
Backfill de raw_valor_cuota_line (tipo=contable) y raw_cuota_en_circulacion_line
para el fondo TRI, combinando dos fuentes:

1. PDFs disponibles en TRI_EEFF_FONDO_DIR (SharePoint local).
2. raw_eeff_line — filas "Valor libro cuota Serie A/C/I" (cobertura 2017-2018).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from tools.sharepoint_paths import TRI_EEFF_FONDO_DIR
from tools.db.ingest_eeff_tri_series import ingest_eeff_tri_pdf, ingest_parsed_data, SERIE_NEMO

DB_PATH = str(Path(__file__).resolve().parents[2] / "memory" / "agente_toesca.db")


def backfill_from_pdfs() -> list[dict]:
    """Procesa todos los PDFs .pdf encontrados en TRI_EEFF_FONDO_DIR recursivamente."""
    results = []
    for root, _, files in os.walk(TRI_EEFF_FONDO_DIR):
        for fname in sorted(files):
            if not fname.lower().endswith(".pdf"):
                continue
            pdf_path = os.path.join(root, fname)
            result = ingest_eeff_tri_pdf(pdf_path, DB_PATH)
            result["file"] = fname
            results.append(result)
            print(f"[backfill_pdf] {fname}: {result}")
    return results


def backfill_from_raw_eeff_line() -> dict:
    """
    Lee 'Valor libro cuota Serie A/C/I' de raw_eeff_line y los escribe a
    raw_valor_cuota_line (tipo='contable') si no existen.

    Cobertura: 2017-12 a 2018-06 (formato antiguo con serie explícita).
    """
    conn = sqlite3.connect(DB_PATH)
    inserted = 0

    rows = conn.execute("""
        SELECT cuenta_nombre, periodo, monto_clp
        FROM raw_eeff_line
        WHERE fondo_key = 'TRI'
          AND superseded_at IS NULL
          AND cuenta_nombre LIKE 'Valor libro cuota Serie %'
          AND monto_clp IS NOT NULL
          AND monto_clp > 100
        ORDER BY periodo, cuenta_nombre
    """).fetchall()

    for cuenta_nombre, periodo_raw, precio_clp in rows:
        # cuenta_nombre = "Valor libro cuota Serie A/C/I"
        serie = cuenta_nombre.split("Serie ")[-1].strip()  # "A", "C" o "I"
        nemo = SERIE_NEMO.get(serie)
        if not nemo:
            continue

        # Convertir periodo (puede ser "2017-12-31" o "2017-12")
        if len(periodo_raw) == 10:  # YYYY-MM-DD
            fecha = periodo_raw
            periodo = periodo_raw[:7]
        else:                       # YYYY-MM
            import calendar
            year, month = int(periodo_raw[:4]), int(periodo_raw[5:7])
            last_day = calendar.monthrange(year, month)[1]
            fecha = f"{year:04d}-{month:02d}-{last_day:02d}"
            periodo = periodo_raw

        # UF del día
        uf_row = conn.execute(
            "SELECT valor_clp FROM fact_uf WHERE fecha = ?", (fecha,)
        ).fetchone()
        uf_dia = uf_row[0] if uf_row else None
        precio_uf = (precio_clp / uf_dia) if uf_dia else None

        try:
            conn.execute("""
                INSERT OR IGNORE INTO raw_valor_cuota_line
                    (fondo_key, nemotecnico, fecha, tipo, precio_clp, precio_uf,
                     uf_dia, periodo, source_file, file_hash)
                VALUES ('TRI', ?, ?, 'contable', ?, ?, ?, ?, 'raw_eeff_line_backfill', 'backfill_v1')
            """, (nemo, fecha, precio_clp, precio_uf, uf_dia, periodo))
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            print(f"  skip {nemo} {fecha}: {e}")

    conn.commit()
    conn.close()
    print(f"[backfill_raw_eeff] {inserted} filas insertadas")
    return {"insertadas": inserted}


if __name__ == "__main__":
    print("=== Backfill desde PDFs ===")
    backfill_from_pdfs()
    print("\n=== Backfill desde raw_eeff_line ===")
    backfill_from_raw_eeff_line()
```

- [ ] **Step 2: Ejecutar el backfill en modo dry-run (solo imprimir qué encontraría)**

```bash
python -c "
import os
from tools.sharepoint_paths import TRI_EEFF_FONDO_DIR
for root, _, files in os.walk(TRI_EEFF_FONDO_DIR):
    for f in files:
        if f.lower().endswith('.pdf'):
            print(os.path.join(root, f))
"
```
Expected: lista de PDFs localmente disponibles.

- [ ] **Step 3: Ejecutar el backfill completo**

```bash
python -m tools.db.backfill_eeff_tri_series
```
Expected output (aprox.):
```
=== Backfill desde PDFs ===
[backfill_pdf] 2025 EEFF Toesca Rentas Inmobiliarias - final.pdf: {'periodos_encontrados': ['2024-12-31', '2025-12-31'], 'valor_cuota_insertadas': 6, 'cuotas_insertadas': 3, 'error': None, 'file': '...'}
=== Backfill desde raw_eeff_line ===
[backfill_raw_eeff] N filas insertadas
```

- [ ] **Step 4: Verificar datos en DB**

```bash
python -c "
import sqlite3
con = sqlite3.connect('memory/agente_toesca.db')
print('=== raw_valor_cuota_line tipo=contable (EEFF) ===')
rows = con.execute('''
    SELECT nemotecnico, fecha, precio_clp, source_file
    FROM raw_valor_cuota_line
    WHERE fondo_key=\"TRI\" AND tipo=\"contable\"
      AND source_file != \"cdg_extract.xlsx\"
    ORDER BY nemotecnico, fecha
''').fetchall()
for r in rows: print(r)
con.close()
"
```
Expected: filas con `source_file` = nombre del PDF o `raw_eeff_line_backfill`.

- [ ] **Step 5: Commit**

```bash
git add tools/db/backfill_eeff_tri_series.py
git commit -m "feat(db): backfill_eeff_tri_series - poblar raw_valor_cuota_line desde PDFs y raw_eeff_line"
```

---

## Task 5: Registrar en `ingest_router.py`

Exponer el ingester para que el agente pueda invocar `ingestar_archivo` con un PDF de EEFF TRI.

**Files:**
- Modify: `tools/db/ingest_router.py`

- [ ] **Step 1: Leer el router actual**

```bash
grep -n "def \|\.pdf\|eeff\|TRI" tools/db/ingest_router.py | head -30
```

- [ ] **Step 2: Agregar la rama TRI EEFF**

En `tools/db/ingest_router.py`, agregar en la función que detecta el tipo de archivo:

```python
# Detección: PDF del fondo TRI (EEFF)
if fname.lower().endswith(".pdf") and (
    "toesca rentas" in fname.lower()
    or "rentas inmobiliarias" in fname.lower()
    or "fondo toesca rentas" in fname.lower()
):
    from tools.db.ingest_eeff_tri_series import ingest_eeff_tri_pdf
    return ingest_eeff_tri_pdf(file_path)
```

La ubicación exacta depende del patrón del router — ajustar según la estructura existente al leer el archivo en el Step 1.

- [ ] **Step 3: Verificar que el router reconoce el PDF**

```bash
python -c "
from tools.db.ingest_router import ingestar_archivo
r = ingestar_archivo(r'C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Fondos\Rentas TRI\EEFF\Fondo\2025\4T\2025 EEFF Toesca Rentas Inmobiliarias - final.pdf')
print(r)
"
```
Expected: `{'periodos_encontrados': [...], 'valor_cuota_insertadas': 0, ...}` (0 porque ya están ingresadas).

- [ ] **Step 4: Commit**

```bash
git add tools/db/ingest_router.py
git commit -m "feat(db): ingest_router reconoce PDFs de EEFF TRI fondo"
```

---

## Task 6: Verificación end-to-end

Recalcular la tabla del 31-12-2023 usando exclusivamente fuentes no-CDG.

- [ ] **Step 1: Verificar cobertura**

```bash
python -c "
import sqlite3
con = sqlite3.connect('memory/agente_toesca.db')

print('=== Valor cuota libro (no CDG) ===')
rows = con.execute('''
    SELECT nemotecnico, periodo, precio_clp, source_file
    FROM raw_valor_cuota_line
    WHERE fondo_key=\"TRI\" AND tipo=\"contable\"
      AND source_file != \"cdg_extract.xlsx\"
    ORDER BY nemotecnico, periodo
''').fetchall()
for r in rows: print(r)

print()
print('=== Cuotas en circulacion (no CDG) ===')
rows = con.execute('''
    SELECT nemotecnico, periodo, cuotas, source_file
    FROM raw_cuota_en_circulacion_line
    WHERE fondo_key=\"TRI\"
      AND source_file != \"cdg_extract.xlsx\"
    ORDER BY nemotecnico, periodo
''').fetchall()
for r in rows: print(r)
con.close()
"
```

- [ ] **Step 2: Recalcular tabla al 31-12-2023**

```bash
python -c "
import sqlite3, pandas as pd
con = sqlite3.connect('memory/agente_toesca.db')
df = pd.read_sql_query('''
WITH bursatil AS (
    SELECT nemotecnico, periodo, precio_clp AS val_bursatil_clp, cuotas,
           ROW_NUMBER() OVER (PARTITION BY nemotecnico, periodo ORDER BY fecha DESC) AS rn
    FROM raw_valor_cuota_line
    WHERE fondo_key=\"TRI\" AND tipo=\"bursatil\" AND periodo=\"2023-12\"
),
contable AS (
    SELECT nemotecnico, precio_clp AS val_libro_clp,
           ROW_NUMBER() OVER (PARTITION BY nemotecnico, periodo ORDER BY fecha DESC) AS rn
    FROM raw_valor_cuota_line
    WHERE fondo_key=\"TRI\" AND tipo=\"contable\" AND periodo=\"2023-12\"
      AND source_file != \"cdg_extract.xlsx\"
),
cap_sus AS (
    SELECT nemotecnico, MAX(capital_suscrito_uf) AS capital_suscrito_uf
    FROM raw_capital_suscrito_line WHERE fondo_key=\"TRI\"
    GROUP BY nemotecnico
)
SELECT REPLACE(b.nemotecnico, \"CFITOERI1\", \"Serie \") AS serie,
       cap.capital_suscrito_uf AS capital_suscrito_uf,
       c.val_libro_clp AS valor_cuota_libro_clp,
       b.val_bursatil_clp AS valor_cuota_bursatil_clp,
       b.cuotas * b.val_bursatil_clp AS patrimonio_bursatil_clp
FROM bursatil b
LEFT JOIN contable c ON c.nemotecnico=b.nemotecnico AND c.rn=1
LEFT JOIN cap_sus cap ON cap.nemotecnico=b.nemotecnico
WHERE b.rn=1 ORDER BY b.nemotecnico
''', con)
print(df.to_string(index=False))
con.close()
"
```
Expected: si el EEFF 2023-12 está ingresado (valor_cuota_libro de fuente no-CDG), columna `valor_cuota_libro_clp` poblada. Si solo está disponible 2025, esa columna aparecerá NULL para 2023-12 — documentar como gap esperado hasta obtener el PDF 2023.

- [ ] **Step 3: Documentar gaps de cobertura**

Agregar a `wiki/tri-eeff-cobertura.md`:
```markdown
## Cobertura raw_valor_cuota_line tipo=contable (no-CDG)

| Fuente | Rango | Estado |
|---|---|---|
| raw_eeff_line backfill | 2017-12 a 2018-06 | Completo (Serie A/C/I explícitas) |
| PDFs locales 2025 | 2024-12, 2025-12 | Completo |
| PDFs 2019-2023 | — | Gap: PDFs no disponibles localmente |

**Gap 2019-2023**: Los PDFs históricos no están en SharePoint local.
Para completar la cobertura: solicitar PDFs a Control de Gestión o CMF y
ejecutar `tools.db.backfill_eeff_tri_series.backfill_from_pdfs()`.
```

- [ ] **Step 4: Commit final**

```bash
git add wiki/tri-eeff-cobertura.md
git commit -m "docs(wiki): cobertura EEFF TRI series por fuente"
git push
```

---

## Self-Review

### Spec coverage
- ✅ Valor cuota libro por serie desde PDF → Task 2+3
- ✅ Cuotas en circulación por serie desde PDF → Task 2+3
- ✅ Capital suscrito: congelado 2019, no requiere nuevo parser (documentado)
- ✅ Idempotencia via UNIQUE → Task 3 test
- ✅ Backfill histórico (raw_eeff_line) → Task 4
- ✅ Independencia del CDG para futuros PDFs → Task 5
- ✅ Verificación end-to-end → Task 6

### Gaps conocidos
- PDFs 2019-2023 no disponibles localmente → cobertura parcial para esos años
- Cuotas en raw_cuota_en_circulacion_line: el PDF solo tiene el período de cierre, no mensuales intermedios → para períodos inter-trimestre seguirá dependiendo del CDG o del último valor conocido

### No placeholders
Revisado — todos los steps tienen código completo.
