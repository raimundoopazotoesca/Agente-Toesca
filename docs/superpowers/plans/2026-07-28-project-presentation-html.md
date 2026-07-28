# Presentación ejecutiva interactiva del proyecto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar y publicar una presentación HTML interactiva de 13 pantallas que muestre los avances del Automation Agent Toesca, acompañe la demostración en vivo y explique el roadmap al directorio y comité ejecutivo.

**Architecture:** Reutilizar la aplicación Sites de una ruta que ya existe en `project-presentation/`. Separar el contenido verificable de la lógica de navegación, mantener el deck como componente cliente sin dependencias de runtime y cubrir el contrato ejecutivo mediante tests de render y helpers puros.

**Tech Stack:** React 19, Next.js 16 sobre vinext/Vite, TypeScript, CSS nativo, Node test runner y OpenAI Sites.

## Global Constraints

- La presentación contiene exactamente 13 pantallas.
- La secuencia narrativa es avance → evidencia → demostración → roadmap → decisiones.
- La pantalla de productos prepara la demo en este orden: factsheet → centro de ingesta → asistente.
- La presentación no abre ni controla las aplicaciones demostradas.
- El contenido representa el estado verificado al 2026-07-28.
- Las cifras se obtienen de `memory/agente_toesca_v2.db`, `ROADMAP.md`, `CODEX.md`, `wiki/log.md` o código productivo verificable.
- No hay APIs, persistencia, autenticación ni conexión a la DB en tiempo de ejecución.
- El deck usa azul petróleo, marfil, verde menta y ámbar; no usa emojis ni imágenes decorativas.
- El contenido debe funcionar con teclado, touch, impresión y `prefers-reduced-motion`.
- Machalí queda excluido del portfolio vigente.
- Preservar `.openai/hosting.json` y su `project_id`; no crear otro sitio.
- Ejecutar los comandos de Tasks 1–5 desde `project-presentation/`, que es un repositorio Git independiente y actualmente limpio.

---

## File Map

- `project-presentation/app/presentation-data.ts` — contenido estático, métricas verificadas y tipos compartidos.
- `project-presentation/app/presentation-navigation.mjs` — helpers puros de navegación usados por React y por tests Node.
- `project-presentation/app/page.tsx` — composición de las 13 pantallas, tabs y controles del deck.
- `project-presentation/app/globals.css` — sistema visual, responsive, accesibilidad, animación e impresión.
- `project-presentation/app/layout.tsx` — metadatos del sitio y social preview.
- `project-presentation/public/og.png` — tarjeta social específica del proyecto, solo si la imagen generada supera validación visual.
- `project-presentation/tests/render-site.mjs` — helper que ejecuta el Worker compilado y devuelve el HTML real.
- `project-presentation/tests/content-contract.test.mjs` — contrato observable de contenido y fuentes en el HTML renderizado.
- `project-presentation/tests/navigation.test.mjs` — comportamiento puro de navegación.
- `project-presentation/tests/rendered-html.test.mjs` — render SSR, semántica y ausencia del starter.

---

### Task 1: Congelar el contrato de contenido verificable

**Files:**
- Create: `project-presentation/tests/render-site.mjs`
- Create: `project-presentation/tests/content-contract.test.mjs`
- Create: `project-presentation/app/presentation-data.ts`
- Modify: `project-presentation/app/page.tsx`
- Modify: `project-presentation/tests/rendered-html.test.mjs`

**Interfaces:**
- Consumes: cifras verificadas contra SQLite y estados de `ROADMAP.md`.
- Produces: `SLIDES`, `ARCHITECTURE`, `SURFACES`, `PHASES` y `VERIFIED_METRICS` importables por `page.tsx`; `renderHtml()` para tests de comportamiento.

- [ ] **Step 1: Escribir el test fallido del contrato**

Crear primero `tests/render-site.mjs` extrayendo el render real que hoy vive en
`rendered-html.test.mjs`:

```js
import assert from "node:assert/strict";

export async function renderHtml() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  const response = await worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
  assert.equal(response.status, 200);
  return response.text();
}
```

