# Ingesta y consolidación de mercado de oficinas (JLL) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir la tabla trimestral de mercado de oficinas (JLL) en `agente_toesca_v2.db` vía un flujo de ingesta copy-paste en la app web existente, y hacer que la página 4 del fact sheet de Apoquindo la consuma desde la DB en vez de mostrar placeholders.

**Architecture:** Tabla wide `raw_mercado_oficinas` (una fila = una fila de la tabla JLL, 9 métricas como columnas). Parser de texto plano (`tools/db/ingest_mercado.py`) con el patrón validate/commit ya usado por `ingest_eeff_validated.py`. Nuevo tab "Mercado" en `web/ingesta.html` + endpoints Flask en `scripts/ingesta_server.py`. `scripts/build_factsheet.py` inyecta los valores reales en `cfg["page4"]["mercado_rows"]` para el fondo Apo antes de serializar a JSON.

**Tech Stack:** Python 3, sqlite3, Flask, pytest, vanilla JS/HTML (sin build step).

## Global Constraints

- Períodos en formato `'YYYY-MM'` (string), último mes del trimestre del informe.
- `vacancia_pct` en escala 0-100 (no 0-1).
- Toda escritura a la DB pasa por `tools/db/ingest_mercado.py` — no SQL crudo fuera de ese módulo.
- Idempotencia vía `UNIQUE(file_hash, source_row)`; re-pegar el mismo texto no duplica.
- Filtrar siempre `WHERE superseded_at IS NULL` en las lecturas de `raw_mercado_oficinas`.
- Naming de fondo: `APO` (nunca "A&R Apoquindo").
- Spec de referencia: `docs/superpowers/specs/2026-07-22-mercado-oficinas-jll-design.md`.

---

## File Structure

- **Create:** `tools/db/migrations/052_raw_mercado_oficinas.sql` — schema de la tabla nueva.
- **Create:** `tools/db/ingest_mercado.py` — parser (`parse_tabla_jll`, `_parse_num_cl`), `ValidationResult`, `validate()`, `commit()`.
- **Create:** `tests/db/test_ingest_mercado.py` — tests del parser + validate/commit + idempotencia.
- **Modify:** `scripts/ingesta_server.py` — 3 endpoints nuevos (`/api/mercado/periodo_check`, `/validate`, `/commit`).
- **Create:** `tests/test_ingesta_server_mercado.py` — tests de los endpoints Flask.
- **Modify:** `web/ingesta.html` — nuevo tab "Mercado" (HTML + JS), siguiendo el patrón de los tabs EEFF/Rent Roll ya existentes.
- **Modify:** `scripts/build_factsheet.py` — `fetch_fondo()` inyecta datos reales de mercado en `cfg["page4"]["mercado_rows"]` para Apo.
- **Modify:** `factsheet.html` — el JS de render de `tbl-mercado-tbody` deja de imprimir `—` fijo y usa los valores reales que ya vienen en `S.page4.mercado_rows`.

---

## Task 1: Migración de schema `raw_mercado_oficinas`

**Files:**
- Create: `tools/db/migrations/052_raw_mercado_oficinas.sql`
- Test: manual (aplicar migración a una DB temporal y verificar columnas)

**Interfaces:**
- Produces: tabla `raw_mercado_oficinas` con columnas `periodo, proveedor, submercado, clase, es_total, inventario_m2, absorcion_trim_m2, absorcion_u12m_m2, vacancia_pct, renta_uf_m2, renta_usd_m2, produccion_trim_m2, produccion_u12m_m2, construccion_m2, file_hash, source_row, ingest_run_id, loaded_at, superseded_at`.

- [ ] **Step 1: Crear el archivo de migración**

```sql
-- tools/db/migrations/052_raw_mercado_oficinas.sql
-- Datos de mercado de oficinas de proveedores externos (JLL), ingesta trimestral
-- copy-paste desde el PDF del informe. Una fila = una fila de la tabla del informe.

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

- [ ] **Step 2: Aplicar la migración a una DB temporal y verificar**

Run:
```bash
python -c "
from tools.db.connection import apply_migrations, get_conn_for
import tempfile, os
path = os.path.join(tempfile.gettempdir(), 'test_052.db')
if os.path.exists(path): os.remove(path)
applied = apply_migrations(path)
print('applied:', applied)
con = get_conn_for(path)
cols = [r[1] for r in con.execute('PRAGMA table_info(raw_mercado_oficinas)')]
print('columns:', cols)
assert 'vacancia_pct' in cols and 'renta_uf_m2' in cols
print('OK')
"
```
Expected: imprime `OK` sin excepciones, `columns` incluye las 19 columnas del schema.

- [ ] **Step 3: Aplicar la migración a la DB real del agente**

Run: `python -c "from tools.db.connection import apply_migrations, DEFAULT_DB_PATH; print(apply_migrations(DEFAULT_DB_PATH))"`
Expected: imprime una lista que incluye `52`.

- [ ] **Step 4: Commit**

```bash
git add tools/db/migrations/052_raw_mercado_oficinas.sql
git commit -m "feat(db): agrega tabla raw_mercado_oficinas para datos de mercado JLL"
```

---

## Task 2: Parser de texto JLL (`parse_tabla_jll`, `_parse_num_cl`)

**Files:**
- Create: `tools/db/ingest_mercado.py`
- Test: `tests/db/test_ingest_mercado.py`

**Interfaces:**
- Consumes: nada (módulo nuevo, funciones puras).
- Produces:
  - `_parse_num_cl(raw: str) -> float`
  - `parse_tabla_jll(texto: str) -> list[dict]` — cada dict con claves: `submercado, clase, es_total, inventario_m2, absorcion_trim_m2, absorcion_u12m_m2, vacancia_pct, renta_uf_m2, renta_usd_m2, produccion_trim_m2, produccion_u12m_m2, construccion_m2`.
  - `EXPECTED_PARES: set[tuple[str, str]]` — las 18 combinaciones (submercado, clase) válidas.

- [ ] **Step 1: Escribir el test del texto real (fixture completo del anexo)**

```python
# tests/db/test_ingest_mercado.py
"""Tests para tools.db.ingest_mercado."""
from __future__ import annotations

