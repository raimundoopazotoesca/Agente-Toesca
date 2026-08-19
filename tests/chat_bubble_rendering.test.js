const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.style = {};
    this.listeners = {};
    this.scrollHeight = 0;
    this.scrollTop = 0;
    this.value = "";
    this.disabled = false;
    this.insertions = 0;
    this.textWrites = 0;
    this._textContent = "";
    this._innerHTML = "";
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    if (this.className === "tc-row bot") {
      const message = new Element("div");
      message.className = "tc-msg bot";
      const match = this._innerHTML.match(/<div class="tc-msg bot">([\s\S]*)<\/div>$/);
      message.innerHTML = match ? match[1] : "";
      this.children = [message];
    }
  }

  get innerHTML() { return this._innerHTML; }
  set textContent(value) { this.textWrites += 1; this._textContent = String(value); }
  get textContent() { return this._textContent; }
  appendChild(child) { this.children.push(child); return child; }
  remove() { this.removed = true; }
  focus() {}
  addEventListener(type, callback) { this.listeners[type] = callback; }
  querySelector(selector) {
    if (selector === ".tc-msg") return this.children.find((child) => child.className === "tc-msg bot") || null;
    return null;
  }
  insertAdjacentHTML(_position, html) { this.insertions += 1; this._innerHTML += html; }
}

function createDocument() {
  const body = new Element("body");
  const head = new Element("head");
  const elements = new Map();
  const panel = new Element("div");
  const chatBody = new Element("div");
  const input = new Element("textarea");
  const send = new Element("button");
  const close = new Element("button");
  elements.set("#tc-body", chatBody);
  elements.set("#tc-q", input);
  elements.set("#tc-send", send);
  elements.set(".tc-close", close);
  panel.querySelector = (selector) => elements.get(selector) || null;
  let divCount = 0;
  const originalCreate = (tag) => {
    if (tag !== "div") return new Element(tag);
    divCount += 1;
    return divCount === 1 ? panel : new Element(tag);
  };
  return {
    body,
    head,
    createElement: originalCreate,
    getElementById: () => null,
    panel,
    chatBody,
    input,
    send,
  };
}

function makeResponse(status, payload) {
  return { ok: status >= 200 && status < 300, status, json: async () => payload };
}

async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function run() {
  const source = fs.readFileSync("web/chat_bubble.js", "utf8");
  const document = createDocument();
  const stored = new Map();
  const complex = [
    "### Datos verificados",
    "",
    "**Mall Curicó** concentra la mayor cantidad de m² vacantes.",
    "",
    "| Mes | Vacancia |",
    "| --- | --- |",
    "| Mayo 2026 | 5,790% |",
    "| Junio 2026 | 5,945% |",
    "",
    "| Activo | m² vacantes | Vacancia | Participación |",
    "| --- | ---: | ---: | ---: |",
    "| Mall Curicó | 2.476,0 | 22,75% | 57,5% |",
    "| Apoquindo 3001 | 1.632,6 | 36,33% | 37,9% |",
    "",
    "### Lectura / inferencia",
    "",
    "El desempeño muestra una **recuperación** desde febrero.",
    "",
    "```chart",
    '{"type":"line","title":"Vacancia","labels":["Mayo","Junio"],"series":[{"name":"TRI","values":[5.79,5.945]}]}',
    "```",
  ].join("\n");
  const context = {
    document,
    location: { protocol: "http:" },
    sessionStorage: {
      getItem: (key) => stored.get(key) || null,
      setItem: (key, value) => stored.set(key, String(value)),
      removeItem: (key) => stored.delete(key),
    },
    fetch: async (url, init = {}) => {
      if (url.endsWith("/conversations")) return makeResponse(201, { id: "conv-1" });
      if (init.method === "POST") return makeResponse(201, { id: "msg-1", role: "assistant", content: complex });
      return makeResponse(200, { id: "conv-1" });
    },
    ToescaQuickChat: {
      createQuickChatController: () => ({
        isPending: () => false,
        getStoredConversationId: () => null,
        sendAnalystMessage: async () => ({ message: { content: complex } }),
        loadConversation: async () => ({ stale: false, messages: [] }),
      }),
      buildFactsheetContext: () => ({}),
    },
    window: null,
    requestAnimationFrame: (callback) => callback(),
    setTimeout: (callback) => { callback(); return 0; },
    currentFund: "TRI",
  };
  context.window = context;
  vm.runInNewContext(source, context, { filename: "web/chat_bubble.js" });

  document.input.value = "Compara mayo y junio";
  await document.send.listeners.click();
  await flush();

  const row = document.chatBody.children.at(-1);
  const message = row.querySelector(".tc-msg");
  assert.equal(message.insertions, 0, "complex Markdown bypasses partial HTML typewriter insertion");
  assert.match(message.innerHTML, /<h3>Datos verificados<\/h3>/, "heading is rendered from complete content");
  assert.match(message.innerHTML, /<b>Mall Curicó<\/b>/, "bold text is rendered from complete content");
  assert.match(message.innerHTML, /<table><thead><tr><th>Mes<\/th><th>Vacancia<\/th>/, "table is rendered with separate columns");
  assert.match(message.innerHTML, /<th>Participación<\/th>/, "asset table keeps its separate columns");
  assert.match(message.innerHTML, /<h3>Lectura \/ inferencia<\/h3>/, "second heading is rendered intact");
  assert.match(message.innerHTML, /<b>recuperación<\/b>/, "later bold text is rendered intact");
  assert.match(message.innerHTML, /<svg /, "chart blocks still render as inline SVG");
  assert.match(message.innerHTML, /Junio 2026/, "Unicode and complete words are preserved");

  const simple = "Dato verificado: la vacancia de TRI en junio de 2026 fue de **5,945%**.\n\n¿cómo evolucionó la ocupación en Viña Centro?\n<img src=x onerror=alert(1)>";
  const restoredDocument = createDocument();
  const restoredContext = {
    document: restoredDocument,
    location: { protocol: "http:" },
    sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    fetch: async () => makeResponse(200, {}),
    ToescaQuickChat: {
      createQuickChatController: () => ({
        isPending: () => false,
        getStoredConversationId: () => "conv-2",
        sendAnalystMessage: async () => ({ message: { content: simple } }),
        loadConversation: async () => ({ stale: false, messages: [{ role: "assistant", content: simple }] }),
      }),
      buildFactsheetContext: () => ({}),
    },
    window: null,
    requestAnimationFrame: (callback) => callback(),
    setTimeout: (callback) => { callback(); return 0; },
    currentFund: "TRI",
  };
  restoredContext.window = restoredContext;
  vm.runInNewContext(source, restoredContext, { filename: "web/chat_bubble.js" });
  await flush();
  const directHtml = restoredDocument.chatBody.children.at(-1).querySelector(".tc-msg").innerHTML;

  restoredDocument.input.value = "Vacancia TRI";
  await restoredDocument.send.listeners.click();
  await flush();
  const animated = restoredDocument.chatBody.children.at(-1).querySelector(".tc-msg");
  assert.ok(animated.textWrites > 1, "simple Markdown keeps a progressive plain-text animation");
  assert.equal(animated.insertions, 0, "typewriter never inserts partial HTML");
  assert.equal(animated.innerHTML, directHtml, "animated response final DOM equals direct render of complete content");
  assert.match(animated.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/, "final renderer preserves HTML escaping");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
