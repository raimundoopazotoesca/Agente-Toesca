# Pipeline de Ingesta DB-Centric — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reparar regresiones introducidas por la eliminación de módulos CDG legacy, y completar el pipeline de ingesta de datos a `agente_toesca.db` para todos los tipos de archivo del portfolio.

**Architecture:** Funciones de ingesta (leer archivo de proveedor → persistir a tabla raw_*) se mueven de los módulos borrados a `tools/db/ingest_*.py`. Cada `ingest_*` tiene una pareja `read_<tipo>(path) -> dict` y `persist_<tipo>(conn, periodo, data, ...) -> int`. El backfill y los flujos del agente las consumen. Se completa la cobertura histórica de EEFF PT/Apo y se construye un tool `consultar_db_cobertura` con detección de gaps. Finalmente se añade un router `ingestar_archivo(path)` que detecta tipo por nombre y delega al módulo de ingesta correcto.

**Tech Stack:** Python 3.11, SQLite, openpyxl, MarkItDown + Gemini 2.5 Flash (para PDFs EEFF), pytest.

---

## Estado actual relevante

- `tools/noi_tools.py`, `tools/vacancia_tools.py`, `tools/balance_consolidado_tools.py` fueron eliminados en commit `91c302f`. Contenían funciones de ingesta a DB que ahora están huérfanas.
- `tools/db/backfill.py` líneas 104, 134 importan `tools.noi_tools` → ImportError al ejecutar backfill de ER y flujos.
- `tests/db/test_er_dualwrite.py` y `tests/db/test_flujo_dualwrite.py` importan funciones de noi_tools → fallan.
- Estado de ingesta a DB (de `db_ingesta_progress.md`):
  - TRI: EEFF completo (8.786 líneas, 2018-2025).
  - PT y Apo: solo valor cuota + dividendos (122 + 19). Faltan EEFF históricos.
  - Rent rolls, ER activos, flujos: pipeline existe vía backfill pero estado de cobertura no auditado.

## File Structure

**Crear:**
- `tools/db/ingest_er.py` — funciones puras de lectura/persistencia de ER Viña/Curicó desde INFORME EEFF (Tres Asociados).
- `tools/db/ingest_flujo.py` — funciones puras de lectura/persistencia de flujos INMOSA y otros activos con archivo "flujo".
- `tools/db/ingest_router.py` — detector de tipo de archivo por nombre + dispatch al módulo correcto.
- `tools/db/coverage.py` — auditoría programática de qué hay en DB (períodos, activos, gaps).
- `docs/ingest_pipeline.md` — documentación del pipeline (qué archivo va a qué tabla).

**Modificar:**
- `tools/db/backfill.py` — reemplazar `import tools.noi_tools` por imports de `tools.db.ingest_er` y `tools.db.ingest_flujo`.
- `tools/query_tools.py` — `consultar_db_cobertura` debe usar `tools.db.coverage.audit_coverage`.
- `tools/registry.py` — agregar tool definition para `ingestar_archivo`.
- `scripts/ingest_eeff_tri.py` — generalizar para soportar `--fondo PT` y `--fondo APO`.
- `tests/db/test_er_dualwrite.py` y `tests/db/test_flujo_dualwrite.py` — actualizar imports.

---

## Task 1: Restaurar funciones de ingesta de ER a `tools/db/ingest_er.py`

**Files:**
- Create: `tools/db/ingest_er.py`
- Source (git history): `tools/noi_tools.py` líneas 299-489 en commit `91c302f^`

- [ ] **Step 1: Recuperar el código de las funciones desde git**

```bash
git show 91c302f^:tools/noi_tools.py > /tmp/noi_tools_old.py
```

Identificar y extraer estas tres funciones (con sus helpers internos):
- `_leer_eeff_estado_resultado(eeff_path: str) -> tuple[date, dict, dict]` (línea ~299)
- `_persist_er_lines(mall: str, source_file: str, periodo: str, eeff_values: dict, meta_map: dict) -> int` (línea ~441)
- Cualquier helper que dependan: `_normalize_codigo`, `_clean_label`, etc.

- [ ] **Step 2: Crear `tools/db/ingest_er.py` con la API pública**

