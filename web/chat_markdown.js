/* Shared, DOM-free message rendering: Markdown -> HTML + ```chart``` -> inline SVG.
   Used by both the quick chat bubble and the fullscreen analyst workspace so a
   message renders identically in either surface. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ToescaChatMarkdown = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const CHART_COLORS = ["#0f172a", "#2563eb", "#16a34a", "#dc2626"];

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    }[c]));
  }

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

  function hasComplexMarkdown(content) {
    return /```|^#{1,6}\s|^\s*\|.*\|\s*\n\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$/m.test(content);
  }

  return { escapeHtml, mdToHtml, hasComplexMarkdown, buildChartSvg, renderChartBlock };
});
