// Script compartido por las páginas de un solo edificio con rent roll
// (Viña Centro, Mall Curicó) — misma UI de Apoquindos/PT (composición,
// vencimiento, vacancia histórica, drill-down por arrendatario) pero sin
// selector de scope, porque acá solo hay un edificio. El endpoint se deriva
// de la URL (/reports/vina -> /api/reports/vina) para que este mismo archivo
// sirva a cualquier página de este tipo sin configuración por página.
(() => {
  const q = new URLSearchParams(location.search), sel = document.querySelector('#period');
  const page = location.pathname.split('/').filter(Boolean).pop();

  const pct = v => v == null ? '—' : `${Number(v).toLocaleString('es-CL',{maximumFractionDigits:1})}%`;
  const m2 = v => v == null ? '—' : `${Number(v).toLocaleString('es-CL',{maximumFractionDigits:0})} m²`;
  const ufM2 = v => v == null ? '—' : `${Number(v).toLocaleString('es-CL',{maximumFractionDigits:2})} UF/m²`;
  const ufAmount = v => v == null ? '—' : `${Number(v).toLocaleString('es-CL',{maximumFractionDigits:0})} UF`;
  const escAttr = s => String(s ?? '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  function buildCategoryDetail(kind, eyebrow, title, totalUf, sharePct, grouped, scopeLabel, arrendatarios) {
    const tenants = ((grouped && grouped.tenants) || []).map(t => ({
      ...t, perfil: (arrendatarios || {})[t.arrendatario] || null,
    }));
    const sorted = [...tenants].sort((a, b) => (b.monto_uf ?? 0) - (a.monto_uf ?? 0));
    const nUnidades = tenants.reduce((sum, t) => sum + (t.n_unidades || 1), 0);
    return {
      kind, eyebrow, title, scope_label: scopeLabel,
      total_uf: totalUf, share_pct: sharePct, n_unidades: nUnidades,
      by_building: (grouped && grouped.by_building) || [],
      units: sorted,
    };
  }

  function coverageMarkup(data) {
    const status = data.coverage.status;
    if (status === 'unavailable') {
      return `<span class="chip chip--unavailable"><span class="chip__dot"></span>Sin datos observados</span>`;
    }
    const periodTxt = `<span class="context-bar__period">Datos observados <strong>${data.context.period}</strong></span>`;
    if (status === 'partial') {
      return `<span class="chip chip--partial"><span class="chip__dot"></span>Cobertura parcial</span>` +
        `<span class="context-bar__period">Solicitado ${data.context.requested_period} · disponible <strong>${data.context.period}</strong></span>`;
    }
    return `<span class="chip chip--ok"><span class="chip__dot"></span>Cobertura completa</span>${periodTxt}`;
  }

  function buildingCard(b) {
    return `<article class="panel building-card building-card--solo">
      <div class="building-card__head">
        <div><span class="building-card__tag">Edificio</span><h2 class="building-card__name">${escAttr(b.label)}</h2></div>
        <div class="building-card__stats">
          <div class="stat"><span class="stat__value is-occupancy">${pct(b.occupancy_pct)}</span><span class="stat__label">Ocupación</span></div>
          <div class="stat"><span class="stat__value">${m2(b.vacant_m2)}</span><span class="stat__label">Vacantes</span></div>
          <div class="stat"><span class="stat__value">${m2(b.gla_m2)}</span><span class="stat__label">GLA</span></div>
        </div>
      </div>
    </article>`;
  }

  function toEntries(obj) {
    return Object.entries(obj || {})
      .map(([label, value]) => ({ label, value: Number(value) || 0 }))
      .filter(e => e.value > 0)
      .sort((a, b) => b.value - a.value);
  }

  function renderHBarChart(selector, entries, opts) {
    const el = document.querySelector(selector);
    if (!entries.length) {
      el.innerHTML = '<div class="notice">Sin datos de rent roll observados para este período.</div>';
      return;
    }
    const max = Math.max(...entries.map(e => e.value));
    const total = entries.reduce((sum, e) => sum + e.value, 0);
    const rows = entries.map(e => {
      const widthPct = max ? Math.max(3, (e.value / max) * 100) : 0;
      const sharePct = total ? (e.value / total) * 100 : 0;
      const tipLines = [ufAmount(e.value), `${pct(sharePct)} del total`].join('|');
      const detail = buildCategoryDetail(opts.kind, opts.eyebrow, e.label, e.value, sharePct, opts.detalle[e.label], opts.scopeLabel, opts.arrendatarios);
      return `<div class="hbar-row">
        <span class="hbar-row__label" title="${escAttr(e.label)}">${escAttr(e.label)}</span>
        <div class="hbar-row__track">
          <div class="hbar-row__fill" tabindex="0" role="button" aria-haspopup="dialog" aria-expanded="false" style="width:${widthPct}%"
            aria-label="${escAttr(`${e.label}: ${ufAmount(e.value)}, ${pct(sharePct)} del total`)}"
            data-tip-title="${escAttr(e.label)}" data-tip-lines="${escAttr(tipLines)}"
            data-detail="${escAttr(JSON.stringify(detail))}"></div>
        </div>
        <span class="hbar-row__value">${ufAmount(e.value)}</span>
      </div>`;
    }).join('');
    el.innerHTML = `<div class="hbar-list">${rows}</div>`;
  }

  function renderVencimientoChart(selector, venc, scopeLabel, arrendatarios) {
    const el = document.querySelector(selector);
    const anios = (venc && venc.anios) || [];
    const values = anios.map(a => (venc.por_anio_uf || {})[a] || 0);
    if (!anios.length || !values.some(v => v > 0)) {
      el.innerHTML = '<div class="notice">Sin contratos con vencimiento observado para este período.</div>';
      return;
    }
    const max = Math.max(...values, 1);
    const total = values.reduce((s, v) => s + v, 0);
    const unidadesPorAnio = venc.unidades_por_anio || {};
    const cols = anios.map((a, i) => {
      const v = values[i];
      const heightPct = v > 0 ? Math.max(2, (v / max) * 100) : 0;
      const sharePct = total ? (v / total) * 100 : 0;
      const detail = buildCategoryDetail('vencimiento', 'Vencimiento', a, v, sharePct, unidadesPorAnio[a], scopeLabel, arrendatarios);
      return `<div class="cols-chart__col">
        <div class="cols-chart__bar" tabindex="0" role="button" aria-haspopup="dialog" aria-expanded="false" style="height:${heightPct}%"
          aria-label="${escAttr(`${a}: ${ufAmount(v)}`)}"
          data-tip-title="${escAttr(a)}" data-tip-lines="${escAttr(ufAmount(v))}"
          data-detail="${escAttr(JSON.stringify(detail))}"></div>
        <span class="cols-chart__label">${escAttr(a)}</span>
      </div>`;
    }).join('');
    const plazo = venc.plazo_medio_anios;
    const foot = plazo != null
      ? `<p class="cols-chart__foot">Plazo medio de contratos vigentes: <strong>${Number(plazo).toLocaleString('es-CL', { maximumFractionDigits: 1 })} años</strong></p>`
      : '';
    el.innerHTML = `<div class="cols-chart">${cols}</div>${foot}`;
  }

  function renderVacanciaChart(selector, series, scopeLabel) {
    const el = document.querySelector(selector);
    const points = (series || []).filter(p => p.occupancy_pct != null);
    if (!points.length) {
      el.innerHTML = '<div class="notice">Sin histórico de vacancia observado.</div>';
      return;
    }
    if (points.length === 1) {
      const p = points[0];
      el.innerHTML = `<div class="notice">Histórico disponible desde <strong>${escAttr(p.periodo)}</strong> ` +
        `(${pct(p.occupancy_pct)} ocupación). Se ampliará a medida que se ingesten más períodos.</div>`;
      return;
    }
    const W = 300, H = 120, padY = 16;
    const n = points.length;
    const xAt = i => (i / (n - 1)) * W;
    const yAt = v => H - padY - (Math.max(0, Math.min(100, v)) / 100) * (H - padY * 2);
    const linePts = points.map((p, i) => `${xAt(i)},${yAt(p.occupancy_pct)}`).join(' ');
    const areaPts = `0,${H - padY / 2} ${linePts} ${W},${H - padY / 2}`;
    // Con series largas (histórico real de varios años, ej. Viña/Curicó con
    // 100+ meses) un punto/etiqueta por mes satura el gráfico — la línea usa
    // todos los puntos (fiel a la tendencia), pero solo se marcan e
    // interactúan ~10 repartidos (siempre primero y último), con menos
    // etiquetas todavía para que no se encimen.
    const pickIndices = (count) => {
      if (n <= count) return points.map((_, i) => i);
      const idx = new Set([0, n - 1]);
      for (let k = 1; k < count - 1; k++) idx.add(Math.round((k * (n - 1)) / (count - 1)));
      return [...idx].sort((a, b) => a - b);
    };
    const markerIdx = pickIndices(10);
    const labelIdx = pickIndices(Math.min(6, markerIdx.length));
    const dots = markerIdx.map(i => {
      const p = points[i];
      const x = xAt(i), y = yAt(p.occupancy_pct);
      const tipLines = [`${pct(p.occupancy_pct)} ocupación`, `${m2(p.vacant_m2)} vacantes`].join('|');
      const detail = {
        kind: 'vacancia_periodo', eyebrow: 'Período', title: p.periodo, scope_label: scopeLabel,
        occupancy_pct: p.occupancy_pct, gla_m2: p.gla_m2, vacant_m2: p.vacant_m2,
      };
      return `<circle class="line-chart__dot" cx="${x}" cy="${y}" r="3.5" tabindex="0" role="button" aria-haspopup="dialog" aria-expanded="false" ` +
        `aria-label="${escAttr(`${p.periodo}: ${pct(p.occupancy_pct)} ocupación`)}" ` +
        `data-tip-title="${escAttr(p.periodo)}" data-tip-lines="${escAttr(tipLines)}" ` +
        `data-detail="${escAttr(JSON.stringify(detail))}"></circle>`;
    }).join('');
    const labels = labelIdx.map(i => {
      const p = points[i];
      const anchor = i === 0 ? 'start' : (i === n - 1 ? 'end' : 'middle');
      return `<text class="line-chart__axis-label" x="${xAt(i)}" y="${H - 2}" text-anchor="${anchor}">${escAttr(p.periodo)}</text>`;
    }).join('');
    el.innerHTML = `<svg class="line-chart" viewBox="0 0 ${W} ${H}">
      <line class="line-chart__grid" x1="0" y1="${yAt(100)}" x2="${W}" y2="${yAt(100)}"></line>
      <line class="line-chart__grid" x1="0" y1="${yAt(0)}" x2="${W}" y2="${yAt(0)}"></line>
      <polygon class="line-chart__area" points="${areaPts}"></polygon>
      <polyline class="line-chart__line" points="${linePts}"></polyline>
      ${dots}
      ${labels}
    </svg>`;
  }

  function renderInsights(insights, period) {
    const periodEl = document.querySelector('#insights-period');
    if (periodEl) periodEl.textContent = period || '—';
    const data = insights || {};
    const scopeLabel = data.label || '';
    const arrendatarios = data.arrendatarios || {};
    renderHBarChart('#chart-rubro', toEntries(data.rubro_arrendatario), {
      kind: 'rubro', eyebrow: 'Rubro de arrendatario', detalle: data.rubro_arrendatario_detalle || {}, scopeLabel, arrendatarios,
    });
    renderHBarChart('#chart-tipo', toEntries(data.tipo_activo), {
      kind: 'tipo_activo', eyebrow: 'Tipo de activo', detalle: data.tipo_activo_detalle || {}, scopeLabel, arrendatarios,
    });
    renderVencimientoChart('#chart-vencimiento', data.vencimiento || {}, scopeLabel, arrendatarios);
    renderVacanciaChart('#chart-vacancia', data.vacancia_historica || [], scopeLabel);
  }

  function show(data) {
    sel.innerHTML = data.context.period ? `<option>${data.context.period}</option>` : '';
    sel.value = data.context.period || '';
    document.querySelector('#coverage').innerHTML = coverageMarkup(data);

    const container = document.querySelector('#building-cards');
    const insightsSection = document.querySelector('#asset-insights');
    if (!data.building) {
      container.innerHTML = `<div class="empty-state"><strong>No hay datos observados</strong>No existe un período con datos ingestados para este activo.</div>`;
      if (insightsSection) insightsSection.hidden = true;
      return;
    }
    container.innerHTML = buildingCard(data.building);
    if (insightsSection) {
      insightsSection.hidden = false;
      renderInsights(data.insights, data.context.period);
    }
  }

  function initInteractions() {
    const tip = document.createElement('div');
    tip.className = 'tooltip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    document.body.appendChild(tip);

    const panel = document.createElement('div');
    panel.className = 'detail-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'false');
    panel.hidden = true;
    document.body.appendChild(panel);

    let tipTarget = null, panelTarget = null;

    function place(el, target) {
      const r = target.getBoundingClientRect();
      const left = Math.min(window.innerWidth - el.offsetWidth - 8, Math.max(8, r.left + r.width / 2 - el.offsetWidth / 2));
      const top = r.top - el.offsetHeight - 8;
      el.style.left = `${left}px`;
      el.style.top = `${top < 8 ? r.bottom + 8 : top}px`;
    }

    function showTip(target) {
      if (panelTarget || target === tipTarget) return;
      const title = target.getAttribute('data-tip-title');
      if (!title) return;
      const lines = (target.getAttribute('data-tip-lines') || '').split('|').filter(Boolean);
      tip.innerHTML = '';
      const h = document.createElement('div');
      h.className = 'tooltip__title';
      h.textContent = title;
      tip.appendChild(h);
      lines.forEach((line, i) => {
        const row = document.createElement('div');
        row.className = i > 0 ? 'tooltip__row tooltip__row--muted' : 'tooltip__row';
        row.textContent = line;
        tip.appendChild(row);
      });
      tip.hidden = false;
      tipTarget = target;
      place(tip, target);
    }

    function hideTip() { tip.hidden = true; tipTarget = null; }

    function el(tag, cls, text) {
      const node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }

    function factRow(label, value) {
      const row = el('div', 'detail-facts__row');
      row.append(el('dt', null, label), el('dd', null, value));
      return row;
    }

    const shortEdificio = label => String(label || '');

    function arrendatarioLink(nombre, perfil) {
      if (!perfil) return document.createTextNode(nombre);
      const link = el('span', 'arrendatario-link', nombre);
      link.tabIndex = 0;
      link.setAttribute('role', 'button');
      link.setAttribute('aria-haspopup', 'dialog');
      link.title = `Ver detalle de ${nombre}`;
      link.dataset.arrendatario = JSON.stringify(perfil);
      return link;
    }

    function formatUnidades(unidades) {
      const byEd = new Map();
      (unidades || []).forEach(u => {
        const ed = shortEdificio(u.edificio);
        if (!byEd.has(ed)) byEd.set(ed, []);
        byEd.get(ed).push(u.unidad);
      });
      const multiEd = byEd.size > 1;
      return [...byEd.entries()].map(([ed, codes]) => {
        const shown = codes.slice(0, 3).join(', ');
        const extra = codes.length > 3 ? ` +${codes.length - 3}` : '';
        return multiEd ? `${ed}: ${shown}${extra}` : `${shown}${extra}`;
      }).join(' · ');
    }

    function sizeText(t) {
      const parts = [];
      if (t.m2 > 0) parts.push(m2(t.m2));
      if (t.n_estacionamientos > 0) parts.push(`${t.n_estacionamientos} estac.`);
      return parts.join(' + ') || '—';
    }

    function tenantRow(t) {
      const row = el('div', 'unit-row is-occ');
      const top = el('div', 'unit-row__top');
      const code = el('span', 'unit-row__code');
      code.appendChild(arrendatarioLink(t.arrendatario, t.perfil));
      top.append(code, el('span', 'status-dot is-occ'));
      top.appendChild(el('span', 'unit-row__m2', sizeText(t)));
      row.appendChild(top);
      const unidadesTxt = formatUnidades(t.unidades) + (t.n_unidades > 1 ? ` (${t.n_unidades} unidades)` : '');
      const sub = [unidadesTxt, t.renta_uf ? ufM2(t.renta_uf) : null].filter(Boolean).join(' · ');
      const subEl = el('div', 'unit-row__sub', sub);
      subEl.title = sub;
      row.appendChild(subEl);
      return row;
    }

    function renderCategoryPanel(body, d) {
      const summary = el('div', 'detail-panel__summary');
      const m1 = el('div', 'detail-metric');
      m1.append(el('span', 'detail-metric__value', ufAmount(d.total_uf)), el('span', 'detail-metric__label', 'Renta mensual'));
      const m2wrap = el('div', 'detail-metric');
      m2wrap.append(el('span', 'detail-metric__value', d.share_pct != null ? pct(d.share_pct) : '—'), el('span', 'detail-metric__label', 'del total'));
      const m3wrap = el('div', 'detail-metric');
      m3wrap.append(el('span', 'detail-metric__value', String(d.n_unidades)), el('span', 'detail-metric__label', d.n_unidades === 1 ? 'unidad' : 'unidades'));
      summary.append(m1, m2wrap, m3wrap);
      body.appendChild(summary);

      if (d.units.length) {
        const shown = d.units.slice(0, 40);
        const list = el('div', 'detail-units');
        shown.forEach(t => list.appendChild(tenantRow(t)));
        body.appendChild(list);
        if (d.units.length > shown.length) {
          body.appendChild(el('p', 'detail-panel__note', `Mostrando ${shown.length} de ${d.units.length} arrendatarios, ordenados por renta.`));
        }
      } else {
        body.appendChild(el('p', 'detail-panel__note', 'Sin arrendatarios observados para esta categoría.'));
      }
    }

    function renderVacanciaPeriodoPanel(body, d) {
      const summary = el('div', 'detail-panel__summary');
      const m1 = el('div', 'detail-metric');
      m1.append(el('span', 'detail-metric__value is-occupancy', pct(d.occupancy_pct)), el('span', 'detail-metric__label', 'Ocupación'));
      const m2wrap = el('div', 'detail-metric');
      m2wrap.append(el('span', 'detail-metric__value', m2(d.vacant_m2)), el('span', 'detail-metric__label', 'Vacantes'));
      summary.append(m1, m2wrap);
      body.appendChild(summary);
      const facts = el('dl', 'detail-facts');
      facts.appendChild(factRow('GLA', m2(d.gla_m2)));
      body.appendChild(facts);
    }

    const fecha = s => s ? s.slice(0, 10).split('-').reverse().join('-') : '—';

    function groupUnidadesPorTipo(unidades) {
      const grupos = new Map();
      (unidades || []).forEach(u => {
        const tipo = u.tipo_activo || 'Otro';
        if (!grupos.has(tipo)) grupos.set(tipo, []);
        grupos.get(tipo).push(u);
      });
      return [...grupos.entries()].map(([tipo_activo, us]) => {
        const esParking = tipo_activo === 'Estacionamientos';
        const m2Total = us.reduce((s, u) => s + (esParking ? 0 : (u.m2 || 0)), 0);
        const m2Ponderador = us.reduce((s, u) => s + (u.m2 || 0), 0);
        const peso = us.reduce((s, u) => s + (u.renta_uf || 0) * (u.m2 || 0), 0);
        const inicios = us.map(u => u.fecha_inicio).filter(Boolean).sort();
        const vencs = us.map(u => u.vencimiento).filter(Boolean).sort();
        const edificios = [...new Set(us.map(u => shortEdificio(u.edificio)))];
        return {
          tipo_activo, n: us.length, es_parking: esParking, m2: round1(m2Total), edificios,
          renta_uf: m2Ponderador ? peso / m2Ponderador : null,
          inicio: inicios[0] || null, inicio_max: inicios[inicios.length - 1] || null,
          venc: vencs[0] || null, venc_max: vencs[vencs.length - 1] || null,
        };
      }).sort((a, b) => b.n - a.n);
    }

    const round1 = v => Math.round(v * 10) / 10;

    function renderArrendatarioPanel(body, d) {
      const unidades = d.unidades || [];
      const summary = el('div', 'detail-panel__summary');
      const m1 = el('div', 'detail-metric');
      m1.append(el('span', 'detail-metric__value', ufAmount(d.monto_uf)), el('span', 'detail-metric__label', 'Renta mensual'));
      const m2wrap = el('div', 'detail-metric');
      m2wrap.append(el('span', 'detail-metric__value', String(d.n_unidades)), el('span', 'detail-metric__label', d.n_unidades === 1 ? 'unidad' : 'unidades'));
      summary.append(m1, m2wrap);
      body.appendChild(summary);

      const facts = el('dl', 'detail-facts detail-facts--compact');
      if (d.m2 > 0) facts.appendChild(factRow('Superficie', m2(d.m2)));
      if (d.n_estacionamientos > 0) facts.appendChild(factRow('Estacionamientos', String(d.n_estacionamientos)));
      if (d.renta_uf != null) facts.appendChild(factRow('Renta promedio', ufM2(d.renta_uf)));
      const inicios = unidades.map(u => u.fecha_inicio).filter(Boolean).sort();
      const vencimientos = unidades.map(u => u.vencimiento).filter(Boolean).sort();
      if (inicios.length) facts.appendChild(factRow('Relación desde', fecha(inicios[0])));
      if (vencimientos.length) facts.appendChild(factRow('Próximo vencimiento', fecha(vencimientos[0])));
      body.appendChild(facts);

      const listHead = el('p', 'detail-panel__subhead', 'Unidades por tipo');
      body.appendChild(listHead);
      const list = el('div', 'detail-units');
      groupUnidadesPorTipo(unidades).forEach(g => {
        const row = el('div', 'unit-row is-occ');
        const top = el('div', 'unit-row__top');
        const codeText = g.tipo_activo + (g.n > 1 ? ` ×${g.n}` : '');
        const code = el('span', 'unit-row__code', codeText);
        code.title = codeText;
        top.append(code, el('span', 'status-dot is-occ'));
        top.appendChild(el('span', 'unit-row__m2', g.es_parking ? `${g.n} estac.` : m2(g.m2)));
        row.appendChild(top);
        const subParts = [g.renta_uf != null ? ufM2(g.renta_uf) : null].filter(Boolean);
        const subEl = el('div', 'unit-row__sub', subParts.join(' · '));
        row.appendChild(subEl);
        const rangeTxt = g.inicio === g.inicio_max && g.venc === g.venc_max
          ? `${fecha(g.inicio)} → ${fecha(g.venc)}`
          : `desde ${fecha(g.inicio)} · próx. vence ${fecha(g.venc)}`;
        const rangeEl = el('div', 'unit-row__sub unit-row__sub--muted', rangeTxt);
        rangeEl.title = rangeTxt;
        row.appendChild(rangeEl);
        list.appendChild(row);
      });
      body.appendChild(list);
    }

    let currentDetail = null;
    let panelHistory = [];

    function renderDetail(detail) {
      currentDetail = detail;
      panel.classList.toggle('detail-panel--wide', detail.kind === 'arrendatario');
      panel.innerHTML = '';
      const head = el('div', 'detail-panel__head');
      const headLeft = el('div', 'detail-panel__head-left');
      if (panelHistory.length) {
        const back = el('button', 'detail-panel__back', '←');
        back.type = 'button';
        back.setAttribute('aria-label', 'Volver');
        back.addEventListener('click', () => renderDetail(panelHistory.pop()));
        headLeft.appendChild(back);
      }
      const heading = el('div');
      heading.append(el('span', 'detail-panel__eyebrow', detail.eyebrow), el('h3', 'detail-panel__title', detail.title));
      headLeft.appendChild(heading);
      const close = el('button', 'detail-panel__close', '×');
      close.type = 'button';
      close.setAttribute('aria-label', 'Cerrar');
      close.addEventListener('click', () => { const t = panelTarget; closePanel(); if (t) t.focus(); });
      head.append(headLeft, close);
      panel.appendChild(head);

      const body = el('div', 'detail-panel__body');
      if (detail.kind === 'vacancia_periodo') renderVacanciaPeriodoPanel(body, detail);
      else if (detail.kind === 'arrendatario') renderArrendatarioPanel(body, detail);
      else renderCategoryPanel(body, detail);
      panel.appendChild(body);
      close.focus();
    }

    function openPanel(target) {
      hideTip();
      let detail;
      try { detail = JSON.parse(target.getAttribute('data-detail') || 'null'); } catch { detail = null; }
      if (!detail) return;
      panelHistory = [];
      renderDetail(detail);
      panel.hidden = false;
      target.setAttribute('aria-expanded', 'true');
      panelTarget = target;
      place(panel, target);
    }

    function openArrendatarioProfile(linkEl) {
      let perfil;
      try { perfil = JSON.parse(linkEl.dataset.arrendatario || 'null'); } catch { perfil = null; }
      if (!perfil) return;
      const detail = {
        kind: 'arrendatario', eyebrow: 'Arrendatario', title: perfil.arrendatario,
        ...perfil,
      };
      if (currentDetail) panelHistory.push(currentDetail);
      renderDetail(detail);
    }

    function closePanel() {
      if (panelTarget) panelTarget.setAttribute('aria-expanded', 'false');
      panel.hidden = true;
      panelTarget = null;
      currentDetail = null;
      panelHistory = [];
    }

    function activate(target) { panelTarget === target ? closePanel() : openPanel(target); }

    document.addEventListener('mouseover', e => { const t = e.target.closest('[data-tip-title]'); if (t) showTip(t); });
    document.addEventListener('mouseout', e => { const t = e.target.closest('[data-tip-title]'); if (t && !t.contains(e.relatedTarget)) hideTip(); });
    document.addEventListener('focusin', e => {
      if (panel.contains(e.target)) return;
      const t = e.target.closest('[data-tip-title]');
      if (t) showTip(t); else hideTip();
    });
    document.addEventListener('focusout', e => { const t = e.target.closest('[data-tip-title]'); if (t) hideTip(); });
    document.addEventListener('click', e => {
      const link = e.target.closest('[data-arrendatario]');
      if (link) { openArrendatarioProfile(link); return; }
      if (panel.contains(e.target)) return;
      const t = e.target.closest('[data-tip-title]');
      if (t && t.hasAttribute('data-detail')) activate(t);
      else if (!t) closePanel();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        const t = panelTarget;
        closePanel();
        hideTip();
        if (t) t.focus();
        return;
      }
      if (e.key === 'Enter' || e.key === ' ') {
        const link = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-arrendatario]');
        if (link && link === document.activeElement) { e.preventDefault(); openArrendatarioProfile(link); return; }
        const t = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-tip-title]');
        if (t && t === document.activeElement && t.hasAttribute('data-detail')) { e.preventDefault(); activate(t); }
      }
    });
    window.addEventListener('scroll', () => { if (tipTarget) place(tip, tipTarget); if (panelTarget) place(panel, panelTarget); }, true);
    window.addEventListener('resize', () => { if (tipTarget) place(tip, tipTarget); if (panelTarget) place(panel, panelTarget); });
  }

  async function load() {
    const r = await fetch(`/api/reports/${page}${q.get('period') ? `?period=${q.get('period')}` : ''}`);
    show(await r.json());
  }

  sel.addEventListener('change', () => { q.set('period', sel.value); history.replaceState(null, '', `?${q}`); load(); });
  initInteractions();
  load();
})();
