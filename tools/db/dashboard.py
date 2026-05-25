"""
Genera un dashboard HTML autocontenido con todo lo que tiene la DB del agente.

Sirve para ver la cobertura de datos y saber cómo seguir poblando la base.
No requiere servidor: produce un único archivo `dashboard.html` con los datos
embebidos como JSON y renderizado con HTML/CSS + Chart.js (CDN).

Uso:
    python -m tools.db.dashboard            # genera dashboard.html en la raíz
    python -m tools.db.dashboard ruta.html  # ruta de salida custom
"""
import json
import os
import sys
from datetime import datetime

from tools.db.connection import get_conn

_OUT_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "dashboard.html",
)

# Dominios raw keyed por activo
_RAW_ACTIVO = {
    "rent_roll": "raw_rent_roll_line",
    "er_activo": "raw_er_activo_line",
    "flujo": "raw_flujo_line",
}


def _periodos_ordenados(conn) -> list[str]:
    """Lista de períodos YYYY-MM presentes en cualquier dominio, ordenada."""
    periodos: set[str] = set()
    for tabla in _RAW_ACTIVO.values():
        for (p,) in conn.execute(f"SELECT DISTINCT periodo FROM {tabla}"):
            if p:
                periodos.add(p)
    for tabla, col in [("fact_precio_cuota", "fecha"), ("fact_dividendo", "fecha_pago"),
                       ("derived_kpi", "periodo")]:
        for (p,) in conn.execute(f"SELECT DISTINCT {col} FROM {tabla}"):
            if p:
                periodos.add(p[:7])
    return sorted(periodos)


def _recolectar(conn) -> dict:
    data: dict = {
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "resumen": [],
        "cobertura": {},
        "activos": [],
        "precios": {},
        "uf": [],
        "dividendos": {},
        "kpi": [],
        "gaps": [],
        "muestra": {},
    }

    # ── Resumen por dominio ───────────────────────────────────────────────────
    def _resumen(dom, tabla, period_col, ent_col):
        total = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        if total == 0:
            return {"dominio": dom, "filas": 0, "desde": None, "hasta": None, "entidades": []}
        rng = conn.execute(
            f"SELECT MIN({period_col}), MAX({period_col}) FROM {tabla}"
        ).fetchone()
        ents = []
        if ent_col:
            ents = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {ent_col} FROM {tabla} ORDER BY {ent_col}")]
        return {"dominio": dom, "filas": total, "desde": rng[0], "hasta": rng[1],
                "entidades": ents}

    data["resumen"] = [
        _resumen("rent_roll", "raw_rent_roll_line", "periodo", "activo_key"),
        _resumen("er_activo", "raw_er_activo_line", "periodo", "activo_key"),
        _resumen("flujo", "raw_flujo_line", "periodo", "activo_key"),
        _resumen("precios", "fact_precio_cuota", "fecha", "nemotecnico"),
        _resumen("uf", "fact_uf", "fecha", None),
        _resumen("dividendos", "fact_dividendo", "fecha_pago", "nemotecnico"),
        _resumen("kpi", "derived_kpi", "periodo", "kpi"),
    ]

    periodos = _periodos_ordenados(conn)
    data["periodos"] = periodos

    # ── Cobertura raw: dominio → {activo → {periodo: count}} ───────────────────
    activos_set: set[str] = set()
    for dom, tabla in _RAW_ACTIVO.items():
        matriz: dict = {}
        for activo, periodo, cnt in conn.execute(
            f"SELECT activo_key, periodo, COUNT(*) FROM {tabla} GROUP BY activo_key, periodo"
        ):
            activos_set.add(activo)
            matriz.setdefault(activo, {})[periodo] = cnt
        data["cobertura"][dom] = matriz
    data["activos"] = sorted(activos_set)

    # ── Precios: serie mensual por nemotécnico (último día del mes) ────────────
    for nemo, fecha, precio in conn.execute(
        "SELECT nemotecnico, fecha, precio FROM fact_precio_cuota ORDER BY fecha"
    ):
        data["precios"].setdefault(nemo, []).append({"x": fecha, "y": precio})

    # ── UF: serie mensual (último valor de cada mes) ──────────────────────────
    uf_mes: dict = {}
    for fecha, valor in conn.execute("SELECT fecha, valor_clp FROM fact_uf ORDER BY fecha"):
        uf_mes[fecha[:7]] = {"x": fecha, "y": valor}  # último del mes gana
    data["uf"] = list(uf_mes.values())

    # ── Dividendos por nemotécnico ────────────────────────────────────────────
    for nemo, fecha, monto in conn.execute(
        "SELECT nemotecnico, fecha_pago, monto FROM fact_dividendo ORDER BY fecha_pago"
    ):
        data["dividendos"].setdefault(nemo, []).append({"x": fecha, "y": monto})

    # ── KPI ────────────────────────────────────────────────────────────────────
    for et, ek, per, kpi, val, uni, recipe in conn.execute(
        "SELECT entidad_tipo, entidad_key, periodo, kpi, valor, unidad, recipe "
        "FROM derived_kpi ORDER BY kpi, entidad_key, periodo"
    ):
        data["kpi"].append({"entidad_tipo": et, "entidad_key": ek, "periodo": per,
                            "kpi": kpi, "valor": val, "unidad": uni, "recipe": recipe})

    # ── Vacancia: serie m² vacantes por segmento ───────────────────────────────
    data["vacancia"] = {}
    for ek, per, val in conn.execute(
        "SELECT entidad_key, periodo, valor FROM derived_kpi "
        "WHERE kpi='m2_vacantes' ORDER BY periodo"
    ):
        data["vacancia"].setdefault(ek, []).append({"x": per, "y": val})

    # ── Muestra de datos (último período por activo, capado) ───────────────────
    for dom, tabla in _RAW_ACTIVO.items():
        filas = []
        # último período global del dominio
        row = conn.execute(f"SELECT MAX(periodo) FROM {tabla}").fetchone()
        ult = row[0] if row else None
        if ult:
            cur = conn.execute(f"SELECT * FROM {tabla} WHERE periodo=? LIMIT 400", (ult,))
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                filas.append({c: r[c] for c in cols})
        data["muestra"][dom] = {"periodo": ult, "filas": filas}

    # ── Gaps: por dominio raw, (activo, periodo) faltantes en el rango ─────────
    # Rango de períodos relevante = min..max del dominio
    for dom, tabla in _RAW_ACTIVO.items():
        cob = data["cobertura"][dom]
        if not cob:
            continue
        # períodos presentes en este dominio
        pres = sorted({p for m in cob.values() for p in m})
        if not pres:
            continue
        rango = [p for p in periodos if pres[0] <= p <= pres[-1]]
        activos_dom = sorted(cob.keys())
        faltantes = []
        for a in activos_dom:
            for p in rango:
                if p not in cob.get(a, {}):
                    faltantes.append({"activo": a, "periodo": p})
        if faltantes:
            data["gaps"].append({"dominio": dom, "faltantes": faltantes})

    return data


