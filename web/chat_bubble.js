/* Burbuja flotante del Asistente Virtual Inmobiliario Toesca.
   Incluir con un tag <script> apuntando a este archivo (src="/chat_bubble.js" defer),
   o inlineado directo dentro de otro documento (ver build_factsheet.py).
   Requiere endpoint POST /api/chat. */
(function () {
  if (window.__toescaChatMounted) return;
  window.__toescaChatMounted = true;

  // factsheet.html se abre a menudo como file:// (doble clic) en vez de servido
  // por Flask. En ese caso las rutas relativas no resuelven, asi que se apunta
  // directo al servidor local del agente.
  const API_BASE = window.__TC_API_BASE__ ||
    (location.protocol === "file:" ? "http://127.0.0.1:8765" : "");

  const CSS = `
  .tc-fab{position:fixed;right:22px;bottom:22px;z-index:99998;width:58px;height:58px;
    border-radius:50%;background:#111;color:#e8e3dc;display:flex;align-items:center;
    justify-content:center;cursor:pointer;box-shadow:0 10px 25px rgba(15,23,42,.35);
    border:1px solid #222;transition:transform .15s ease, background .15s ease;
    font-family:Georgia,"Times New Roman",serif;font-size:24px;letter-spacing:-.5px}
  .tc-fab:hover{transform:translateY(-2px);background:#1e293b}
  .tc-fab.hidden{display:none}
  .tc-fab-label{position:fixed;right:92px;bottom:32px;z-index:99997;background:#fff;
    color:#0f172a;border:1px solid #e2e8f0;border-radius:999px;padding:8px 12px;
    box-shadow:0 10px 25px rgba(15,23,42,.16);font-family:-apple-system,
    BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:13px;font-weight:600;
    cursor:pointer;white-space:nowrap;transition:opacity .18s ease,transform .18s ease}
  .tc-fab-label::after{content:"";position:absolute;right:-5px;top:50%;width:9px;height:9px;
    background:#fff;border-right:1px solid #e2e8f0;border-top:1px solid #e2e8f0;
    transform:translateY(-50%) rotate(45deg)}
  .tc-fab-label:hover{transform:translateY(-1px)}
  .tc-fab-label.hidden{display:none}
  @media (max-width: 560px){.tc-fab-label{right:86px;bottom:32px;font-size:12.5px}}
  .tc-panel{position:fixed;right:22px;bottom:22px;z-index:99999;width:420px;
    max-width:calc(100vw - 32px);height:620px;max-height:calc(100vh - 40px);
    background:#fff;border-radius:16px;box-shadow:0 20px 45px rgba(15,23,42,.28);
    display:none;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,
    "Segoe UI",Roboto,sans-serif;color:#0f172a;overflow:hidden}
  .tc-panel.open{display:flex}
  .tc-head{padding:14px 16px;background:#0f172a;color:#fff;display:flex;
    align-items:center;justify-content:space-between}
  .tc-head-brand{display:flex;align-items:center;gap:10px}
  .tc-mark{width:32px;height:32px;border-radius:4px;background:#111;border:1px solid #222;
    color:#e8e3dc;display:inline-flex;align-items:center;justify-content:center;
    font-family:Georgia,"Times New Roman",serif;font-size:16px;letter-spacing:-.5px;
    flex:0 0 auto}
  .tc-head strong{font-size:15px}
  .tc-head small{opacity:.75;font-size:11px;display:block;margin-top:2px}
  .tc-close{background:transparent;border:none;color:#fff;font-size:22px;
    cursor:pointer;line-height:1;padding:0 4px}
  .tc-body{flex:1;overflow-y:auto;padding:14px;background:#f8fafc;
    display:flex;flex-direction:column;gap:10px}
  .tc-msg{max-width:88%;padding:9px 12px;border-radius:12px;font-size:13.5px;
    line-height:1.45;word-wrap:break-word}
  .tc-msg.user{align-self:flex-end;background:#0f172a;color:#fff;border-bottom-right-radius:4px}
  .tc-msg.bot{align-self:flex-start;background:#fff;border:1px solid #e2e8f0;
    color:#0f172a;border-bottom-left-radius:4px}
  .tc-msg.bot h1,.tc-msg.bot h2,.tc-msg.bot h3{margin:.4em 0;font-size:14px}
  .tc-msg.bot table{border-collapse:collapse;margin:.4em 0;font-size:12px}
  .tc-msg.bot th,.tc-msg.bot td{border:1px solid #e2e8f0;padding:3px 6px;text-align:left}
  .tc-msg.bot code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}
  .tc-msg.bot pre{background:#0f172a;color:#e2e8f0;padding:8px;border-radius:6px;
    overflow-x:auto;font-size:11.5px}
  .tc-row{display:flex;gap:8px;align-items:flex-end}
  .tc-row.bot{align-self:flex-start;max-width:94%}
  .tc-row.bot .tc-msg{max-width:none}
  .tc-row .tc-mark{width:28px;height:28px;font-size:14px}
  .tc-sql{margin-top:6px;font-size:11px;color:#64748b;cursor:pointer;user-select:none}
  .tc-sql code{background:#f1f5f9;padding:1px 5px;border-radius:3px}
  .tc-sql-body{display:none;margin-top:6px;background:#0f172a;color:#e2e8f0;
    padding:8px;border-radius:6px;font-size:11px;overflow-x:auto;white-space:pre-wrap}
  .tc-sql.open .tc-sql-body{display:block}
  .tc-typing{align-self:flex-start;color:#64748b;font-size:12.5px;font-style:italic}
  .tc-input{border-top:1px solid #e2e8f0;padding:10px;background:#fff;
    display:flex;gap:8px}
  .tc-input textarea{flex:1;border:1px solid #cbd5e1;border-radius:10px;
    padding:9px 12px;font-size:13.5px;resize:none;height:42px;max-height:120px;
    font-family:inherit;outline:none}
  .tc-input textarea:focus{border-color:#0f172a}
  .tc-send{background:#0f172a;color:#fff;border:none;border-radius:10px;
    padding:0 16px;cursor:pointer;font-size:13px;font-weight:600}
  .tc-send:disabled{opacity:.45;cursor:not-allowed}
  .tc-hint{font-size:11px;color:#94a3b8;padding:0 14px 8px}
  .tc-chart-wrap{margin:.4em 0}
  .tc-chart{display:block;max-width:100%}
  .tc-chart-legend{font-size:10px;color:#64748b;margin-bottom:2px}
  .tc-chart-legend span{margin-right:8px;white-space:nowrap}
  `;

  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  const fab = document.createElement("button");
  fab.className = "tc-fab";
  fab.title = "Preguntale al asistente";
  fab.innerHTML = "t.";
  document.body.appendChild(fab);

  const fabLabel = document.createElement("button");
  fabLabel.className = "tc-fab-label";
  fabLabel.type = "button";
  fabLabel.textContent = "Abrir chat";
  document.body.appendChild(fabLabel);

  const panel = document.createElement("div");
  panel.className = "tc-panel";
  panel.innerHTML = `
    <div class="tc-head">
      <div class="tc-head-brand">
        <span class="tc-mark">t.</span>
        <div>
          <strong>Asistente Virtual Inmobiliario Toesca</strong>
          <small>Respuestas con informacion interna verificada</small>
        </div>
      </div>
      <button class="tc-close" title="Cerrar">×</button>
    </div>
    <div class="tc-body" id="tc-body">
      <div class="tc-row bot">
        <span class="tc-mark">t.</span>
        <div class="tc-msg bot">
          ¡Hola! Soy el asistente virtual inmobiliario de Toesca.
          Preguntame por un fondo, activo, periodo o indicador.
        </div>
      </div>
    </div>
    <div class="tc-hint">El contenido generado por la IA puede ser inexacto.</div>
    <div class="tc-input">
      <textarea id="tc-q" placeholder="Escribe tu pregunta…" rows="1"></textarea>
      <button class="tc-send" id="tc-send">Enviar</button>
    </div>`;
  document.body.appendChild(panel);

  const body = panel.querySelector("#tc-body");
  const input = panel.querySelector("#tc-q");
  const sendBtn = panel.querySelector("#tc-send");
  const closeBtn = panel.querySelector(".tc-close");

  const history = [];

  function toggle(open) {
    const isOpen = open ?? !panel.classList.contains("open");
    panel.classList.toggle("open", isOpen);
    fab.classList.toggle("hidden", isOpen);
    fabLabel.classList.toggle("hidden", isOpen);
    if (isOpen) setTimeout(() => input.focus(), 50);
  }

  fab.addEventListener("click", () => toggle(true));
  fabLabel.addEventListener("click", () => toggle(true));
  closeBtn.addEventListener("click", () => toggle(false));

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener("click", send);

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    }[c]));
  }

  // ─── Graficos: bloques ```chart con JSON crudo -> SVG inline (sin libs) ───
  const CHART_COLORS = ["#0f172a", "#2563eb", "#16a34a", "#dc2626"];

  function fmtAxis(v) {
    if (typeof v !== "number" || !isFinite(v)) return "";
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1).replace(".", ",") + "k";
    const r = Math.round(v * 10) / 10;
    return String(r).replace(".", ",");
  }

  function buildChartSvg(spec) {
    const labels = Array.isArray(spec.labels) ? spec.labels : [];
    const series = Array.isArray(spec.series) ? spec.series : [];
    if (!labels.length || !series.length) throw new Error("chart vacio");
    const W = 300, H = 150, padL = 30, padB = 20, padT = spec.title ? 18 : 6, padR = 6;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const allVals = series.flatMap((s) => (s.values || []).filter((v) => typeof v === "number"));
    if (!allVals.length) throw new Error("sin valores numericos");
    const maxV = Math.max(...allVals, 0);
    const minV = Math.min(...allVals, 0);
    const range = (maxV - minV) || 1;
    const y = (v) => padT + plotH - ((v - minV) / range) * plotH;
    const zeroY = y(0);
    const isLine = spec.type === "line";

    let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" class="tc-chart">`;
    if (spec.title) {
      svg += `<text x="${padL}" y="12" font-size="9" fill="#334155">${escapeHtml(spec.title)}</text>`;
    }
    svg += `<line x1="${padL}" y1="${zeroY}" x2="${W - padR}" y2="${zeroY}" stroke="#cbd5e1" stroke-width="1"/>`;
    svg += `<text x="1" y="${padT + 4}" font-size="7" fill="#94a3b8">${fmtAxis(maxV)}</text>`;
    if (minV !== maxV) {
      svg += `<text x="1" y="${padT + plotH}" font-size="7" fill="#94a3b8">${fmtAxis(minV)}</text>`;
    }

    if (isLine) {
      const stepX = labels.length > 1 ? plotW / (labels.length - 1) : 0;
      series.forEach((s, si) => {
        const color = CHART_COLORS[si % CHART_COLORS.length];
        const vals = s.values || [];
        const pts = vals.map((v, i) => `${padL + i * stepX},${y(v)}`).join(" ");
        svg += `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6"/>`;
        vals.forEach((v, i) => {
          svg += `<circle cx="${padL + i * stepX}" cy="${y(v)}" r="1.8" fill="${color}">` +
            `<title>${escapeHtml(String(labels[i]))}: ${fmtAxis(v)}</title></circle>`;
        });
      });
    } else {
      const n = labels.length;
      const groupW = plotW / n;
      const barGap = 2;
      const barW = Math.max((groupW - barGap * 2) / series.length, 1);
      labels.forEach((_lab, i) => {
        series.forEach((s, si) => {
          const v = (s.values || [])[i];
          if (typeof v !== "number") return;
          const x = padL + i * groupW + barGap + si * barW;
          const yTop = Math.min(y(v), zeroY);
          const h = Math.max(Math.abs(y(v) - zeroY), 0.5);
          const color = CHART_COLORS[si % CHART_COLORS.length];
          svg += `<rect x="${x}" y="${yTop}" width="${Math.max(barW - 1, 1)}" height="${h}" fill="${color}">` +
            `<title>${escapeHtml(String(labels[i]))} ${escapeHtml(s.name || "")}: ${fmtAxis(v)}</title></rect>`;
        });
      });
    }

    const showEvery = Math.max(1, Math.ceil(labels.length / 6));
    labels.forEach((lab, i) => {
      if (i % showEvery !== 0 && i !== labels.length - 1) return;
      const x = isLine
        ? padL + (labels.length > 1 ? (plotW / (labels.length - 1)) * i : 0)
        : padL + (i + 0.5) * (plotW / labels.length);
      svg += `<text x="${x}" y="${H - 4}" font-size="7" fill="#94a3b8" text-anchor="middle">` +
        `${escapeHtml(String(lab).slice(-5))}</text>`;
    });

    svg += `</svg>`;

    let legend = "";
    if (series.length > 1) {
      legend = `<div class="tc-chart-legend">${series.map((s, si) =>
        `<span style="color:${CHART_COLORS[si % CHART_COLORS.length]}">■ ${escapeHtml(s.name || "")}</span>`
      ).join("")}</div>`;
    }
    return `<div class="tc-chart-wrap">${legend}${svg}</div>`;
  }

  function renderChartBlock(jsonStr) {
    try {
      const spec = JSON.parse(jsonStr);
      return buildChartSvg(spec);
    } catch (e) {
      return `<pre>${escapeHtml(jsonStr)}</pre>`;
    }
  }

  // Renderer Markdown minimalista (headings, bold, italic, code, tablas, lists, graficos)
  function mdToHtml(md) {
    // Extraer bloques ```chart ANTES de escapar (necesitan el JSON crudo con
    // comillas dobles intactas). Se sustituyen por placeholders sin newlines
    // para que sobrevivan intactos a las transformaciones de parrafos/saltos.
    const chartBlocks = [];
    md = md.replace(/```chart\s*\n([\s\S]*?)```/g, (_m, jsonStr) => {
      const idx = chartBlocks.length;
      chartBlocks.push(jsonStr.trim());
      return `CHART${idx}`;
    });
    md = escapeHtml(md);
    // fenced code
    md = md.replace(/```(\w+)?\n([\s\S]*?)```/g, (_m, _l, code) =>
      `<pre>${code}</pre>`);
    // tablas GFM simples
    md = md.replace(/((?:^\|.*\|\n)+)/gm, (block) => {
      const lines = block.trim().split("\n");
      if (lines.length < 2) return block;
      const head = lines[0].split("|").slice(1, -1).map((c) => c.trim());
      const rows = lines.slice(2).map((r) =>
        r.split("|").slice(1, -1).map((c) => c.trim()));
      const th = head.map((c) => `<th>${c}</th>`).join("");
      const trs = rows.map((r) =>
        `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
      return `<table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`;
    });
    // headings
    md = md.replace(/^### (.*)$/gm, "<h3>$1</h3>");
    md = md.replace(/^## (.*)$/gm, "<h2>$1</h2>");
    md = md.replace(/^# (.*)$/gm, "<h1>$1</h1>");
    // bold + italic + inline code
    md = md.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    md = md.replace(/\*([^*]+)\*/g, "<i>$1</i>");
    md = md.replace(/_([^_]+)_/g, "<i>$1</i>");
    md = md.replace(/`([^`]+)`/g, "<code>$1</code>");
    // listas
    md = md.replace(/(^|\n)([\-*] .+(?:\n[\-*] .+)*)/g, (m, pre, list) => {
      const items = list.split("\n").map((l) =>
        `<li>${l.replace(/^[\-*] /, "")}</li>`).join("");
      return `${pre}<ul>${items}</ul>`;
    });
    // parrafos
    md = md.replace(/\n{2,}/g, "</p><p>");
    md = md.replace(/\n/g, "<br>");
    let html = `<p>${md}</p>`;
    // sustituir placeholders de graficos por el SVG ya renderizado
    html = html.replace(/CHART(\d+)/g, (_m, i) => renderChartBlock(chartBlocks[+i]));
    return html;
  }

  function addMsg(role, html) {
    if (role === "bot") {
      const row = document.createElement("div");
      row.className = "tc-row bot";
      row.innerHTML = `<span class="tc-mark">t.</span><div class="tc-msg bot">${html}</div>`;
      body.appendChild(row);
      body.scrollTop = body.scrollHeight;
      return row;
    }
    const div = document.createElement("div");
    div.className = `tc-msg ${role}`;
    div.innerHTML = html;
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  function typeHtml(el, html) {
    return new Promise((resolve) => {
      const chunk = Math.max(1, Math.floor(html.length / 220));
      let i = 0;
      function step() {
        if (i >= html.length) {
          resolve();
          return;
        }
        let n = chunk;
        let piece = "";
        while (n-- > 0 && i < html.length) {
          if (html[i] === "<") {
            const close = html.indexOf(">", i);
            const end = close === -1 ? html.length : close + 1;
            piece += html.slice(i, end);
            i = end;
          } else if (html[i] === "&") {
            const semi = html.indexOf(";", i);
            const end = semi !== -1 && semi - i <= 8 ? semi + 1 : i + 1;
            piece += html.slice(i, end);
            i = end;
          } else {
            piece += html[i];
            i++;
          }
        }
        // insertAdjacentHTML solo parsea el fragmento nuevo, sin re-serializar
        // el DOM ya insertado (innerHTML += rompe entidades como &quot; a mitad de tipeo).
        el.insertAdjacentHTML("beforeend", piece);
        body.scrollTop = body.scrollHeight;
        requestAnimationFrame(() => setTimeout(step, 15));
      }
      step();
    });
  }

  function addTyping() {
    const div = document.createElement("div");
    div.className = "tc-typing";
    div.textContent = "Consultando informacion…";
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  async function send() {
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    input.style.height = "42px";
    sendBtn.disabled = true;

    addMsg("user", escapeHtml(q));
    history.push({ role: "user", content: q });
    const typing = addTyping();

    try {
      // El servidor exige X-Ingesta-Token; lo inyecta al servir la pagina. Si el
      // factsheet se abrio como file:// no hay token y la respuesta es 401.
      const headers = { "Content-Type": "application/json" };
      if (window.INGESTA_TOKEN) headers["X-Ingesta-Token"] = window.INGESTA_TOKEN;
      const r = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({ question: q, history }),
      });
      if (r.status === 401) {
        typing.remove();
        addMsg("bot", "⚠️ Abre el factsheet desde <b>http://127.0.0.1:8765/factsheet</b> para usar el asistente.");
        return;
      }
      const data = await r.json();
      typing.remove();

      let html = mdToHtml(data.answer_md || "(sin respuesta)");
      if (data.sql) {
        const sqlEsc = escapeHtml(data.sql);
        html += `<div class="tc-sql" onclick="this.classList.toggle('open')">
          ▸ Ver detalle tecnico (${data.rows ? data.rows.length : 0} resultados)
          <div class="tc-sql-body">${sqlEsc}</div></div>`;
      }
      const row = addMsg("bot", "");
      const msgEl = row.querySelector(".tc-msg");
      await typeHtml(msgEl, html);
      history.push({ role: "assistant", content: data.answer_md || "" });
    } catch (err) {
      typing.remove();
      addMsg("bot", `⚠️ Error de red: ${escapeHtml(String(err))}`);
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  // autosize del textarea
  input.addEventListener("input", () => {
    input.style.height = "42px";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });
})();
