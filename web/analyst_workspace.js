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
      if (response.status === 401) location.assign("/login");
      const error = new Error(data.error || "request_failed");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  const listConversations = () => api("/api/analyst/conversations").then((d) => d.conversations);
  const getCurrentUser = () => api("/api/auth/me");
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
  const submitFeedbackReport = (conversationId, anchorMessageId, comment) => api("/api/analyst/feedback_reports", {
    method: "POST", body: JSON.stringify({ conversation_id: conversationId, anchor_message_id: anchorMessageId, comment }),
  });
  const listConversationFeedback = (id) => api(`/api/analyst/conversations/${encodeURIComponent(id)}/feedback`).then((d) => d.feedback || {});
  const setMessageFeedback = (messageId, rating) => api(`/api/analyst/messages/${encodeURIComponent(messageId)}/feedback`, {
    method: "POST", body: JSON.stringify({ rating }),
  });
  const clearMessageFeedback = (messageId) => api(`/api/analyst/messages/${encodeURIComponent(messageId)}/feedback`, {
    method: "DELETE",
  });
  const listProductUpdates = () => api("/api/analyst/product_updates").then((d) => d.product_updates);
  const getUnseenProductUpdateCount = () => api("/api/analyst/product_updates/unseen_count").then((d) => d.count);
  const markProductUpdateSeen = (id) => api(`/api/analyst/product_updates/${encodeURIComponent(id)}/seen`, { method: "POST" });

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
  const composerEl = document.querySelector(".composer");
  const novedadesNavBtn = document.getElementById("novedades-nav-btn");
  const novedadesUnreadDot = document.getElementById("novedades-unread-dot");
  document.getElementById("logout-btn").addEventListener("click", async () => {
    clearActivePointer();
    await fetch("/api/auth/logout", { method: "POST" });
    location.assign("/login");
  });

  // ── Reportar problema ──
  const reportModal = document.getElementById("report-modal");
  const reportComment = document.getElementById("report-comment");
  const reportModalError = document.getElementById("report-modal-error");
  const reportCancelBtn = document.getElementById("report-cancel-btn");
  const reportSubmitBtn = document.getElementById("report-submit-btn");
  const toastEl = document.getElementById("toast");
  let reportTargetMessageId = null;
  let reportPending = false;
  let toastTimer = null;

  function showToast(message) {
    toastEl.textContent = message;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2600);
  }

  function openReportModal(messageId) {
    reportTargetMessageId = messageId;
    reportComment.value = "";
    reportModalError.classList.remove("show");
    reportModal.classList.remove("hidden");
    reportComment.focus();
  }

  function closeReportModal() {
    reportModal.classList.add("hidden");
    reportTargetMessageId = null;
  }

  reportCancelBtn.addEventListener("click", closeReportModal);
  reportModal.addEventListener("click", (e) => {
    if (e.target === reportModal) closeReportModal();
  });

  reportSubmitBtn.addEventListener("click", async () => {
    const comment = reportComment.value.trim();
    if (!comment || !reportTargetMessageId || !activeId || reportPending) return;
    reportPending = true;
    reportSubmitBtn.disabled = true;
    reportModalError.classList.remove("show");
    try {
      await submitFeedbackReport(activeId, reportTargetMessageId, comment);
      closeReportModal();
      showToast("Reporte enviado. Gracias.");
    } catch (_err) {
      reportModalError.classList.add("show");
    } finally {
      reportPending = false;
      reportSubmitBtn.disabled = false;
    }
  });

  let conversations = [];
  let activeId = null;
  let displayName = "";
  let pending = false;
  let openMenuId = null;
  let viewingNovedades = false;
  let unseenProductUpdateCount = 0;
  let unseenProductUpdateStateVersion = 0;

  // ── Novedades ("what's new") ──
  // Pure product-discovery feed: no LLM call, no tool call, no analytical
  // session -- see /api/analyst/product_updates* in scripts/ingesta_server.py.
  function setComposerVisible(visible) {
    composerEl.style.display = visible ? "" : "none";
  }

  function updateUnreadDot(count) {
    unseenProductUpdateCount = count;
    novedadesUnreadDot.classList.toggle("show", count > 0);
    renderHomeDiscoveryCard();
  }

  function handleProductUpdateCta(update) {
    const cta = update.cta_config;
    if (!cta || typeof cta !== "object") return;
    if (cta.type === "route" && typeof cta.value === "string") {
      location.assign(cta.value);
      return;
    }
    if (cta.type === "chat_prompt" && typeof cta.value === "string" && cta.value.trim()) {
      // Routes through the exact same composer/send path a typed prompt uses --
      // no separate handler for update-card prompts.
      viewingNovedades = false;
      novedadesNavBtn.classList.remove("active");
      setComposerVisible(true);
      activeId = null;
      clearActivePointer();
      navigateTo(null);
      renderSidebar();
      renderHome();
      composerInput.value = cta.value.trim();
      send();
    }
  }

  function renderNovedadesList(updates) {
    conversationEl.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "novedades-wrap";
    if (!updates.length) {
      const empty = document.createElement("div");
      empty.className = "novedades-empty";
      empty.textContent = "No hay novedades por ahora.";
      wrap.appendChild(empty);
    } else {
      updates.forEach((u) => {
        const card = document.createElement("div");
        card.className = "novedades-card";
        const title = document.createElement("div");
        title.className = "novedades-card-title";
        title.textContent = u.title;
        const body = document.createElement("div");
        body.className = "novedades-card-body";
        body.textContent = u.body;
        const date = document.createElement("div");
        date.className = "novedades-card-date";
        date.textContent = fmtDate(u.published_at);
        card.append(title, body);
        if (u.cta_label) {
          const cta = document.createElement("button");
          cta.type = "button";
          cta.className = "novedades-cta-btn";
          cta.textContent = u.cta_label;
          cta.addEventListener("click", () => handleProductUpdateCta(u));
          card.appendChild(cta);
        }
        card.appendChild(date);
        wrap.appendChild(card);
      });
    }
    conversationEl.appendChild(wrap);
  }

  async function openNovedades() {
    unseenProductUpdateStateVersion += 1;
    clearError();
    openMenuId = null;
    viewingNovedades = true;
    novedadesNavBtn.classList.add("active");
    setComposerVisible(false);
    navigateTo(null, { replace: true });
    renderSidebar();
    chatTitle.textContent = "Novedades";
    chatSub.textContent = "Nuevas capacidades del Analyst";
    conversationEl.innerHTML = "";
    try {
      const updates = await listProductUpdates();
      renderNovedadesList(updates);
      const unseen = updates.filter((u) => !u.seen).map((u) => u.id);
      if (unseen.length) {
        await Promise.all(unseen.map((id) => markProductUpdateSeen(id).catch(() => {})));
      }
      updateUnreadDot(0);
    } catch (_err) {
      showError("No se pudieron cargar las novedades.");
    }
  }
  novedadesNavBtn.addEventListener("click", openNovedades);

  function renderHomeDiscoveryCard() {
    const existing = document.querySelector(".home-discovery-card");
    if (existing) existing.remove();
    if (viewingNovedades || unseenProductUpdateCount <= 0) return;
    const homeState = document.querySelector(".home-state");
    if (!homeState) return;
    const card = document.createElement("div");
    card.className = "home-discovery-card";
    card.innerHTML = `<span class="dot"></span> Nuevo · ${unseenProductUpdateCount} novedad${unseenProductUpdateCount === 1 ? "" : "es"}`;
    card.addEventListener("click", openNovedades);
    homeState.appendChild(card);
  }

  collapseBtn.addEventListener("click", () => sidebar.classList.toggle("collapsed"));

  function showError(message) {
    errorBanner.textContent = message;
    errorBanner.classList.add("show");
  }
  function clearError() {
    errorBanner.classList.remove("show");
  }

  function clearActivePointer() {
    try {
      sessionStorage.removeItem(CONVERSATION_ID_KEY);
      localStorage.removeItem(CONVERSATION_ID_KEY);
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
      title.textContent = conv.title || "Nueva conversación";
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
              renderHome();
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

  function renderHome({ focusComposer = false } = {}) {
    conversationEl.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "home-state";
    const logoPlate = document.createElement("div");
    logoPlate.className = "home-logo-plate";
    const logo = document.createElement("img");
    logo.className = "home-logo";
    logo.src = "/assets/toesca_logo_white.png";
    logo.alt = "Toesca";
    logoPlate.appendChild(logo);
    const kicker = document.createElement("p");
    kicker.className = "home-kicker";
    kicker.textContent = "Toesca Real Estate AI Analyst";
    const heading = document.createElement("h1");
    heading.textContent = displayName ? `Hola, ${displayName}` : "Hola";
    const copy = document.createElement("p");
    copy.textContent = "¿Qué quieres analizar hoy?";
    wrap.append(logoPlate, kicker, heading, copy);
    conversationEl.appendChild(wrap);
    chatTitle.textContent = "Toesca Real Estate AI Analyst";
    chatSub.textContent = "Nueva conversación";
    renderHomeDiscoveryCard();
    if (focusComposer) composerInput.focus();
  }

  // ── Thumbs feedback (up/down) ──
  // Fast, low-friction quality signal on assistant responses. Deliberately
  // separate from "Reportar problema": no reason picker, no forced comment,
  // no LLM/tool call -- just a rating the server persists per user/message.
  let feedbackPending = new Set();

  function buildFeedbackWidget(messageId, initialRating) {
    const wrap = document.createElement("div");
    wrap.className = "feedback-widget";
    let current = initialRating || null;

    function makeBtn(rating, label, glyph) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "feedback-btn";
      btn.dataset.rating = rating;
      btn.setAttribute("aria-label", label);
      btn.textContent = glyph;
      return btn;
    }

    const upBtn = makeBtn("up", "Marcar respuesta como útil", "👍");
    const downBtn = makeBtn("down", "Marcar respuesta como no útil", "👎");

    function render() {
      upBtn.classList.toggle("selected", current === "up");
      upBtn.setAttribute("aria-pressed", String(current === "up"));
      downBtn.classList.toggle("selected", current === "down");
      downBtn.setAttribute("aria-pressed", String(current === "down"));
    }
    render();

    async function toggle(rating, btn) {
      if (feedbackPending.has(messageId)) return;
      const previous = current;
      const next = current === rating ? null : rating;
      feedbackPending.add(messageId);
      upBtn.disabled = true;
      downBtn.disabled = true;
      current = next;
      render();
      try {
        if (next === null) {
          await clearMessageFeedback(messageId);
        } else {
          await setMessageFeedback(messageId, next);
        }
      } catch (_err) {
        current = previous;
        render();
        showToast("No se pudo guardar tu calificación. Intenta nuevamente.");
      } finally {
        feedbackPending.delete(messageId);
        upBtn.disabled = false;
        downBtn.disabled = false;
      }
    }

    upBtn.addEventListener("click", () => toggle("up", upBtn));
    downBtn.addEventListener("click", () => toggle("down", downBtn));
    wrap.append(upBtn, downBtn);
    return wrap;
  }

  function addTurn(role, html, messageId, feedbackRating) {
    const turn = document.createElement("div");
    turn.className = "turn " + role;
    if (role === "assistant") {
      turn.innerHTML = `<div class="turn-label"><span class="mark-sm">t.</span> Toesca Real Estate AI Analyst</div>
        <div class="prose">${html}</div>`;
      if (messageId) {
        const actions = document.createElement("div");
        actions.className = "turn-actions";
        actions.appendChild(buildFeedbackWidget(messageId, feedbackRating));
        const reportBtn = document.createElement("button");
        reportBtn.type = "button";
        reportBtn.className = "report-btn";
        reportBtn.textContent = "Reportar problema";
        reportBtn.addEventListener("click", () => openReportModal(messageId));
        actions.appendChild(reportBtn);
        turn.appendChild(actions);
      }
    } else {
      turn.innerHTML = `<div class="user-bubble"></div>`;
      turn.querySelector(".user-bubble").innerHTML = html;
    }
    if (messageId) turn.dataset.messageId = messageId;
    conversationEl.appendChild(turn);
    scrollArea.scrollTop = scrollArea.scrollHeight;
    return turn;
  }

  function renderMessages(messages, feedbackByMessageId) {
    conversationEl.innerHTML = "";
    const feedback = feedbackByMessageId || {};
    messages.forEach((m) => {
      if (m.role === "assistant") addTurn("assistant", mdToHtml(m.content || ""), m.id, feedback[m.id]);
      else if (m.role === "user") addTurn("user", escapeHtml(m.content || ""), m.id);
    });
    scrollArea.scrollTop = scrollArea.scrollHeight;
  }

  function addTyping() {
    const div = document.createElement("div");
    div.className = "thinking";
    div.innerHTML = `<span class="thinking-dots"><span></span><span></span><span></span></span>
      Consultando información…`;
    conversationEl.appendChild(div);
    scrollArea.scrollTop = scrollArea.scrollHeight;
    return div;
  }

  // Frontend-only progressive reveal: the backend returns the complete
  // answer in one response (no token streaming today), so this replays
  // already-received plain text in chunks to *feel* like it's being
  // written. It is a visual approximation, not real streaming — see
  // typePlainText in chat_bubble.js, which uses the same technique.
  function typePlainText(el, content) {
    return new Promise((resolve) => {
      const chunk = Math.max(1, Math.floor(content.length / 200));
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
        while (end < content.length && !/\s/.test(content[end])) end++;
        el.textContent += content.slice(i, end);
        i = end;
        scrollArea.scrollTop = scrollArea.scrollHeight;
        requestAnimationFrame(() => setTimeout(step, 14));
      }
      step();
    });
  }

  function leaveNovedadesView() {
    if (!viewingNovedades) return;
    viewingNovedades = false;
    novedadesNavBtn.classList.remove("active");
    setComposerVisible(true);
  }

  async function selectConversation(id, { pushHistory = true } = {}) {
    clearError();
    leaveNovedadesView();
    activeId = id;
    if (pushHistory) navigateTo(id);
    renderSidebar();
    conversationEl.innerHTML = "";
    try {
      const [conv, messages, feedback] = await Promise.all([
        getConversation(id), listMessages(id), listConversationFeedback(id).catch(() => ({})),
      ]);
      chatTitle.textContent = conv.title || "Nueva conversación";
      chatSub.textContent = `Actualizado ${fmtDate(conv.updated_at)}`;
      renderMessages(messages, feedback);
      composerInput.focus();
    } catch (err) {
      if (err.status === 404) {
        conversations = conversations.filter((c) => c.id !== id);
        activeId = null;
        clearActivePointer();
        navigateTo(null, { replace: true });
        renderSidebar();
        renderHome();
        showError("Esa conversación ya no existe.");
      } else {
        showError("No se pudo cargar la conversación. Intenta nuevamente.");
      }
    }
  }

  async function startNewChat() {
    clearError();
    leaveNovedadesView();
    activeId = null;
    clearActivePointer();
    navigateTo(null);
    renderSidebar();
    renderHome({ focusComposer: true });
  }
  newChatBtn.addEventListener("click", startNewChat);

  async function send() {
    if (pending) return;
    const text = composerInput.value.trim();
    if (!text) return;
    composerSend.disabled = true;
    pending = true;
    let typing = null;
    try {
      if (!activeId) {
        const conversation = await createConversation();
        conversations.push(conversation);
        activeId = conversation.id;
        navigateTo(activeId);
        renderSidebar();
        conversationEl.innerHTML = "";
        chatTitle.textContent = conversation.title || "Nueva conversación";
        chatSub.textContent = "Nueva conversación";
      }
      composerInput.value = "";
      composerInput.style.height = "24px";
      addTurn("user", escapeHtml(text));
      typing = addTyping();
      const message = await sendMessage(activeId, text);
      typing.remove();
      const content = message.content || "(sin respuesta)";
      if (hasComplexMarkdown(content)) {
        addTurn("assistant", mdToHtml(content), message.id);
      } else {
        const turn = addTurn("assistant", "", message.id);
        const proseEl = turn.querySelector(".prose");
        await typePlainText(proseEl, content);
        proseEl.innerHTML = mdToHtml(content);
        scrollArea.scrollTop = scrollArea.scrollHeight;
      }
      const conv = conversations.find((c) => c.id === activeId);
      if (conv) { conv.updated_at = message.created_at; renderSidebar(); }
    } catch (_err) {
      if (typing) typing.remove();
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
    composerInput.style.height = "24px";
    composerInput.style.height = Math.min(composerInput.scrollHeight, 160) + "px";
  });

  window.addEventListener("popstate", () => {
    leaveNovedadesView();
    const id = pathConversationId();
    if (id) selectConversation(id, { pushHistory: false });
    else { activeId = null; clearActivePointer(); renderHome(); renderSidebar(); }
  });

  function pathConversationId() {
    const match = location.pathname.match(/^\/analyst\/chat\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  async function init() {
    clearActivePointer();
    renderHome();
    try {
      const [principal, loadedConversations] = await Promise.all([getCurrentUser(), listConversations()]);
      displayName = typeof principal.short_name === "string" ? principal.short_name.trim() : "";
      conversations = loadedConversations;
    } catch (_err) {
      showError("No se pudo conectar con el servidor del Asistente.");
      conversations = [];
    }
    renderHome({ focusComposer: true });
    renderSidebar();
    if (!viewingNovedades) {
      const unseenCountRequestVersion = ++unseenProductUpdateStateVersion;
      getUnseenProductUpdateCount().then((count) => {
        if (
          unseenCountRequestVersion === unseenProductUpdateStateVersion &&
          !viewingNovedades
        ) {
          updateUnreadDot(count);
        }
      }).catch(() => {});
    }

    const urlId = pathConversationId();
    if (urlId) {
      await selectConversation(urlId, { pushHistory: false });
    } else {
      navigateTo(null, { replace: true });
    }
  }

  init();
})();