import pytest

from tools.db import ingest_mercado as mod

TEXTO_JLL_Q3_2025 = """Clase
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
"""


def test_parse_num_cl_miles():
    assert mod._parse_num_cl("1.733.422") == 1733422.0


def test_parse_num_cl_porcentaje():
    assert mod._parse_num_cl("5,6%") == 5.6


def test_parse_num_cl_decimal():
    assert mod._parse_num_cl("0,57") == 0.57


def test_parse_num_cl_negativo():
    assert mod._parse_num_cl("-7.786") == -7786.0


def test_parse_num_cl_cero():
    assert mod._parse_num_cl("0") == 0.0


def test_parse_tabla_jll_18_filas():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    assert len(filas) == 18


def test_parse_tabla_jll_primera_fila():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    f = filas[0]
    assert f["submercado"] == "Las Condes (CBD)"
    assert f["clase"] == "Total"
    assert f["es_total"] == 0
    assert f["inventario_m2"] == 1733422.0
    assert f["absorcion_trim_m2"] == 9388.0
    assert f["absorcion_u12m_m2"] == 39913.0
    assert f["vacancia_pct"] == 5.6
    assert f["renta_uf_m2"] == 0.57
    assert f["renta_usd_m2"] == 24.63
    assert f["produccion_trim_m2"] == 7013.0
    assert f["produccion_u12m_m2"] == 36704.0
    assert f["construccion_m2"] == 104187.0


def test_parse_tabla_jll_fila_santiago_total_es_total():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    santiago_total = [f for f in filas if f["submercado"] == "Santiago" and f["clase"] == "Total"][0]
    assert santiago_total["es_total"] == 1
    assert santiago_total["inventario_m2"] == 3161963.0


def test_parse_tabla_jll_absorcion_negativa():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    sc_total = [f for f in filas if f["submercado"] == "Santiago Centro" and f["clase"] == "Total"][0]
    assert sc_total["absorcion_trim_m2"] == -7786.0


def test_parse_tabla_jll_pares_coinciden_con_expected():
    filas = mod.parse_tabla_jll(TEXTO_JLL_Q3_2025)
    pares = {(f["submercado"], f["clase"]) for f in filas}
    assert pares == mod.EXPECTED_PARES