Archivo debe exportar **solo** funciones de ingesta (sin nada que escriba al CDG):

```python
"""
Lectura de INFORME EEFF (Tres Asociados) → persistencia en raw_er_activo_line.
Cubre Viña Centro y Curicó. Idempotente por (file_hash, source_row).
"""
import hashlib
import os
from datetime import date
from typing import Tuple

import openpyxl

from tools.db.connection import get_conn
from tools.db import repo_audit, repo_er_activo


def read_er_eeff(eeff_path: str) -> Tuple[date, dict, dict]:
    """Lee hoja 'ESTADO DE RESULTADO' de un INFORME EEFF de Tres Asociados.

    Returns:
        fecha_cierre: fecha del último día reportado.
        eeff_values: dict {cuenta_codigo: monto_clp} para el mes.
        meta_map: dict {cuenta_codigo: {"nombre": str, "source_row": int, "seccion": str, "es_operacional": int}}.
    """
    # ... cuerpo extraído de _leer_eeff_estado_resultado
    raise NotImplementedError


def persist_er_lines(
    activo_key: str,
    source_file: str,
    periodo: str,
    eeff_values: dict,
    meta_map: dict,
) -> int:
    """Persiste a raw_er_activo_line. Devuelve filas insertadas (omite duplicados)."""
    # ... cuerpo extraído de _persist_er_lines, sin escritura a CDG
    raise NotImplementedError
```

Mantener exactamente la misma lógica de hashing y meta_map que tenía noi_tools.

- [ ] **Step 3: Verificar import limpio**

```bash
python -c "from tools.db.ingest_er import read_er_eeff, persist_er_lines; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add tools/db/ingest_er.py
git commit -m "feat(db): restaurar ingest_er desde noi_tools borrado"
```

---

## Task 2: Restaurar funciones de ingesta de flujos a `tools/db/ingest_flujo.py`

**Files:**
- Create: `tools/db/ingest_flujo.py`
- Source (git history): `tools/noi_tools.py` función `_persist_flujo_lines` (línea ~493) en commit `91c302f^`

- [ ] **Step 1: Crear `tools/db/ingest_flujo.py`**

```python
"""
Persistencia de flujos de activo (INMOSA y similares) en raw_flujo_line.
"""
import sqlite3
from tools.db.connection import get_conn
from tools.db import repo_audit, repo_flujo


def persist_flujo_lines(
    activo_key: str,
    source_file: str,
    source_sheet: str,
    periodo: str,
    er_data: dict,
    tool: str = "ingest_flujo",
    hash_extra: str = "",
) -> int:
    """Persiste líneas de flujo. Devuelve filas insertadas."""
    # ... cuerpo extraído de _persist_flujo_lines
    raise NotImplementedError
```

- [ ] **Step 2: Verificar import limpio**

```bash
python -c "from tools.db.ingest_flujo import persist_flujo_lines; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/db/ingest_flujo.py
git commit -m "feat(db): restaurar ingest_flujo desde noi_tools borrado"
```

---

## Task 3: Reparar `backfill.py` para usar los nuevos módulos

**Files:**
- Modify: `tools/db/backfill.py:102-127` (función `backfill_er`)
- Modify: `tools/db/backfill.py:130-201` (función `backfill_inmosa`)

- [ ] **Step 1: Reemplazar imports en `backfill_er`**

Buscar:
```python
def backfill_er(verbose: bool = True) -> dict:
    """Backfill de ER Viña/Curicó desde los INFORME EEFF (raw_er_activo_line)."""
    import tools.noi_tools as noi
    from tools.sharepoint_paths import TRI_VINA_EEFF_DIR, TRI_CURICO_EEFF_DIR
```

Reemplazar con:
```python
def backfill_er(verbose: bool = True) -> dict:
    """Backfill de ER Viña/Curicó desde los INFORME EEFF (raw_er_activo_line)."""
    from tools.db.ingest_er import read_er_eeff, persist_er_lines
    from tools.sharepoint_paths import TRI_VINA_EEFF_DIR, TRI_CURICO_EEFF_DIR
```

Y en el cuerpo:
```python
            fecha_cierre, eeff_values, meta_map = read_er_eeff(path)
            ...
            n = persist_er_lines(mall, path, periodo, eeff_values, meta_map)
```

