from __future__ import annotations

import json
import sqlite3
import base64
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"
OUT_PATH = ROOT / "web" / "db_diagrama_interactivo.html"
ASSETS = ROOT / "assets"


DOMAIN_META = {
    "dimensiones": {"label": "Dimensiones", "color": "#2f80ed"},
    "raw_finanzas": {"label": "Raw financiero", "color": "#00a676"},
    "raw_operacional": {"label": "Raw operacional", "color": "#f2994a"},
    "facts": {"label": "Facts", "color": "#9b51e0"},
    "derived": {"label": "KPIs derivados", "color": "#eb5757"},
    "audit": {"label": "Auditoria", "color": "#828282"},
    "views": {"label": "Vistas", "color": "#56ccf2"},
}

DOMAIN_ORDER = [
    "dimensiones",
    "raw_finanzas",
    "raw_operacional",
    "facts",
    "derived",
    "audit",
    "views",
]

RELATION_TARGETS = {
    "activo_key": ("dim_activo", "activo_key"),
    "fondo_key": ("dim_fondo", "fondo_key"),
    "fondo_padre": ("dim_fondo", "fondo_key"),
    "nemotecnico": ("dim_serie", "nemotecnico"),
    "credito_key": ("dim_credito", "credito_key"),
    "sociedad_key": ("dim_sociedad", "sociedad_key"),
    "cuenta_codigo": ("dim_cuenta_eeff", "cuenta_codigo"),
    "ingest_run_id": ("ingest_run", "id"),
    "run_id": ("ingest_run", "id"),
    "concepto_id": ("dim_concepto_parking", "id"),
}

FACET_COLUMNS = {
    "fondo_key",
    "activo_key",
    "nemotecnico",
    "credito_key",
    "sociedad_key",
    "cuenta_codigo",
    "entidad_tipo",
    "entidad_key",
    "kpi",
    "variante",
    "tipo",
    "proveedor",
    "submercado",
    "clase",
    "acreedor",
    "herramienta",
    "tool",
    "status",
}


def data_uri(filename: str) -> str:
    data = (ASSETS / filename).read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def classify(name: str, object_type: str) -> str:
    if object_type == "view":
        return "views"
    if name.startswith("dim_"):
        return "dimensiones"
    if name == "derived_kpi":
        return "derived"
    if name in {"ingest_run", "schema_version"}:
        return "audit"
    if name.startswith("fact_"):
        return "facts"
    if name.startswith("raw_parking") or name in {
        "raw_er_activo_line",
        "raw_flujo_line",
        "raw_rent_roll_line",
        "raw_mercado_oficinas",
    }:
        return "raw_operacional"
    return "raw_finanzas"


def simplify_value(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str)):
        if isinstance(value, str) and len(value) > 140:
            return value[:137] + "..."
        return value
    return str(value)


def count_rows(cur: sqlite3.Cursor, name: str) -> int | None:
    try:
        return int(cur.execute(f"SELECT COUNT(*) FROM {quote_ident(name)}").fetchone()[0])
    except sqlite3.Error:
        return None


def date_ranges(cur: sqlite3.Cursor, name: str, columns: list[dict[str, Any]]) -> list[dict[str, str]]:
    ranges: list[dict[str, str]] = []
    for col in columns:
        column = col["name"]
        lc = column.lower()
        if "fecha" not in lc and "periodo" not in lc and lc not in {"vigente_hasta", "applied_at", "loaded_at", "computed_at", "started_at", "ended_at"}:
            continue
        try:
            row = cur.execute(
                f"SELECT MIN({quote_ident(column)}), MAX({quote_ident(column)}) "
                f"FROM {quote_ident(name)} WHERE {quote_ident(column)} IS NOT NULL"
            ).fetchone()
        except sqlite3.Error:
            continue
        if row and (row[0] is not None or row[1] is not None):
            ranges.append({"column": column, "min": str(row[0]), "max": str(row[1])})
    return ranges[:6]