def test_parse_tabla_jll_bloque_incompleto_lanza_error():
    texto_roto = "\n".join(TEXTO_JLL_Q3_2025.strip().splitlines()[:-3])  # corta el último bloque
    with pytest.raises(ValueError, match="bloques de 11"):
        mod.parse_tabla_jll(texto_roto)
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/db/test_ingest_mercado.py -v`
Expected: `ModuleNotFoundError: No module named 'tools.db.ingest_mercado'` (o similar) — todos los tests fallan.

- [ ] **Step 3: Implementar el parser**

```python
# tools/db/ingest_mercado.py
"""Ingesta de datos de mercado de oficinas (JLL, trimestral) desde texto
copy-paste de la tabla del PDF del informe.

Formato de entrada (una línea por valor, sin tabs):
    Clase
    Inventario (m²)
    ... (10 líneas de encabezado)
    <submercado>
    <clase>
    <9 valores numéricos>
    ... (18 bloques de 11 líneas)

No expone CLI; lo consume scripts/ingesta_server.py (Flask).
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

sys.path.insert(0, str(ROOT))
from tools.db.connection import get_conn_for  # noqa: E402

PROVEEDORES_VALIDOS = {"JLL"}

_METRIC_KEYS = (
    "inventario_m2",
    "absorcion_trim_m2",
    "absorcion_u12m_m2",
    "vacancia_pct",
    "renta_uf_m2",
    "renta_usd_m2",
    "produccion_trim_m2",
    "produccion_u12m_m2",
    "construccion_m2",
)

EXPECTED_PARES = {
    ("Las Condes (CBD)", "Total"), ("Providencia", "Total"), ("Santiago Centro", "Total"),
    ("Vitacura", "Total"), ("Ciudad empresarial", "Total"), ("Estoril", "Total"), ("Santiago", "Total"),
    ("Las Condes (CBD)", "A"), ("Providencia", "A"), ("Santiago Centro", "A"), ("Santiago", "A"),
    ("Las Condes (CBD)", "B"), ("Providencia", "B"), ("Santiago Centro", "B"),
    ("Vitacura", "B"), ("Ciudad empresarial", "B"), ("Estoril", "B"), ("Santiago", "B"),
}

_CAMPOS_NO_NEGATIVOS = (
    "inventario_m2", "produccion_trim_m2", "produccion_u12m_m2",
    "construccion_m2", "renta_uf_m2", "renta_usd_m2",
)


def _parse_num_cl(raw: str) -> float:
    """Convierte formato numérico chileno a float.

    '1.733.422' -> 1733422.0 (puntos = miles)
    '5,6%'      -> 5.6       (coma = decimal, se descarta el %)
    '-7.786'    -> -7786.0
    """
    s = raw.strip().rstrip("%").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    return float(s)


def parse_tabla_jll(texto: str) -> list[dict]:
    """Parsea el texto copy-paste de la tabla de mercado JLL."""
    lines = [l.strip() for l in texto.strip().splitlines() if l.strip()]
    if lines and lines[0] == "Clase":
        lines = lines[10:]
    if len(lines) % 11 != 0:
        raise ValueError(
            f"Se esperaban bloques de 11 líneas (submercado + clase + 9 métricas), "
            f"quedaron {len(lines)} líneas después del encabezado — revisa el texto pegado."
        )
    filas = []
    for i in range(0, len(lines), 11):
        chunk = lines[i:i + 11]
        submercado, clase = chunk[0], chunk[1]
        valores_raw = chunk[2:11]
        try:
            valores = [_parse_num_cl(v) for v in valores_raw]
        except ValueError as exc:
            raise ValueError(
                f"No se pudo parsear un valor numérico en el bloque de "
                f"'{submercado}' / '{clase}': {exc}"
            ) from exc
        fila = {
            "submercado": submercado,
            "clase": clase,
            "es_total": 1 if submercado == "Santiago" else 0,
        }
        fila.update(dict(zip(_METRIC_KEYS, valores)))
        filas.append(fila)
    return filas
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/db/test_ingest_mercado.py -v`
Expected: todos los tests `PASSED` (10 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/db/ingest_mercado.py tests/db/test_ingest_mercado.py
git commit -m "feat(db): parser de texto copy-paste de tabla mercado JLL"
```

---

## Task 3: `validate()` y `commit()` con persistencia idempotente

**Files:**
- Modify: `tools/db/ingest_mercado.py`
- Modify: `tests/db/test_ingest_mercado.py`

**Interfaces:**
- Consumes: `parse_tabla_jll`, `EXPECTED_PARES`, `PROVEEDORES_VALIDOS`, `get_conn_for`, `DB_PATH` (de Task 2).
- Produces:
  - `class ValidationResult` con `.ok: bool`, `.errors: list[str]`, `.warnings: list[str]`, `.data: dict`, `.add_error(msg)`, `.to_dict() -> dict`.
  - `validate(texto: str, periodo: str, proveedor: str = "JLL") -> ValidationResult`
  - `commit(texto: str, periodo: str, proveedor: str = "JLL") -> dict` — retorna `{"status": "ok"|"skipped_duplicate", "run_id": int, "filas_insertadas": int, "filas_superseded": int}`.

- [ ] **Step 1: Escribir los tests de validate/commit**

```python
# Agregar a tests/db/test_ingest_mercado.py

from tools.db.connection import apply_migrations, get_conn_for


def test_validate_ok(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    assert result.ok
    assert result.data["n_filas"] == 18
    assert result.data["periodo"] == "2025-09"
    assert result.data["file_hash"]


def test_validate_texto_vacio(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate("", "2025-09", "JLL")
    assert not result.ok
    assert any("texto" in e.lower() for e in result.errors)


def test_validate_sin_periodo(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate(TEXTO_JLL_Q3_2025, "", "JLL")
    assert not result.ok


def test_validate_proveedor_invalido(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    result = mod.validate(TEXTO_JLL_Q3_2025, "2025-09", "Colliers")
    assert not result.ok


def test_validate_faltan_filas(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    texto_incompleto = "\n".join(TEXTO_JLL_Q3_2025.strip().splitlines()[:-11])  # quita el último bloque
    result = mod.validate(texto_incompleto, "2025-09", "JLL")
    assert not result.ok
    assert any("faltan" in e.lower() for e in result.errors)


def test_commit_inserta_18_filas(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    summary = mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    assert summary["status"] == "ok"
    assert summary["filas_insertadas"] == 18
    assert summary["filas_superseded"] == 0

    con = get_conn_for(tmp_db_path)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE superseded_at IS NULL"
        ).fetchone()[0]
        assert n == 18
    finally:
        con.close()


def test_commit_es_idempotente(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    summary2 = mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")
    assert summary2["status"] == "skipped_duplicate"

    con = get_conn_for(tmp_db_path)
    try:
        n = con.execute("SELECT COUNT(*) FROM raw_mercado_oficinas").fetchone()[0]
        assert n == 18  # no se duplicó
    finally:
        con.close()


def test_commit_correccion_marca_superseded(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(mod, "DB_PATH", tmp_db_path)
    mod.commit(TEXTO_JLL_Q3_2025, "2025-09", "JLL")

    texto_corregido = TEXTO_JLL_Q3_2025.replace("1.733.422", "1.733.999")
    summary2 = mod.commit(texto_corregido, "2025-09", "JLL")
    assert summary2["status"] == "ok"
    assert summary2["filas_superseded"] == 18
    assert summary2["filas_insertadas"] == 18

    con = get_conn_for(tmp_db_path)
    try:
        vigentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE superseded_at IS NULL"
        ).fetchone()[0]
        assert vigentes == 18
        total = con.execute("SELECT COUNT(*) FROM raw_mercado_oficinas").fetchone()[0]
        assert total == 36
    finally:
        con.close()
```

- [ ] **Step 2: Correr los tests nuevos y verificar que fallan**

Run: `python -m pytest tests/db/test_ingest_mercado.py -k "validate or commit" -v`
Expected: `AttributeError: module 'tools.db.ingest_mercado' has no attribute 'validate'` (y similares) — todos fallan.

- [ ] **Step 3: Implementar `ValidationResult`, `validate()` y `commit()`**

```python
# Agregar a tools/db/ingest_mercado.py, después de parse_tabla_jll


class ValidationResult:
    def __init__(self):
        self.ok = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.data: dict = {}

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.ok = False

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, **self.data}


def validate(texto: str, periodo: str, proveedor: str = "JLL") -> ValidationResult:
    """Dry-run completo: parsea, valida, arma preview. No escribe en la DB (salvo lecturas)."""
    result = ValidationResult()

    if proveedor not in PROVEEDORES_VALIDOS:
        result.add_error(f"Proveedor {proveedor!r} inválido (válidos: {sorted(PROVEEDORES_VALIDOS)})")
        return result
    if not periodo:
        result.add_error("Falta declarar el período (YYYY-MM) del informe.")
        return result
    if not texto.strip():
        result.add_error("Pega el texto de la tabla antes de validar.")
        return result

    try:
        filas = parse_tabla_jll(texto)
    except ValueError as exc:
        result.add_error(str(exc))
        return result

    pares_encontrados = {(f["submercado"], f["clase"]) for f in filas}
    faltantes = EXPECTED_PARES - pares_encontrados
    sobrantes = pares_encontrados - EXPECTED_PARES
    if faltantes:
        result.add_error(f"Faltan combinaciones submercado/clase: {sorted(faltantes)}")
    if sobrantes:
        result.add_error(f"Combinaciones submercado/clase no reconocidas: {sorted(sobrantes)}")

    for f in filas:
        vac = f.get("vacancia_pct")
        if vac is not None and not (0 <= vac <= 100):
            result.add_error(
                f"{f['submercado']}/{f['clase']}: vacancia_pct fuera de rango 0-100 ({vac})"
            )
        for campo in _CAMPOS_NO_NEGATIVOS:
            valor = f.get(campo)
            if valor is not None and valor < 0:
                result.add_error(
                    f"{f['submercado']}/{f['clase']}: {campo} negativo ({valor}) — valor inesperado"
                )

    if not result.ok:
        return result

    fhash = hashlib.sha256(f"{proveedor}|{periodo}|{texto.strip()}".encode("utf-8")).hexdigest()

    con = get_conn_for(str(DB_PATH))
    try:
        n_existentes = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas "
            "WHERE periodo=? AND proveedor=? AND superseded_at IS NULL",
            (periodo, proveedor),
        ).fetchone()[0]
        ya_mismo_hash = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
    finally:
        con.close()

    if n_existentes:
        result.warnings.append(
            f"Ya existen {n_existentes} fila(s) vigentes para {periodo}/{proveedor}. "
            "Si confirmas, se marcarán como reemplazadas y se insertarán las nuevas."
        )

    result.data = {
        "periodo": periodo,
        "proveedor": proveedor,
        "filas": filas,
        "n_filas": len(filas),
        "file_hash": fhash,
        "ya_ingestado": bool(ya_mismo_hash),
    }
    return result


def commit(texto: str, periodo: str, proveedor: str = "JLL") -> dict:
    """Re-valida (defensa en profundidad) y persiste. Lanza ValueError si no pasa validación."""
    result = validate(texto, periodo, proveedor)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    filas = result.data["filas"]
    fhash = result.data["file_hash"]
    source_file = f"jll_manual_{periodo}"

    con = get_conn_for(str(DB_PATH))
    try:
        existing_hash_count = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing_hash_count:
            return {"status": "skipped_duplicate", "run_id": None, "filas_insertadas": 0, "filas_superseded": 0}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            """INSERT INTO ingest_run (tool, source_file, file_hash, started_at, status, periodo_declarado)
               VALUES (?,?,?,?,?,?)""",
            ("ingest_mercado", source_file, fhash, now, "running", periodo),
        )
        run_id = cur.lastrowid

        cur2 = con.execute(
            """UPDATE raw_mercado_oficinas SET superseded_at=?
               WHERE periodo=? AND proveedor=? AND superseded_at IS NULL""",
            (now, periodo, proveedor),
        )
        filas_superseded = cur2.rowcount if cur2.rowcount > 0 else 0

        rows = [
            (
                periodo, proveedor, f["submercado"], f["clase"], f["es_total"],
                f["inventario_m2"], f["absorcion_trim_m2"], f["absorcion_u12m_m2"],
                f["vacancia_pct"], f["renta_uf_m2"], f["renta_usd_m2"],
                f["produccion_trim_m2"], f["produccion_u12m_m2"], f["construccion_m2"],
                fhash, idx, run_id,
            )
            for idx, f in enumerate(filas)
        ]
        con.executemany(
            """INSERT INTO raw_mercado_oficinas
               (periodo, proveedor, submercado, clase, es_total,
                inventario_m2, absorcion_trim_m2, absorcion_u12m_m2, vacancia_pct,
                renta_uf_m2, renta_usd_m2, produccion_trim_m2, produccion_u12m_m2,
                construccion_m2, file_hash, source_row, ingest_run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(filas), len(rows), run_id),
        )
        con.commit()
        return {
            "status": "ok",
            "run_id": run_id,
            "filas_insertadas": len(rows),
            "filas_superseded": filas_superseded,
        }
    finally:
        con.close()