Luego escribir `content-contract.test.mjs` contra el HTML ejecutado:

```js
import assert from "node:assert/strict";
import test from "node:test";
import { renderHtml } from "./render-site.mjs";

test("renders the verified executive snapshot in thirteen slides", async () => {
  const html = await renderHtml();
  assert.equal((html.match(/<section\b/g) ?? []).length, 13);
  assert.match(html, /dateTime="2026-07-28"/i);
  assert.match(html, /schema v73/i);
  assert.match(html, /36\.793/);
  assert.match(html, /12\.782/);
  assert.match(html, /37 tablas/i);
  assert.match(html, /23 vistas/i);
  assert.match(html, />0<[\s\S]*violaciones FK/i);
  assert.match(html, /Machalí está fuera del portfolio vigente/i);
});
```

- [ ] **Step 2: Ejecutar el test y confirmar que falla**

Run: `npm run build && node --test tests/content-contract.test.mjs`
Expected: FAIL porque el HTML aún no expone `dateTime="2026-07-28"`.

- [ ] **Step 3: Crear el módulo de contenido**

```ts
export const VERIFIED_METRICS = {
  asOf: "2026-07-28",
  schemaVersion: 73,
  eeffLines: 36_793,
  derivedKpis: 12_782,
  tables: 37,
  views: 23,
  foreignKeyViolations: 0,
} as const;

export const SLIDES = [
  { label: "Portada", short: "Inicio" },
  { label: "Tesis ejecutiva", short: "Tesis" },
  { label: "Evolución", short: "Historia" },
  { label: "Portfolio", short: "Fondos" },
  { label: "Arquitectura", short: "Sistema" },
  { label: "Base de datos", short: "Datos" },
  { label: "Productos", short: "Demo" },
  { label: "Confianza", short: "Control" },
  { label: "Fase 0", short: "F0" },
  { label: "Roadmap F1", short: "F1" },
  { label: "Horizonte", short: "F2–F4" },
  { label: "Decisiones", short: "Decidir" },
  { label: "Cierre", short: "Norte" },
] as const;
```

Mover sin alterar su significado los arrays `ARCHITECTURE` y `PHASES` actuales.
Definir `SURFACES` exactamente en este orden:

```ts
export const SURFACES = [
  {
    id: "factsheet",
    eyebrow: "01 · Publicación",
    title: "Factsheet HTML",
    copy: "Salida canónica generada desde SQLite, con KPIs por fondo y sin edición manual de cifras.",
    metric: "SQL → KPI → HTML",
  },
  {
    id: "ingesta",
    eyebrow: "02 · Operación",
    title: "Centro de ingesta",
    copy: "Carga guiada con validación, preview y confirmación humana antes de persistir.",
    metric: "validar → revisar → confirmar",
  },
  {
    id: "assistant",
    eyebrow: "03 · Consulta",
    title: "Asistente inmobiliario",
    copy: "Consulta en lenguaje natural con SQL de solo lectura y límites explícitos.",
    metric: "SELECT only",
  },
] as const;
```

- [ ] **Step 4: Importar el módulo desde `page.tsx`**

```tsx
import {
  ARCHITECTURE,
  PHASES,
  SLIDES,
  SURFACES,
  VERIFIED_METRICS,
} from "./presentation-data";
```

Eliminar las definiciones duplicadas del componente y sustituir las cifras
literales de portada por `VERIFIED_METRICS`. Renderizar la fecha con:

```tsx
<time dateTime={VERIFIED_METRICS.asOf}>Actualizado 28.07.2026</time>
```

Actualizar `rendered-html.test.mjs` para importar `renderHtml()` y eliminar su
helper duplicado.

- [ ] **Step 5: Ejecutar el test del contrato**

Run: `npm run build && node --test tests/content-contract.test.mjs`
Expected: PASS.

- [ ] **Step 6: Confirmar que el render previo no retrocede**

Run: `node --test tests/rendered-html.test.mjs`
Expected: PASS en los 2 tests existentes.