def facets(cur: sqlite3.Cursor, name: str, columns: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    column_names = {c["name"] for c in columns}
    for column in sorted(column_names & FACET_COLUMNS):
        try:
            rows = cur.execute(
                f"SELECT {quote_ident(column)}, COUNT(*) AS n FROM {quote_ident(name)} "
                f"WHERE {quote_ident(column)} IS NOT NULL "
                f"GROUP BY {quote_ident(column)} ORDER BY n DESC, {quote_ident(column)} LIMIT 12"
            ).fetchall()
        except sqlite3.Error:
            continue
        if rows and len(rows) <= 12:
            out[column] = [{"value": simplify_value(value), "count": count} for value, count in rows]
        elif rows:
            out[column] = [{"value": simplify_value(value), "count": count} for value, count in rows[:8]]
    return out


def sample_rows(cur: sqlite3.Cursor, name: str, object_type: str, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if object_type != "table" or not columns:
        return []
    select_cols = columns[: min(len(columns), 9)]
    order_by = ""
    pk_cols = [c["name"] for c in columns if c["pk"]]
    if pk_cols:
        order_by = " ORDER BY " + ", ".join(quote_ident(c) for c in pk_cols)
    col_sql = ", ".join(quote_ident(c["name"]) for c in select_cols)
    try:
        rows = cur.execute(f"SELECT {col_sql} FROM {quote_ident(name)}{order_by} LIMIT 3").fetchall()
    except sqlite3.Error:
        return []
    result = []
    for row in rows:
        result.append({col["name"]: simplify_value(row[idx]) for idx, col in enumerate(select_cols)})
    return result


def index_summary(cur: sqlite3.Cursor, name: str) -> list[dict[str, Any]]:
    indexes: list[dict[str, Any]] = []
    try:
        rows = cur.execute(f"PRAGMA index_list({quote_ident(name)})").fetchall()
    except sqlite3.Error:
        return indexes
    for seq, idx_name, unique, origin, partial in rows:
        try:
            cols = [r[2] for r in cur.execute(f"PRAGMA index_info({quote_ident(idx_name)})").fetchall()]
        except sqlite3.Error:
            cols = []
        indexes.append(
            {
                "name": idx_name,
                "unique": bool(unique),
                "origin": origin,
                "partial": bool(partial),
                "columns": cols,
            }
        )
    return indexes[:8]


def collect_metadata() -> dict[str, Any]:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"No existe la DB canonica: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    objects_raw = cur.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name"
    ).fetchall()
    object_names = {name for _, name, _ in objects_raw}

    objects: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    for object_type, name, sql in objects_raw:
        columns = [
            {
                "cid": cid,
                "name": col_name,
                "type": col_type or "",
                "notnull": bool(notnull),
                "default": default,
                "pk": bool(pk),
            }
            for cid, col_name, col_type, notnull, default, pk in cur.execute(f"PRAGMA table_info({quote_ident(name)})").fetchall()
        ]
        domain = classify(name, object_type)

        try:
            fk_rows = cur.execute(f"PRAGMA foreign_key_list({quote_ident(name)})").fetchall()
        except sqlite3.Error:
            fk_rows = []
        for fk in fk_rows:
            _, _, target_table, from_col, to_col, *_ = fk
            if target_table in object_names:
                edges.append(
                    {
                        "from": name,
                        "to": target_table,
                        "fromColumn": from_col,
                        "toColumn": to_col,
                        "kind": "declared",
                    }
                )

        column_names = {c["name"] for c in columns}
        for from_col, (target_table, to_col) in RELATION_TARGETS.items():
            if from_col in column_names and target_table in object_names and name != target_table:
                edge = {
                    "from": name,
                    "to": target_table,
                    "fromColumn": from_col,
                    "toColumn": to_col,
                    "kind": "inferred",
                }
                if edge not in edges:
                    edges.append(edge)

        row_count = count_rows(cur, name)
        objects.append(
            {
                "name": name,
                "type": object_type,
                "domain": domain,
                "domainLabel": DOMAIN_META[domain]["label"],
                "rowCount": row_count,
                "columnCount": len(columns),
                "columns": columns,
                "dateRanges": date_ranges(cur, name, columns),
                "facets": facets(cur, name, columns) if object_type == "table" else {},
                "indexes": index_summary(cur, name) if object_type == "table" else [],
                "sampleRows": sample_rows(cur, name, object_type, columns),
                "hasSql": bool(sql),
            }
        )

    schema_version = None
    if "schema_version" in object_names:
        schema_version = cur.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    groups = []
    for key in DOMAIN_ORDER:
        count = sum(1 for obj in objects if obj["domain"] == key)
        groups.append({**DOMAIN_META[key], "key": key, "count": count})

    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "dbPath": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "schemaVersion": schema_version,
        "tableCount": sum(1 for obj in objects if obj["type"] == "table"),
        "viewCount": sum(1 for obj in objects if obj["type"] == "view"),
        "totalRows": sum(obj["rowCount"] or 0 for obj in objects if obj["type"] == "table"),
        "groups": groups,
        "objects": objects,
        "edges": edges,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Diagrama interactivo DB Toesca</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #101214;
    --panel: #181b1f;
    --panel-2: #20242a;
    --line: #343a42;
    --text: #eff3f6;
    --muted: #a5afb9;
    --quiet: #717b86;
    --accent: #00a676;
    --warn: #f2994a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg);
    color: var(--text);
  }
  header {
    border-bottom: 1px solid var(--line);
    background: #14171a;
    padding: 18px 24px 14px;
  }
  h1 {
    margin: 0;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0;
  }
  .subhead {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    align-items: center;
    margin-top: 8px;
    color: var(--muted);
    font-size: 13px;
  }
  .statbar {
    display: grid;
    grid-template-columns: repeat(5, minmax(120px, 1fr));
    gap: 10px;
    padding: 14px 24px;
    border-bottom: 1px solid var(--line);
    background: #121518;
  }
  .stat {
    min-height: 58px;
    padding: 10px 12px;
    background: var(--panel);
    border: 1px solid #2b3037;
    border-radius: 8px;
  }
  .stat strong { display: block; font-size: 20px; line-height: 1.1; }
  .stat span { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; }
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 390px;
    min-height: calc(100vh - 154px);
  }
  .workspace {
    min-width: 0;
    border-right: 1px solid var(--line);
    display: flex;
    flex-direction: column;
  }
  .toolbar {
    display: grid;
    grid-template-columns: minmax(180px, 1fr) 190px 150px 150px 120px;
    gap: 10px;
    padding: 12px 14px;
    border-bottom: 1px solid var(--line);
    background: #15191d;
  }
  input, select, button {
    width: 100%;
    min-height: 36px;
    border-radius: 7px;
    border: 1px solid #3a414a;
    background: #0f1215;
    color: var(--text);
    padding: 0 10px;
    font: inherit;
    font-size: 13px;
  }
  button {
    cursor: pointer;
    background: #20262d;
  }
  button:hover { border-color: #5a6571; background: #262d35; }
  .diagram-wrap {
    position: relative;
    flex: 1;
    min-height: 620px;
    overflow: hidden;
  }
  svg {
    display: block;
    width: 100%;
    height: 100%;
    background:
      linear-gradient(#1b2025 1px, transparent 1px),
      linear-gradient(90deg, #1b2025 1px, transparent 1px);
    background-size: 28px 28px;
  }
  .edge {
    fill: none;
    stroke-width: 1.3;
    opacity: 0.24;
  }
  .edge.declared { stroke-width: 2.1; opacity: 0.44; }
  .edge.selected { opacity: 0.95; stroke-width: 3; }
  .domain-title {
    font-size: 12px;
    fill: #c8d0d8;
    font-weight: 700;
  }
  .domain-count {
    font-size: 11px;
    fill: #7f8a96;
  }
  .node { cursor: pointer; }
  .node rect {
    stroke: #424a54;
    stroke-width: 1;
    rx: 8;
  }
  .node text { pointer-events: none; }
  .node .name {
    fill: #f5f8fb;
    font-size: 12px;
    font-weight: 700;
  }
  .node .meta {
    fill: #b5bec8;
    font-size: 10.5px;
  }
  .node .badge {
    fill: #0d1012;
    opacity: 0.74;
  }
  .node .badge-text {
    fill: #d9e1e8;
    font-size: 9.5px;
    font-weight: 700;
  }
  .node.dimmed { opacity: 0.13; }
  .node.hidden, .edge.hidden { display: none; }
  .node.selected rect {
    stroke: #ffffff;
    stroke-width: 2;
    filter: drop-shadow(0 0 10px rgba(255,255,255,0.22));
  }
  aside {
    min-width: 0;
    background: #15181c;
    display: flex;
    flex-direction: column;
  }
  .panel-head {
    padding: 16px 16px 12px;
    border-bottom: 1px solid var(--line);
  }
  .panel-head h2 {
    margin: 0 0 8px;
    font-size: 18px;
    letter-spacing: 0;
    word-break: break-word;
  }
  .pill-row { display: flex; flex-wrap: wrap; gap: 6px; }
  .pill {
    border: 1px solid #3b434d;
    border-radius: 999px;
    padding: 4px 8px;
    color: #d8dee5;
    background: #20242a;
    font-size: 11px;
  }
  .panel-body {
    overflow: auto;
    padding: 14px 16px 22px;
  }
  .section { margin-bottom: 18px; }
  .section h3 {
    margin: 0 0 8px;
    color: #f3f6f8;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: .08em;
  }
  .kv {
    display: grid;
    grid-template-columns: 130px minmax(0, 1fr);
    gap: 6px 10px;
    font-size: 12px;
    color: var(--muted);
  }
  .kv strong { color: #dfe5ea; font-weight: 600; }
  .columns, .facets, .sample, .edges-list {
    border: 1px solid #2e353d;
    border-radius: 8px;
    overflow: hidden;
    background: #111418;
  }
  .col-row, .facet-row, .edge-row {
    display: grid;
    gap: 8px;
    align-items: center;
    padding: 8px 10px;
    border-bottom: 1px solid #252b32;
    font-size: 12px;
  }
  .col-row { grid-template-columns: minmax(0, 1fr) 86px 54px; }
  .facet-row { grid-template-columns: 90px minmax(0, 1fr); }
  .edge-row { grid-template-columns: 72px minmax(0, 1fr); }
  .col-row:last-child, .facet-row:last-child, .edge-row:last-child { border-bottom: 0; }
  .col-name, .facet-values, .edge-text { min-width: 0; overflow-wrap: anywhere; }
  .col-type, .key-mark, .facet-col, .edge-kind { color: var(--muted); font-size: 11px; }
  .key-mark { text-align: right; color: #f2c94c; font-weight: 700; }
  .range-line {
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 5px;
    overflow-wrap: anywhere;
  }
  pre {
    margin: 0;
    max-height: 220px;
    overflow: auto;
    padding: 10px;
    color: #c9d4df;
    font-size: 11px;
    line-height: 1.45;
  }
  .hint {
    position: absolute;
    left: 14px;
    bottom: 12px;
    padding: 8px 10px;
    background: rgba(15,18,21,.86);
    border: 1px solid #313942;
    border-radius: 8px;
    color: #9da8b4;
    font-size: 12px;
    backdrop-filter: blur(8px);
  }
  @media (max-width: 1020px) {
    .statbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .layout { grid-template-columns: 1fr; }
    .workspace { border-right: 0; }
    aside { min-height: 520px; border-top: 1px solid var(--line); }
    .toolbar { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 620px) {
    header, .statbar { padding-left: 14px; padding-right: 14px; }
    .toolbar { grid-template-columns: 1fr; }
    .statbar { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <h1>Diagrama interactivo de la DB Toesca</h1>
  <div class="subhead">
    <span id="db-path"></span>
    <span id="generated-at"></span>
  </div>
</header>

<section class="statbar">
  <div class="stat"><strong id="stat-version"></strong><span>schema_version</span></div>
  <div class="stat"><strong id="stat-tables"></strong><span>tablas</span></div>
  <div class="stat"><strong id="stat-views"></strong><span>vistas</span></div>
  <div class="stat"><strong id="stat-rows"></strong><span>filas en tablas</span></div>
  <div class="stat"><strong id="stat-edges"></strong><span>relaciones</span></div>
</section>

<main class="layout">
  <section class="workspace">
    <div class="toolbar">
      <input id="search" type="search" placeholder="Buscar tabla, vista o columna">
      <select id="domain-filter" aria-label="Dominio"></select>
      <select id="type-filter" aria-label="Tipo">
        <option value="all">Tablas y vistas</option>
        <option value="table">Solo tablas</option>
        <option value="view">Solo vistas</option>
      </select>
      <select id="edge-filter" aria-label="Relaciones">
        <option value="all">Todas las relaciones</option>
        <option value="declared">Solo FK declaradas</option>
        <option value="inferred">Solo inferidas</option>
        <option value="none">Sin relaciones</option>
      </select>
      <button id="reset-view" type="button">Centrar</button>
    </div>
    <div class="diagram-wrap">
      <svg id="diagram" role="img" aria-label="Mapa de tablas y vistas de SQLite"></svg>
      <div class="hint">Rueda para zoom, arrastra para mover, click en un nodo para detalle.</div>
    </div>
  </section>
  <aside>
    <div class="panel-head">
      <h2 id="detail-title"></h2>
      <div id="detail-pills" class="pill-row"></div>
    </div>
    <div id="detail-body" class="panel-body"></div>
  </aside>
</main>

<script>
const DB_DATA = __DATA_JSON__;

const byName = new Map(DB_DATA.objects.map(obj => [obj.name, obj]));
const domainByKey = new Map(DB_DATA.groups.map(group => [group.key, group]));
const svg = document.getElementById("diagram");
const searchInput = document.getElementById("search");
const domainFilter = document.getElementById("domain-filter");
const typeFilter = document.getElementById("type-filter");
const edgeFilter = document.getElementById("edge-filter");
const resetButton = document.getElementById("reset-view");
const detailTitle = document.getElementById("detail-title");
const detailPills = document.getElementById("detail-pills");
const detailBody = document.getElementById("detail-body");

let selectedName = DB_DATA.objects.find(obj => obj.type === "table")?.name || DB_DATA.objects[0]?.name;
let transform = { x: 26, y: 28, scale: 1 };
let panning = null;
let nodesLayer;
let edgesLayer;

const NODE_W = 220;
const NODE_H = 64;
const GROUP_GAP = 276;
const ROW_GAP = 88;

function fmt(value) {
  if (value === null || value === undefined) return "n/d";
  if (typeof value === "number") return value.toLocaleString("es-CL");
  return String(value);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[ch]));
}

function matchesSearch(obj, term) {
  if (!term) return true;
  const haystack = [
    obj.name,
    obj.domainLabel,
    obj.type,
    ...obj.columns.map(col => col.name),
    ...obj.columns.map(col => col.type || "")
  ].join(" ").toLowerCase();
  return haystack.includes(term);
}

function visibleObjects() {
  const term = searchInput.value.trim().toLowerCase();
  const domain = domainFilter.value;
  const type = typeFilter.value;
  return DB_DATA.objects.filter(obj => {
    if (domain !== "all" && obj.domain !== domain) return false;
    if (type !== "all" && obj.type !== type) return false;
    return matchesSearch(obj, term);
  });
}

function computeLayout() {
  const positions = new Map();
  const groupStart = new Map();
  DB_DATA.groups.forEach((group, groupIndex) => {
    const items = DB_DATA.objects
      .filter(obj => obj.domain === group.key)
      .sort((a, b) => a.name.localeCompare(b.name));
    const x = 50 + groupIndex * GROUP_GAP;
    groupStart.set(group.key, { x, count: items.length, label: group.label, color: group.color });
    items.forEach((obj, idx) => {
      positions.set(obj.name, { x, y: 72 + idx * ROW_GAP });
    });
  });
  const maxRows = Math.max(...DB_DATA.groups.map(group => group.count), 1);
  return {
    positions,
    groupStart,
    width: 80 + DB_DATA.groups.length * GROUP_GAP,
    height: 130 + maxRows * ROW_GAP
  };
}

const layout = computeLayout();

function edgePath(source, target) {
  const sx = source.x + NODE_W;
  const sy = source.y + NODE_H / 2;
  const tx = target.x;
  const ty = target.y + NODE_H / 2;
  const dx = Math.max(70, Math.abs(tx - sx) * 0.48);
  return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${tx - dx} ${ty}, ${tx} ${ty}`;
}

function applyTransform() {
  const value = `translate(${transform.x} ${transform.y}) scale(${transform.scale})`;
  document.getElementById("viewport").setAttribute("transform", value);
}

function render() {
  svg.innerHTML = "";
  svg.setAttribute("viewBox", `0 0 ${Math.max(900, svg.clientWidth)} ${Math.max(640, svg.clientHeight)}`);

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", "arrow");
  marker.setAttribute("markerWidth", "8");
  marker.setAttribute("markerHeight", "8");
  marker.setAttribute("refX", "7");
  marker.setAttribute("refY", "3");
  marker.setAttribute("orient", "auto");
  const markerPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  markerPath.setAttribute("d", "M 0 0 L 7 3 L 0 6 z");
  markerPath.setAttribute("fill", "#8a96a3");
  marker.appendChild(markerPath);
  defs.appendChild(marker);
  svg.appendChild(defs);

  const viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.setAttribute("id", "viewport");
  svg.appendChild(viewport);

  const headers = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.appendChild(headers);
  layout.groupStart.forEach(group => {
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("class", "domain-title");
    text.setAttribute("x", group.x);
    text.setAttribute("y", 28);
    text.textContent = group.label;
    headers.appendChild(text);

    const count = document.createElementNS("http://www.w3.org/2000/svg", "text");
    count.setAttribute("class", "domain-count");
    count.setAttribute("x", group.x);
    count.setAttribute("y", 46);
    count.textContent = `${group.count} objetos`;
    headers.appendChild(count);
  });

  edgesLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
  nodesLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.appendChild(edgesLayer);
  viewport.appendChild(nodesLayer);

  DB_DATA.edges.forEach(edge => {
    const source = layout.positions.get(edge.from);
    const target = layout.positions.get(edge.to);
    if (!source || !target) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const sourceObj = byName.get(edge.from);
    const color = domainByKey.get(sourceObj?.domain)?.color || "#8a96a3";
    path.setAttribute("d", edgePath(source, target));
    path.setAttribute("stroke", color);
    path.setAttribute("marker-end", "url(#arrow)");
    path.setAttribute("class", `edge ${edge.kind}`);
    path.dataset.from = edge.from;
    path.dataset.to = edge.to;
    path.dataset.kind = edge.kind;
    edgesLayer.appendChild(path);
  });

  DB_DATA.objects.forEach(obj => {
    const pos = layout.positions.get(obj.name);
    const group = domainByKey.get(obj.domain);
    const node = document.createElementNS("http://www.w3.org/2000/svg", "g");
    node.setAttribute("class", "node");
    node.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
    node.dataset.name = obj.name;

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", NODE_W);
    rect.setAttribute("height", NODE_H);
    rect.setAttribute("fill", obj.type === "view" ? "#172027" : "#1b1f24");
    rect.setAttribute("stroke", group?.color || "#424a54");
    node.appendChild(rect);

    const bar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bar.setAttribute("width", "5");
    bar.setAttribute("height", NODE_H);
    bar.setAttribute("rx", "2");
    bar.setAttribute("fill", group?.color || "#888");
    node.appendChild(bar);

    const name = document.createElementNS("http://www.w3.org/2000/svg", "text");
    name.setAttribute("class", "name");
    name.setAttribute("x", "14");
    name.setAttribute("y", "22");
    name.textContent = obj.name.length > 25 ? obj.name.slice(0, 23) + "..." : obj.name;
    node.appendChild(name);

    const meta = document.createElementNS("http://www.w3.org/2000/svg", "text");
    meta.setAttribute("class", "meta");
    meta.setAttribute("x", "14");
    meta.setAttribute("y", "42");
    meta.textContent = `${obj.columnCount} cols · ${fmt(obj.rowCount)} filas`;
    node.appendChild(meta);

    const badge = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    badge.setAttribute("class", "badge");
    badge.setAttribute("x", String(NODE_W - 52));
    badge.setAttribute("y", "43");
    badge.setAttribute("width", "42");
    badge.setAttribute("height", "15");
    badge.setAttribute("rx", "5");
    node.appendChild(badge);

    const badgeText = document.createElementNS("http://www.w3.org/2000/svg", "text");
    badgeText.setAttribute("class", "badge-text");
    badgeText.setAttribute("x", String(NODE_W - 31));
    badgeText.setAttribute("y", "54");
    badgeText.setAttribute("text-anchor", "middle");
    badgeText.textContent = obj.type === "view" ? "VIEW" : "TABLE";
    node.appendChild(badgeText);

    node.addEventListener("click", () => selectNode(obj.name));
    nodesLayer.appendChild(node);
  });

  applyTransform();
  updateVisibility();
  selectNode(selectedName || DB_DATA.objects[0]?.name);
}

function updateVisibility() {
  const visible = new Set(visibleObjects().map(obj => obj.name));
  const edgeMode = edgeFilter.value;
  document.querySelectorAll(".node").forEach(node => {
    const show = visible.has(node.dataset.name);
    node.classList.toggle("hidden", !show);
    node.classList.toggle("selected", node.dataset.name === selectedName);
  });
  document.querySelectorAll(".edge").forEach(edge => {
    const selectedRelated = selectedName && (edge.dataset.from === selectedName || edge.dataset.to === selectedName);
    const edgeAllowed = edgeMode === "all" || edgeMode === edge.dataset.kind;
    const show = edgeMode !== "none" && edgeAllowed && visible.has(edge.dataset.from) && visible.has(edge.dataset.to);
    edge.classList.toggle("hidden", !show);
    edge.classList.toggle("selected", selectedRelated);
  });
}

function selectNode(name) {
  const obj = byName.get(name);
  if (!obj) return;
  selectedName = name;
  detailTitle.textContent = obj.name;
  const group = domainByKey.get(obj.domain);
  detailPills.innerHTML = `
    <span class="pill">${esc(obj.type === "table" ? "Tabla" : "Vista")}</span>
    <span class="pill">${esc(obj.domainLabel)}</span>
    <span class="pill">${fmt(obj.rowCount)} filas</span>
    <span class="pill">${fmt(obj.columnCount)} columnas</span>
  `;

  const outgoing = DB_DATA.edges.filter(edge => edge.from === obj.name);
  const incoming = DB_DATA.edges.filter(edge => edge.to === obj.name);
  const ranges = obj.dateRanges.length
    ? obj.dateRanges.map(r => `<div class="range-line"><strong>${esc(r.column)}</strong>: ${esc(r.min)} -> ${esc(r.max)}</div>`).join("")
    : `<div class="range-line">Sin columnas de fecha o periodo con datos.</div>`;
  const indexes = obj.indexes.length
    ? obj.indexes.map(idx => `<div class="range-line"><strong>${esc(idx.name)}</strong>: ${idx.unique ? "UNIQUE · " : ""}${esc(idx.columns.join(", ") || "sin columnas")}</div>`).join("")
    : `<div class="range-line">Sin indices propios reportados.</div>`;
  const columns = obj.columns.map(col => `
    <div class="col-row">
      <div class="col-name">${esc(col.name)}</div>
      <div class="col-type">${esc(col.type || "sin tipo")}</div>
      <div class="key-mark">${col.pk ? "PK" : col.notnull ? "NN" : ""}</div>
    </div>
  `).join("");
  const facetKeys = Object.keys(obj.facets || {});
  const facetHtml = facetKeys.length
    ? facetKeys.map(key => {
        const values = obj.facets[key].map(item => `${esc(item.value)} (${fmt(item.count)})`).join(", ");
        return `<div class="facet-row"><div class="facet-col">${esc(key)}</div><div class="facet-values">${values}</div></div>`;
      }).join("")
    : `<div class="facet-row"><div class="facet-col">n/d</div><div class="facet-values">Sin facetas pequeñas para mostrar.</div></div>`;
  const edgeRows = [...outgoing.map(edge => ({...edge, dir: "sale"})), ...incoming.map(edge => ({...edge, dir: "entra"}))]
    .map(edge => `<div class="edge-row"><div class="edge-kind">${esc(edge.kind)} · ${esc(edge.dir)}</div><div class="edge-text">${esc(edge.from)}.${esc(edge.fromColumn)} -> ${esc(edge.to)}.${esc(edge.toColumn)}</div></div>`)
    .join("") || `<div class="edge-row"><div class="edge-kind">n/d</div><div class="edge-text">Sin relaciones detectadas.</div></div>`;
  const sample = obj.sampleRows.length
    ? `<pre>${esc(JSON.stringify(obj.sampleRows, null, 2))}</pre>`
    : `<pre>No hay muestra embebida para vistas o tablas vacias.</pre>`;

  detailBody.innerHTML = `
    <div class="section">
      <h3>Resumen</h3>
      <div class="kv">
        <strong>Dominio</strong><span>${esc(obj.domainLabel)}</span>
        <strong>Tipo</strong><span>${esc(obj.type)}</span>
        <strong>Filas</strong><span>${fmt(obj.rowCount)}</span>
        <strong>Columnas</strong><span>${fmt(obj.columnCount)}</span>
        <strong>Color</strong><span style="color:${group?.color || "#fff"}">${esc(group?.color || "n/d")}</span>
      </div>
    </div>
    <div class="section"><h3>Rangos</h3>${ranges}</div>
    <div class="section"><h3>Relaciones</h3><div class="edges-list">${edgeRows}</div></div>
    <div class="section"><h3>Columnas</h3><div class="columns">${columns}</div></div>
    <div class="section"><h3>Facetas</h3><div class="facets">${facetHtml}</div></div>
    <div class="section"><h3>Indices</h3>${indexes}</div>
    <div class="section"><h3>Muestra</h3><div class="sample">${sample}</div></div>
  `;
  updateVisibility();
}

function initControls() {
  domainFilter.innerHTML = `<option value="all">Todos los dominios</option>` +
    DB_DATA.groups.map(group => `<option value="${esc(group.key)}">${esc(group.label)} (${group.count})</option>`).join("");
  document.getElementById("db-path").textContent = DB_DATA.dbPath;
  document.getElementById("generated-at").textContent = `Generado: ${DB_DATA.generatedAt}`;
  document.getElementById("stat-version").textContent = fmt(DB_DATA.schemaVersion);
  document.getElementById("stat-tables").textContent = fmt(DB_DATA.tableCount);
  document.getElementById("stat-views").textContent = fmt(DB_DATA.viewCount);
  document.getElementById("stat-rows").textContent = fmt(DB_DATA.totalRows);
  document.getElementById("stat-edges").textContent = fmt(DB_DATA.edges.length);

  [searchInput, domainFilter, typeFilter, edgeFilter].forEach(control => {
    control.addEventListener("input", () => {
      const visible = visibleObjects();
      if (!visible.some(obj => obj.name === selectedName) && visible[0]) {
        selectedName = visible[0].name;
        selectNode(selectedName);
      } else {
        updateVisibility();
      }
    });
  });
  resetButton.addEventListener("click", () => {
    transform = { x: 26, y: 28, scale: 1 };
    applyTransform();
  });
}

function initPanZoom() {
  svg.addEventListener("wheel", event => {
    event.preventDefault();
    const delta = event.deltaY > 0 ? 0.92 : 1.08;
    const next = Math.min(1.8, Math.max(0.42, transform.scale * delta));
    transform.scale = next;
    applyTransform();
  }, { passive: false });
  svg.addEventListener("pointerdown", event => {
    panning = { x: event.clientX, y: event.clientY, tx: transform.x, ty: transform.y };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", event => {
    if (!panning) return;
    transform.x = panning.tx + event.clientX - panning.x;
    transform.y = panning.ty + event.clientY - panning.y;
    applyTransform();
  });
  svg.addEventListener("pointerup", () => { panning = null; });
  svg.addEventListener("pointercancel", () => { panning = null; });
}

initControls();
render();
initPanZoom();
window.addEventListener("resize", render);
</script>
</body>
</html>
"""


FS_HTML_TEMPLATE = r"""<!-- ARCHIVO AUTOGENERADO por scripts/build_db_diagram.py — NO editar a mano. Regenerar con `python -X utf8 scripts/build_db_diagram.py`. -->
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Toesca · Mapa DB</title>
<style>
  :root {
    --green: #00B27A;
    --green-soft: #C8ECD8;
    --green-pale: #EAF7F0;
    --green-header: #A6DEC1;
    --text: #202020;
    --muted: #626262;
    --border: #A6A6A6;
    --line: #E6E6E6;
    --page: #FFFFFF;
    --paper: #F4F4F4;
    --dark-a: #3D3D3D;
    --dark-b: #2B2B2B;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--paper);
    color: var(--text);
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 12px;
  }
  .page {
    max-width: 1360px;
    margin: 12px auto;
    background: var(--page);
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    min-height: calc(100vh - 24px);
  }
  header {
    background: linear-gradient(180deg,var(--dark-a),var(--dark-b));
    color: #fff;
    padding: 22px 32px 18px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 18px;
  }
  header h1 { margin: 0; font-size: 30px; font-weight: 300; letter-spacing: 0.5px; }
  header h2 {
    margin: 4px 0 0;
    font-size: 12px;
    font-weight: 400;
    color: #dedede;
    font-variant: small-caps;
    letter-spacing: 1px;
  }
  header .logo { height: 32px; width: auto; display: block; }
  .month-bar {
    padding: 8px 32px 4px;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 1px;
    border-bottom: 2px solid var(--green);
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .month-bar span:last-child { color: #555; font-weight: 600; font-size: 11px; letter-spacing: 0; }
  .content { padding: 18px 32px 26px; }
  .section-title {
    background: var(--green-header);
    color: #000;
    font-weight: 700;
    font-size: 11px;
    padding: 4px 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0 0 8px;
  }
  .control-grid {
    display: grid;
    grid-template-columns: minmax(220px, 1.25fr) minmax(200px, 1fr) 140px 145px 160px;
    gap: 10px;
    align-items: end;
    margin-bottom: 12px;
  }
  .field { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .field-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: #4a6b5c;
  }
  input, select, button {
    font: inherit;
    min-height: 34px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: #fff;
    color: var(--text);
    padding: 5px 9px;
  }
  button {
    cursor: pointer;
    font-weight: 600;
    color: var(--green);
    border-color: var(--green);
    transition: background-color 150ms ease, color 150ms ease;
  }
  button:hover { background: #E6F5EC; }
  button.active { background: var(--green); color: #fff; }
  .mode-row, .chip-row {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  .mode-btn, .chip-btn { min-width: 74px; }
  .chip-btn { color: #555; border-color: #d2d2d2; }
  .chip-btn.active { border-color: var(--green); }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(110px, 1fr));
    gap: 8px;
    margin-bottom: 14px;
  }
  .stat {
    border: 1px solid #DCDCDC;
    background: #FAFBFA;
    padding: 8px 10px;
    min-height: 58px;
  }
  .stat strong { display: block; font-size: 20px; line-height: 1; color: #1a1a1a; font-weight: 700; }
  .stat span { display: block; margin-top: 5px; color: #555; font-size: 10px; text-transform: uppercase; letter-spacing: .5px; }
  .work-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 18px;
    align-items: start;
  }
  .canvas-panel, .detail-panel, .table-panel {
    border: 1px solid #D8D8D8;
    background: #fff;
    min-width: 0;
  }
  .panel-head {
    min-height: 36px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border-bottom: 1px solid var(--line);
    background: #F6F9F7;
  }
  .panel-head strong {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #33413b;
  }
  .panel-actions { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
  .panel-actions button { min-height: 26px; padding: 3px 8px; font-size: 11px; }
  .canvas-wrap {
    height: 620px;
    position: relative;
    overflow: hidden;
    background:
      linear-gradient(#F0F0F0 1px, transparent 1px),
      linear-gradient(90deg, #F0F0F0 1px, transparent 1px);
    background-size: 28px 28px;
  }
  svg { display: block; width: 100%; height: 100%; }
  .edge {
    fill: none;
    stroke: #8D8D8D;
    stroke-width: 1.1;
    opacity: .28;
  }
  .edge.declared { stroke-width: 1.9; opacity: .52; }
  .edge.highlight { stroke: var(--green); stroke-width: 3; opacity: .95; }
  .edge.hidden { display: none; }
  .domain-title { font-size: 11px; fill: #33413b; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; }
  .domain-count { font-size: 10px; fill: #666; }
  .node { cursor: pointer; }
  .node .hitbox { fill: transparent; pointer-events: all; }
  .node rect.main { fill: #fff; stroke: #A8A8A8; stroke-width: 1; rx: 3; }
  .node:hover rect.main { fill: var(--green-pale); stroke: var(--green); stroke-width: 2; }
  .node .stripe { opacity: .98; }
  .node .name { fill: #1f1f1f; font-size: 12px; font-weight: 700; }
  .node .meta { fill: #5f5f5f; font-size: 10.5px; }
  .node .tag { fill: #F6F9F7; stroke: #D8D8D8; rx: 3; }
  .node .tag-text { fill: #4b4b4b; font-size: 9px; font-weight: 700; }
  .node.hidden { display: none; }
  .node.dimmed { opacity: .16; }
  .node.selected rect.main { fill: #F0F8F4; stroke: var(--green); stroke-width: 2.4; }
  .node.highlight rect.main { stroke: #222; stroke-width: 2; }
  .hint {
    position: absolute;
    left: 10px;
    bottom: 10px;
    background: rgba(255,255,255,.92);
    border: 1px solid #D8D8D8;
    padding: 7px 9px;
    color: #555;
    font-size: 11px;
  }
  .path-bar {
    display: grid;
    grid-template-columns: 1fr 1fr auto;
    gap: 8px;
    margin: 0 0 12px;
  }
  .path-result {
    margin: -4px 0 12px;
    color: #555;
    font-size: 11px;
    min-height: 16px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-variant-numeric: tabular-nums;
  }
  table th, table td {
    padding: 6px 8px;
    font-size: 11px;
    line-height: 1.35;
    border-bottom: 1px solid #E6E6E6;
    text-align: right;
    vertical-align: top;
  }
  table th:first-child, table td:first-child { text-align: left; }
  table th {
    background: #F6F9F7;
    color: #33413b;
    font-weight: 700;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 2px solid var(--green);
  }
  tbody tr:nth-child(even) { background: #FAFBFA; }
  tbody tr:hover { background: #EAF7F0; }
  tr.selected-row, tr.selected-row:nth-child(even) { background: var(--green-soft); color: #0d3a29; font-weight: 700; }
  .object-table-wrap, .matrix-wrap { max-height: 620px; overflow: auto; }
  .object-table td:first-child { cursor: pointer; font-weight: 600; color: #1e5f47; }
  .view { display: none; }
  .view.active { display: block; }
  .detail-panel { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; }
  .detail-title {
    padding: 12px 12px 6px;
    border-bottom: 1px solid var(--line);
  }
  .detail-title h3 { margin: 0 0 6px; font-size: 18px; line-height: 1.2; overflow-wrap: anywhere; }
  .pill-row { display: flex; flex-wrap: wrap; gap: 4px; }
  .pill {
    display: inline-flex;
    border: 1px solid #D8D8D8;
    background: #FAFBFA;
    border-radius: 3px;
    padding: 3px 7px;
    color: #444;
    font-size: 10px;
    font-weight: 600;
  }
  .detail-body { padding: 10px 12px 14px; }
  .detail-section { margin-bottom: 14px; }
  .detail-section h4 {
    margin: 0 0 6px;
    font-size: 10px;
    color: #4a6b5c;
    letter-spacing: .8px;
    text-transform: uppercase;
    border-bottom: 1px solid #DDD;
    padding-bottom: 3px;
  }
  .kv {
    display: grid;
    grid-template-columns: 115px minmax(0,1fr);
    gap: 5px 8px;
    color: #555;
    font-size: 11px;
  }
  .kv strong { color: #333; }
  .mini-list {
    border: 1px solid #E1E1E1;
    border-radius: 3px;
    overflow: hidden;
  }
  .mini-row {
    display: grid;
    grid-template-columns: minmax(0,1fr) 80px 40px;
    gap: 8px;
    padding: 6px 8px;
    border-bottom: 1px solid #EDEDED;
    font-size: 11px;
  }
  .mini-row:last-child { border-bottom: 0; }
  .mini-row:nth-child(even) { background: #FAFBFA; }
  .mini-row span { overflow-wrap: anywhere; }
  .muted { color: #666; }
  pre {
    margin: 0;
    padding: 8px 10px;
    background: #F6F8F7;
    border-left: 3px solid var(--green);
    overflow: auto;
    max-height: 190px;
    font-size: 10.5px;
    line-height: 1.35;
  }
  .matrix-cell { text-align: center; cursor: pointer; }
  .matrix-cell.has { color: #0d6b4b; font-weight: 700; background: #F0F8F4; }
  .matrix-cell.has:hover { background: var(--green-soft); }
  .notice {
    color: #555;
    font-size: 11px;
    margin: 8px 0 12px;
    line-height: 1.4;
  }
  @media (max-width: 1050px) {
    .control-grid { grid-template-columns: 1fr 1fr; }
    .stats-grid { grid-template-columns: repeat(2, minmax(0,1fr)); }
    .work-grid { grid-template-columns: 1fr; }
    .detail-panel { position: static; max-height: none; }
  }
  @media (max-width: 680px) {
    header, .month-bar, .content { padding-left: 16px; padding-right: 16px; }
    header { align-items: flex-start; flex-direction: column; }
    .control-grid, .path-bar, .stats-grid { grid-template-columns: 1fr; }
    .canvas-wrap { height: 520px; }
  }
</style>
</head>
<body>
<div class="page">
  <header>
    <div>
      <h1>Mapa de Base de Datos</h1>
      <h2>Automation Agent · Toesca</h2>
    </div>
    <img class="logo" src="__LOGO_SRC__" alt="Toesca">
  </header>

  <div class="month-bar">
    <span id="schema-label">SCHEMA VERSION</span>
    <span id="generated-label">Generado</span>
  </div>

  <div class="content">
    <div class="section-title">Explorador interactivo</div>
    <div class="stats-grid">
      <div class="stat"><strong id="stat-version">—</strong><span>schema_version</span></div>
      <div class="stat"><strong id="stat-tables">—</strong><span>tablas</span></div>
      <div class="stat"><strong id="stat-views">—</strong><span>vistas</span></div>
      <div class="stat"><strong id="stat-rows">—</strong><span>filas en tablas</span></div>
      <div class="stat"><strong id="stat-edges">—</strong><span>relaciones</span></div>
    </div>

    <div class="control-grid">
      <div class="field">
        <label class="field-label" for="search">Buscar tabla, vista o columna</label>
        <input id="search" type="search" placeholder="Ej: raw_eeff_line, periodo, fondo_key">
      </div>
      <div class="field">
        <label class="field-label" for="domain-filter">Dominio</label>
        <select id="domain-filter"></select>
      </div>
      <div class="field">
        <label class="field-label" for="type-filter">Tipo</label>
        <select id="type-filter">
          <option value="all">Tablas y vistas</option>
          <option value="table">Solo tablas</option>
          <option value="view">Solo vistas</option>
        </select>
      </div>
      <div class="field">
        <label class="field-label" for="edge-filter">Relaciones</label>
        <select id="edge-filter">
          <option value="all">Todas</option>
          <option value="declared">FK declaradas</option>
          <option value="inferred">Inferidas</option>
          <option value="selected">Del nodo seleccionado</option>
          <option value="none">Ocultar</option>
        </select>
      </div>
      <div class="field">
        <label class="field-label" for="row-sort">Orden lista</label>
        <select id="row-sort">
          <option value="domain">Dominio</option>
          <option value="name">Nombre</option>
          <option value="rows">Filas</option>
          <option value="columns">Columnas</option>
          <option value="relations">Relaciones</option>
        </select>
      </div>
    </div>

    <div class="chip-row" id="domain-chips"></div>

    <div class="mode-row">
      <button class="mode-btn active" type="button" data-mode="map">Mapa</button>
      <button class="mode-btn" type="button" data-mode="list">Lista</button>
      <button class="mode-btn" type="button" data-mode="matrix">Matriz</button>
      <button id="reset-all" type="button">Limpiar foco</button>
    </div>

    <div class="path-bar">
      <select id="path-from" aria-label="Origen"></select>
      <select id="path-to" aria-label="Destino"></select>
      <button id="path-find" type="button">Buscar ruta</button>
    </div>
    <div class="path-result" id="path-result"></div>

    <div class="work-grid">
      <section>
        <div class="view active" id="view-map">
          <div class="canvas-panel">
            <div class="panel-head">
              <strong>Mapa entidad-relación</strong>
              <div class="panel-actions">
                <button id="zoom-in" type="button">+</button>
                <button id="zoom-out" type="button">−</button>
                <button id="center-map" type="button">Centrar</button>
                <button id="focus-upstream" type="button">Upstream</button>
                <button id="focus-downstream" type="button">Downstream</button>
              </div>
            </div>
            <div class="canvas-wrap">
              <svg id="diagram" role="img" aria-label="Mapa de tablas y vistas de SQLite"></svg>
              <div class="hint">Click en cualquier nodo para ver detalle. Doble click enfoca sus vecinos.</div>
            </div>
          </div>
        </div>

        <div class="view" id="view-list">
          <div class="table-panel">
            <div class="panel-head">
              <strong>Inventario del esquema</strong>
              <span class="muted" id="list-count">—</span>
            </div>
            <div class="object-table-wrap">
              <table class="object-table">
                <thead>
                  <tr><th>Objeto</th><th>Dominio</th><th>Tipo</th><th>Filas</th><th>Cols</th><th>Rel.</th><th>Rango principal</th></tr>
                </thead>
                <tbody id="object-tbody"></tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="view" id="view-matrix">
          <div class="table-panel">
            <div class="panel-head">
              <strong>Matriz de relaciones por dominio</strong>
              <span class="muted">Filas: origen · columnas: destino</span>
            </div>
            <div class="notice">Haz click en una celda con valor para filtrar el mapa por relaciones entre esos dominios.</div>
            <div class="matrix-wrap">
              <table>
                <thead id="matrix-head"></thead>
                <tbody id="matrix-body"></tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <aside class="detail-panel">
        <div class="panel-head">
          <strong>Detalle</strong>
          <div class="panel-actions">
            <button id="detail-focus" type="button">Foco</button>
            <button id="detail-neighbors" type="button">Vecinos</button>
          </div>
        </div>
        <div class="detail-title">
          <h3 id="detail-title">—</h3>
          <div class="pill-row" id="detail-pills"></div>
        </div>
        <div class="detail-body" id="detail-body"></div>
      </aside>
    </div>
  </div>
</div>

<script>
const DB_DATA = __DATA_JSON__;

const byName = new Map(DB_DATA.objects.map(obj => [obj.name, obj]));
const domainByKey = new Map(DB_DATA.groups.map(group => [group.key, group]));
const svg = document.getElementById("diagram");
const searchInput = document.getElementById("search");
const domainFilter = document.getElementById("domain-filter");
const typeFilter = document.getElementById("type-filter");
const edgeFilter = document.getElementById("edge-filter");
const rowSort = document.getElementById("row-sort");
const pathFrom = document.getElementById("path-from");
const pathTo = document.getElementById("path-to");
const pathResult = document.getElementById("path-result");
const detailTitle = document.getElementById("detail-title");
const detailPills = document.getElementById("detail-pills");
const detailBody = document.getElementById("detail-body");
const objectTbody = document.getElementById("object-tbody");

let selectedName = DB_DATA.objects.find(obj => obj.name === "raw_eeff_line")?.name || DB_DATA.objects[0]?.name;
let currentMode = "map";
let activeFocus = null;
let activePath = [];
let matrixDomainFilter = null;
let transform = { x: 20, y: 18, scale: 1 };
let panning = null;
let pointerMoved = false;

const NODE_W = 212;
const NODE_H = 58;
const GROUP_GAP = 260;
const ROW_GAP = 78;

function fmt(value) {
  if (value === null || value === undefined) return "n/d";
  if (typeof value === "number") return value.toLocaleString("es-CL");
  return String(value);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[ch]));
}

function rangeLabel(obj) {
  if (!obj.dateRanges.length) return "";
  const r = obj.dateRanges[0];
  return `${r.column}: ${r.min} → ${r.max}`;
}

function relationsFor(name) {
  return DB_DATA.edges.filter(edge => edge.from === name || edge.to === name);
}

function outgoing(name) {
  return DB_DATA.edges.filter(edge => edge.from === name).map(edge => edge.to);
}

function incoming(name) {
  return DB_DATA.edges.filter(edge => edge.to === name).map(edge => edge.from);
}

function dependencySet(name, mode) {
  const seen = new Set([name]);
  const queue = [name];
  while (queue.length) {
    const current = queue.shift();
    const next = mode === "upstream" ? outgoing(current) : incoming(current);
    next.forEach(n => {
      if (!seen.has(n)) {
        seen.add(n);
        queue.push(n);
      }
    });
  }
  return seen;
}

function matchesSearch(obj, term) {
  if (!term) return true;
  const haystack = [
    obj.name, obj.domainLabel, obj.type,
    ...obj.columns.map(col => col.name),
    ...obj.columns.map(col => col.type || ""),
    ...Object.keys(obj.facets || {})
  ].join(" ").toLowerCase();
  return haystack.includes(term);
}

function baseVisibleObjects() {
  const term = searchInput.value.trim().toLowerCase();
  const domain = domainFilter.value;
  const type = typeFilter.value;
  return DB_DATA.objects.filter(obj => {
    if (domain !== "all" && obj.domain !== domain) return false;
    if (type !== "all" && obj.type !== type) return false;
    if (matrixDomainFilter && obj.domain !== matrixDomainFilter.from && obj.domain !== matrixDomainFilter.to) return false;
    return matchesSearch(obj, term);
  });
}

function visibleSet() {
  let set = new Set(baseVisibleObjects().map(obj => obj.name));
  if (activeFocus?.names) {
    set = new Set([...set].filter(name => activeFocus.names.has(name)));
  }
  if (activePath.length) {
    const pathSet = new Set(activePath);
    set = new Set([...set].filter(name => pathSet.has(name)));
  }
  return set;
}

function computeLayout() {
  const positions = new Map();
  const groupStart = new Map();
  DB_DATA.groups.forEach((group, groupIndex) => {
    const items = DB_DATA.objects
      .filter(obj => obj.domain === group.key)
      .sort((a, b) => a.name.localeCompare(b.name));
    const x = 36 + groupIndex * GROUP_GAP;
    groupStart.set(group.key, { x, count: items.length, label: group.label, color: group.color });
    items.forEach((obj, idx) => positions.set(obj.name, { x, y: 64 + idx * ROW_GAP }));
  });
  return { positions, groupStart };
}

const layout = computeLayout();

function edgePath(source, target) {
  const sx = source.x + NODE_W;
  const sy = source.y + NODE_H / 2;
  const tx = target.x;
  const ty = target.y + NODE_H / 2;
  const dx = Math.max(60, Math.abs(tx - sx) * .45);
  return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${tx - dx} ${ty}, ${tx} ${ty}`;
}

function applyTransform() {
  const viewport = document.getElementById("viewport");
  if (viewport) viewport.setAttribute("transform", `translate(${transform.x} ${transform.y}) scale(${transform.scale})`);
}

function renderMap() {
  svg.innerHTML = "";
  const width = Math.max(900, svg.clientWidth || 900);
  const height = Math.max(620, svg.clientHeight || 620);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.setAttribute("id", "viewport");
  svg.appendChild(viewport);

  const headers = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.appendChild(headers);
  layout.groupStart.forEach(group => {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("class", "domain-title");
    t.setAttribute("x", group.x);
    t.setAttribute("y", 24);
    t.textContent = group.label;
    headers.appendChild(t);
    const c = document.createElementNS("http://www.w3.org/2000/svg", "text");
    c.setAttribute("class", "domain-count");
    c.setAttribute("x", group.x);
    c.setAttribute("y", 40);
    c.textContent = `${group.count} objetos`;
    headers.appendChild(c);
  });

  const edgesLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
  const nodesLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.appendChild(edgesLayer);
  viewport.appendChild(nodesLayer);

  DB_DATA.edges.forEach((edge, index) => {
    const source = layout.positions.get(edge.from);
    const target = layout.positions.get(edge.to);
    if (!source || !target) return;
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", edgePath(source, target));
    p.setAttribute("class", `edge ${edge.kind}`);
    p.dataset.from = edge.from;
    p.dataset.to = edge.to;
    p.dataset.kind = edge.kind;
    p.dataset.index = String(index);
    edgesLayer.appendChild(p);
  });

  DB_DATA.objects.forEach(obj => {
    const pos = layout.positions.get(obj.name);
    const group = domainByKey.get(obj.domain);
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "node");
    g.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
    g.setAttribute("role", "button");
    g.setAttribute("tabindex", "0");
    g.setAttribute("aria-label", `Ver detalle de ${obj.name}`);
    g.dataset.name = obj.name;

    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `Click: detalle de ${obj.name}. Doble click: vecinos.`;
    g.appendChild(title);

    const hitbox = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    hitbox.setAttribute("class", "hitbox");
    hitbox.setAttribute("width", NODE_W);
    hitbox.setAttribute("height", NODE_H);
    g.appendChild(hitbox);

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("class", "main");
    rect.setAttribute("width", NODE_W);
    rect.setAttribute("height", NODE_H);
    g.appendChild(rect);

    const stripe = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    stripe.setAttribute("class", "stripe");
    stripe.setAttribute("width", "5");
    stripe.setAttribute("height", NODE_H);
    stripe.setAttribute("fill", group?.color || "#888");
    g.appendChild(stripe);

    const name = document.createElementNS("http://www.w3.org/2000/svg", "text");
    name.setAttribute("class", "name");
    name.setAttribute("x", "13");
    name.setAttribute("y", "20");
    name.textContent = obj.name.length > 25 ? obj.name.slice(0, 23) + "…" : obj.name;
    g.appendChild(name);

    const meta = document.createElementNS("http://www.w3.org/2000/svg", "text");
    meta.setAttribute("class", "meta");
    meta.setAttribute("x", "13");
    meta.setAttribute("y", "39");
    meta.textContent = `${fmt(obj.rowCount)} filas · ${obj.columnCount} cols`;
    g.appendChild(meta);

    const tag = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    tag.setAttribute("class", "tag");
    tag.setAttribute("x", String(NODE_W - 48));
    tag.setAttribute("y", "38");
    tag.setAttribute("width", "40");
    tag.setAttribute("height", "14");
    g.appendChild(tag);
    const tagText = document.createElementNS("http://www.w3.org/2000/svg", "text");
    tagText.setAttribute("class", "tag-text");
    tagText.setAttribute("x", String(NODE_W - 28));
    tagText.setAttribute("y", "48");
    tagText.setAttribute("text-anchor", "middle");
    tagText.textContent = obj.type === "view" ? "VIEW" : "TABLE";
    g.appendChild(tagText);

    g.addEventListener("pointerdown", event => event.stopPropagation());
    g.addEventListener("click", event => {
      event.stopPropagation();
      activateNode(obj.name);
    });
    g.addEventListener("dblclick", event => {
      event.stopPropagation();
      selectNode(obj.name);
      activePath = [];
      matrixDomainFilter = null;
      activeFocus = { mode: "neighbors", names: new Set([obj.name, ...incoming(obj.name), ...outgoing(obj.name)]) };
      edgeFilter.value = "selected";
      pathResult.textContent = `Vecinos de ${obj.name}: ${activeFocus.names.size} objetos visibles.`;
      updateVisibility();
    });
    g.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activateNode(obj.name);
      }
    });
    nodesLayer.appendChild(g);
  });

  applyTransform();
}

function edgeVisible(edge, visible) {
  if (!visible.has(edge.from) || !visible.has(edge.to)) return false;
  if (matrixDomainFilter) {
    const fromDomain = byName.get(edge.from)?.domain;
    const toDomain = byName.get(edge.to)?.domain;
    if (fromDomain !== matrixDomainFilter.from || toDomain !== matrixDomainFilter.to) return false;
  }
  const mode = edgeFilter.value;
  if (mode === "none") return false;
  if (mode === "selected") return edge.from === selectedName || edge.to === selectedName;
  if (mode !== "all" && edge.kind !== mode) return false;
  if (activePath.length) {
    for (let i = 0; i < activePath.length - 1; i++) {
      if (edge.from === activePath[i] && edge.to === activePath[i + 1]) return true;
    }
    return false;
  }
  return true;
}

function updateVisibility() {
  const visible = visibleSet();
  document.querySelectorAll(".node").forEach(node => {
    const show = visible.has(node.dataset.name);
    node.classList.toggle("hidden", !show);
    node.classList.toggle("selected", node.dataset.name === selectedName);
    node.classList.toggle("highlight", activePath.includes(node.dataset.name));
    const shouldDim = activeFocus?.names && show && !activeFocus.names.has(node.dataset.name);
    node.classList.toggle("dimmed", Boolean(shouldDim));
  });
  document.querySelectorAll(".edge").forEach(edgeEl => {
    const edge = {
      from: edgeEl.dataset.from,
      to: edgeEl.dataset.to,
      kind: edgeEl.dataset.kind
    };
    const show = edgeVisible(edge, visible);
    edgeEl.classList.toggle("hidden", !show);
    const inPath = activePath.some((name, i) => i < activePath.length - 1 && edge.from === name && edge.to === activePath[i + 1]);
    const selected = edge.from === selectedName || edge.to === selectedName;
    edgeEl.classList.toggle("highlight", inPath || (selected && edgeFilter.value === "selected"));
  });
  renderObjectTable();
}

function sortObjects(objects) {
  const mode = rowSort.value;
  return [...objects].sort((a, b) => {
    if (mode === "rows") return (b.rowCount || 0) - (a.rowCount || 0);
    if (mode === "columns") return b.columnCount - a.columnCount;
    if (mode === "relations") return relationsFor(b.name).length - relationsFor(a.name).length;
    if (mode === "name") return a.name.localeCompare(b.name);
    return `${a.domain}-${a.name}`.localeCompare(`${b.domain}-${b.name}`);
  });
}

function renderObjectTable() {
  const visible = visibleSet();
  const objects = sortObjects(DB_DATA.objects.filter(obj => visible.has(obj.name)));
  document.getElementById("list-count").textContent = `${objects.length} objetos visibles`;
  objectTbody.innerHTML = objects.map(obj => `
    <tr data-name="${esc(obj.name)}" class="${obj.name === selectedName ? "selected-row" : ""}">
      <td>${esc(obj.name)}</td>
      <td>${esc(obj.domainLabel)}</td>
      <td>${esc(obj.type)}</td>
      <td>${fmt(obj.rowCount)}</td>
      <td>${fmt(obj.columnCount)}</td>
      <td>${fmt(relationsFor(obj.name).length)}</td>
      <td>${esc(rangeLabel(obj) || "—")}</td>
    </tr>
  `).join("");
  objectTbody.querySelectorAll("tr").forEach(row => {
    row.addEventListener("click", () => selectNode(row.dataset.name));
  });
}

function renderMatrix() {
  const groups = DB_DATA.groups;
  document.getElementById("matrix-head").innerHTML = `
    <tr><th>Origen \\ Destino</th>${groups.map(g => `<th>${esc(g.label)}</th>`).join("")}</tr>
  `;
  const counts = new Map();
  DB_DATA.edges.forEach(edge => {
    const f = byName.get(edge.from)?.domain;
    const t = byName.get(edge.to)?.domain;
    if (!f || !t) return;
    counts.set(`${f}|${t}`, (counts.get(`${f}|${t}`) || 0) + 1);
  });
  document.getElementById("matrix-body").innerHTML = groups.map(from => `
    <tr>
      <td><strong>${esc(from.label)}</strong></td>
      ${groups.map(to => {
        const n = counts.get(`${from.key}|${to.key}`) || 0;
        return `<td class="matrix-cell ${n ? "has" : ""}" data-from="${esc(from.key)}" data-to="${esc(to.key)}">${n || ""}</td>`;
      }).join("")}
    </tr>
  `).join("");
  document.querySelectorAll(".matrix-cell.has").forEach(cell => {
    cell.addEventListener("click", () => {
      matrixDomainFilter = { from: cell.dataset.from, to: cell.dataset.to };
      activePath = [];
      activeFocus = null;
      setMode("map");
      updateVisibility();
      pathResult.textContent = `Filtro matriz: ${domainByKey.get(matrixDomainFilter.from).label} → ${domainByKey.get(matrixDomainFilter.to).label}.`;
    });
  });
}

function renderDetail(obj) {
  detailTitle.textContent = obj.name;
  detailPills.innerHTML = `
    <span class="pill">${esc(obj.type === "table" ? "Tabla" : "Vista")}</span>
    <span class="pill">${esc(obj.domainLabel)}</span>
    <span class="pill">${fmt(obj.rowCount)} filas</span>
    <span class="pill">${fmt(obj.columnCount)} columnas</span>
  `;
  const outEdges = DB_DATA.edges.filter(e => e.from === obj.name);
  const inEdges = DB_DATA.edges.filter(e => e.to === obj.name);
  const ranges = obj.dateRanges.length
    ? obj.dateRanges.map(r => `<div class="muted"><strong>${esc(r.column)}</strong>: ${esc(r.min)} → ${esc(r.max)}</div>`).join("")
    : `<div class="muted">Sin rango de fecha o periodo detectado.</div>`;
  const relRows = [...outEdges.map(e => ({...e, dir: "sale"})), ...inEdges.map(e => ({...e, dir: "entra"}))]
    .map(e => `<div class="mini-row"><span>${esc(e.from)}.${esc(e.fromColumn)} → ${esc(e.to)}.${esc(e.toColumn)}</span><span class="muted">${esc(e.kind)}</span><span>${esc(e.dir)}</span></div>`)
    .join("") || `<div class="mini-row"><span>Sin relaciones detectadas.</span><span></span><span></span></div>`;
  const colRows = obj.columns.map(col => `
    <div class="mini-row">
      <span>${esc(col.name)}</span>
      <span class="muted">${esc(col.type || "sin tipo")}</span>
      <span>${col.pk ? "PK" : col.notnull ? "NN" : ""}</span>
    </div>
  `).join("");
  const facetKeys = Object.keys(obj.facets || {});
  const facets = facetKeys.length
    ? facetKeys.map(key => {
      const vals = obj.facets[key].map(item => `${esc(item.value)} (${fmt(item.count)})`).join(", ");
      return `<div class="mini-row"><span>${esc(key)}</span><span class="muted" style="grid-column: span 2">${vals}</span></div>`;
    }).join("")
    : `<div class="mini-row"><span>Sin facetas pequeñas.</span><span></span><span></span></div>`;
  const indexes = obj.indexes.length
    ? obj.indexes.map(idx => `<div class="muted"><strong>${esc(idx.name)}</strong>: ${idx.unique ? "UNIQUE · " : ""}${esc(idx.columns.join(", ") || "sin columnas")}</div>`).join("")
    : `<div class="muted">Sin índices propios reportados.</div>`;
  const sample = obj.sampleRows.length ? JSON.stringify(obj.sampleRows, null, 2) : "Sin muestra embebida para este objeto.";

  detailBody.innerHTML = `
    <div class="detail-section">
      <h4>Resumen</h4>
      <div class="kv">
        <strong>Objeto</strong><span>${esc(obj.name)}</span>
        <strong>Dominio</strong><span>${esc(obj.domainLabel)}</span>
        <strong>Tipo</strong><span>${esc(obj.type)}</span>
        <strong>Relaciones</strong><span>${fmt(outEdges.length)} salientes · ${fmt(inEdges.length)} entrantes</span>
      </div>
    </div>
    <div class="detail-section"><h4>Rangos</h4>${ranges}</div>
    <div class="detail-section"><h4>Relaciones</h4><div class="mini-list">${relRows}</div></div>
    <div class="detail-section"><h4>Columnas</h4><div class="mini-list">${colRows}</div></div>
    <div class="detail-section"><h4>Facetas</h4><div class="mini-list">${facets}</div></div>
    <div class="detail-section"><h4>Índices</h4>${indexes}</div>
    <div class="detail-section"><h4>Muestra</h4><pre>${esc(sample)}</pre></div>
  `;
}

function selectNode(name) {
  const obj = byName.get(name);
  if (!obj) return;
  selectedName = name;
  renderDetail(obj);
  updateVisibility();
}

function activateNode(name) {
  selectNode(name);
  activePath = [];
  matrixDomainFilter = null;
  activeFocus = null;
  edgeFilter.value = "selected";
  pathResult.textContent = `Nodo seleccionado: ${name}. Mostrando sus relaciones directas.`;
  updateVisibility();
}

function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll(".mode-btn").forEach(btn => btn.classList.toggle("active", btn.dataset.mode === mode));
  document.querySelectorAll(".view").forEach(view => view.classList.toggle("active", view.id === `view-${mode}`));
  if (mode === "matrix") renderMatrix();
  if (mode === "list") renderObjectTable();
}

function findPath(from, to) {
  if (from === to) return [from];
  const prev = new Map();
  const queue = [from];
  const seen = new Set([from]);
  while (queue.length) {
    const current = queue.shift();
    DB_DATA.edges.filter(e => e.from === current).forEach(edge => {
      if (seen.has(edge.to)) return;
      seen.add(edge.to);
      prev.set(edge.to, current);
      queue.push(edge.to);
    });
    if (seen.has(to)) break;
  }
  if (!seen.has(to)) return [];
  const path = [to];
  while (path[0] !== from) path.unshift(prev.get(path[0]));
  return path;
}

function applyFocus(mode) {
  if (!selectedName) return;
  activePath = [];
  matrixDomainFilter = null;
  activeFocus = { mode, names: dependencySet(selectedName, mode) };
  edgeFilter.value = "all";
  pathResult.textContent = `${mode === "upstream" ? "Upstream" : "Downstream"} de ${selectedName}: ${activeFocus.names.size} objetos.`;
  updateVisibility();
}

function clearFocus() {
  activeFocus = null;
  activePath = [];
  matrixDomainFilter = null;
  pathResult.textContent = "";
  domainFilter.value = "all";
  typeFilter.value = "all";
  edgeFilter.value = "all";
  searchInput.value = "";
  updateVisibility();
}

function clearSelection() {
  selectedName = null;
  activeFocus = null;
  activePath = [];
  matrixDomainFilter = null;
  edgeFilter.value = "all";
  pathResult.textContent = "";
  detailTitle.textContent = "Sin nodo seleccionado";
  detailPills.innerHTML = `<span class="pill">Click en un nodo</span>`;
  detailBody.innerHTML = `
    <div class="detail-section">
      <h4>Detalle</h4>
      <div class="muted">Selecciona una tabla o vista del mapa o de la lista para ver columnas, relaciones, rangos y muestra.</div>
    </div>
  `;
  updateVisibility();
}

function initControls() {
  document.getElementById("schema-label").textContent = `SCHEMA VERSION ${DB_DATA.schemaVersion}`;
  document.getElementById("generated-label").textContent = `${DB_DATA.dbPath} · ${DB_DATA.generatedAt}`;
  document.getElementById("stat-version").textContent = fmt(DB_DATA.schemaVersion);
  document.getElementById("stat-tables").textContent = fmt(DB_DATA.tableCount);
  document.getElementById("stat-views").textContent = fmt(DB_DATA.viewCount);
  document.getElementById("stat-rows").textContent = fmt(DB_DATA.totalRows);
  document.getElementById("stat-edges").textContent = fmt(DB_DATA.edges.length);

  domainFilter.innerHTML = `<option value="all">Todos los dominios</option>` +
    DB_DATA.groups.map(g => `<option value="${esc(g.key)}">${esc(g.label)} (${g.count})</option>`).join("");
  const sortedNames = DB_DATA.objects.map(obj => obj.name).sort((a,b) => a.localeCompare(b));
  pathFrom.innerHTML = sortedNames.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
  pathTo.innerHTML = sortedNames.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
  pathFrom.value = "raw_eeff_line";
  pathTo.value = "dim_fondo";

  document.getElementById("domain-chips").innerHTML =
    `<button class="chip-btn active" type="button" data-domain="all">Todos</button>` +
    DB_DATA.groups.map(g => `<button class="chip-btn" type="button" data-domain="${esc(g.key)}">${esc(g.label)}</button>`).join("");
  document.querySelectorAll(".chip-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".chip-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      domainFilter.value = btn.dataset.domain;
      matrixDomainFilter = null;
      updateVisibility();
    });
  });

  [searchInput, domainFilter, typeFilter, edgeFilter, rowSort].forEach(control => {
    control.addEventListener("input", () => {
      matrixDomainFilter = null;
      const visible = baseVisibleObjects();
      if (!visible.some(obj => obj.name === selectedName) && visible[0]) selectNode(visible[0].name);
      updateVisibility();
    });
  });
  domainFilter.addEventListener("input", () => {
    document.querySelectorAll(".chip-btn").forEach(btn => btn.classList.toggle("active", btn.dataset.domain === domainFilter.value));
  });
  document.querySelectorAll(".mode-btn").forEach(btn => btn.addEventListener("click", () => setMode(btn.dataset.mode)));
  document.getElementById("reset-all").addEventListener("click", clearFocus);
  document.getElementById("center-map").addEventListener("click", () => { transform = { x: 20, y: 18, scale: 1 }; applyTransform(); });
  document.getElementById("zoom-in").addEventListener("click", () => { transform.scale = Math.min(1.9, transform.scale * 1.12); applyTransform(); });
  document.getElementById("zoom-out").addEventListener("click", () => { transform.scale = Math.max(.4, transform.scale / 1.12); applyTransform(); });
  document.getElementById("focus-upstream").addEventListener("click", () => applyFocus("upstream"));
  document.getElementById("focus-downstream").addEventListener("click", () => applyFocus("downstream"));
  document.getElementById("detail-focus").addEventListener("click", () => { activeFocus = { mode: "neighbors", names: new Set([selectedName, ...incoming(selectedName), ...outgoing(selectedName)]) }; edgeFilter.value = "selected"; updateVisibility(); });
  document.getElementById("detail-neighbors").addEventListener("click", () => { edgeFilter.value = "selected"; updateVisibility(); });
  document.getElementById("path-find").addEventListener("click", () => {
    activeFocus = null;
    matrixDomainFilter = null;
    const path = findPath(pathFrom.value, pathTo.value);
    activePath = path;
    if (path.length) {
      selectedName = path[0];
      renderDetail(byName.get(selectedName));
      pathResult.textContent = `Ruta: ${path.join(" → ")}`;
    } else {
      pathResult.textContent = `Sin ruta dirigida desde ${pathFrom.value} hacia ${pathTo.value}.`;
    }
    updateVisibility();
    setMode("map");
  });
}

