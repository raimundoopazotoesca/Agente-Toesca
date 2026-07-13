# Plan de ingesta — Gastos del Fondo PT (EEFF históricos)

**Fecha**: 2026-07-07
**Fondo**: Toesca Rentas Inmobiliarias PT (`fondo_key='PT'`)
**Objetivo**: completar la sección "GASTOS DE OPERACIÓN" del ER en `raw_eeff_line` para todos los trimestres que le faltan al fact sheet HTML (`factsheet.html`).

---

## 1. Contexto

El fact sheet dinámico multi-fondo (`factsheet.html`, generado por `scripts/build_factsheet.py`) lee gastos desde `raw_eeff_line`. Los otros dos fondos ya están al 100 %:

- **TRI**: 37/37 trimestres coherentes (2017-03 → 2026-03).
- **APO**: 29/29 trimestres coherentes (2019-03 → 2026-03).
- **PT**: 6/36 trimestres → **quedan 30 trimestres por ingresar**.

Regla dura del proyecto (memoria `feedback_gastos_check_suma`):
`sum(componentes) == ER.total_gastos_operacion (±2K CLP)`, si no cuadra **no persistir**.

---

## 2. Trimestres faltantes de PT (30 en total)

```
2017-12, 2018-03, 2018-06, 2018-09, 2018-12,
2019-03, 2019-12,
2020-03, 2020-06, 2020-09, 2020-12,
2021-03, 2021-06, 2021-09, 2021-12,
2022-03, 2022-06, 2022-09, 2022-12,
2023-03, 2023-06, 2023-09, 2023-12,
2024-03, 2024-06, 2024-09,
2025-03, 2025-06, 2025-09,
2026-03
```

Trimestres YA ingestados y validados (NO tocar): `2017-03, 2017-09, 2019-06, 2019-09, 2024-12, 2025-12`.

---

## 2b. Por qué falta PT gastos si tenemos valor libro

Los valor cuota libro de PT (33 periodos) vienen de `cdg_extract.xlsx` — la planilla
mensual de control de gestión donde el equipo Toesca copia el VNA por serie desde su
fuente contable. Los **gastos** en cambio se ingestan directamente de los PDF de EEFF,
que sólo existen en el repo para 2017–2019 + 2024-12 + 2025-12. La brecha 2020–2024
nunca se ingestó porque los PDFs originales no están en el repo.

**Fuente alternativa a explorar antes de ir a CMF**: revisar si `cdg_extract.xlsx` (o
alguna hoja adyacente en los CDGs mensuales de la carpeta SharePoint
`Control de Gestión\CDG Mensual`) contiene una fila de gastos trimestrales del PT.
Si sí, se puede extraer sin recurrir a los PDFs.

---

## 3. Dónde están los PDFs

**Único PDF disponible localmente**:
`work/eeff_ingesta/PT/pdf/` — solo pre-2020.

**SharePoint**: `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Fondos\Rentas PT\EEFF\<YYYY>\<T>T\` → carpetas por año vacías salvo 2025/4T.

**Fuentes a probar en orden**:
1. **CMF pública** (recomendado). Los EEFF de fondos regulados se publican en:
   `https://www.cmf.cl/portal/principal/613/w3-propertyvalue-30013.html`
   Buscar "Toesca Rentas Inmobiliarias PT Fondo de Inversión" → descargar cada trimestre.
2. **Correos Deloitte/Toesca** (Outlook). Buscar `"EEFF"+"PT"` o `"Rentas Inmobiliarias PT"`.
3. Preguntar al usuario si tiene un backup local.

Los PDFs descargados deben copiarse a: `work/eeff_ingesta/PT/pdf/`.
Convención de nombres sugerida: `PT_YYYYMM.pdf` (o dejar el nombre original si tiene fecha reconocible como `2506 EEFF...`, `250630...`, etc.).

---

## 4. Estrategia de ingesta (2 vías, en este orden)

### Vía A — Extractor posicional automático (`ingest_gastos_pdf.py`)

Ya existe y es preciso para PDFs con tabla de gastos legible por `pdfplumber`. Reglas:
- Reconoce columnas YTD (`01/01/YYYY Al DD/MM/YYYY`) y descarta trimestre solo.
- Valida `sum(comp) == total` antes de persistir.
- Rechaza el periodo si no cuadra (imprime warning).

**Comando**:
```bash
python -m tools.db.ingest_gastos_pdf --fondo PT --all
```

