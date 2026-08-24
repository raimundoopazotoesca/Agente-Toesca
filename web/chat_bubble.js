/* Burbuja flotante del Asistente Virtual Inmobiliario Toesca.
   Incluir con un tag <script> apuntando a este archivo (src="/chat_bubble.js" defer),
   o inlineado directo dentro de otro documento (ver build_factsheet.py).
   Requiere la API /api/analyst y ToescaQuickChat. */
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
  .tc-head-actions{display:flex;align-items:center;gap:2px}
  .tc-close,.tc-expand{background:transparent;border:none;color:#fff;font-size:22px;
    cursor:pointer;line-height:1;padding:0 4px;opacity:.85}
  .tc-expand{font-size:16px}
  .tc-close:hover,.tc-expand:hover{opacity:1}
  .tc-body{flex:1;overflow-y:auto;padding:14px;background:#f8fafc;
    display:flex;flex-direction:column;gap:10px}
  .tc-msg{max-width:88%;padding:9px 12px;border-radius:12px;font-size:13.5px;
    line-height:1.45;word-wrap:break-word}
  .tc-msg.user{align-self:flex-end;background:#0f172a;color:#fff;border-bottom-right-radius:4px}
  .tc-msg.bot{align-self:flex-start;background:#fff;border:1px solid #e2e8f0;
    color:#0f172a;border-bottom-left-radius:4px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
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
  .tc-typing{align-self:flex-start;display:flex;align-items:center;gap:7px;
    padding:9px 12px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;
    border-bottom-left-radius:4px}
  .tc-typing-dots{display:flex;gap:3px}
  .tc-typing-dots span{width:5px;height:5px;border-radius:50%;background:#94a3b8;
    animation:tc-bounce 1.1s infinite ease-in-out both}
  .tc-typing-dots span:nth-child(1){animation-delay:-.24s}
  .tc-typing-dots span:nth-child(2){animation-delay:-.12s}
  @keyframes tc-bounce{0%,80%,100%{transform:scale(.6);opacity:.5}40%{transform:scale(1);opacity:1}}
  .tc-typing-label{color:#94a3b8;font-size:12px}
  .tc-error{margin:0 14px 10px;color:#b91c1c;font-size:12.5px;line-height:1.35}
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
      <div class="tc-head-actions">
        <button class="tc-expand" title="Abrir en pantalla completa">↗</button>
        <button class="tc-close" title="Cerrar">×</button>
      </div>
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
  const expandBtn = panel.querySelector(".tc-expand");

  // La conversación activa vive en sessionStorage (por pestaña, como antes)
  // pero también se refleja en localStorage bajo la misma clave: así una
  // pestaña nueva, o el workspace en pantalla completa, puede retomar la
  // última conversación usada sin necesitar sincronización en tiempo real.
  const sharedStorage = {
    getItem: (key) => sessionStorage.getItem(key) || localStorage.getItem(key),
    setItem: (key, value) => {
      sessionStorage.setItem(key, value);
      localStorage.setItem(key, value);
    },
    removeItem: (key) => {
      sessionStorage.removeItem(key);
      localStorage.removeItem(key);
    },
  };

  function analystHeaders() {
    const headers = {};
    if (window.INGESTA_TOKEN) headers["X-Ingesta-Token"] = window.INGESTA_TOKEN;
    return headers;
  }

  function buildFactsheetContext() {
    const periodSelector = document.getElementById("sel-periodo-op");
    return window.ToescaQuickChat.buildFactsheetContext(
      typeof currentFund === "string" ? currentFund : "",
      periodSelector ? periodSelector.value : "",
    );
  }

  const chatController = window.ToescaQuickChat.createQuickChatController({
    apiBase: API_BASE,
    storage: sharedStorage,
    fetch: window.fetch.bind(window),
    getHeaders: analystHeaders,
    buildFactsheetContext,
  });
  let restoredConversationId = null;

  function toggle(open) {
    const isOpen = open ?? !panel.classList.contains("open");
    panel.classList.toggle("open", isOpen);
    fab.classList.toggle("hidden", isOpen);
    fabLabel.classList.toggle("hidden", isOpen);
    if (isOpen) {
      restoreTranscript();
      setTimeout(() => input.focus(), 50);
    }
  }

  fab.addEventListener("click", () => toggle(true));
  fabLabel.addEventListener("click", () => toggle(true));
  closeBtn.addEventListener("click", () => toggle(false));
  expandBtn.addEventListener("click", async () => {
    expandBtn.disabled = true;
    try {
      const conversationId = await chatController.ensureConversation();
      window.open(`${API_BASE}/analyst/chat/${encodeURIComponent(conversationId)}`, "_blank");
    } catch (_error) {
      showTransientError();
    } finally {
      expandBtn.disabled = false;
    }
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener("click", send);

  const { escapeHtml, mdToHtml, hasComplexMarkdown } = window.ToescaChatMarkdown;

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

  function typePlainText(el, content) {
    return new Promise((resolve) => {
      const chunk = Math.max(1, Math.floor(content.length / 220));
      let i = 0;
      el.textContent = "";
      el.style.whiteSpace = "pre-wrap";
      function step() {
        if (i >= content.length) {
          el.style.whiteSpace = "";
          resolve();
          return;
        }
        let end = Math.min(content.length, i + chunk);
        while (end < content.length && !/\s/.test(content[end])) {
          end++;
        }
        el.textContent += content.slice(i, end);
        i = end;
        body.scrollTop = body.scrollHeight;
        requestAnimationFrame(() => setTimeout(step, 15));
      }
      step();
    });
  }

  function addTyping() {
    const div = document.createElement("div");
    div.className = "tc-typing";
    div.innerHTML = `<span class="tc-typing-dots"><span></span><span></span><span></span></span>
      <span class="tc-typing-label">Consultando información…</span>`;
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  function renderPersistedTranscript(messages) {
    body.innerHTML = "";
    messages.forEach((message) => {
      if (message.role === "assistant") addMsg("bot", mdToHtml(message.content || ""));
      else if (message.role === "user") addMsg("user", escapeHtml(message.content || ""));
    });
  }

  function showTransientError() {
    const error = document.createElement("div");
    error.className = "tc-error";
    error.textContent = "No se pudo obtener una respuesta. Intenta nuevamente.";
    body.appendChild(error);
    body.scrollTop = body.scrollHeight;
  }

  async function restoreTranscript() {
    const conversationId = chatController.getStoredConversationId();
    if (!conversationId || restoredConversationId === conversationId) return;
    try {
      const transcript = await chatController.loadConversation();
      if (transcript.stale) {
        restoredConversationId = null;
        return;
      }
      restoredConversationId = conversationId;
      renderPersistedTranscript(transcript.messages);
    } catch (_error) {
      // Keep the initial UI available; a send may still report a safe error.
    }
  }

  async function send() {
    if (chatController.isPending()) return;
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    input.style.height = "42px";
    sendBtn.disabled = true;

    addMsg("user", escapeHtml(q));
    const typing = addTyping();

    try {
      const result = await chatController.sendAnalystMessage(q);
      typing.remove();
      if (result.error) {
        renderPersistedTranscript(result.messages || []);
        showTransientError();
        return;
      }
      restoredConversationId = chatController.getStoredConversationId();
      const content = result.message.content || "(sin respuesta)";
      if (hasComplexMarkdown(content)) {
        addMsg("bot", mdToHtml(content));
        return;
      }
      const row = addMsg("bot", "");
      const msgEl = row.querySelector(".tc-msg");
      await typePlainText(msgEl, content);
      msgEl.innerHTML = mdToHtml(content);
      body.scrollTop = body.scrollHeight;
    } catch (err) {
      typing.remove();
      showTransientError();
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

  // A stored pointer is restored from WorkspaceStore without creating a chat.
  restoreTranscript();

  // Boton de reinicio rapido de servidores (ingesta 8765 + agente 5000).
  const restartBtn = document.createElement("button");
  restartBtn.type = "button";
  restartBtn.title = "Reinicia el servidor de ingesta y el del agente (puertos 8765 y 5000)";
  restartBtn.textContent = "↻ Reiniciar servidores";
  restartBtn.style.cssText = "position:fixed;right:22px;bottom:90px;z-index:99997;" +
    "padding:8px 12px;border-radius:8px;border:1px solid #cbd5e1;background:#fff;" +
    "color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;" +
    "font-size:12px;font-weight:600;cursor:pointer;box-shadow:0 6px 16px rgba(15,23,42,.12);";
  restartBtn.addEventListener("click", async () => {
    if (!confirm("¿Reiniciar el servidor de ingesta (8765) y el del agente (5000)?")) return;
    restartBtn.disabled = true;
    restartBtn.textContent = "Reiniciando…";
    const headers = {};
    if (window.INGESTA_TOKEN) headers["X-Ingesta-Token"] = window.INGESTA_TOKEN;
    try {
      await fetch(API_BASE + "/api/restart_servidores", { method: "POST", headers });
    } catch (e) {
      // Se espera que la conexion se corte apenas el proceso muere.
    }
    setTimeout(() => location.reload(), 6000);
  });
  document.body.appendChild(restartBtn);
})();
