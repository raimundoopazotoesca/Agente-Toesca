/* Shared, DOM-free state and HTTP flow for the factsheet quick chat. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ToescaQuickChat = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const CONVERSATION_ID_KEY = "toesca_asistente_conversation_id";

  function buildFactsheetContext(fund, period) {
    return {
      source_surface: "factsheet",
      fund: fund || "",
      period: period || "",
      period_type: "operating",
    };
  }

  function createQuickChatController(options) {
    const fetchImpl = options.fetch;
    const storage = options.storage;
    const apiBase = options.apiBase || "";
    const getHeaders = options.getHeaders || (() => ({}));
    const buildFactsheetContext = options.buildFactsheetContext;
    let pending = false;

    function getStoredConversationId() {
      return storage.getItem(CONVERSATION_ID_KEY);
    }

    function setStoredConversationId(conversationId) {
      storage.setItem(CONVERSATION_ID_KEY, conversationId);
    }

    function clearStoredConversationId() {
      storage.removeItem(CONVERSATION_ID_KEY);
    }

    async function request(path, init) {
      const response = await fetchImpl(`${apiBase}${path}`, init);
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error || "request_failed");
        error.status = response.status;
        throw error;
      }
      return data;
    }

    function jsonRequest(method, body) {
      return {
        method,
        headers: { "Content-Type": "application/json", ...getHeaders() },
        body: JSON.stringify(body),
      };
    }

    async function loadConversation() {
      const conversationId = getStoredConversationId();
      if (!conversationId) return { stale: false, messages: [] };
      try {
        await request(`/api/analyst/conversations/${encodeURIComponent(conversationId)}`, { headers: getHeaders() });
        const transcript = await request(
          `/api/analyst/conversations/${encodeURIComponent(conversationId)}/messages`,
          { headers: getHeaders() },
        );
        return { stale: false, messages: transcript.messages || [] };
      } catch (error) {
        if (error.status === 404) clearStoredConversationId();
        return throwOrReturnStale(error);
      }
    }

    function throwOrReturnStale(error) {
      if (error.status === 404) return { stale: true, messages: [] };
      throw error;
    }

    async function ensureConversation() {
      const existing = getStoredConversationId();
      if (existing) return existing;
      const conversation = await request(
        "/api/analyst/conversations",
        jsonRequest("POST", { context: buildFactsheetContext() }),
      );
      setStoredConversationId(conversation.id);
      return conversation.id;
    }

    async function sendAnalystMessage(text) {
      if (pending) return { pending: true };
      pending = true;
      try {
        const conversationId = await ensureConversation();
        const message = await request(
          `/api/analyst/conversations/${encodeURIComponent(conversationId)}/messages`,
          jsonRequest("POST", { text }),
        );
        return { message };
      } catch (error) {
        let messages = [];
        try {
          const refreshed = await loadConversation();
          messages = refreshed.messages;
        } catch (_refreshError) {
          // The UI shows one safe error state; no request is retried.
        }
        return { error: true, messages };
      } finally {
        pending = false;
      }
    }

    return {
      getStoredConversationId,
      setStoredConversationId,
      clearStoredConversationId,
      loadConversation,
      ensureConversation,
      sendAnalystMessage,
      isPending: () => pending,
    };
  }

  return { CONVERSATION_ID_KEY, buildFactsheetContext, createQuickChatController };
});