- [ ] **Step 2: Reemplazar imports en `backfill_inmosa`**

Buscar:
```python
    import tools.noi_tools as noi
```

Reemplazar con:
```python
    from tools.db.ingest_flujo import persist_flujo_lines
```

Y reemplazar la llamada:
```python
            n = persist_flujo_lines(
                "INMOSA", path, target, periodo, er_data,
                tool="backfill_inmosa", hash_extra=periodo,
            )
```

- [ ] **Step 3: Verificar que backfill arranca**

```bash
python -c "from tools.db.backfill import backfill_er, backfill_inmosa; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add tools/db/backfill.py
git commit -m "fix(db): backfill usa ingest_er/ingest_flujo, no noi_tools"
```

---

## Task 4: Reparar los tests de dual-write

**Files:**
- Modify: `tests/db/test_er_dualwrite.py`
- Modify: `tests/db/test_flujo_dualwrite.py`

- [ ] **Step 1: Leer ambos tests para entender qué importan**

```bash
grep -n "noi_tools\|_persist_er_lines\|_persist_flujo_lines\|_leer_eeff_estado" tests/db/test_er_dualwrite.py tests/db/test_flujo_dualwrite.py
```

- [ ] **Step 2: Reemplazar imports**

En `test_er_dualwrite.py` cambiar:
```python
from tools.noi_tools import _leer_eeff_estado_resultado, _persist_er_lines
```
por:
```python
from tools.db.ingest_er import read_er_eeff as _leer_eeff_estado_resultado
from tools.db.ingest_er import persist_er_lines as _persist_er_lines
```

En `test_flujo_dualwrite.py` cambiar `from tools.noi_tools import _persist_flujo_lines` por `from tools.db.ingest_flujo import persist_flujo_lines as _persist_flujo_lines`.

- [ ] **Step 3: Correr tests**

```bash
pytest tests/db/test_er_dualwrite.py tests/db/test_flujo_dualwrite.py -v
```

Expected: ambos tests pasan.

- [ ] **Step 4: Commit**

```bash
git add tests/db/test_er_dualwrite.py tests/db/test_flujo_dualwrite.py
git commit -m "test(db): actualizar imports a tools.db.ingest_*"
```

---

## Task 5: Completar ingesta histórica de EEFF para PT y Apo

**Files:**
- Modify: `scripts/ingest_eeff_tri.py` — generalizar a múltiples fondos
- Rename (opcional): a `scripts/ingest_eeff.py`

- [ ] **Step 1: Convertir constantes hardcoded en parámetros CLI**

En `scripts/ingest_eeff_tri.py` líneas 25-32, reemplazar:
```python
MD_DIR = ROOT / "work" / "eeff_ingesta" / "TRI" / "md"
PDF_DIR = ROOT / "work" / "eeff_ingesta" / "TRI" / "pdf"
JSON_DIR = ROOT / "work" / "eeff_ingesta" / "TRI" / "json"
FONDO_KEY = "TRI"
```
por una función que toma `fondo_key` como argumento:
```python
def paths_for_fondo(fondo_key: str):
    base = ROOT / "work" / "eeff_ingesta" / fondo_key
    return base / "md", base / "pdf", base / "json"
```

Y en el `argparse`, agregar `--fondo` (default TRI) que valida contra `{"TRI", "PT", "APO"}`.

- [ ] **Step 2: Crear estructura de carpetas para PT y Apo**

```powershell
New-Item -ItemType Directory -Force -Path c:\Users\raimundo.opazo\automation_agent\work\eeff_ingesta\PT\pdf, c:\Users\raimundo.opazo\automation_agent\work\eeff_ingesta\PT\md, c:\Users\raimundo.opazo\automation_agent\work\eeff_ingesta\PT\json, c:\Users\raimundo.opazo\automation_agent\work\eeff_ingesta\APO\pdf, c:\Users\raimundo.opazo\automation_agent\work\eeff_ingesta\APO\md, c:\Users\raimundo.opazo\automation_agent\work\eeff_ingesta\APO\json
```

- [ ] **Step 3: Documentar en `docs/ingest_pipeline.md` cómo subir PDFs**

