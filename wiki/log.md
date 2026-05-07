# Log — Wiki Agente Toesca

> Log cronológico append-only. Una entrada por operación.
> Parsear últimas entradas: `grep "^## \[" wiki/log.md | tail -10`

---

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
