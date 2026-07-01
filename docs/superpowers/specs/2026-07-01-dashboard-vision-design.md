# Vision: Toesca Dashboard — Diseño Estratégico

**Fecha:** 2026-07-01  
**Estado:** Norte estratégico — implementación incremental

---

## Problema

El proyecto arrancó como un agente de chat (CLI/Streamlit) para automatizar tareas manuales del CDG. El enfoque ha madurado: el producto final debe ser una **web app con dashboard** donde los datos del portfolio se visualizan de forma interactiva, y el agente pasa a ser una herramienta secundaria de soporte.

---

## Visión del producto

Una página web con login donde el equipo de Toesca puede ver toda la información relevante del portfolio graficada e interactiva — filtrable por fecha, fondo y activo. El agente conversacional existe como burbuja flotante para consultas puntuales.

---

## Flujo de datos (canónico e inamovible)

```
Archivos externos (Excel, PDF, SharePoint)
        ↓  ingesta via agente (tools/db/ingest_*.py)
agente_toesca.db  ←  única fuente de verdad
        ↓  queries (tools/db/repo_*.py + SQL views)
Streamlit pages (gráficos Plotly, tablas interactivas)
```

**Regla:** Ninguna página del dashboard calcula nada. Solo lee desde la DB (tablas raw, derived_kpi, o views). Si un KPI no está en la DB, no aparece en el dashboard. Esto mantiene la DB como contrato estable.

---

## Arquitectura

### Stack
- **Frontend:** Streamlit multi-página con Plotly para gráficos
- **Backend/datos:** SQLite (`agente_toesca.db`) con repos Python (`tools/db/`)
- **Auth:** `streamlit-authenticator` (igual al actual) + `login_template.html` custom
- **Agente:** `agent.py` con Gemini, integrado como burbuja flotante

### Estructura de archivos

```
app.py                    # entrada principal — solo login + routing
pages/                    # una página = una sección del dashboard
    01_overview.py
    02_rentabilidades.py
    ...
components/
    chat_bubble.py        # burbuja flotante con agent.py
tools/db/                 # repos y migraciones (sin cambios)
memory/agente_toesca.db   # única fuente de verdad
```

El `app.py` actual (chat-first) se reemplaza. El login, `style.css`, `login_template.html` y `agent.py` se reutilizan sin cambios.

---

## Principios de desarrollo incremental

1. **DB primero:** Antes de crear una página del dashboard, los datos que muestra deben existir y ser confiables en la DB.
2. **Una página a la vez:** Cada sprint agrega una página nueva. El resto del dashboard no se toca.
3. **Sin cálculos en el frontend:** Todo KPI se consolida en `derived_kpi` o en una view SQL antes de aparecer en pantalla.
4. **Agente como ingesta:** El rol principal del agente Gemini es ingestar archivos y consolidar cálculos en la DB — no responder preguntas.

---

## Páginas previstas (orden tentativo, sujeto a disponibilidad de datos)

| Página | Datos requeridos en DB | Estado datos |
|--------|------------------------|--------------|
| Rentabilidades (TIR / YTD / U12M / DY) | `derived_kpi`, `fact_precio_cuota`, `fact_dividendo` | TRI: completo |
| NOI por activo | `raw_er_activo`, views NOI | parcial |
| Vacancia | `raw_rent_roll_line` | parcial |
| Deuda / LTV / Caja | `raw_deuda_saldo_line`, `raw_caja_line` | parcial |
| Overview ejecutivo | composición de las anteriores | — |

---

## Lo que NO cambia

- `agent.py`, `config.py`, `tools/` (excepto adiciones)
- Schema DB existente (solo se agregan tablas/views, nunca se rompe lo existente)
- Login y autenticación
- `style.css` y branding Toesca