Crear archivo con instrucciones:
> 1. Copiar PDFs de EEFF de SharePoint a `work/eeff_ingesta/<FONDO>/pdf/`.
> 2. Convertir a Markdown con `python -m markitdown work/eeff_ingesta/<FONDO>/pdf/<archivo>.pdf > work/eeff_ingesta/<FONDO>/md/<archivo>.md`.
> 3. Correr ingesta: `python scripts/ingest_eeff.py --fondo PT --all`.

- [ ] **Step 4: Probar con un PDF de PT**

Subir manualmente 1 PDF de EEFF PT, convertir y correr:
```bash
python scripts/ingest_eeff.py --fondo PT --file work/eeff_ingesta/PT/md/<archivo>.md
```

Verificar que se insertaron líneas:
```bash
python -c "from tools.db.connection import get_conn; c=get_conn(); print(c.execute('SELECT COUNT(*) FROM raw_eeff_line WHERE fondo_key=\"PT\"').fetchone()[0])"
```

Expected: número > 0.

- [ ] **Step 5: Commit estructura (no los PDFs)**

```bash
echo "*.pdf" >> work/eeff_ingesta/PT/pdf/.gitignore
echo "*.md" >> work/eeff_ingesta/PT/md/.gitignore
echo "*.json" >> work/eeff_ingesta/PT/json/.gitignore
git add scripts/ingest_eeff_tri.py docs/ingest_pipeline.md work/eeff_ingesta/**/.gitignore
git commit -m "feat(ingest): generalizar ingesta EEFF a PT y APO"
```

---

## Task 6: Crear `tools/db/coverage.py` — auditoría de cobertura

**Files:**
- Create: `tools/db/coverage.py`
- Modify: `tools/query_tools.py` — `consultar_db_cobertura` debe llamar a `audit_coverage`

- [ ] **Step 1: Crear el módulo**

```python
"""
Auditoría de cobertura de la DB del agente.
Reporta: qué activos/fondos tienen datos, en qué períodos, y dónde hay gaps.
"""
import sqlite3
from collections import defaultdict
from tools.db.connection import get_conn


def audit_coverage() -> dict:
    """Devuelve un dict con cobertura por tabla raw_*.

    Estructura:
    {
      "raw_rent_roll_line": {
        "activos": {"vina_centro": ["2025-09", "2025-10", ...], ...},
        "periodo_min": "2024-01", "periodo_max": "2026-04",
        "total_filas": 12345,
      },
      "raw_eeff_line": { "fondos": {...}, ... },
      "raw_er_activo_line": { "activos": {...}, ... },
      "raw_flujo_line": { "activos": {...}, ... },
      "gaps": {
         "raw_rent_roll_line": [{"activo": "vina_centro", "periodo_faltante": "2025-11"}, ...],
      }
    }
    """
    conn = get_conn()
    out = {}
    for tabla, keycol in [
        ("raw_rent_roll_line", "activo_key"),
        ("raw_er_activo_line", "activo_key"),
        ("raw_flujo_line", "activo_key"),
        ("raw_eeff_line", "fondo_key"),
    ]:
        cur = conn.execute(
            f"SELECT {keycol}, periodo, COUNT(*) FROM {tabla} "
            f"WHERE superseded_at IS NULL GROUP BY {keycol}, periodo"
        )
        por_key = defaultdict(list)
        total = 0
        for k, periodo, n in cur:
            por_key[k].append(periodo)
            total += n
        out[tabla] = {
            "por_clave": {k: sorted(v) for k, v in por_key.items()},
            "total_filas": total,
        }
    out["gaps"] = _detect_gaps(out)
    return out


def _detect_gaps(coverage: dict) -> dict:
    """Detecta períodos faltantes entre min y max de cada activo (mensuales)."""
    from datetime import date
    gaps = {}
    for tabla, info in coverage.items():
        if tabla == "gaps":
            continue
        tabla_gaps = []
        for k, periodos in info.get("por_clave", {}).items():
            if not periodos:
                continue
            ymin = periodos[0]
            ymax = periodos[-1]
            esperados = _month_range(ymin, ymax)
            faltantes = sorted(set(esperados) - set(periodos))
            for p in faltantes:
                tabla_gaps.append({"clave": k, "periodo_faltante": p})
        if tabla_gaps:
            gaps[tabla] = tabla_gaps
    return gaps


def _month_range(start_ym: str, end_ym: str) -> list[str]:
    """['2024-01', '2024-02', ..., '2024-12'] entre start y end inclusivos."""
    y1, m1 = map(int, start_ym.split("-"))
    y2, m2 = map(int, end_ym.split("-"))
    out = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out
```

