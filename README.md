# Plataforma de Inteligencia Financiera — Toesca

Plataforma local para los fondos inmobiliarios de Toesca (**PT**, **TRI**, **Apoquindo**):
ingesta de datos (rent roll, EEFF, ER, flujos, mercado), una base SQLite como
fuente única de verdad, un fact sheet HTML generado desde la DB, y un asistente
conversacional ("Analyst") para consultar el portafolio en lenguaje natural.

Complementa (sin depender de) el **Asistente Virtual Inmobiliario Toesca**
(`agent.py`), un agente CLI más antiguo para automatizar Outlook, SharePoint y
Excel.

## Componentes

| Componente | Qué hace | Cómo se ejecuta |
|---|---|---|
| **Servidor local** (`scripts/ingesta_server.py`) | Sirve ingesta, factsheet, Analyst y pilot control por HTTP en `127.0.0.1:8765` | `ingesta.bat` o `python -X utf8 -m scripts.ingesta_server` |
| **Base de datos** (`memory/agente_toesca_v2.db`) | SQLite: fuente única de verdad de todos los fondos/activos | consultada por todo lo demás |
| **Fact sheet** (`factsheet.html`) | Reporte HTML autocontenido con KPIs por fondo, generado desde la DB | `scripts/build_factsheet.py` |
| **Analyst** (`tools/analyst*`, `web/analyst.html`) | Chat que responde preguntas del portafolio contra la DB, con feedback y control center para pilotos | vía servidor local |
| **Asistente CLI** (`agent.py`) | Automatiza Outlook/SharePoint/Excel (planillas CDG, NOI-RCSD, rent roll, factsheets PPTX) | `python -X utf8 agent.py` |

## Requisitos

- Python 3.11+
- Windows para el Asistente CLI (usa Outlook vía COM); el servidor local y la
  DB son multiplataforma

## Instalación

```bash
git clone https://github.com/raimundoopazotoesca/Agente-Toesca.git
cd Agente-Toesca
pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
```

Editar `.env` (ver comentarios en `.env.example` para cada variable):

```env
GEMINI_API_KEY=...              # solo requerido por agent.py (Asistente CLI)
INGESTA_TOKEN=...               # fijo, o se genera uno por sesión al arrancar
SHAREPOINT_DIR=...              # OneDrive sincronizado, solo lo usa agent.py
RENTA_COMERCIAL_DIR=...         # solo lo usa agent.py
```

> `pywin32` (Outlook) se instala solo en Windows; en Mac se omite automáticamente.

## Uso — Plataforma local (ingesta, factsheet, Analyst)

```bash
python -X utf8 -m scripts.ingesta_server
```

o en Windows, doble clic en `ingesta.bat`. Levanta el servidor en
`http://127.0.0.1:8765` con:

- `/ingesta` — carga de rent roll, EEFF, ER, flujos, mercado, parking, caja, etc.
- `/factsheet` — fact sheet HTML + Analyst embebido (**no abrir el .html directo
  con doble clic**: sin el token inyectado por el servidor, el Analyst responde 401)
- `/analyst` — chat completo del portafolio
- `/pilot-control`, `/pilot-feedback` — panel de administración del piloto
- `/login` — autenticación de usuarios del piloto

Todo endpoint `/api/*` exige el header `X-Ingesta-Token` (tomado de
`INGESTA_TOKEN` o impreso al arrancar si no está definido). El servidor lo
inyecta automáticamente en las páginas que sirve, así que el flujo por
navegador funciona sin configuración extra.

### Regenerar el fact sheet manualmente

```bash
python -X utf8 -m scripts.build_factsheet
```

## Uso — Asistente CLI (Outlook / SharePoint / Excel)

```bash
python -X utf8 agent.py
```

Automatiza planillas CDG Rentas Comerciales, hoja NOI-RCSD, validación de rent
roll, y actualización de fact sheets PPTX (PT/APO/TRI legado). Ver
`python agent.py --server` para exponerlo como servicio HTTP interno (requiere
`AGENT_SERVER_API_TOKEN` de al menos 32 caracteres; escucha solo en
`127.0.0.1` por defecto — no exponer en `0.0.0.0` sin firewall/TLS/control de
acceso).

## Arquitectura del código

```
agent.py                    # Asistente CLI: loop de conversación, system prompt
config.py                   # variables de entorno
scripts/
  ingesta_server.py         # servidor Flask: ingesta + factsheet + Analyst + pilot control
  build_factsheet.py        # genera factsheet.html desde la DB
  ingest_eeff.py            # EEFF (PDF vía MarkItDown/LLM) → raw_eeff_line
  ...                       # scripts puntuales de backfill/consolidación
tools/
  db/                       # conexión, migraciones, ingesta validada por dominio
  analyst/                  # resolución de entidades, ambigüedad, contexto temporal
  analyst_workspace/        # conversaciones, feedback, servicio del chat Analyst
  registry.py                # tools del Asistente CLI (TOOL_DEFINITIONS, dispatch)
  email_tools.py, sharepoint_tools.py, excel_tools.py, ...  # tools del Asistente CLI
web/
  ingesta.html, analyst.html, pilot_control.html, pilot_feedback.html, login.html
memory/
  agente_toesca_v2.db       # DB canónica de negocio (EEFF, rent roll, precios, KPIs)
  agente_state.db           # historial de chat y contexto por usuario
wiki/                       # memoria acumulativa del proyecto (vault Obsidian)
docs/                       # guías y planes de arquitectura
tests/                      # pytest — 140+ casos
```

Detalle de la base de datos, convenciones de claves de fondo, y el flujo
mensual de planillas: ver `CLAUDE.md` (contexto del proyecto) y
`docs/db-poblar-fondos.md`.

## Tests

```bash
pytest
```

## Seguridad

- Todo `/api/*` del servidor local exige `X-Ingesta-Token`
  (`hmac.compare_digest`); CORS restringido a `localhost:8765`.
- El servidor opcional de `agent.py --server` rechaza arrancar sin
  `AGENT_SERVER_API_TOKEN` de ≥32 caracteres.
- `.env` nunca se sube a Git (está en `.gitignore`); cada máquina mantiene el
  suyo con sus propias rutas y tokens.

## Sincronizar entre computadores

```bash
git add -A && git commit -m "descripción" && git push   # subir
git pull                                                  # bajar
```