function initPanZoom() {
  svg.addEventListener("wheel", event => {
    event.preventDefault();
    const delta = event.deltaY > 0 ? .92 : 1.08;
    transform.scale = Math.min(1.9, Math.max(.4, transform.scale * delta));
    applyTransform();
  }, { passive: false });
  svg.addEventListener("pointerdown", event => {
    panning = { x: event.clientX, y: event.clientY, tx: transform.x, ty: transform.y };
    pointerMoved = false;
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", event => {
    if (!panning) return;
    if (Math.abs(event.clientX - panning.x) > 3 || Math.abs(event.clientY - panning.y) > 3) pointerMoved = true;
    transform.x = panning.tx + event.clientX - panning.x;
    transform.y = panning.ty + event.clientY - panning.y;
    applyTransform();
  });
  svg.addEventListener("pointerup", event => {
    if (panning && !pointerMoved && event.target === svg) clearSelection();
    panning = null;
  });
  svg.addEventListener("pointercancel", () => { panning = null; pointerMoved = false; });
}

initControls();
renderMap();
renderMatrix();
selectNode(selectedName);
initPanZoom();
window.addEventListener("resize", renderMap);
</script>
</body>
</html>
"""


def main() -> None:
    metadata = collect_metadata()
    data_json = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    html = (
        FS_HTML_TEMPLATE
        .replace("__DATA_JSON__", data_json)
        .replace("__LOGO_SRC__", data_uri("toesca_logo_white.png"))
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8", newline="\n")
    print(f"Generado {OUT_PATH.relative_to(ROOT)}")
    print(
        f"Objetos: {metadata['tableCount']} tablas, {metadata['viewCount']} vistas, "
        f"{metadata['totalRows']:,} filas en tablas, {len(metadata['edges'])} relaciones."
    )


if __name__ == "__main__":
    main()