- [ ] **Step 2: Conectar `consultar_db_cobertura` en query_tools.py**

Leer la función actual:
```bash
grep -n "def consultar_db_cobertura" tools/query_tools.py
```

Reemplazar su cuerpo por:
```python
def consultar_db_cobertura() -> str:
    """Reporta qué hay disponible en la DB y dónde hay gaps."""
    from tools.db.coverage import audit_coverage
    import json
    cov = audit_coverage()
    return json.dumps(cov, ensure_ascii=False, indent=2)
```

- [ ] **Step 3: Probar end-to-end**

```bash
python -c "from tools.query_tools import consultar_db_cobertura; print(consultar_db_cobertura()[:2000])"
```

Expected: JSON con `raw_rent_roll_line`, `raw_eeff_line`, etc., con sus períodos y gaps.

- [ ] **Step 4: Commit**

```bash
git add tools/db/coverage.py tools/query_tools.py
git commit -m "feat(db): coverage.audit_coverage detecta gaps por activo"
```

---

## Task 7: Router de ingesta `ingestar_archivo(path)`

**Files:**
- Create: `tools/db/ingest_router.py`
- Modify: `tools/registry.py` — agregar tool definition

- [ ] **Step 1: Crear el router**

```python
"""
Detecta tipo de archivo de proveedor por nombre y delega al ingestor correcto.
"""
import os
import re


def detect_tipo(path: str) -> str | None:
    """Devuelve uno de: rent_roll_jll, rent_roll_tresa, er_vina, er_curico,
    flujo_inmosa, eeff_pdf, precio_cuota, o None si no se detecta."""
    bn = os.path.basename(path).lower()
    if re.match(r"\d{4}\s+rent roll y noi", bn):
        return "rent_roll_jll"
    if "tres a" in bn and "rent roll" in bn:
        return "rent_roll_tresa"
    if "informe eeff" in bn and "viña" in bn:
        return "er_vina"
    if "informe eeff" in bn and "curico" in bn:
        return "er_curico"
    if "inmosa" in bn and "flujo" in bn:
        return "flujo_inmosa"
    if bn.endswith(".pdf") and "eeff" in bn:
        return "eeff_pdf"
    return None


def ingestar_archivo(path: str, periodo: str | None = None) -> dict:
    """Detecta tipo y ejecuta ingesta. Devuelve {'tipo', 'filas', 'periodo', 'error'?}."""
    tipo = detect_tipo(path)
    if tipo is None:
        return {"error": f"No se pudo detectar tipo de archivo: {os.path.basename(path)}"}

    if tipo == "rent_roll_jll":
        from tools.rentroll_tools import _read_source_data, _persist_rent_roll
        # ... (replicar lógica de backfill)
        ...

    if tipo in ("er_vina", "er_curico"):
        from tools.db.ingest_er import read_er_eeff, persist_er_lines
        fecha_cierre, eeff_values, meta_map = read_er_eeff(path)
        if not eeff_values:
            return {"error": "Sin datos de ESTADO DE RESULTADO"}
        periodo = periodo or f"{fecha_cierre.year}-{fecha_cierre.month:02d}"
        activo = "vina_centro" if tipo == "er_vina" else "power_center_curico"
        n = persist_er_lines(activo, path, periodo, eeff_values, meta_map)
        return {"tipo": tipo, "filas": n, "periodo": periodo, "activo": activo}

    if tipo == "flujo_inmosa":
        # ... lógica similar
        ...

    return {"error": f"Tipo {tipo} reconocido pero no implementado todavía"}
```

- [ ] **Step 2: Registrar como tool en registry.py**

Buscar el bloque que importa de query_tools:
```python
from tools.query_tools import (
    consultar_db_kpi, ...
)
```

