# Log — Wiki Agente Toesca

> Log cronológico append-only. Una entrada por operación.
> Parsear últimas entradas: `grep "^## \[" wiki/log.md | tail -10`

## [2026-05-07] feat | Balance Consolidado Rentas Nuevo — implementación parcial

Implementada `actualizar_balance_consolidado_rentas_nuevo(mes, año)` en `tools/balance_consolidado_tools.py`.
Balance de 4 entidades (Chañarcillo, Curicó, Inmob VC, Viña Centro) + EERR Inmosa desde Senior Assist.
Copy de hojas PT/Apoquindo desde sus vAgente. Pendiente: EERR de 4 entidades, balance Inmosa Q1-Q3, Fondo Rentas PDF.
Instrucciones completas en `wiki/procesos/balance-consolidado-rentas-nuevo.md`.

---

## [2026-05-07] reorganización | SharePoint restructurado + carpeta RAW + raw_tools

- Nueva estructura: `Fondos/{Apoquindo|Parque Titanium|Rentas TRI}/` agrupa EEFF, Fact Sheets y activos por fondo
- Activos de TRI (Viña, Curicó, INMOSA) ahora en `Fondos/Rentas TRI/Activos/{activo}/{EEFF|Rent Roll}/`
- CDG mensual: `Controles de Gestión/.../` → `Control de Gestión/CDG Mensual/`
- Saldo Caja, Balances, TIR bajo `Control de Gestión/`
- Carpeta `RAW/` creada: usuario sube archivos, agente llama `ordenar_archivos_raw()` para clasificarlos
- Código actualizado: 7 tool files + registry.py + raw_tools.py (nuevo)
- Bug corregido en `factsheet_tools.py`: eliminado `_INMOBILIARIO` que causaba double-nesting

## [2026-05-07] integración | Power Automate — servidor HTTP + flujos recomendados

- `run_agent()` ahora retorna `str` (antes era `None`)
- Agregado `start_server()` en `agent.py` — Flask en puerto 5000 vía `python agent.py --server`
- Endpoints: `POST /run {"instruction": "..."}` y `GET /health`
- Wiki: `integraciones/power-automate.md` con flujos PA y framework de evaluación
- Flask 3.1.3 instalado

## [2026-05-06] aprendizaje | Estructura TRI desde diagrama validado

- Registrada estructura de Toesca Rentas Inmobiliarias con sociedades, participaciones y activos finales.
- Machalí marcado como liquidado; no debe considerarse activo vigente.
- Pesos históricos del diagrama rebajados pro forma excluyendo Machalí: base 96%.
- Fuente: diagrama enviado por usuario y confirmaciones del usuario en conversación.

## [2026-05-04] aprendizaje | Balance Consolidado PT documentado

- Mapeada hoja Fondo PT: clasificaciones, unidades (M$×1000), procedimiento inserción columna
- Verificado cruce EEFF 4Q2025 → planilla: Total Activo, Patrimonio, Resultado cuadran
- Fuente EEFF: SharePoint/Fondo Rentas PT/EEFF/{año}/{TT}/
- Fuente planilla vF: SharePoint/Controles de Gestión/Renta Comercial/Balances Consolidados/
- Pendiente: mapeo Inmob Boulevard, Torre A (fuente desconocida), EEFF trimestrales

## [2026-05-01] init | Wiki creada

- Estructura inicial creada: `raw/`, `wiki/agente/`, `fondos/`, `activos/`, `procesos/`, `conceptos/`, `errores/`
- CLAUDE.md escrito con schema completo de la wiki
- `index.md` inicializado con páginas semilla basadas en CLAUDE.md del agente
- `log.md` iniciado
- Páginas semilla creadas en todas las categorías
- Fuentes ingresadas: 0 — wiki lista para primer ingest real
