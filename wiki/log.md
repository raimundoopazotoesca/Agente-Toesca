# Log — Wiki Agente Toesca

> Log cronológico append-only. Una entrada por operación.
> Parsear últimas entradas: `grep "^## \[" wiki/log.md | tail -10`

## [2026-05-12] feat | EERR Viña Centro implementado en Balance Consolidado Rentas Nuevo

`VINA_EERR_MAP` (73 filas) en `tools/balance_consolidado_tools.py`. Fuente: hoja `BALANCE ACUMULADO` del INFORME EEFF Viña. Mapeado por descripción/valor en vez de strictly por label code: 7 filas re-mapeadas (94, 97, 113, 119, 120, 123, 137) por desalineación entre label y chart of accounts real del TB. Verificado Dec 2025: total G-Pd = 3.093.097.786 = D189 histórico (2.848.461.407) + D194 control (244.636.379) — el map nuevo elimina ese descuadre histórico de 244M. 0 cuentas EERR del TB quedan sin mapear. Wireado reemplazando `EERR: TODO` en `actualizar_balance_consolidado_rentas_nuevo`.

## [2026-05-12] feat | EERR Curicó implementado en Balance Consolidado Rentas Nuevo

`CURICO_EERR_MAP` (57 filas) en `tools/balance_consolidado_tools.py`. Códigos extraídos de los labels en col B filas 76-168 hoja `Curicó` del vF. Fuente: hoja `Acum MM-AAAA` del informe Curicó (misma que el balance). Verificado vs trial balance Dec 2025: resultado del período -405.776.897 calza con D174 histórico, 0 diferencias en las 57 filas. Wireado en `actualizar_balance_consolidado_rentas_nuevo` reemplazando el `EERR: TODO`. Fila 162 (`4-2-01-004`) duplica la 94 — se omite.

## [2026-05-11] feat | EERR Chañarcillo implementado en Balance Consolidado Rentas Nuevo

`CHANAR_EERR_MAP` (31 filas) en `tools/balance_consolidado_tools.py`. Códigos extraídos de los labels en col B filas 76-116 de la hoja Chañarcillo. Verificado vs trial balance Dec 2025: resultado del período 470.785.569 calza con D119 histórico.

**Observación importante:** los valores históricos en col D del planilla estaban desalineados respecto a sus labels — quien llenaba históricamente puso COMISIONES en la fila labelada ESTRUCTURACION, etc. (7 filas afectadas, rango 93-99). El nuevo map sigue el código del label (criterio contable correcto), por lo que los valores escritos en esas filas cambiarán respecto al histórico.

**Pendiente identificado:** bug `_copy_vals_sheet_rn` falla con `'MergedCell' object attribute 'value' is read-only` al copiar Resumen PT/Apoquindo. Hay que saltar celdas merged.

## [2026-05-11] fix | INMOSA — distinguir ER-FC vs Balance General + reconocer naming nuevo

Dos archivos distintos compartían carpetas mal asignadas:
- **ER-FC INMOSA** (estado de resultado + flujo de caja) → `INMOSA/Flujos/` — usado por CDG/NOI-RCSD.
- **Balance General Senior Assist** → `INMOSA/Contabilidad/` — usado por balance consolidado.

Desde 2026 el ER-FC viene nombrado `EEFF y FC Senior Assist Mar.26.xlsx` (sin "INMOSA" ni "ER-FC" en el nombre). `raw_tools.py` lo ruteaba a Contabilidad por matchear "senior assist", y `buscar_er_inmosa` no lo encontraba (filtraba por `"inmosa" in nombre`).

Cambios:
- `tools/raw_tools.py`: ruta ER-FC si nombre contiene "EEFF/FC" + "Senior Assist"; ruta Contabilidad solo si contiene "Balance" + "Senior Assist".
- `tools/noi_tools.py::buscar_er_inmosa`: matchea "inmosa" o "senior assist", excluye "balance".
- `tools/gestion_renta_tools.py`: el chequeo de "mes en filename" fallaba ("Ene a Feb" no implica que falte marzo). Ahora solo se valida existencia.
- Archivo `EEFF y FC Senior Assist Mar.26.xlsx` movido de Contabilidad/2026 → Flujos/2026.

## [2026-05-07] feat | Balance Consolidado Rentas Nuevo — implementación parcial

Implementada `actualizar_balance_consolidado_rentas_nuevo(mes, año)` en `tools/balance_consolidado_tools.py`.
Balance de 4 entidades (Chañarcillo, Curicó, Inmob VC, Viña Centro) + EERR Inmosa desde Senior Assist.
Copy de hojas PT/Apoquindo desde sus vAgente. Pendiente: EERR de 4 entidades, balance Inmosa Q1-Q3, Fondo Rentas PDF.
Instrucciones completas en `wiki/procesos/balance-consolidado-rentas-nuevo.md`.

---

## [2026-05-07] reorganización | SharePoint restructurado + carpeta RAW + raw_tools

- Nueva estructura: `Fondos/{Rentas Apoquindo|Rentas PT|Rentas TRI|Renta Residencial}/` agrupa EEFF, Fact Sheets y activos por fondo
- Activos de TRI (Viña, Curicó, INMOSA) ahora en `Fondos/Rentas TRI/Activos/{activo}/{EEFF|Rent Roll}/`
- CDG mensual: estructura canonica en `Control de Gestión/CDG Mensual/`
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
- Fuente EEFF: SharePoint/Fondos/Rentas PT/EEFF/{año}/{TT}/
- Fuente planilla vF: SharePoint/Control de Gestión/Balances Consolidados/
- Pendiente: mapeo Inmob Boulevard, Torre A (fuente desconocida), EEFF trimestrales

## [2026-05-01] init | Wiki creada

- Estructura inicial creada: `raw/`, `wiki/agente/`, `fondos/`, `activos/`, `procesos/`, `conceptos/`, `errores/`
- CLAUDE.md escrito con schema completo de la wiki
- `index.md` inicializado con páginas semilla basadas en CLAUDE.md del agente
- `log.md` iniciado
- Páginas semilla creadas en todas las categorías
- Fuentes ingresadas: 0 — wiki lista para primer ingest real