```

- [ ] **Step 4: Correr todos los tests del módulo y verificar que pasan**

Run: `python -m pytest tests/db/test_ingest_mercado.py -v`
Expected: todos `PASSED` (17 tests en total).

- [ ] **Step 5: Commit**

```bash
git add tools/db/ingest_mercado.py tests/db/test_ingest_mercado.py
git commit -m "feat(db): validate/commit idempotentes para ingesta de mercado JLL"
```

---

## Task 4: Endpoints Flask en `scripts/ingesta_server.py`

**Files:**
- Modify: `scripts/ingesta_server.py`
- Create: `tests/test_ingesta_server_mercado.py`

**Interfaces:**
- Consumes: `tools.db.ingest_mercado.validate`, `.commit` (de Task 3); `tools.db.connection.get_conn_for`.
- Produces: rutas Flask `GET /api/mercado/periodo_check`, `POST /api/mercado/validate`, `POST /api/mercado/commit` sobre la app `app` ya definida en `ingesta_server.py`.

- [ ] **Step 1: Escribir los tests de los endpoints**

```python
# tests/test_ingesta_server_mercado.py
"""Tests de los endpoints /api/mercado/* de scripts/ingesta_server.py."""
from __future__ import annotations

import pytest

from tools.db.connection import apply_migrations
from tools.db import ingest_mercado

TEXTO_MINI = None  # se completa abajo, reusa el fixture de test_ingest_mercado


@pytest.fixture
def texto_jll():
    from tests.db.test_ingest_mercado import TEXTO_JLL_Q3_2025
    return TEXTO_JLL_Q3_2025


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    apply_migrations(tmp_db_path)
    monkeypatch.setattr(ingest_mercado, "DB_PATH", tmp_db_path)
    from scripts import ingesta_server
    monkeypatch.setattr(ingesta_server, "get_conn_for", ingesta_server.get_conn_for)
    ingesta_server.app.config["TESTING"] = True
    with ingesta_server.app.test_client() as c:
        yield c


def test_periodo_check_no_ingestado(client):
    res = client.get("/api/mercado/periodo_check?periodo=2025-09&proveedor=JLL")
    assert res.status_code == 200
    assert res.get_json()["ya_ingestado"] is False