Después:
```bash
python "C:/Users/RAIMUN~1.OPA/AppData/Local/Temp/claude/c--Users-raimundo-opazo-automation-agent/aa5f8666-9cd9-47f4-8d5f-c1c8da634cb2/scratchpad/audit_gastos.py"
```
o cualquier query equivalente:
```sql
SELECT periodo,
       SUM(CASE WHEN cuenta_codigo_canonical='ER.total_gastos_operacion' THEN monto_clp END) AS total,
       SUM(CASE WHEN cuenta_codigo_canonical<>'ER.total_gastos_operacion' THEN monto_clp END) AS suma
FROM raw_eeff_line
WHERE fondo_key='PT' AND superseded_at IS NULL
  AND cuenta_codigo_canonical LIKE 'ER.%'
GROUP BY periodo
HAVING ABS(total - suma) > 2000;
```

### Vía B — ChatGPT para PDFs que Vía A no logra

Cuando `pdfplumber` falla (PDFs escaneados, layouts raros, tablas fragmentadas), subir el PDF a ChatGPT (u otro LLM multimodal) y usar el prompt de la sección 5. El agente toma la salida JSON, valida la suma, y la persiste con el script de la sección 6.

---

## 5. Prompt para ChatGPT (extracción de gastos EEFF PT)

Copiar tal cual, adjuntar UN PDF por vez.

```
Eres un extractor de datos de EEFF de fondos de inversión chilenos (formato CMF).

Adjunto un PDF de "Toesca Rentas Inmobiliarias PT Fondo de Inversión". En la sección
"Estado de Resultados Integrales" hay una tabla con la subsección "GASTOS DE OPERACIÓN".
Esa tabla tiene 2 o 4 columnas de fechas. Solo me interesan las columnas ACUMULADAS
YTD (período que empieza el 01/01/YYYY, NO las columnas trimestrales solas que empiezan
en 01/04, 01/07 o 01/10).

Extrae, para cada columna YTD, los siguientes rubros en MILES DE PESOS (M$),
respetando el signo del PDF (los paréntesis = negativo):

- Depreciaciones
- Remuneración del Comité de Vigilancia
- Comisión de administración
- Honorarios por custodia y administración
- Costos de transacción
- Otros gastos de operación
- TOTAL GASTOS DE OPERACIÓN

Devuelve SOLO JSON válido con esta estructura EXACTA (sin markdown, sin comentarios):

{
  "fondo": "PT",
  "periodos": [
    {
      "periodo": "YYYY-MM",           // ej: "2022-06" para YTD 01/01/2022–30/06/2022
      "fecha_corte": "YYYY-MM-DD",    // ej: "2022-06-30"
      "en_miles_pesos": true,         // siempre true si el PDF dice M$
      "gastos": {
        "ER.depreciaciones": 0,
        "ER.remun_comite": -5637,
        "ER.comision_admin": -353963,
        "ER.honorarios_custodia": -60601,
        "ER.costos_transaccion": 0,
        "ER.otros_gastos": -490,
        "ER.total_gastos_operacion": -420691
      },
      "verificacion_suma": {
        "suma_componentes": -420691,
        "total_reportado": -420691,
        "cuadra": true
      }
    }
  ]
}

REGLAS ESTRICTAS:
1. NUNCA inventes valores. Si en el PDF una fila está vacía o "-", pon 0.
2. Si el signo no es claro, prefiere negativo (los gastos son negativos por convención).
3. Antes de responder, calcula suma_componentes = deprec + comite + comision + honorarios
   + costos_transaccion + otros_gastos. Si NO iguala a total_gastos_operacion
   (tolerancia 1 miles), pon "cuadra": false y agrega un campo "warning" con la
   explicación. NO invento valores para forzar cuadre.
4. Ambas columnas YTD (año actual y año comparativo) deben aparecer como periodos separados.
5. El campo "periodo" es siempre "YYYY-MM" según fecha de cierre (30/06 → "06", 30/09 → "09",
   31/12 → "12", 31/03 → "03").
6. Devuelve SOLO el JSON. Nada más.
```

**Ejemplo de output esperado** (para un PDF con corte al 30/06/2022 y comparativo 30/06/2021):