- [ ] **Step 7: Commit**

```bash
git add app/presentation-data.ts app/page.tsx tests/render-site.mjs tests/content-contract.test.mjs tests/rendered-html.test.mjs
git commit -m "refactor(presentation): centralize verified executive content"
```

---

### Task 2: Convertir productos en el puente explícito hacia la demo

**Files:**
- Modify: `project-presentation/tests/rendered-html.test.mjs`
- Modify: `project-presentation/app/page.tsx`
- Modify: `project-presentation/app/globals.css`

**Interfaces:**
- Consumes: `SURFACES` con los tres productos en orden.
- Produces: pantalla 7 con tabs y cue de demo comprensible aun sin interacción.

- [ ] **Step 1: Agregar assertions fallidas al render**

```js
assert.match(html, /Tres productos\. Una sola fuente de información\./);
assert.match(html, /Momento de demostración en vivo/);
assert.match(html, /Factsheet HTML[\s\S]*Centro de ingesta[\s\S]*Asistente inmobiliario/);
assert.match(html, /factsheet → ingesta → asistente/i);
assert.doesNotMatch(html, /Una plataforma, cuatro puntos de contacto/);
```

- [ ] **Step 2: Ejecutar el test y confirmar que falla**

Run: `npm run build && node --test tests/rendered-html.test.mjs`  
Expected: FAIL porque el borrador aún muestra cuatro superficies.

- [ ] **Step 3: Actualizar la pantalla de productos**

Reemplazar el encabezado de la pantalla 7 por:

```tsx
<SectionHeader
  number="06"
  eyebrow="Productos funcionando"
  title="Tres productos. Una sola fuente de información."
  copy="Este es el momento de demostración en vivo: factsheet → ingesta → asistente."
/>
```

Agregar debajo de los tabs:

```tsx
<div className="demo-cue" aria-label="Momento de demostración en vivo">
  <span>Momento de demostración en vivo</span>
  <strong>Factsheet → ingesta → asistente</strong>
  <small>Las aplicaciones se muestran desde pestañas preparadas previamente.</small>
</div>
```

Cambiar la fecha del topbar a `Actualizado 28.07.2026`. Mantener las aplicaciones
fuera de enlaces o iframes.

- [ ] **Step 4: Estilizar el cue sin competir con la demo**

```css
.demo-cue {
  margin-top: 14px;
  padding: 12px 16px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 16px;
  border-left: 2px solid var(--mint);
  background: rgba(120, 242, 188, 0.045);
}

.demo-cue span,
.demo-cue small {
  color: var(--paper-muted);
  font-size: 9px;
}

.demo-cue strong {
  color: var(--paper);
  font-size: 11px;
  letter-spacing: 0.04em;
}
```

En el breakpoint móvil, usar `grid-template-columns: 1fr`.

- [ ] **Step 5: Ejecutar render y contrato**

Run: `npm run build && node --test tests/rendered-html.test.mjs tests/content-contract.test.mjs`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/page.tsx app/globals.css tests/rendered-html.test.mjs
git commit -m "feat(presentation): stage the live product demo"
```

---

### Task 3: Aislar y probar la navegación del deck

**Files:**
- Create: `project-presentation/app/presentation-navigation.mjs`
- Create: `project-presentation/tests/navigation.test.mjs`
- Modify: `project-presentation/app/page.tsx`

**Interfaces:**
- Produces: `clampSlide(next, total)` y `slideForKey(key, current, total)`.
- Consumes: `SLIDES.length` desde el componente.

- [ ] **Step 1: Escribir tests fallidos para límites y teclas**

```js
import assert from "node:assert/strict";
import test from "node:test";
import {
  clampSlide,
  slideForKey,
} from "../app/presentation-navigation.mjs";

test("clampSlide never leaves the deck", () => {
  assert.equal(clampSlide(-1, 13), 0);
  assert.equal(clampSlide(13, 13), 12);
  assert.equal(clampSlide(6, 13), 6);
});

