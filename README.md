# Toesca Real Estate AI Analyst

A data and reporting platform for Toesca's real-estate funds (TRI, PT, Apo) and their
underlying assets. A governed SQLite database is the single source of financial truth;
an AI Analyst workspace, a validated ingestion pipeline, and a deterministic HTML
factsheet sit on top of it.

The project also still carries a legacy piece: `agent.py`, a Gemini-based CLI agent for
Outlook/SharePoint/Excel automation, predating the data platform and not yet
decommissioned. See `docs/CURRENT_STATE.md` for exactly which surfaces are current,
which are legacy, and which are approved-but-not-yet-built.

## What's here

| Doc | For |
|---|---|
| **[docs/CURRENT_STATE.md](docs/CURRENT_STATE.md)** | What actually exists right now — canonical, evidence-checked |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | What's planned next |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Component map and data flow |
| **[AGENTS.md](AGENTS.md)** | Universal rules for any coding agent working in this repo |
| **[CLAUDE.md](CLAUDE.md)** | Claude-specific workflow notes |
| **[wiki/](wiki/index.md)** | Domain knowledge — fund structure, processes, KPI methodology |

## Architecture, in one paragraph

One Flask process (`scripts/ingesta_server.py`) serves the Analyst, the validated
ingestion wizard, the factsheet, and pilot-feedback tooling from a single SQLite database
(`memory/agente_toesca_v2.db`). The Analyst runtime (`tools/analyst_runtime/`) is
provider-neutral by design — it doesn't import any specific LLM SDK. Data flows in
through human-confirmed validation (never silently), and every number the Analyst or the
factsheet shows traces back to a governed table or view. Detail: `docs/ARCHITECTURE.md`.

## Running it locally

### Windows

```bash
git clone https://github.com/raimundoopazotoesca/Agente-Toesca.git
cd Agente-Toesca
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` — at minimum:

```env
GEMINI_API_KEY=tu_clave_de_google_ai_studio
INGESTA_TOKEN=un_secreto_local_para_el_servidor_de_ingesta
```

Run the ingesta/Analyst/factsheet server:

```bash
python -X utf8 scripts/ingesta_server.py
```

Then open `http://127.0.0.1:8765/analyst` (not the file directly — the server injects
the auth token; opening `factsheet.html` via `file://` will 401).

For the legacy Outlook/Excel agent (`agent.py`), also set
`AGENT_SERVER_API_TOKEN` (≥32 chars) if you plan to run `python agent.py --server`.

### Mac

```bash
git clone https://github.com/raimundoopazotoesca/Agente-Toesca.git
cd Agente-Toesca
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

> `pywin32` (Windows-only) is skipped automatically on Mac. `agent.py`'s Outlook
> integration (`email_tools.py`) does not work on Mac — it returns a clear error instead
> of crashing. The data platform (Analyst, ingesta, factsheet) is 100% cross-platform.

## Security

The ingesta/Analyst server binds to `127.0.0.1` by default and requires
`X-Ingesta-Token` on every `/api/*` route. Never expose it on `0.0.0.0` without a
firewall, TLS via a reverse proxy, and network access control. Never commit `.env` or
any `*_TOKEN`/`*_API_KEY` value to git.

## Git safety

See `AGENTS.md` for the full rules. In short: never `git add -A` or `git add .` — stage
files by name. Check `git status` before any command that could discard uncommitted
work. Don't push or open a PR unless explicitly asked.