```json
{
  "fondo": "PT",
  "periodos": [
    {
      "periodo": "2022-06",
      "fecha_corte": "2022-06-30",
      "en_miles_pesos": true,
      "gastos": {"ER.depreciaciones": 0, "ER.remun_comite": -1234,
                 "ER.comision_admin": -45678, "ER.honorarios_custodia": -8765,
                 "ER.costos_transaccion": 0, "ER.otros_gastos": -321,
                 "ER.total_gastos_operacion": -55998},
      "verificacion_suma": {"suma_componentes": -55998, "total_reportado": -55998, "cuadra": true}
    },
    {
      "periodo": "2021-06",
      "fecha_corte": "2021-06-30",
      "en_miles_pesos": true,
      "gastos": {"...": "..."},
      "verificacion_suma": {"...": "..."}
    }
  ]
}
```

---

## 6. Script de persistencia (a usar con la salida JSON de ChatGPT)

Guardar como `scripts/ingest_pt_gastos_from_json.py`. El agente lo escribirá si no existe. Lógica:

```python
"""Persiste gastos PT desde JSON extraído por ChatGPT.
Uso: python scripts/ingest_pt_gastos_from_json.py <archivo.json>
"""
import json, sqlite3, sys
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent.parent / "memory" / "agente_toesca_v2.db"

COMP = ['ER.depreciaciones','ER.remun_comite','ER.comision_admin',
        'ER.honorarios_custodia','ER.costos_transaccion','ER.otros_gastos']

def main(json_path):
    data = json.loads(Path(json_path).read_text(encoding='utf-8'))
    assert data['fondo'] == 'PT'
    con = sqlite3.connect(str(DB))
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur = con.cursor()
    for p in data['periodos']:
        periodo = p['periodo']
        gastos_miles = p['gastos']
        # Convertir miles → pesos
        gastos = {k: (v * 1000 if v is not None else 0) for k, v in gastos_miles.items()}
        total = gastos['ER.total_gastos_operacion']
        s = sum(gastos.get(k, 0) for k in COMP)
        if abs(s - total) > 2000:
            print(f"  ❌ PT {periodo}: NO cuadra (sum={s:,}, total={total:,}, diff={s-total:,}) — skip")
            continue
        print(f"  ✅ PT {periodo}: OK  total={total:,}")
        # Supersede activos existentes
        for cta in gastos.keys():
            cur.execute(
                "UPDATE raw_eeff_line SET superseded_at=? "
                "WHERE fondo_key='PT' AND periodo=? AND cuenta_codigo_canonical=? "
                "AND superseded_at IS NULL",
                (now, periodo, cta))
        src = f"EEFF PT {periodo} (chatgpt json)"
        for cta, monto in gastos.items():
            cur.execute(
                """INSERT INTO raw_eeff_line
                     (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
                      source_file, source_sheet, source_row, file_hash, ingest_run_id,
                      loaded_at, cuenta_codigo_canonical)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ('PT', periodo, None, 'gpt_extract', monto, None,
                 src, 'ER (json)', None, 'gpt_extract_v1', None, now, cta))
    con.commit()
    con.close()

if __name__ == "__main__":
    main(sys.argv[1])
```

---

## 7. Flujo completo que ejecutará el agente nuevo

### Paso 1 — Diagnóstico (5 min)
```bash
# Confirmar qué falta
python -c "
import sqlite3
c = sqlite3.connect('memory/agente_toesca_v2.db')
have = {p[0] for p in c.execute(\"SELECT DISTINCT periodo FROM raw_eeff_line WHERE fondo_key='PT' AND cuenta_codigo_canonical='ER.total_gastos_operacion' AND superseded_at IS NULL AND substr(periodo,6,2) IN ('03','06','09','12')\").fetchall()}
esperados = [f'{y}-{m}' for y in range(2017,2027) for m in ('03','06','09','12')]
esperados = [p for p in esperados if (int(p[:4]),int(p[5:7])) >= (2017,12) and (int(p[:4]),int(p[5:7])) <= (2026,3)]
missing = [p for p in esperados if p not in have]
print('faltan:', missing)
"
```

### Paso 2 — Ubicar la fuente de datos (variable)
Probar en este orden y detenerse cuando algo funcione:

**2a — CDG mensual (probable atajo)**
- Abrir `cdg_extract.xlsx` (el archivo que ya está en el repo/DB) y buscar si contiene
  una fila con gastos trimestrales del PT (comisión admin, honorarios, etc). Si sí,
  extraer y saltarse el resto.
