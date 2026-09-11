// Script compartido por páginas de un solo activo sin composición por
// arrendatario (Sucden: un solo contrato fijo; INMOSA: sin rent roll
// ingestado) — solo métricas de edificio + lo que sí existe, sin gráficos.
(() => {
  const q = new URLSearchParams(location.search), sel = document.querySelector('#period');
  const page = location.pathname.split('/').filter(Boolean).pop();

  const pct = v => v == null ? '—' : `${Number(v).toLocaleString('es-CL',{maximumFractionDigits:1})}%`;
  const m2 = v => v == null ? '—' : `${Number(v).toLocaleString('es-CL',{maximumFractionDigits:0})} m²`;
  const ufM2 = v => v == null ? '—' : `${Number(v).toLocaleString('es-CL',{maximumFractionDigits:2})} UF/m²`;
  const escAttr = s => String(s ?? '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // Fecha 'YYYY-MM-DD' -> 'DD-MM-YYYY', sin pasar por Date() (evita corrimiento de zona horaria).
  const fecha = s => s ? s.slice(0, 10).split('-').reverse().join('-') : '—';

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

  function factRow(label, value) {
    return `<div class="detail-facts__row"><dt>${escAttr(label)}</dt><dd>${escAttr(value)}</dd></div>`;
  }

  function contratoCard(c) {
    if (!c) {
      return `<div class="notice">Sin contrato ocupado observado para este período.</div>`;
    }
    const rows = [
      factRow('Arrendatario', c.arrendatario || '—'),
      factRow('Superficie', m2(c.m2)),
      factRow('Renta', ufM2(c.renta_uf)),
      factRow('Inicio de contrato', fecha(c.fecha_inicio)),
      factRow('Vencimiento', fecha(c.vencimiento)),
    ].join('');
    return `<article class="panel info-card">
      <h2 class="info-card__title">Contrato</h2>
      <dl class="detail-facts">${rows}</dl>
    </article>`;
  }

  function show(data) {
    sel.innerHTML = data.context.period ? `<option>${data.context.period}</option>` : '';
    sel.value = data.context.period || '';
    document.querySelector('#coverage').innerHTML = coverageMarkup(data);

    const container = document.querySelector('#building-cards');
    if (!data.building) {
      container.innerHTML = `<div class="empty-state"><strong>No hay datos observados</strong>No existe un período con datos ingestados para este activo.</div>`;
      return;
    }
    let html = buildingCard(data.building);
    if (Object.prototype.hasOwnProperty.call(data, 'contrato')) {
      html += contratoCard(data.contrato);
    }
    if (data.detalle_disponible === false) {
      html += `<div class="notice">El detalle por arrendatario no está disponible: este activo no tiene rent roll ingestado en el sistema.</div>`;
    }
    container.innerHTML = html;
  }

  async function load() {
    const r = await fetch(`/api/reports/${page}${q.get('period') ? `?period=${q.get('period')}` : ''}`);
    show(await r.json());
  }

  sel.addEventListener('change', () => { q.set('period', sel.value); history.replaceState(null, '', `?${q}`); load(); });
  load();
})();
