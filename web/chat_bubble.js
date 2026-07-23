/* Burbuja flotante de chat contra la DB del agente.
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
    border-radius:50%;background:#0f172a;color:#fff;display:flex;align-items:center;
    justify-content:center;cursor:pointer;box-shadow:0 10px 25px rgba(15,23,42,.35);
    border:none;transition:transform .15s ease, background .15s ease;font-size:26px}
  .tc-fab:hover{transform:translateY(-2px);background:#1e293b}
  .tc-fab.hidden{display:none}
  .tc-panel{position:fixed;right:22px;bottom:22px;z-index:99999;width:420px;
    max-width:calc(100vw - 32px);height:620px;max-height:calc(100vh - 40px);
    background:#fff;border-radius:16px;box-shadow:0 20px 45px rgba(15,23,42,.28);
    display:none;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,
    "Segoe UI",Roboto,sans-serif;color:#0f172a;overflow:hidden}
  .tc-panel.open{display:flex}
  .tc-head{padding:14px 16px;background:#0f172a;color:#fff;display:flex;
    align-items:center;justify-content:space-between}
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
  `;

  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  const fab = document.createElement("button");
  fab.className = "tc-fab";
  fab.title = "Preguntale a la DB";
  fab.innerHTML = "💬";
  document.body.appendChild(fab);

  const panel = document.createElement("div");
  panel.className = "tc-panel";
  panel.innerHTML = `
    <div class="tc-head">
      <div>
        <strong>Agente DB Toesca</strong>
        <small>Responde solo con datos reales de agente_toesca_v2.db</small>
      </div>
      <button class="tc-close" title="Cerrar">×</button>
    </div>
    <div class="tc-body" id="tc-body">
      <div class="tc-msg bot">
        Hola. Preguntame lo que quieras sobre el portfolio: NOI, vacancia,
        rent roll, EEFF, precios cuota, dividendos, KPIs, comparativas.
        Respondo <b>solo</b> con lo que hay en la DB.
      </div>
    </div>
    <div class="tc-hint">Ejemplos: "NOI Viña Centro 2026", "vacancia PT ultimos 6 meses", "valor cuota TRI serie A al cierre 2026-03"</div>
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
    if (isOpen) setTimeout(() => input.focus(), 50);
  }

  fab.addEventListener("click", () => toggle(true));
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

  // Renderer Markdown minimalista (headings, bold, italic, code, tablas, lists)
  function mdToHtml(md) {
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
    return `<p>${md}</p>`;
  }

  function addMsg(role, html) {
    const div = document.createElement("div");
    div.className = `tc-msg ${role}`;
    div.innerHTML = html;
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  function addTyping() {
    const div = document.createElement("div");
    div.className = "tc-typing";
    div.textContent = "Consultando la DB…";
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
      const r = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, history }),
      });
      const data = await r.json();
      typing.remove();

      let html = mdToHtml(data.answer_md || "(sin respuesta)");
      if (data.sql) {
        const sqlEsc = escapeHtml(data.sql);
        html += `<div class="tc-sql" onclick="this.classList.toggle('open')">
          ▸ Ver SQL (${data.rows ? data.rows.length : 0} filas)
          <div class="tc-sql-body">${sqlEsc}</div></div>`;
      }
      addMsg("bot", html);
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