def test_validate_endpoint_ok(client, texto_jll):
    res = client.post("/api/mercado/validate", json={
        "texto": texto_jll, "periodo": "2025-09", "proveedor": "JLL",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["n_filas"] == 18


def test_validate_endpoint_texto_vacio(client):
    res = client.post("/api/mercado/validate", json={
        "texto": "", "periodo": "2025-09", "proveedor": "JLL",
    })
    data = res.get_json()
    assert data["ok"] is False


def test_commit_endpoint_inserta_y_periodo_check_refleja(client, texto_jll):
    res = client.post("/api/mercado/commit", json={
        "texto": texto_jll, "periodo": "2025-09", "proveedor": "JLL",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["filas_insertadas"] == 18

    res2 = client.get("/api/mercado/periodo_check?periodo=2025-09&proveedor=JLL")
    data2 = res2.get_json()
    assert data2["ya_ingestado"] is True
    assert data2["n_filas"] == 18


def test_commit_endpoint_texto_invalido_retorna_400(client):
    res = client.post("/api/mercado/commit", json={
        "texto": "esto no es una tabla", "periodo": "2025-09", "proveedor": "JLL",
    })
    assert res.status_code == 400
    assert res.get_json()["ok"] is False
```

Nota: la fixture `client` monkeypatchea `ingest_mercado.DB_PATH` — como `ingesta_server.py` importa las funciones `mercado_core.validate`/`mercado_core.commit` (no las copia), estas siguen leyendo el atributo de módulo en tiempo de llamada, así que el monkeypatch aplica correctamente. El endpoint `periodo_check` usa `ROOT / "memory" / "agente_toesca_v2.db"` como el resto de endpoints existentes (mismo patrón que `api_rentroll_periodo_check`) — para el test, se ajusta igual vía monkeypatch de esa misma constante si hace falta (ver Step 3, se define localmente igual que `mercado_core.DB_PATH`).

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_ingesta_server_mercado.py -v`
Expected: `404 NOT FOUND` en las rutas `/api/mercado/*` (no existen todavía) — tests fallan.

- [ ] **Step 3: Agregar los endpoints a `scripts/ingesta_server.py`**

Modificar el import (línea ~22-24):

```python
from tools.db import ingest_eeff_validated as core  # noqa: E402
from tools.db import ingest_rent_roll_validated as rr_core  # noqa: E402
from tools.db import ingest_mercado as mercado_core  # noqa: E402
from tools.db.connection import get_conn_for  # noqa: E402
```

Agregar al final del archivo, antes de `if __name__ == "__main__":` (después de `api_rentroll_commit`, línea ~152):

```python
@app.get("/api/mercado/periodo_check")
def api_mercado_periodo_check():
    periodo = request.args.get("periodo", "")
    proveedor = request.args.get("proveedor", "JLL")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"
    con = get_conn_for(str(DB_PATH))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas "
            "WHERE periodo=? AND proveedor=? AND superseded_at IS NULL",
            (periodo, proveedor),
        ).fetchone()[0]
        return jsonify({"ya_ingestado": bool(n), "n_filas": n})
    finally:
        con.close()


@app.post("/api/mercado/validate")
def api_mercado_validate():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    proveedor = body.get("proveedor", "JLL")
    result = mercado_core.validate(texto, periodo, proveedor)
    return jsonify(result.to_dict())


@app.post("/api/mercado/commit")
def api_mercado_commit():
    body = request.get_json(force=True, silent=True) or {}
    texto = body.get("texto", "")
    periodo = body.get("periodo", "")
    proveedor = body.get("proveedor", "JLL")
    try:
        summary = mercado_core.commit(texto, periodo, proveedor)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **summary})
```

Ajustar la fixture del test (Step 1) si el endpoint `periodo_check` usa su propio `DB_PATH` local en vez del de `mercado_core` — como se ve arriba, `api_mercado_periodo_check` construye `DB_PATH` localmente igual que los endpoints EEFF/RentRoll existentes, apuntando a `memory/agente_toesca_v2.db`. Para que el test use la DB temporal, monkeypatchear el `ROOT` no es práctico; en su lugar, monkeypatchear directamente donde se arma `DB_PATH` dentro del endpoint no es posible sin refactor. **Ajuste:** en vez de recalcular `DB_PATH` dentro de `api_mercado_periodo_check`, reusar `mercado_core.DB_PATH` (ya monkeypatcheable):

```python
@app.get("/api/mercado/periodo_check")
def api_mercado_periodo_check():
    periodo = request.args.get("periodo", "")
    proveedor = request.args.get("proveedor", "JLL")
    if not periodo:
        return jsonify({"ya_ingestado": False})
    con = get_conn_for(str(mercado_core.DB_PATH))
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM raw_mercado_oficinas "
            "WHERE periodo=? AND proveedor=? AND superseded_at IS NULL",
            (periodo, proveedor),
        ).fetchone()[0]
        return jsonify({"ya_ingestado": bool(n), "n_filas": n})
    finally:
        con.close()
```

Con este cambio, el fixture del test en Step 1 (que monkeypatchea `ingest_mercado.DB_PATH`) funciona correctamente también para `periodo_check`, porque el endpoint lee `mercado_core.DB_PATH` (mismo objeto módulo) en tiempo de request.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_ingesta_server_mercado.py -v`
Expected: 5 tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingesta_server.py tests/test_ingesta_server_mercado.py
git commit -m "feat(ingesta): endpoints /api/mercado/* para validar y persistir tabla JLL"
```

---

## Task 5: Tab "Mercado" en `web/ingesta.html`

**Files:**
- Modify: `web/ingesta.html`

**Interfaces:**
- Consumes: endpoints `GET /api/mercado/periodo_check`, `POST /api/mercado/validate`, `POST /api/mercado/commit` (de Task 4).
- Produces: UI navegable en `http://localhost:8765/ingesta` con un tercer tab "Mercado".

- [ ] **Step 1: Agregar el botón de tab**

Modificar (línea ~137-140):

```html
  <div class="tabs">
    <button class="tab-btn active" data-tab="eeff">EEFF</button>
    <button class="tab-btn" data-tab="rentroll">Rent Roll</button>
    <button class="tab-btn" data-tab="mercado">Mercado</button>
  </div>
```

- [ ] **Step 2: Agregar el panel HTML del tab**

Insertar después del cierre del tab Rent Roll (después de la línea `</div>` que cierra `<div id="tab-rentroll" ...>`, antes de `</main>`):

```html
<!-- ══════════════════════════ TAB MERCADO ══════════════════════════ -->
<div id="tab-mercado" class="tab-panel">

  <div class="step">
    <div class="step-title"><span class="step-num">1</span> Período y proveedor</div>
    <div class="row">
      <label class="muted" for="mercado-periodo">Período del informe (trimestral):</label>
      <input type="month" id="mercado-periodo">
      <label class="muted" for="mercado-proveedor">Proveedor:</label>
      <select id="mercado-proveedor">
        <option value="JLL">JLL</option>
      </select>
    </div>
    <div class="row" id="mercado-periodo-status-row" style="margin-top:6px"></div>
  </div>

  <div class="step">
    <div class="step-title"><span class="step-num">2</span> Copia la tabla del PDF y pégala aquí</div>
    <ol class="instructions">
      <li>Abre el informe JLL del trimestre.</li>
      <li>Selecciona y copia la tabla de mercado de oficinas completa (encabezado + las 18 filas).</li>
      <li>Pega el texto tal cual en el cuadro de abajo.</li>
    </ol>
    <textarea id="mercado-input" placeholder="Pega aquí el texto copiado de la tabla del informe JLL..."></textarea>
    <div class="row">
      <button id="btn-mercado-validate">Validar y previsualizar</button>
      <span id="mercado-validate-status" class="muted"></span>
    </div>

    <div id="mercado-preview" class="preview hidden">
      <div class="badges" id="mercado-badges"></div>
      <ul id="mercado-errors" class="msg-list err"></ul>
      <ul id="mercado-warnings" class="msg-list warn"></ul>

      <div id="mercado-section-tabla" class="hidden">
        <h3>Filas detectadas</h3>
        <table>
          <thead><tr>
            <th>Submercado</th><th>Clase</th><th class="num">Inventario (m²)</th>
            <th class="num">Absorción U12M (m²)</th><th class="num">Vacancia (%)</th>
            <th class="num">Renta (UF/m²)</th><th class="num">En construcción (m²)</th>
          </tr></thead>
          <tbody id="mercado-tabla-body"></tbody>
        </table>
      </div>
    </div>

    <div class="row" style="margin-top:20px;">
      <button id="btn-mercado-confirm" disabled>Confirmar e ingestar</button>
      <span id="mercado-ingest-status" class="muted"></span>
    </div>
  </div>

</div>
```

- [ ] **Step 3: Agregar la lógica JS**

Insertar antes del cierre de `<script>` (después del bloque de Rent Roll, al final del script existente):

```javascript
// ── TAB MERCADO ──────────────────────────────────────────────────────────
let lastMercadoTexto = null;
let lastMercadoPeriodo = null;
let lastMercadoProveedor = null;
let lastMercadoValidationOk = false;

const mercadoPeriodo = document.getElementById('mercado-periodo');
const mercadoProveedor = document.getElementById('mercado-proveedor');
const mercadoInput = document.getElementById('mercado-input');
const btnMercadoValidate = document.getElementById('btn-mercado-validate');
const mercadoValidateStatus = document.getElementById('mercado-validate-status');
const btnMercadoConfirm = document.getElementById('btn-mercado-confirm');
const mercadoIngestStatus = document.getElementById('mercado-ingest-status');
const mercadoPeriodoStatusRow = document.getElementById('mercado-periodo-status-row');

async function checkMercadoPeriodoStatus() {
  const periodo = mercadoPeriodo.value;
  const proveedor = mercadoProveedor.value;
  mercadoPeriodoStatusRow.innerHTML = '';
  if (!periodo) return;
  try {
    const res = await fetch(`/api/mercado/periodo_check?periodo=${periodo}&proveedor=${proveedor}`);
    const data = await res.json();
    if (data.ya_ingestado) {
      const el = document.createElement('span');
      el.className = 'badge';
      el.innerHTML = `<span class="dot warn"></span>${proveedor} ${periodo} ya tiene ${data.n_filas} fila(s) vigentes — reingestar las reemplazará.`;
      mercadoPeriodoStatusRow.appendChild(el);
    }
  } catch (e) { /* silencioso */ }
}
mercadoPeriodo.addEventListener('change', checkMercadoPeriodoStatus);
mercadoProveedor.addEventListener('change', checkMercadoPeriodoStatus);

function resetMercadoPreview() {
  document.getElementById('mercado-preview').classList.add('hidden');
  btnMercadoConfirm.disabled = true;
  lastMercadoValidationOk = false;
  mercadoIngestStatus.textContent = '';
}
mercadoInput.addEventListener('input', resetMercadoPreview);
mercadoPeriodo.addEventListener('change', resetMercadoPreview);

function renderMercadoPreview(data) {
  document.getElementById('mercado-preview').classList.remove('hidden');
  const badges = document.getElementById('mercado-badges');
  badges.innerHTML = '';
  const errUl = document.getElementById('mercado-errors');
  const warnUl = document.getElementById('mercado-warnings');
  errUl.innerHTML = '';
  warnUl.innerHTML = '';

  function addBadge(label, status) {
    const el = document.createElement('span');
    el.className = 'badge';
    el.innerHTML = `<span class="dot ${status}"></span>${label}`;
    badges.appendChild(el);
  }
  addBadge(data.ok ? 'Validación OK' : 'Validación con errores', data.ok ? 'ok' : 'err');
  (data.errors || []).forEach(e => {
    const li = document.createElement('li'); li.textContent = e; errUl.appendChild(li);
  });
  (data.warnings || []).forEach(w => {
    const li = document.createElement('li'); li.textContent = w; warnUl.appendChild(li);
  });

  const tablaBody = document.getElementById('mercado-tabla-body');
  tablaBody.innerHTML = '';
  if (data.ok && data.filas && data.filas.length) {
    document.getElementById('mercado-section-tabla').classList.remove('hidden');
    data.filas.forEach(f => {
      const tr = document.createElement('tr');
      if (f.es_total) tr.style.fontWeight = '700';
      tr.innerHTML = `<td>${f.submercado}</td><td>${f.clase}</td>` +
        `<td class="num">${fmt(f.inventario_m2)}</td><td class="num">${fmt(f.absorcion_u12m_m2)}</td>` +
        `<td class="num">${f.vacancia_pct}%</td><td class="num">${f.renta_uf_m2}</td>` +
        `<td class="num">${fmt(f.construccion_m2)}</td>`;
      tablaBody.appendChild(tr);
    });
  } else {
    document.getElementById('mercado-section-tabla').classList.add('hidden');
  }

  lastMercadoValidationOk = data.ok;
  btnMercadoConfirm.disabled = !data.ok;
}

btnMercadoValidate.addEventListener('click', async () => {
  const texto = mercadoInput.value;
  const periodo = mercadoPeriodo.value;
  const proveedor = mercadoProveedor.value;
  if (!periodo) { mercadoValidateStatus.textContent = 'Declara el período del informe.'; return; }
  mercadoValidateStatus.textContent = 'Validando…';
  btnMercadoConfirm.disabled = true;
  try {
    const res = await fetch('/api/mercado/validate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto, periodo, proveedor}),
    });
    const data = await res.json();
    lastMercadoTexto = texto;
    lastMercadoPeriodo = periodo;
    lastMercadoProveedor = proveedor;
    renderMercadoPreview(data);
    mercadoValidateStatus.textContent = '';
  } catch (e) {
    mercadoValidateStatus.textContent = 'Error: ' + e.message;
  }
});

btnMercadoConfirm.addEventListener('click', async () => {
  if (!lastMercadoValidationOk || lastMercadoTexto !== mercadoInput.value ||
      lastMercadoPeriodo !== mercadoPeriodo.value || lastMercadoProveedor !== mercadoProveedor.value) {
    mercadoIngestStatus.textContent = 'Los datos cambiaron desde la última validación — vuelve a validar.';
    return;
  }
  btnMercadoConfirm.disabled = true;
  mercadoIngestStatus.textContent = 'Ingestando…';
  try {
    const res = await fetch('/api/mercado/commit', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texto: lastMercadoTexto, periodo: lastMercadoPeriodo, proveedor: lastMercadoProveedor}),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'error desconocido');
    if (data.status === 'skipped_duplicate') {
      mercadoIngestStatus.textContent = 'Este texto ya había sido ingestado antes — no se creó nada nuevo.';
    } else {
      mercadoIngestStatus.textContent =
        `Listo: ${data.filas_insertadas} filas insertadas` +
        (data.filas_superseded ? `, ${data.filas_superseded} filas anteriores reemplazadas` : '') +
        ` (run #${data.run_id}).`;
    }
  } catch (e) {
    mercadoIngestStatus.textContent = 'Error al ingestar: ' + e.message;
    btnMercadoConfirm.disabled = false;
  }
});
```

Y ajustar el hash-router existente (línea ~303-305) para soportar `#mercado`:

```javascript
if (location.hash === '#rentroll') {
  document.querySelector('[data-tab="rentroll"]').click();
} else if (location.hash === '#mercado') {
  document.querySelector('[data-tab="mercado"]').click();
}
```

- [ ] **Step 4: Verificar manualmente en el navegador**

Run: `python -m scripts.ingesta_server` (deja corriendo en background)
Abrir `http://localhost:8765/ingesta#mercado` en el navegador.
Expected: se ve el tercer tab "Mercado" activo, con selector de período, textarea, y botones "Validar" / "Confirmar e ingestar". Pegar el texto del anexo del spec y período `2025-09`, click "Validar y previsualizar" → debe mostrar 18 filas en la tabla de preview sin errores. Click "Confirmar e ingestar" → debe mostrar "Listo: 18 filas insertadas".

- [ ] **Step 5: Commit**

```bash
git add web/ingesta.html
git commit -m "feat(ingesta): tab Mercado en la app de ingesta web"
```

---

## Task 6: Consumo data-driven en `build_factsheet.py` + `factsheet.html`

**Files:**
- Modify: `scripts/build_factsheet.py:371-567` (`fetch_fondo`)
- Modify: `factsheet.html:2520-2524` (render JS de `tbl-mercado-tbody`)

**Interfaces:**
- Consumes: tabla `raw_mercado_oficinas` (Task 1); `cfg["page4"]["mercado_rows"]` ya existente en `FONDO_CONFIG["APO"]` (lista de dicts `{comuna, clase, total?}`).
- Produces: `all_data["APO"]["static"]["page4"]["mercado_rows"]` con valores reales (`inventario_m2, absorcion_u12m_m2, vacancia_pct, renta_uf_m2, construccion_m2`) cuando hay datos en la DB para el trimestre; placeholders `—` cuando no.

- [ ] **Step 1: Escribir un test de humo para la nueva lógica de merge**

Crear `tests/test_build_factsheet_mercado.py`:

```python
"""Test de humo: fetch_fondo inyecta datos reales de mercado en page4 para Apo."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from tools.db.connection import apply_migrations


def test_merge_mercado_rows_con_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """INSERT INTO raw_mercado_oficinas
           (periodo, proveedor, submercado, clase, es_total, inventario_m2,
            absorcion_trim_m2, absorcion_u12m_m2, vacancia_pct, renta_uf_m2,
            renta_usd_m2, produccion_trim_m2, produccion_u12m_m2, construccion_m2,
            file_hash, source_row)
           VALUES ('2025-09','JLL','Las Condes (CBD)','Total',0,1733422,9388,39913,
                    5.6,0.57,24.63,7013,36704,104187,'HASH1',0)"""
    )
    con.commit()
    con.close()

    cfg = {
        "page4": {
            "mercado_rows": [{"comuna": "Las Condes (CBD)", "clase": "Total"}],
            "notas": [], "submercado": "Las Condes",
        }
    }
    filas = bf._fetch_mercado_rows(db_path, "2025-09")
    assert len(filas) == 1
    assert filas[0]["inventario_m2"] == 1733422.0
    assert filas[0]["vacancia_pct"] == 5.6


def test_merge_mercado_rows_sin_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    filas = bf._fetch_mercado_rows(db_path, "2025-09")
    assert filas == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_build_factsheet_mercado.py -v`
Expected: `AttributeError: module 'build_factsheet' has no attribute '_fetch_mercado_rows'`.

- [ ] **Step 3: Implementar `_fetch_mercado_rows` y usarla en `fetch_fondo`**

Agregar esta función en `scripts/build_factsheet.py`, antes de `def fetch_fondo(...)` (línea 371):

```python
def _fetch_mercado_rows(db_path: str, periodo: str, proveedor: str = "JLL") -> list[dict]:
    """Lee raw_mercado_oficinas para el periodo/proveedor dado, ordenado igual
    que la tabla del fact sheet (Total, luego A, luego B; Santiago al final
    de cada bloque)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """SELECT submercado, clase, inventario_m2, absorcion_u12m_m2,
                      vacancia_pct, renta_uf_m2, construccion_m2, es_total
               FROM raw_mercado_oficinas
               WHERE periodo = ? AND proveedor = ? AND superseded_at IS NULL
               ORDER BY
                   CASE clase WHEN 'Total' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
                   es_total, id""",
            (periodo, proveedor),
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "comuna": r[0],
            "clase": r[1],
            "inventario_m2": r[2],
            "absorcion_u12m_m2": r[3],
            "vacancia_pct": r[4],
            "renta_uf_m2": r[5],
            "construccion_m2": r[6],
            "total": bool(r[7]),
        }
        for r in rows
    ]
```

Modificar el `return` de `fetch_fondo` (línea 557-567) para inyectar los datos de mercado solo para Apo:

```python
    static_cfg = cfg
    if fondo_key == "APO" and cfg.get("page4"):
        periodos_disponibles = [
            r[0] for r in cur.execute(
                "SELECT DISTINCT periodo FROM raw_mercado_oficinas "
                "WHERE proveedor='JLL' AND superseded_at IS NULL ORDER BY periodo DESC"
            )
        ]
        mercado_rows_db = (
            _fetch_mercado_rows(str(DB), periodos_disponibles[0])
            if periodos_disponibles else []
        )
        if mercado_rows_db:
            static_cfg = {**cfg, "page4": {**cfg["page4"], "mercado_rows": mercado_rows_db}}

    return {
        "static": static_cfg,
        "contable": dict(sorted(contable.items())),
        "bursatil": dict(sorted(bursatil.items())),
        "fondo_kpi": dict(sorted(fondo_kpi.items())),
        "balance": dict(sorted(balance.items())),
        "gastos": dict(sorted(gastos.items())),
        "uf": uf_por_periodo,
        "dividendos": dividendos,
        "perf_data": _fetch_perf_data(fondo_key),
    }
```

Nota: `DB` es la constante módulo-level ya existente en `build_factsheet.py` que apunta al path de `agente_toesca_v2.db` (usada para abrir `con` en `main()`). Se usa aquí como string para reabrir una conexión de solo lectura dentro de `_fetch_mercado_rows`, evitando interferir con el cursor `cur` ya abierto sobre la conexión principal.

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python -m pytest tests/test_build_factsheet_mercado.py -v`
Expected: 2 tests `PASSED`.

- [ ] **Step 5: Actualizar el render JS en `factsheet.html`**

Reemplazar (línea ~2522-2524):

```javascript
    document.getElementById("mercado-titulo").textContent =
      `Análisis de Mercado de Oficinas — Submercado ${S.page4.submercado}`;
    document.getElementById("tbl-mercado-tbody").innerHTML =
      S.page4.mercado_rows.map(r => `<tr${r.total ? ' class="row-total"' : ''}><td>${r.comuna}</td><td>${r.clase}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`).join("");
```

por:

```javascript
    document.getElementById("mercado-titulo").textContent =
      `Análisis de Mercado de Oficinas — Submercado ${S.page4.submercado}`;
    function celdaMercado(v, esPct) {
      if (v === null || v === undefined) return '<td class="placeholder">—</td>';
      const texto = esPct
        ? v.toLocaleString("es-CL", {maximumFractionDigits: 1}) + "%"
        : v.toLocaleString("es-CL", {maximumFractionDigits: 2});
      return `<td>${texto}</td>`;
    }
    document.getElementById("tbl-mercado-tbody").innerHTML =
      S.page4.mercado_rows.map(r => {
        const cls = r.total ? ' class="row-total"' : '';
        if (r.inventario_m2 === undefined) {
          // sin datos ingestados para este trimestre: placeholders
          return `<tr${cls}><td>${r.comuna}</td><td>${r.clase}</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td><td class="placeholder">—</td></tr>`;
        }
        return `<tr${cls}><td>${r.comuna}</td><td>${r.clase}</td>` +
          celdaMercado(r.inventario_m2, false) +
          celdaMercado(r.absorcion_u12m_m2, false) +
          celdaMercado(r.vacancia_pct, true) +
          celdaMercado(r.renta_uf_m2, false) +
          celdaMercado(r.construccion_m2, false) +
          `</tr>`;
      }).join("");
```

- [ ] **Step 6: Regenerar el fact sheet y verificar visualmente**

Run: `python -m scripts.build_factsheet`
Abrir `factsheet.html` en el navegador, seleccionar fondo Apo, ir a la página 4.
Expected: si ya se ingestó el trimestre 2025-09 en la Task 5, la tabla de mercado muestra valores reales (no `—`); si no se ingestó ningún trimestre, sigue mostrando `—` sin romper el layout.

- [ ] **Step 7: Correr la suite completa de tests**

Run: `python -m pytest tests/ -q`
Expected: todos los tests pasan (incluye los de las Tasks 1-6), sin regresiones en tests preexistentes.

- [ ] **Step 8: Commit**

```bash
git add scripts/build_factsheet.py factsheet.html tests/test_build_factsheet_mercado.py
git commit -m "feat(factsheet): página 4 Apo consume mercado de oficinas real desde la DB"
```

---

## Self-Review Notes

- **Cobertura del spec:** las 6 secciones del spec (schema, parser/formato real, validate/commit, endpoints, tab UI, consumo factsheet) tienen cada una su task. Los párrafos de texto libre (`txt-mercado-p1/p2`) quedan explícitamente fuera de alcance, sin task asociada — correcto según el spec.
- **Idempotencia verificada:** Task 3 incluye test explícito de re-ingesta (skip) y de corrección (supersede).
- **Consistencia de tipos:** `parse_tabla_jll` devuelve claves idénticas a las columnas de `raw_mercado_oficinas` (Task 1) y a los parámetros posicionales del `INSERT` en `commit()` (Task 3); `_fetch_mercado_rows` devuelve las mismas claves que consume el JS de Task 6 (`inventario_m2, absorcion_u12m_m2, vacancia_pct, renta_uf_m2, construccion_m2, comuna, clase, total`).