test("slideForKey maps presentation keys", () => {
  assert.equal(slideForKey("ArrowRight", 4, 13), 5);
  assert.equal(slideForKey(" ", 4, 13), 5);
  assert.equal(slideForKey("PageUp", 4, 13), 3);
  assert.equal(slideForKey("Home", 4, 13), 0);
  assert.equal(slideForKey("End", 4, 13), 12);
  assert.equal(slideForKey("Enter", 4, 13), null);
});
```

- [ ] **Step 2: Ejecutar y confirmar que falla**

Run: `node --test tests/navigation.test.mjs`  
Expected: FAIL con `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 3: Implementar los helpers mínimos**

```js
export function clampSlide(next, total) {
  return Math.max(0, Math.min(total - 1, next));
}

export function slideForKey(key, current, total) {
  if (["ArrowRight", "ArrowDown", "PageDown", " "].includes(key)) {
    return clampSlide(current + 1, total);
  }
  if (["ArrowLeft", "ArrowUp", "PageUp"].includes(key)) {
    return clampSlide(current - 1, total);
  }
  if (key === "Home") return 0;
  if (key === "End") return total - 1;
  return null;
}
```

- [ ] **Step 4: Reutilizar los helpers en React**

```tsx
import { clampSlide, slideForKey } from "./presentation-navigation.mjs";

const goTo = (next: number) => setSlide(clampSlide(next, SLIDES.length));

useEffect(() => {
  const onKeyDown = (event: KeyboardEvent) => {
    const next = slideForKey(event.key, slide, SLIDES.length);
    if (next === null) return;
    event.preventDefault();
    goTo(next);
  };
  window.addEventListener("keydown", onKeyDown);
  return () => window.removeEventListener("keydown", onKeyDown);
}, [slide]);
```

Mantener los controles deshabilitados en los extremos, el índice lateral, el
swipe y las etiquetas `aria-label`.

- [ ] **Step 5: Ejecutar navegación y render**

Run: `node --test tests/navigation.test.mjs && npm run build && node --test tests/rendered-html.test.mjs`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/presentation-navigation.mjs app/page.tsx tests/navigation.test.mjs
git commit -m "test(presentation): harden deck navigation"
```

---

### Task 4: Completar accesibilidad, responsive y metadatos

**Files:**
- Modify: `project-presentation/tests/rendered-html.test.mjs`
- Modify: `project-presentation/app/page.tsx`
- Modify: `project-presentation/app/globals.css`
- Modify: `project-presentation/app/layout.tsx`
- Create conditionally: `project-presentation/public/og.png`

**Interfaces:**
- Consumes: deck completo y dirección visual aprobada.
- Produces: HTML accesible, impresión apaisada y metadatos coherentes con el sitio.

- [ ] **Step 1: Agregar assertions de accesibilidad y metadatos**

```js
assert.match(html, /aria-live="polite"/);
assert.match(html, /aria-current="step"/);
assert.match(html, /role="tablist"/);
assert.match(html, /role="tabpanel"/);
assert.match(html, /Guardar como PDF/);
assert.match(html, /2026-07-28/);
```

En el test de fuentes:

```js
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
assert.match(css, /@media print/);
assert.match(css, /@media \(max-width: 760px\)/);
assert.match(css, /outline: 2px solid var\(--mint\)/);
```

- [ ] **Step 2: Ejecutar el test y confirmar el fallo relevante**

Run: `npm run build && node --test tests/rendered-html.test.mjs`  
Expected: FAIL hasta que el texto del botón y la fecha semántica estén presentes.

- [ ] **Step 3: Ajustar el HTML y CSS**

Cambiar el botón de portada a:

```tsx
<button className="text-button" onClick={() => window.print()}>
  Guardar como PDF
