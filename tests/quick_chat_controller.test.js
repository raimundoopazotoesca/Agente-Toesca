const assert = require("node:assert/strict");
const { createQuickChatController, buildFactsheetContext } = require("../web/quick_chat_controller.js");

const unicodeQuestions = [
  "¿Cuál es la vacancia de TRI en junio de 2026?",
  "¿Cómo evolucionó la ocupación en Viña Centro?",
];

function response(status, body) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

async function run() {
  assert.deepEqual(buildFactsheetContext("TRI", "2026-06"), {
    source_surface: "factsheet",
    fund: "TRI",
    period: "2026-06",
    period_type: "operating",
  }, "factsheet context contains only live navigation metadata");

  const calls = [];
  const store = storage();
  const controller = createQuickChatController({
    apiBase: "http://localhost:8765",
    storage: store,
    getHeaders: () => ({ "X-Ingesta-Token": "test-token" }),
    buildFactsheetContext: () => ({ source_surface: "factsheet", fund: "TRI", period: "2026-06", period_type: "operating" }),
    fetch: async (url, init = {}) => {
      calls.push({ url, init });
      if (url.endsWith("/conversations")) return response(201, { id: "conv-1" });
      return response(201, { id: "msg-2", conversation_id: "conv-1", role: "assistant", content: unicodeQuestions[0] });
    },
  });

  assert.equal(controller.getStoredConversationId(), null, "page load does not create a conversation");
  const sent = await controller.sendAnalystMessage(unicodeQuestions[0]);
  assert.equal(sent.message.content, unicodeQuestions[0], "unicode round-trips exactly");
  assert.equal(store.getItem("toesca_asistente_conversation_id"), "conv-1", "storage holds only the server conversation id");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    context: { source_surface: "factsheet", fund: "TRI", period: "2026-06", period_type: "operating" },
  });
  assert.deepEqual(JSON.parse(calls[1].init.body), { text: unicodeQuestions[0] }, "message request never includes history");
  assert.equal(calls[1].init.headers["X-Ingesta-Token"], "test-token");

  const staleStore = storage({ toesca_asistente_conversation_id: "stale" });
  const stale = createQuickChatController({
    storage: staleStore,
    getHeaders: () => ({}),
    buildFactsheetContext: () => { throw new Error("stale lookup must not create"); },
    fetch: async () => response(404, { error: "not_found" }),
  });
  assert.deepEqual(await stale.loadConversation(), { stale: true, messages: [] });
  assert.equal(staleStore.getItem("toesca_asistente_conversation_id"), null, "404 clears stale pointer without creating a chat");

  const loadedStore = storage({ toesca_asistente_conversation_id: "conv-2" });
  const loaded = createQuickChatController({
    storage: loadedStore,
    getHeaders: () => ({}),
    buildFactsheetContext: () => ({}),
    fetch: async (url) => url.endsWith("/messages")
      ? response(200, { messages: [
          { id: "1", role: "user", content: unicodeQuestions[1] },
          { id: "2", role: "assistant", content: "Respuesta persistida" },
        ] })
      : response(200, { id: "conv-2" }),
  });
  assert.deepEqual((await loaded.loadConversation()).messages.map((item) => item.content), [unicodeQuestions[1], "Respuesta persistida"], "reload restores chronological server transcript");

  let resolveSend;
  const pendingStore = storage({ toesca_asistente_conversation_id: "conv-3" });
  const pending = createQuickChatController({
    storage: pendingStore,
    getHeaders: () => ({}),
    buildFactsheetContext: () => ({}),
    fetch: (url) => url.endsWith("/messages")
      ? new Promise((resolve) => { resolveSend = resolve; })
      : Promise.resolve(response(200, { id: "conv-3" })),
  });
  const first = pending.sendAnalystMessage("Primero");
  assert.deepEqual(await pending.sendAnalystMessage("Duplicado"), { pending: true }, "pending state blocks double submit");
  resolveSend(response(201, { id: "3", role: "assistant", content: "OK" }));
  await first;

  const failureCalls = [];
  const failed = createQuickChatController({
    storage: storage({ toesca_asistente_conversation_id: "conv-4" }),
    getHeaders: () => ({}),
    buildFactsheetContext: () => ({}),
    fetch: async (url, init = {}) => {
      failureCalls.push({ url, init });
      if (init.method === "POST") return response(503, { error: "service_unavailable" });
      if (url.endsWith("/messages")) return response(200, { messages: [{ id: "user", role: "user", content: "Persistido una vez" }] });
      return response(200, { id: "conv-4" });
    },
  });
  const failure = await failed.sendAnalystMessage("Persistido una vez");
  assert.equal(failure.error, true);
  assert.deepEqual(failure.messages.map((item) => item.content), ["Persistido una vez"], "failure refreshes transcript instead of retrying");
  assert.equal(failureCalls.filter((call) => call.init.method === "POST").length, 1, "failure never retries the message");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
