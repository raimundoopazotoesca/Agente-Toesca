# Pantalla de inicio — Menú de Ingesta

**Fecha:** 2026-07-23
**Estado:** Aprobado

## Contexto

`web/ingesta.html` (servido por `scripts/ingesta_server.py` en `/ingesta`) es una SPA con
3 tabs para ingestar datos manualmente: **EEFF**, **Rent Roll**, **Mercado Oficinas**. No
hay hoy ninguna vista que resuma qué está ingestado y qué falta por período — el usuario
tiene que abrir cada tab y usar el "periodo check" existente para descubrirlo.

## Objetivo

Agregar una **landing de estado** que se muestre al abrir `/ingesta`, antes de los tabs,
con un resumen visual de qué se ha ingestado y qué falta para cada tipo de dato
soportado por el menú.

## Alcance

Solo los 3 tipos ya presentes en el menú de ingesta manual:

| Tipo | Tabla | Columna período | Frecuencia | Agrupación |
|---|---|---|---|---|
| EEFF | `raw_eeff_line` | `periodo` (YYYY-MM, fin de trimestre) | Trimestral | `fondo_key` (TRI, PT, APO) |
| Rent Roll | `raw_rent_roll_line` | `periodo` (YYYY-MM) | Mensual | única (todos los activos juntos) |
| Mercado Oficinas | `raw_mercado_oficinas` | `periodo` (YYYY-MM, fin de trimestre) | Trimestral | única |

Nota sobre `raw_dividendo` y `raw_valor_cuota_contable`: se escriben en el mismo commit
que `raw_eeff_line` (mismo paste de ChatGPT del EEFF, no son un tipo de ingesta aparte
en el menú — ver `tools/db/ingest_eeff_validated.py::commit`). No se les crea card propia;
quedan cubiertos implícitamente por el estado de la card EEFF.

Explícitamente fuera de alcance en v1 (se ingestan por scripts fuera de este menú, no
tienen tab propio hoy): ER activos, capital suscrito, flujos, precios cuota bursátil, y
cualquier otra tabla `raw_*` no ingestada desde este menú. Se irán agregando a futuro por
configuración (ver "Extensibilidad").

Todas las consultas filtran `WHERE superseded_at IS NULL`.

## Diseño visual — Enfoque "Cards por tipo"

Se evaluaron 3 layouts (grilla matriz, cards, híbrido) mediante mockup HTML con datos
reales de la DB. Se eligió **Cards**: una card por tipo de dato, cada una con:

1. **Título y subtítulo** — nombre del tipo + frecuencia/alcance (ej. "EEFF — Trimestral · TRI, PT, Apo")
2. **Último ingestado** — período más reciente con datos, en verde
3. **Próximo pendiente** — período que falta y ya debería estar ingestado, en rojo (ver regla abajo). Si no hay pendiente vencido, se muestra "Al día" en vez de rojo.
4. **Timeline de puntos** — últimos N períodos como dots (verde = ingestado, rojo = falta, gris = no aplica todavía / futuro). N=4 para tipos trimestrales (EEFF, Mercado), N=6 para Rent Roll (mensual).
5. **Botón "Ingestar →"** — navega al tab correspondiente y preselecciona el período pendiente en el selector de ese tab.

Paleta y componentes: sin cambios respecto al estilo ya usado en `web/ingesta.html`
(verde/rojo/gris para estado, tipografía y superficies existentes). Ver mockup en
`ingesta-mockups.html` (aprobado, Opción B) para la referencia visual exacta de la card.

## Regla de "pendiente"

Para cada tipo:

1. Calcular el período "esperado" según la frecuencia del tipo (ambos tipos trimestrales
   — EEFF y Mercado Oficinas — usan la misma regla):
   - Trimestral → trimestre recién cerrado (ej. hoy 2026-07-23 → T2 2026, cerrado el
     2026-06-30; T3 2026 aún no cierra y no cuenta como esperado)
   - Mensual (Rent Roll) → mes recién cerrado (ej. hoy 2026-07-23 → Jun 2026)
2. Si ese período (o uno anterior a él) no está en la tabla → se marca **pendiente/falta** (rojo).
3. Si el último ingestado ya cubre el período esperado → **"Al día"**, sin urgencia.

Para EEFF, replica la lógica ya usada en `periodo_check` existente del tab EEFF (reutilizar,
no duplicar).

## Backend

Nuevo endpoint `GET /api/estado_ingesta` en `scripts/ingesta_server.py`:

- Consulta las 3 tablas agrupando por período (y por `fondo_key` en el caso de EEFF).
- Arma un payload JSON con, por tipo: lista de períodos recientes ingestados,
  último período, período pendiente (o null si al día).
- Sin nueva tabla ni cache — queries directas on-demand (tablas chicas, sin costo
  relevante). Reutiliza la lógica de cálculo de "período esperado" ya existente donde
  aplique (EEFF) en vez de duplicarla.

## Frontend

- Nueva vista landing en `web/ingesta.html`, mostrada por defecto al cargar la página.
- Los 3 tabs actuales (EEFF/Rent Roll/Mercado) siguen existiendo y accesibles por
  navegación normal; la landing no los reemplaza, se antepone.
- Click en botón "Ingestar →" de una card:
  - Cambia a la vista/tab correspondiente.
  - Preselecciona el período pendiente en el selector de fondo/trimestre/mes de ese tab.

## Extensibilidad

Para agregar un tipo nuevo al menú en el futuro:

1. Agregar una entrada a una lista de configuración en el backend (tabla, columna
   período, frecuencia, agrupación/fondos aplicables, tab destino).
2. La card correspondiente se genera automáticamente sin tocar HTML/CSS.

No se implementa esta configuración de forma genérica más allá de lo necesario para los
3 tipos actuales — se estructura el código para que sea fácil de extender (lista de
dicts de config), sin sobre-diseñar un sistema de plugins.

## Fuera de alcance

- No se toca `ingest_run` ni se agrega tracking nuevo — se lee directamente de las
  tablas `raw_*`.
- No se agregan los demás tipos de dato de la DB (ER, dividendos, etc.) en esta
  iteración.
- No se cachea el resultado del endpoint — se recalcula en cada carga de página.