- Si no está ahí, revisar el CDG mensual completo en
  `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Control de Gestión\CDG Mensual\`
  — es donde el equipo copia los datos desde las fuentes originales.

**2b — CMF pública**
- Descargar los EEFF trimestrales de "Toesca Rentas Inmobiliarias PT" desde CMF.
- Copiar los PDFs a `work/eeff_ingesta/PT/pdf/`.
- Un PDF trimestral cubre 2 periodos (actual + comparativo del año anterior), así que
  **basta con ~15 PDFs** para cubrir los 30 faltantes.

**2c — Pedir al usuario**
- Si ninguna funciona, avisar y pedir los PDFs o los valores directamente.

### Paso 3 — Vía A automática
```bash
python -m tools.db.ingest_gastos_pdf --fondo PT --all
```
Anotar qué periodos fallaron o no se detectaron.

### Paso 4 — Vía B para lo que Vía A no cubre
Por cada PDF fallido:
1. Subirlo a ChatGPT con el prompt de la sección 5.
2. Guardar la respuesta JSON en `work/eeff_ingesta/PT/json/PT_<YYYYMM>_gpt.json`.
3. Ejecutar:
   ```bash
   python scripts/ingest_pt_gastos_from_json.py work/eeff_ingesta/PT/json/PT_<YYYYMM>_gpt.json
   ```
4. Verificar que cada periodo dijo "OK". Si un periodo dice "NO cuadra", revisar manualmente el PDF y corregir el JSON (nunca forzar el cuadre — el problema está en la extracción).

### Paso 5 — Auditoría final
```bash
python "C:/Users/RAIMUN~1.OPA/AppData/Local/Temp/claude/c--Users-raimundo-opazo-automation-agent/aa5f8666-9cd9-47f4-8d5f-c1c8da634cb2/scratchpad/audit_gastos.py"
```
Objetivo: **100/100 periodos con suma coherente** (TRI 37 + APO 29 + PT 36 = 102).

### Paso 6 — Regenerar y verificar
```bash
python scripts/build_factsheet.py
# Refrescar http://127.0.0.1:8765/factsheet.html, cambiar a PT, recorrer periodos
```

### Paso 7 — Commit
```bash
git add memory/agente_toesca_v2.db work/eeff_ingesta/PT/ scripts/ingest_pt_gastos_from_json.py
git commit -m "eeff: backfill gastos PT históricos (2017-12..2026-03), 30 trimestres"
```

---

## 8. Contexto de DB necesario (cheat sheet)

- **DB path**: `memory/agente_toesca_v2.db` (SQLite).
- **Tabla**: `raw_eeff_line` — columnas relevantes:
  - `fondo_key` (`'PT'`, `'TRI'`, `'APO'` — mayúsculas)
  - `periodo` (`'YYYY-MM'`)
  - `cuenta_codigo_canonical` (`'ER.comision_admin'`, etc.)
  - `monto_clp` (pesos, no miles)
  - `source_file`, `source_sheet`
  - `superseded_at` — NULL = activa. Al reemplazar, marcar la vieja con timestamp `'YYYY-MM-DD HH:MM:SS'`.

**Regla de oro**: nunca UPDATE de `monto_clp` directo — siempre INSERT nueva fila y superseder la vieja (patrón de auditoría).

**Enums de cuentas gasto** (los 7 canonical):
```
ER.depreciaciones
ER.remun_comite
ER.comision_admin
ER.honorarios_custodia
ER.costos_transaccion
ER.otros_gastos
ER.total_gastos_operacion   ← este DEBE cuadrar con la suma de los 6 anteriores
```

---

## 9. Criterios de éxito

- [ ] 30 trimestres PT nuevos persistidos en `raw_eeff_line`.
- [ ] Auditoría: `sum(componentes) == total_gastos_operacion` para los 36 trimestres PT.
- [ ] Fact sheet HTML: al cambiar a PT y recorrer todas las fechas contables, la tabla "Gastos del Fondo" muestra valores razonables (no guiones, no números absurdos).
- [ ] Commit hecho.

---

## 10. Referencias

- Extractor pdfplumber: `tools/db/ingest_gastos_pdf.py`
- Deduplicador raw_eeff_line: `tools/db/dedup_raw_eeff.py`
- Fact sheet builder: `scripts/build_factsheet.py`
- Regla de validación: memoria `feedback_gastos_check_suma`
- Entregable #1: memoria `project_factsheet_html_entregable`