def generar_dashboard(output_path: str = _OUT_DEFAULT) -> str:
    with get_conn() as conn:
        data = _recolectar(conn)
    html = _render_html(data)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return _HTML_TEMPLATE.replace("/*__DATA__*/", payload)


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agente Toesca · Base de Datos</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root{
    --bg:#0f0f10; --panel:#17171a; --panel2:#1e1e22; --line:#2a2a30;
    --ink:#e8e3dc; --muted:#9a958d; --accent:#c9a96a; --ok:#4a9d6e; --warn:#b4823c; --bad:#7a3b3b;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5}
  header{padding:22px 28px;border-bottom:1px solid var(--line);
    display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;background:#111}
  header .logo{font-family:Georgia,serif;font-size:24px;color:var(--accent)}
  header .sub{color:var(--muted);font-size:13px}
  main{padding:24px 28px;max-width:1280px;margin:0 auto}
  h2{font-size:15px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);
    margin:36px 0 14px;font-weight:600;border-bottom:1px solid var(--line);padding-bottom:8px}
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .dom{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .card .big{font-size:26px;font-weight:600;margin:4px 0}
  .card .rng{color:var(--muted);font-size:12px}
  .card.empty{opacity:.55}
  .card.empty .big{color:var(--bad)}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th,td{border:1px solid var(--line);padding:6px 9px;text-align:left}
  th{background:var(--panel2);color:var(--muted);font-weight:600;position:sticky;top:0}
  .matrix td{text-align:center;font-variant-numeric:tabular-nums}
  .heat-0{background:#1b1b1e;color:#55504a}
  .heat-1{background:#243a2e;color:#bfe6cf}
  .heat-2{background:#2c5340;color:#d9f3e3}
  .heat-3{background:#357a55;color:#eafff2}
  .wrap{overflow:auto;border:1px solid var(--line);border-radius:10px;max-height:460px}
  .chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:18px}
  .chartbox{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
  .chartbox h3{margin:0 0 10px;font-size:13px;color:var(--muted);font-weight:600}
  .gaps li{margin:3px 0}
  .pill{display:inline-block;background:var(--panel2);border:1px solid var(--line);
    border-radius:20px;padding:2px 10px;margin:2px;font-size:12px;color:var(--muted)}
  .tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
  .tab{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 12px;
    cursor:pointer;color:var(--muted);font-size:13px}
  .tab.active{background:var(--accent);color:#111;border-color:var(--accent);font-weight:600}
  .muted{color:var(--muted)}
  .gapcount{color:var(--warn);font-weight:600}
</style>
</head>
<body>
<header>
  <span class="logo">t.</span>
  <span><strong>Agente Toesca</strong> · Base de Datos</span>
  <span class="sub" id="gen"></span>
</header>
<main>
  <h2>Resumen por dominio</h2>
  <div class="cards" id="cards"></div>

  <h2>Cobertura — filas por activo y período</h2>
  <div class="tabs" id="cov-tabs"></div>
  <div class="wrap"><div id="cov-matrix"></div></div>
  <p class="muted">Verde = hay datos (más intenso = más filas). Gris = vacío → ahí falta poblar.</p>

  <h2>Series de mercado</h2>
  <div class="chart-grid">
    <div class="chartbox"><h3>Precio cuota por serie</h3><canvas id="ch-precios"></canvas></div>
    <div class="chartbox"><h3>UF (mensual)</h3><canvas id="ch-uf"></canvas></div>
    <div class="chartbox"><h3>Dividendos por cuota</h3><canvas id="ch-div"></canvas></div>
  </div>

  <h2>Vacancia (m² vacantes por segmento)</h2>
  <div class="chartbox"><canvas id="ch-vac"></canvas></div>

  <h2>Gaps a poblar</h2>
  <div id="gaps"></div>

  <h2>Explorador de datos (último período)</h2>
  <div class="tabs" id="expl-tabs"></div>
  <div class="wrap"><div id="expl"></div></div>

  <h2>KPIs calculados</h2>
  <div class="wrap"><div id="kpi"></div></div>
</main>

<script>
const DATA = /*__DATA__*/;
const $ = s => document.querySelector(s);
document.getElementById('gen').textContent = 'generado ' + DATA.generado;

// ── Cards ──────────────────────────────────────────────────────────────────
const fmt = n => (n==null?'—':n.toLocaleString('es-CL'));
$('#cards').innerHTML = DATA.resumen.map(r=>{
  const empty = r.filas===0;
  return `<div class="card ${empty?'empty':''}">
    <div class="dom">${r.dominio}</div>
    <div class="big">${fmt(r.filas)}</div>
    <div class="rng">${empty?'vacío':(r.desde||'')+' → '+(r.hasta||'')}</div>
    ${r.entidades&&r.entidades.length?`<div class="rng">${r.entidades.slice(0,6).join(', ')}</div>`:''}
  </div>`;
}).join('');

// ── Cobertura matriz ───────────────────────────────────────────────────────
const covDoms = Object.keys(DATA.cobertura).filter(d=>Object.keys(DATA.cobertura[d]).length);
let covActive = covDoms[0];
function heatClass(n){ if(!n) return 'heat-0'; if(n<10) return 'heat-1'; if(n<100) return 'heat-2'; return 'heat-3'; }
function renderCov(){
  const cob = DATA.cobertura[covActive]||{};
  const activos = Object.keys(cob).sort();
  const pres = [...new Set(activos.flatMap(a=>Object.keys(cob[a])))].sort();
  let html = '<table class="matrix"><thead><tr><th>activo \\ período</th>'+
    pres.map(p=>`<th>${p}</th>`).join('')+'</tr></thead><tbody>';
  for(const a of activos){
    html += `<tr><td style="text-align:left">${a}</td>`+
      pres.map(p=>{const n=cob[a][p]||0;return `<td class="${heatClass(n)}">${n||''}</td>`}).join('')+'</tr>';
  }
  html+='</tbody></table>';
  $('#cov-matrix').innerHTML = html;
}
$('#cov-tabs').innerHTML = covDoms.map(d=>`<span class="tab ${d===covActive?'active':''}" data-d="${d}">${d}</span>`).join('');
$('#cov-tabs').onclick = e=>{ if(!e.target.dataset.d)return; covActive=e.target.dataset.d;
  document.querySelectorAll('#cov-tabs .tab').forEach(t=>t.classList.toggle('active',t.dataset.d===covActive)); renderCov(); };
renderCov();

// ── Charts ─────────────────────────────────────────────────────────────────
const palette = ['#c9a96a','#6a9ec9','#8ec96a','#c96a8e','#6ac9b8','#b06ac9'];
function lineChart(canvasId, seriesObj){
  if(typeof Chart==='undefined') return;
  const ds = Object.keys(seriesObj).map((k,i)=>({label:k,data:seriesObj[k],
    borderColor:palette[i%palette.length],backgroundColor:palette[i%palette.length],
    pointRadius:0,borderWidth:1.6,tension:.2}));
  new Chart(document.getElementById(canvasId),{type:'line',
    data:{datasets:ds},
    options:{parsing:{xAxisKey:'x',yAxisKey:'y'},responsive:true,
      scales:{x:{type:'category',ticks:{color:'#9a958d',maxTicksLimit:8},grid:{color:'#2a2a30'}},
              y:{ticks:{color:'#9a958d'},grid:{color:'#2a2a30'}}},
      plugins:{legend:{labels:{color:'#e8e3dc',boxWidth:12,font:{size:11}}}}}});
}
lineChart('ch-precios', DATA.precios);
lineChart('ch-uf', {UF: DATA.uf});
lineChart('ch-div', DATA.dividendos);
if(DATA.vacancia && Object.keys(DATA.vacancia).length) lineChart('ch-vac', DATA.vacancia);

// ── Gaps ───────────────────────────────────────────────────────────────────
$('#gaps').innerHTML = DATA.gaps.length ? DATA.gaps.map(g=>{
  const byA = {};
  g.faltantes.forEach(f=>{(byA[f.activo]=byA[f.activo]||[]).push(f.periodo)});
  return `<div style="margin-bottom:12px"><strong>${g.dominio}</strong>
    <span class="gapcount">(${g.faltantes.length} faltantes)</span><br>`+
    Object.keys(byA).map(a=>`<div><span class="pill">${a}</span> ${byA[a].join(', ')}</div>`).join('')+
    `</div>`;
}).join('') : '<p class="muted">Sin gaps en los rangos cubiertos.</p>';

// ── Explorador ─────────────────────────────────────────────────────────────
const explDoms = Object.keys(DATA.muestra).filter(d=>DATA.muestra[d].filas.length);
let explActive = explDoms[0];
function renderExpl(){
  const m = DATA.muestra[explActive];
  if(!m||!m.filas.length){ $('#expl').innerHTML='<p class="muted">Sin datos.</p>'; return; }
  const cols = Object.keys(m.filas[0]).filter(c=>!['id','file_hash','ingest_run_id','loaded_at','superseded_at','extra_json'].includes(c));
  let html=`<table><thead><tr>${cols.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>`;
  for(const f of m.filas){ html+='<tr>'+cols.map(c=>`<td>${f[c]==null?'':f[c]}</td>`).join('')+'</tr>'; }
  html+='</tbody></table>';
  $('#expl').innerHTML = `<p class="muted" style="padding:6px 9px">período ${m.periodo} · ${m.filas.length} filas (máx 400)</p>`+html;
}
$('#expl-tabs').innerHTML = explDoms.map(d=>`<span class="tab ${d===explActive?'active':''}" data-d="${d}">${d}</span>`).join('');
$('#expl-tabs').onclick = e=>{ if(!e.target.dataset.d)return; explActive=e.target.dataset.d;
  document.querySelectorAll('#expl-tabs .tab').forEach(t=>t.classList.toggle('active',t.dataset.d===explActive)); renderExpl(); };
renderExpl();

// ── KPI ────────────────────────────────────────────────────────────────────
if(DATA.kpi.length){
  let html='<table><thead><tr><th>tipo</th><th>entidad</th><th>período</th><th>kpi</th><th>valor</th><th>unidad</th><th>receta</th></tr></thead><tbody>';
  for(const k of DATA.kpi){ html+=`<tr><td>${k.entidad_tipo}</td><td>${k.entidad_key}</td><td>${k.periodo}</td><td>${k.kpi}</td><td style="text-align:right">${(k.valor==null?'':k.valor.toLocaleString('es-CL'))}</td><td>${k.unidad||''}</td><td class="muted">${k.recipe}</td></tr>`; }
  html+='</tbody></table>'; $('#kpi').innerHTML=html;
} else { $('#kpi').innerHTML='<p class="muted">Sin KPIs.</p>'; }
</script>
</body>
</html>"""


def main(argv: list[str]) -> None:
    out = argv[1] if len(argv) > 1 else _OUT_DEFAULT
    path = generar_dashboard(out)
    print(f"Dashboard generado: {path}")


if __name__ == "__main__":
    main(sys.argv)