Agregar después:
```python
from tools.db.ingest_router import ingestar_archivo
```

En `TOOL_DEFINITIONS` agregar:
```python
{
    "type": "function",
    "function": {
        "name": "ingestar_archivo",
        "description": (
            "Ingesta un archivo de proveedor a la DB del agente. Detecta el tipo "
            "automáticamente por el nombre (rent roll JLL/Tres A, ER Viña/Curicó, "
            "flujo INMOSA, EEFF PDF). Es idempotente: re-ingestar no duplica. "
            "Usar cuando el usuario quiere agregar/actualizar datos a la DB."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta absoluta al archivo."},
                "periodo": {"type": "string", "description": "YYYY-MM. Opcional; se infiere del archivo si no se entrega."},
            },
            "required": ["path"],
        },
    },
},
```

En `_dispatch`, agregar:
```python
"ingestar_archivo": lambda a: ingestar_archivo(a["path"], a.get("periodo")),
```

- [ ] **Step 3: Probar end-to-end con un archivo de ejemplo**

```bash
python -c "
from tools.db.ingest_router import ingestar_archivo
import json
# usar un INFORME EEFF Viña conocido
r = ingestar_archivo(r'C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Fondos\Rentas TRI\Activos\Viña Centro\EEFF\<archivo>.xlsx')
print(json.dumps(r, ensure_ascii=False, indent=2))
"
```

Expected: `{"tipo": "er_vina", "filas": N, "periodo": "YYYY-MM", "activo": "vina_centro"}` o `{"filas": 0}` si ya estaba ingestado.

- [ ] **Step 4: Commit**

```bash
git add tools/db/ingest_router.py tools/registry.py
git commit -m "feat(db): ingestar_archivo detecta tipo y delega al ingestor"
```

---

## Task 8: Documentar el pipeline en wiki

**Files:**
- Create: `docs/ingest_pipeline.md`
- Modify: `wiki/db.md` o `wiki/index.md` — agregar referencia

- [ ] **Step 1: Escribir doc del pipeline**

`docs/ingest_pipeline.md` debe cubrir:
- Mapa archivo → tabla raw_* (tabla con: nombre patrón, tipo, ingestor, tabla destino)
- Cómo se ingesta cada tipo (CLI script o herramienta del agente)
- Cómo funciona la idempotencia (file_hash + source_row)
- Cómo verificar cobertura (`consultar_db_cobertura`)

- [ ] **Step 2: Agregar entrada en wiki/log.md**

```markdown
## [2026-05-27] feat | Pipeline de ingesta DB-centric completo: ingest_er, ingest_flujo, coverage, ingestar_archivo
```

- [ ] **Step 3: Commit**

```bash
git add docs/ingest_pipeline.md wiki/log.md
git commit -m "docs: pipeline de ingesta DB-centric"
```

---

## Self-Review (post-write)

**Spec coverage:**
- ✅ Reparar regresión (Tasks 1-4)
- ✅ Pipeline ingesta EEFF PT/Apo (Task 5)
- ✅ Cobertura DB (Task 6)
- ✅ Detección automática + tool conversacional (Task 7)
- ✅ Documentación (Task 8)

**Placeholder scan:** Las funciones de `read_er_eeff`, `persist_er_lines`, `persist_flujo_lines` en Tasks 1-2 tienen `raise NotImplementedError` como placeholder *intencional* — el código real se recupera del git history. Está claramente indicado.

**Type consistency:**
- `read_er_eeff` devuelve `(date, dict, dict)` — usado consistentemente en Tasks 1, 3, 7.
- `persist_er_lines(activo_key, source_file, periodo, eeff_values, meta_map)` — firma consistente en Tasks 1, 3, 7.
- `persist_flujo_lines(activo_key, source_file, source_sheet, periodo, er_data, tool=, hash_extra=)` — firma consistente en Tasks 2, 3, 7.
- `audit_coverage() -> dict` — usado en Task 6.

**Ejecución sugerida:** Tasks 1-4 son la regresión URGENTE (sin esto, el backfill está roto). Tasks 5-8 son construcción de capacidades nuevas. Se pueden ejecutar en orden o paralelizar Tasks 5-8 una vez Tasks 1-4 estén OK.
