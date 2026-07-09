---
tipo: activo
nombre: "Apoquindo"
fondo: "Apo"
administrador: "JLL"
filas_noi: "426–456"
fuentes: 0
actualizado: 2026-05-01
---

# Apoquindo

## Datos básicos

- **Fondo**: [[fondos/ar-apoquindo]]
- **Administrador**: JLL (Nicole Carvajal)
- **Filas NOI-RCSD**: 426–456

## Fuente de datos (CDG mensual)

**Archivo**: `{AAMM} Rent Roll y NOI.xlsx`
**Hoja**: "NOI PT" (misma hoja que Parque Titanium y Apo3001)
**Función**: `actualizar_noi_apoquindo`

## ER en DB (`raw_er_activo_line`) — 2026-07

Mientras no llegan las APIs de JLL y Tres Asociados, el ER mensual de Apo4501
y Apo4700 se ingesta a la DB desde una planilla local en formato "resumen por
categoría" (10 categorías por activo por mes, sin desglose de cuenta contable).

- **Fuente**: `SHAREPOINT_DIR/raw/NOI.xlsx`, hoja `APO`
- **Ingestor**: `tools/db/ingest_er_apoquindo.py`
- **Comando**: `python -m tools.db.ingest_er_apoquindo <xlsx> [--dry-run]`
- **Destino**: `raw_er_activo_line`, `activo_key IN ('Apo4501','Apo4700')`
- **Cobertura ingestada**: 2019-01 a 2026-05 (1405 filas), idempotente por `file_hash`
- **Pseudo-códigos** (todos `es_operacional=1`): `APO_ING_ARR`, `APO_GC_VAC`,
  `APO_COM_CORR`, `APO_ADM`, `APO_PROV_REP`, `APO_BONOS_LEG`, `APO_CONSTRUCT`,
  `APO_IVA_NR`, `APO_CONTRIB`, `APO_SEG`

### Particularidades de la planilla real (`raw/NOI.xlsx`)

- Columna de etiqueta = col C (A y B vacías) — el parser la detecta
  dinámicamente, no asume col A
- Variantes de texto en el origen: mojibake de tildes en "Comisión"/
  "Administración", typo "Constultores" (por "Constructores"), "Vacancia"
  sin slash — todas mapeadas en `_CATEGORIAS`
- **"Gastos Bonos"** bajo la categoría Bono+Legales+Otros es un subtotal
  (= Apoquindo 4700 + Apoquindo 4501), no un monto adicional — el parser lo
  descarta sin pérdida de datos (verificado: suma cuadra exacto)
- **Contribuciones** viene como un solo monto combinado (sin desglose por
  activo) en los 89 meses históricos. Regla de negocio acordada 2026-07-09
  con el usuario: split **25% Apo4700 / 75% Apo4501** sobre el valor
  combinado, aplicado tanto al histórico (donde el excel no trae el
  desglose) como a los meses futuros

### Contribuciones futuras (meses sin dato en la planilla) — pendiente

Fórmula acordada 2026-07-09 para cuando la planilla no traiga el mes:

```
total_clp_mes = (-165.941.575 - 62.167.695) / 3        # constante mensual
total_uf_mes  = total_clp_mes / UF_mes                  # UF desde fact_uf
Apo4700 = 25% del total · Apo4501 = 75% del total
```

No implementado aún (fuera de alcance de la ingesta 2026-07). Ver
[docs/superpowers/specs/2026-07-09-apoquindo-er-ingesta-design.md](../../docs/superpowers/specs/2026-07-09-apoquindo-er-ingesta-design.md).

### Consultas útiles

NOI mensual por activo:
```sql
SELECT activo_key, periodo, SUM(monto_clp) AS noi_clp
  FROM raw_er_activo_line
 WHERE activo_key IN ('Apo4501','Apo4700')
   AND es_operacional=1 AND superseded_at IS NULL
 GROUP BY activo_key, periodo;
```

NOI Fondo Apo consolidado (participación 1.0 en ambos activos, ver fix
`047_fix_participacion_apo_activos.sql`):
```sql
SELECT r.periodo, SUM(r.monto_clp * a.participacion_fondo_activo) AS noi_fondo
  FROM raw_er_activo_line r
  JOIN dim_activo a ON a.activo_key = r.activo_key
 WHERE a.fondo_key = 'Apo'
   AND r.es_operacional = 1 AND r.superseded_at IS NULL
 GROUP BY r.periodo;
```

## Vínculos

- [[fondos/ar-apoquindo]]
- [[activos/apoquindo-3001]]
- [[procesos/noi-rcsd]]
