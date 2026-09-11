(() => {
  const state = new URLSearchParams(location.search);
  const controls = {fund: document.querySelector('#fund'), period: document.querySelector('#period'), parkingScope: document.querySelector('#parking-scope')};
  let report = null;
  let visibleWindow = '12M';

  const format = (value, kind) => value == null ? '—' : kind === 'pct' ? `${Number(value).toLocaleString('es-CL', {maximumFractionDigits: 2})}%` : `${Number(value).toLocaleString('es-CL', {maximumFractionDigits: 0})} m²`;
  const metric = (id) => report.summary.metrics.find(item => item.metric_id === id);

  async function load() {
    const params = new URLSearchParams({fund: state.get('fund') || 'Apo', window: visibleWindow, parking_scope: state.get('parking_scope') || 'exclude'});
    if (state.get('period')) params.set('period', state.get('period'));
    if (state.get('asset')) params.set('asset', state.get('asset'));
    try {
      const response = await fetch(`/api/reports/vacancy?${params}`);
      if (!response.ok) throw new Error('No fue posible cargar el informe.');
      report = await response.json();
      syncContext(); renderRadar(); renderSummary(); renderHistory(); renderSpatial();
    } catch (error) {
      document.querySelector('#report-summary').innerHTML = `<div class="error">${error.message}</div>`;
      document.querySelector('#report-history').innerHTML = '';
    }
  }

  function syncContext() {
    const {context, coverage, freshness} = report;
    controls.fund.innerHTML = context.available_filters.fund.map(fund => `<option value="${fund}">${fund}</option>`).join('');
    controls.period.innerHTML = context.available_filters.period.map(period => `<option value="${period}">${period}</option>`).join('');
    controls.fund.value = context.fund; controls.period.value = context.period || '';
    controls.parkingScope.value = context.parking_scope;
    const coverageEl = document.querySelector('#report-coverage');
    coverageEl.classList.toggle('partial', coverage.status === 'partial');
    coverageEl.textContent = coverage.status === 'partial' ? `Solicitado ${context.requested_period}; datos observados hasta ${freshness.data_through}.` : `Datos observados hasta ${freshness.data_through}.`;
  }

  function renderSummary() {
    const primary = metric(report.history.metric_ids[0]); const vacant = metric('m2_vacantes'); const gla = metric('gla_m2');
    document.querySelector('#report-summary').innerHTML = `<h2>Resumen</h2><p class="sub">Al ${report.context.period || 'sin período observado'} · ${report.context.parking_scope === 'exclude' ? 'sin estacionamientos' : 'con estacionamientos'}</p><div class="kpis"><div class="kpi primary"><label>Vacancia física</label><strong>${format(primary?.value, 'pct')}</strong><small>${primary?.status === 'available' ? 'Medición observada' : 'Cobertura parcial'}</small></div><div class="kpi"><label>m² vacantes</label><strong>${format(vacant?.value, 'm2')}</strong></div><div class="kpi"><label>GLA</label><strong>${format(gla?.value, 'm2')}</strong></div></div>`;
  }

  function renderRadar() {
    const overview = report.asset_overview;
    const selected = report.context.asset;
    const cards = overview.rows.map(row => `<button class="asset-card ${row.asset_key === selected ? 'selected' : ''}" data-asset="${row.asset_key}"><h3>${row.label}</h3><div class="meta">${row.fund} · ${row.category || 'Activo'} · ${row.period}</div><strong>${format(row.vacancy_pct, 'pct')}</strong><div class="numbers">${format(row.vacant_m2, 'm2')} vacantes · ${row.spatial_status === 'available' ? 'layout disponible' : 'sin layout espacial'}</div></button>`).join('');
    document.querySelector('#asset-radar').innerHTML = `<h2>Radar de activos</h2><p class="sub">Vacancia física y superficie observada. Selecciona un activo para profundizar.</p><div class="asset-cards">${cards || '<div class="unavailable">No hay activos disponibles para este período.</div>'}</div>`;
    document.querySelectorAll('[data-asset]').forEach(card => card.addEventListener('click', () => {
      state.set('asset', card.dataset.asset); state.set('period', report.context.requested_period); history.replaceState(null, '', `${location.pathname}?${state}`); load();
    }));
  }

  function renderSpatial() {
    const target = document.querySelector('#spatial-occupancy'); const spatial = report.spatial_occupancy;
    if (spatial.status !== 'available') {
      const copy = report.context.asset ? 'No hay layout espacial observado para este activo y período.' : 'Selecciona un activo para ver su ocupación espacial cuando haya cobertura.';
      target.innerHTML = `<h2>Ocupación espacial</h2><p class="sub">Edificios y pisos con cobertura verificable.</p><div class="unavailable">${copy}</div>`; return;
    }
    const buildings = spatial.buildings.map(building => `<article class="building"><h3>${building.building}</h3><div class="floors">${building.floors.map(floor => { const vacant = Number(floor.vacancy_pct || 0) > 0; const css = floor.vacancy_pct == null ? 'partial' : vacant ? 'vacant' : ''; return `<div class="floor ${css}" title="Piso ${floor.floor}: ${format(floor.vacancy_pct, 'pct')} vacante · ${format(floor.vacant_m2, 'm2')}"><span>Piso ${floor.floor}</span><span>${format(floor.vacancy_pct, 'pct')}</span></div>`; }).join('')}</div></article>`).join('');
    target.innerHTML = `<h2>Ocupación espacial</h2><p class="sub">${report.context.asset} · ${spatial.period}. Verde: ocupado; coral: presenta vacancia.</p><div class="buildings">${buildings}</div>`;
  }

  function renderHistory() {
    const allRows = report.history.rows; const rows = visibleWindow === 'historico' ? allRows : allRows.slice(-Number(visibleWindow.replace('M', '')));
    const tabs = ['6M','12M','24M','historico'].map(window => `<button data-window="${window}" class="${window === visibleWindow ? 'active' : ''}">${window === 'historico' ? 'Histórico' : window}</button>`).join('');
    const points = rows.map((row, index) => {
      const width = 620, height = 185, padding = 18; const values = rows.map(item => item.vacancy_pct).filter(value => value != null); const max = Math.max(...values, 1); const min = Math.min(...values, 0); const x = rows.length === 1 ? width / 2 : padding + index * ((width - 2 * padding) / (rows.length - 1)); const y = height - padding - ((row.vacancy_pct - min) / Math.max(max - min, 0.01)) * (height - 2 * padding); return {x, y, row};
    });
    const path = points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
    const svg = points.length ? `<svg viewBox="0 0 620 185" role="img" aria-label="Evolución de vacancia"><path class="line" d="${path}"/>${points.map(point => `<circle class="dot" cx="${point.x}" cy="${point.y}" r="3"><title>${point.row.period}: ${format(point.row.vacancy_pct, 'pct')}</title></circle>`).join('')}</svg>` : '<div class="unavailable">No hay historia observada para este contexto.</div>';
    const table = rows.slice().reverse().map(row => `<tr><td>${row.period}</td><td>${format(row.vacancy_pct, 'pct')}</td><td>${format(row.vacant_m2, 'm2')}</td><td>${format(row.gla_m2, 'm2')}</td></tr>`).join('');
    document.querySelector('#report-history').innerHTML = `<div class="history-controls"><div><h2>Evolución</h2><p class="sub">Puntos observados; el gráfico y la tabla consumen la misma serie.</p></div><div class="tabs">${tabs}</div></div><div class="legend"><span><i></i> Vacancia física</span></div><div class="chart">${svg}</div><div class="table-wrap"><table><thead><tr><th>Mes</th><th>Vacancia</th><th>m² vacantes</th><th>GLA</th></tr></thead><tbody>${table}</tbody></table></div>`;
    document.querySelectorAll('[data-window]').forEach(button => button.addEventListener('click', () => { visibleWindow = button.dataset.window; renderHistory(); }));
  }

  function updateContext() { state.set('fund', controls.fund.value); state.set('period', controls.period.value); state.set('parking_scope', controls.parkingScope.value); state.delete('asset'); history.replaceState(null, '', `${location.pathname}?${state}`); load(); }
  Object.values(controls).forEach(control => control.addEventListener('change', updateContext));
  load();
})();