</button>
```

Agregar `<time dateTime="2026-07-28">Actualizado 28.07.2026</time>` en el topbar.
Asegurar `min-width: 44px; min-height: 44px` para controles y tabs en touch.
Mantener `@media print` con una pantalla por página apaisada y todos los slides
visibles.

- [ ] **Step 4: Generar una única tarjeta social específica**

Usar `imagegen` una vez con este prompt:

```text
Create a polished 1200x630 landscape social card for “TOESCA · Financial
Intelligence Platform”. Dark petroleum background, warm ivory typography,
mint-green progress accents, subtle financial-data grid, executive editorial
style. Main headline: “De automatizar planillas a una plataforma de inteligencia
financiera.” Supporting line: “Proyecto y roadmap · 2026”. Include no charts
with invented numbers, no stock photography, no logos beyond the word TOESCA,
no extra text.
```

Inspeccionar texto, proporción y legibilidad. Si el resultado es correcto,
guardar como `public/og.png`; si contiene texto incorrecto, omitir `og:image`
según la regla de Sites en vez de publicar una tarjeta falsa.

- [ ] **Step 5: Configurar metadatos absolutos según el host**

```tsx
import type { Metadata } from "next";
import { headers } from "next/headers";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") ??
    requestHeaders.get("host") ??
    "localhost";
  const protocol =
    requestHeaders.get("x-forwarded-proto") ??
    (host.startsWith("localhost") ? "http" : "https");
  const base = new URL(`${protocol}://${host}`);
  const title = "Toesca · Financial Intelligence Platform";
  const description =
    "Presentación ejecutiva interactiva del proyecto Automation Agent Toesca y su roadmap.";

  return {
    metadataBase: base,
    title,
    description,
    icons: { icon: "/favicon.png", shortcut: "/favicon.png" },
    openGraph: {
      title,
      description,
      type: "website",
      images: [new URL("/og.png", base).toString()],
    },
  };
}
```

Si `og.png` fue omitido por validación, omitir también la propiedad `images`.

- [ ] **Step 6: Ejecutar tests y lint**

Run: `npm run test && npm run lint`  
Expected: build exitoso, todos los tests PASS y lint sin errores.

- [ ] **Step 7: Commit**

```bash
git add app/page.tsx app/globals.css app/layout.tsx tests/rendered-html.test.mjs public/og.png
git commit -m "feat(presentation): complete executive delivery polish"
```

Si `public/og.png` fue omitido, excluirlo del `git add`.

---

### Task 5: Verificación final y publicación privada

**Files:**
- Verify: `project-presentation/dist/server/index.js`
- Verify: `project-presentation/dist/.openai/hosting.json`
- Preserve: `project-presentation/.openai/hosting.json`

**Interfaces:**
- Consumes: fuente exacta validada y `project_id` existente.
- Produces: versión privada desplegada y URL final.

- [ ] **Step 1: Ejecutar la suite completa del sitio**

Run: `npm run test && npm run lint`  
Expected: build exitoso, 0 tests fallidos y 0 errores de lint.

- [ ] **Step 2: Verificar artefactos de Sites**

Run:

```powershell
Test-Path -LiteralPath 'dist/server/index.js'
Test-Path -LiteralPath 'dist/.openai/hosting.json'
Get-Content -LiteralPath '.openai/hosting.json' -Raw
```

Expected: ambos `Test-Path` devuelven `True` y el JSON conserva
`project_id="appgprj_6a67d67178a08191add182191d92a857"`.

- [ ] **Step 3: Confirmar el commit exacto a publicar**

Run: `git status --short` desde `project-presentation/`.  
Expected: no hay cambios sin registrar.

- [ ] **Step 4: Empaquetar y guardar una versión**

Usar el helper `scripts/package-site.sh` del plugin Sites con
`project-presentation/` como raíz. Guardar una versión usando el SHA del commit
que contiene exactamente la fuente validada. No volver a llamar `create_site`;
reutilizar el `project_id` existente.

- [ ] **Step 5: Desplegar con acceso privado**

Llamar `deploy_private_site_version`, consultar `get_deployment_status` hasta
`status: "succeeded"` y abrir la URL final mediante `open_in_codex`.

- [ ] **Step 6: Entregar**

Comunicar la URL desplegada como entregable principal e indicar que la
presentación se navega con teclado, índice, controles y touch, y que la pantalla
de productos marca el punto de salida hacia la demo en vivo.
