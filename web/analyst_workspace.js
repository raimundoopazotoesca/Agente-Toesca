/* Fullscreen multi-chat Analyst workspace. Shares the same /api/analyst/*
   backend and the same conversation_id storage key as the quick chat bubble
   (see chat_bubble.js) — this is a second view over the same conversations,
   not a separate chat system. */
(function () {
  const API_BASE = window.__TC_API_BASE__ || "";
  const { CONVERSATION_ID_KEY } = window.ToescaQuickChat;
  const { mdToHtml, hasComplexMarkdown, escapeHtml } = window.ToescaChatMarkdown;

  function headers(extra) {
    const h = { ...(extra || {}) };
    if (window.INGESTA_TOKEN) h["X-Ingesta-Token"] = window.INGESTA_TOKEN;
    return h;
  }

  async function api(path, init) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: headers({ "Content-Type": "application/json", ...(init && init.headers) }),
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || "request_failed");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  const listConversations = () => api("/api/analyst/conversations").then((d) => d.conversations);
  const createConversation = () => api("/api/analyst/conversations", { method: "POST", body: JSON.stringify({}) });
  const getConversation = (id) => api(`/api/analyst/conversations/${encodeURIComponent(id)}`);
  const listMessages = (id) => api(`/api/analyst/conversations/${encodeURIComponent(id)}/messages`).then((d) => d.messages);
  const sendMessage = (id, text) => api(`/api/analyst/conversations/${encodeURIComponent(id)}/messages`, {
    method: "POST", body: JSON.stringify({ text }),
  });
  const renameConversation = (id, title) => api(`/api/analyst/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH", body: JSON.stringify({ title }),
  });
  const archiveConversation = (id) => api(`/api/analyst/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH", body: JSON.stringify({ archived: true }),
  });

  // ── DOM ──
  const sidebar = document.getElementById("sidebar");
  const collapseBtn = document.getElementById("collapse-btn");
  const newChatBtn = document.getElementById("new-chat-btn");
  const convList = document.getElementById("conv-list");
  const chatTitle = document.getElementById("chat-title");
  const chatSub = document.getElementById("chat-sub");
  const conversationEl = document.getElementById("conversation");
  const composerInput = document.getElementById("composer-input");
  const composerSend = document.getElementById("composer-send");
  const errorBanner = document.getElementById("error-banner");
  const scrollArea = document.getElementById("scroll-area");

  let conversations = [];
  let activeId = null;
  let pending = false;
  let openMenuId = null;

  collapseBtn.addEventListener("click", () => sidebar.classList.toggle("collapsed"));

  function showError(message) {
    errorBanner.textContent = message;
    errorBanner.classList.add("show");
  }
  function clearError() {
    errorBanner.classList.remove("show");
  }

  function setActivePointer(id) {
    if (!id) return;
    try {
      sessionStorage.setItem(CONVERSATION_ID_KEY, id);
      localStorage.setItem(CONVERSATION_ID_KEY, id);
    } catch (_e) { /* storage may be unavailable in some contexts */ }
  }

  function navigateTo(id, { replace = false } = {}) {
    const path = id ? `/analyst/chat/${encodeURIComponent(id)}` : "/analyst";
    if (location.pathname !== path) {
      history[replace ? "replaceState" : "pushState"]({ conversationId: id }, "", path);
    }
  }

  function fmtDate(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      return d.toLocaleString("es-CL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch (_e) {
      return "";
    }
  }

  function renderSidebar() {
    convList.innerHTML = "";
    if (!conversations.length) {
      const empty = document.createElement("div");
      empty.className = "conv-empty";
      empty.textContent = "Sin conversaciones todavía. Crea un chat nuevo para empezar.";
      convList.appendChild(empty);
      return;
    }
    const sorted = [...conversations].sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
    sorted.forEach((conv) => {
      const item = document.createElement("div");
      item.className = "conv-item" + (conv.id === activeId ? " active" : "");
      item.dataset.id = conv.id;

      const title = document.createElement("div");
      title.className = "conv-title";
      title.textContent = conv.title || "Nuevo chat";
      const meta = document.createElement("div");
      meta.className = "conv-meta";
      meta.textContent = fmtDate(conv.updated_at);

      const menuBtn = document.createElement("button");
      menuBtn.className = "conv-menu-btn";
      menuBtn.type = "button";
      menuBtn.textContent = "⋯";
      menuBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openMenuId = openMenuId === conv.id ? null : conv.id;
        renderSidebar();
      });

      item.appendChild(title);
      item.appendChild(meta);
      item.appendChild(menuBtn);

      if (openMenuId === conv.id) {
        const menu = document.createElement("div");
        menu.className = "conv-menu";
        const renameBtn = document.createElement("button");
        renameBtn.textContent = "Renombrar";
        renameBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          openMenuId = null;
          startRename(item, conv);
        });
        const archiveBtn = document.createElement("button");
        archiveBtn.textContent = "Archivar";
        archiveBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          openMenuId = null;
          try {
            await archiveConversation(conv.id);
            conversations = conversations.filter((c) => c.id !== conv.id);
            if (activeId === conv.id) {
              activeId = null;
              navigateTo(null, { replace: true });
              renderEmptyConversation();
            }
            renderSidebar();
          } catch (_err) {
            showError("No se pudo archivar la conversación.");
          }
        });
        menu.appendChild(renameBtn);
        menu.appendChild(archiveBtn);
        item.appendChild(menu);
      }

      item.addEventListener("click", () => {
        if (conv.id === activeId) return;
        openMenuId = null;
        selectConversation(conv.id);
      });
      convList.appendChild(item);
    });
  }

  function startRename(item, conv) {
    const titleEl = item.querySelector(".conv-title");
    const input = document.createElement("input");
    input.className = "conv-rename-input";
    input.value = conv.title || "";
    titleEl.replaceWith(input);
    input.focus();
    input.select();
    async function commit() {
      const value = input.value.trim();
      if (value && value !== conv.title) {
        try {
          const updated = await renameConversation(conv.id, value);
          conv.title = updated.title;
          if (conv.id === activeId) chatTitle.textContent = updated.title;
        } catch (_err) {
          showError("No se pudo renombrar la conversación.");
        }
      }
      renderSidebar();
    }
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") input.blur();
      if (e.key === "Escape") { input.value = conv.title || ""; input.blur(); }
    });
  }

  document.addEventListener("click", () => {
    if (openMenuId !== null) { openMenuId = null; renderSidebar(); }
  });

  function renderEmptyConversation() {
    conversationEl.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "empty-state";
    wrap.innerHTML = `
      <div class="mark">t.</div>
      <h2>Toesca Analyst</h2>
      <p>Crea un chat nuevo o selecciona uno del historial para continuar trabajando.</p>`;
    conversationEl.appendChild(wrap);
    chatTitle.textContent = "Toesca Analyst";
    chatSub.textContent = "Selecciona o crea un chat";
  }

  function addRow(role, html) {
    const row = document.createElement("div");
    row.className = "row " + role;
    if (role === "assistant") {
      row.innerHTML = `<span class="mark-sm">t.</span><div class="bubble assistant">${html}</div>`;
    } else {
      row.innerHTML = `<div class="bubble user"></div>`;
      row.querySelector(".bubble").innerHTML = html;
    }
    conversationEl.appendChild(row);
    scrollArea.scrollTop = scrollArea.scrollHeight;
    return row;
  }

  function renderMessages(messages) {
    conversationEl.innerHTML = "";
    messages.forEach((m) => {
      if (m.role === "assistant") addRow("assistant", mdToHtml(m.content || ""));
      else if (m.role === "user") addRow("user", escapeHtml(m.content || ""));
    });
    scrollArea.scrollTop = scrollArea.scrollHeight;
  }

  function addTyping() {
    const div = document.createElement("div");
    div.className = "typing";
    div.textContent = "Consultando información…";
    conversationEl.appendChild(div);
    scrollArea.scrollTop = scrollArea.scrollHeight;
    return div;
  }

  async function selectConversation(id, { pushHistory = true } = {}) {
    clearError();
    activeId = id;
    setActivePointer(id);
    if (pushHistory) navigateTo(id);
    renderSidebar();
    conversationEl.innerHTML = "";
    try {
      const [conv, messages] = await Promise.all([getConversation(id), listMessages(id)]);
      chatTitle.textContent = conv.title || "Nuevo chat";
      chatSub.textContent = `Actualizado ${fmtDate(conv.updated_at)}`;
      renderMessages(messages);
      composerInput.focus();
    } catch (err) {
      if (err.status === 404) {
        conversations = conversations.filter((c) => c.id !== id);
        activeId = null;
        navigateTo(null, { replace: true });
        renderSidebar();
        renderEmptyConversation();
        showError("Esa conversación ya no existe.");
      } else {
        showError("No se pudo cargar la conversación. Intenta nuevamente.");
      }
    }
  }

  async function startNewChat() {
    clearError();
    try {
      const conv = await createConversation();
      conversations.push(conv);
      renderSidebar();
      await selectConversation(conv.id);
    } catch (_err) {
      showError("No se pudo crear un chat nuevo.");
    }
  }
  newChatBtn.addEventListener("click", startNewChat);

  async function send() {
    if (pending || !activeId) return;
    const text = composerInput.value.trim();
    if (!text) return;
    composerInput.value = "";
    composerInput.style.height = "46px";
    composerSend.disabled = true;
    pending = true;

    addRow("user", escapeHtml(text));
    const typing = addTyping();
    try {
      const message = await sendMessage(activeId, text);
      typing.remove();
      addRow("assistant", mdToHtml(message.content || "(sin respuesta)"));
      const conv = conversations.find((c) => c.id === activeId);
      if (conv) { conv.updated_at = message.created_at; renderSidebar(); }
    } catch (_err) {
      typing.remove();
      const errRow = document.createElement("div");
      errRow.className = "turn-error";
      errRow.textContent = "No se pudo obtener una respuesta. Intenta nuevamente.";
      conversationEl.appendChild(errRow);
      scrollArea.scrollTop = scrollArea.scrollHeight;
    } finally {
      pending = false;
      composerSend.disabled = false;
      composerInput.focus();
    }
  }
  composerSend.addEventListener("click", send);
  composerInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  composerInput.addEventListener("input", () => {
    composerInput.style.height = "46px";
    composerInput.style.height = Math.min(composerInput.scrollHeight, 160) + "px";
  });

  window.addEventListener("popstate", () => {
    const id = pathConversationId();
    if (id) selectConversation(id, { pushHistory: false });
    else { activeId = null; renderEmptyConversation(); renderSidebar(); }
  });

  function pathConversationId() {
    const match = location.pathname.match(/^\/analyst\/chat\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  function storedPointer() {
    try {
      return sessionStorage.getItem(CONVERSATION_ID_KEY) || localStorage.getItem(CONVERSATION_ID_KEY);
    } catch (_e) {
      return null;
    }
  }

  async function init() {
    renderEmptyConversation();
    try {
      conversations = await listConversations();
    } catch (_err) {
      showError("No se pudo conectar con el servidor del Asistente.");
      conversations = [];
    }
    renderSidebar();

    const urlId = pathConversationId();
    const targetId = urlId || storedPointer();
    if (targetId && conversations.some((c) => c.id === targetId)) {
      await selectConversation(targetId, { pushHistory: !urlId });
    } else if (targetId) {
      // Not in the (unarchived) list yet, or came from a URL/pointer to a
      // conversation this list call didn't include — try loading it directly.
      try {
        await selectConversation(targetId, { pushHistory: !urlId });
      } catch (_e) {
        navigateTo(null, { replace: true });
      }
    } else {
      navigateTo(null, { replace: true });
    }
  }

  init();
})();
