const i18n = I18N.fromDocument();
Chart.defaults.color = '#6b7077';
Chart.defaults.borderColor = '#d4d6d9';
Chart.defaults.font.family = "system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
Chart.defaults.plugins.legend.labels.padding = 12;
Chart.defaults.elements.line.tension = 0.25;
Chart.defaults.elements.point.radius = 2.5;
Chart.defaults.elements.point.hoverRadius = 5;

const C = {
  green: '#2d8a4e', red: '#c0392b', orange: '#c27d2a',
  blue: '#2563eb', purple: '#6c3bbd', cyan: '#0e7490', gray: '#999',
  grayLine: '#9ca3af',
};

const ONE_DECIMAL = { minimumFractionDigits: 1, maximumFractionDigits: 1 };
const fmt  = v => v != null ? i18n.number(v) : '—';
const fkm  = v => v != null ? i18n.number(v, { maximumFractionDigits: 1 }) : '—';
const fpct = v => v != null ? i18n.percent(v, ONE_DECIMAL) : '—';
const fsigned = v => i18n.number(v, { maximumFractionDigits: 1, signDisplay: 'exceptZero' });

const isoDay = iso => iso + 'T00:00:00Z';
const fdate = iso => i18n.date(isoDay(iso), { dateStyle: 'medium', timeZone: 'UTC' });

const fmonth = (iso, isDaily = false) => isDaily
  ? i18n.date(isoDay(iso), { day: 'numeric', month: 'short', year: '2-digit', timeZone: 'UTC' }) + ' *'
  : i18n.date(isoDay(iso), { month: 'short', year: '2-digit', timeZone: 'UTC' });

const monthsBefore = (iso, n) => {
  const d = new Date(iso + 'T00:00:00Z');
  d.setUTCMonth(d.getUTCMonth() - n);
  return d.toISOString().slice(0, 10);
};


const tooltip = (label, value) => i18n.t('common.chart.tooltip', { label, value });

const chartInstances = {};

fetch(i18n.dataUrl('history.json') + '?t=' + Date.now(), { cache: 'no-store' })
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(data => {
    if (!Array.isArray(data) || data.length === 0) {
      throw new Error(i18n.t('evolution.emptyHistory'));
    }
    data.sort((a, b) => a.date.localeCompare(b.date));
    render(data);
  })
  .catch(e => {
    document.getElementById('loading').textContent =
      i18n.t('common.error', { message: String(e.message || e) });
  });


function render(data) {
  const el = document.getElementById('main');
  el.innerHTML = '';

  const first = data[0];
  const last  = data[data.length - 1];

  const dailyEntry   = last && last.type === 'daily' ? last : null;
  const snapshots    = data.filter(d => d.type !== 'daily');
  const lastSnapshot = snapshots[snapshots.length - 1];
  const showComparison = !!(dailyEntry && lastSnapshot && dailyEntry.date !== lastSnapshot.date);

  const months = data.length;
  const yearsCovered = Number(((new Date(last.date) - new Date(first.date)) / (1000 * 60 * 60 * 24 * 365.25)).toFixed(1));

  el.innerHTML += html`
    <div class="intro">
      ${i18n.t('evolution.intro', { snapshots: months, count: yearsCovered })}
      <div class="meta">
        ${i18n.t('evolution.meta.range', { from: fdate(first.date), to: fdate(last.date) })}
        · ${i18n.t('evolution.meta.pedKm', { now: fkm(last.ped_km), first: fkm(first.ped_km) })}
        ${dailyEntry ? `· ${i18n.t('evolution.meta.daily', { date: fdate(dailyEntry.date) })}` : ''}
        · ${i18n.t('evolution.meta.area')}
      </div>
    </div>`;

  const defaultStart = (() => {
    const sixMonthsAgo = monthsBefore(last.date, 6);
    return sixMonthsAgo > first.date ? sixMonthsAgo : first.date;
  })();

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('evolution.period.title')}</div>
      <div class="period-controls">
        <label>${i18n.t('evolution.period.from')} <input type="date" id="period-start" min="${first.date}" max="${last.date}" value="${defaultStart}"></label>
        <label>${i18n.t('evolution.period.to')} <input type="date" id="period-end" min="${first.date}" max="${last.date}" value="${last.date}"></label>
        <button type="button" id="period-6m">${i18n.t('evolution.period.last6Months')}</button>
        <button type="button" id="period-reset">${i18n.t('evolution.period.full')}</button>
        <span class="period-info" id="period-info"></span>
        <div class="period-hint">
          ${i18n.t('evolution.period.hint')}
        </div>
      </div>
    </div>`;

  el.innerHTML += html`
    <div class="section">
      <div class="section-title" id="deltas-title">${i18n.t('evolution.deltas.title')}</div>
      <div class="delta-grid" id="deltas"></div>
    </div>`;

  if (showComparison) {
    el.innerHTML += html`
      <div class="section" id="compare-section">
        <div class="section-title">${i18n.t('evolution.compare.title')}</div>
        <div class="chart-card">
          <h3>${i18n.t('evolution.compare.hwTitle')}</h3>
          <div class="subtitle">
            ${i18n.t('evolution.compare.hwSubtitle', { snapshot: fdate(lastSnapshot.date), today: fdate(dailyEntry.date) })}
          </div>
          <div class="chart-wrap"><canvas id="c-compare-hw"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>${i18n.t('evolution.compare.fwTitle')}</h3>
          <div class="subtitle">
            ${i18n.t('evolution.compare.fwSubtitle')}
          </div>
          <div class="chart-wrap"><canvas id="c-compare-fw"></canvas></div>
        </div>
        <div class="delta-grid" id="compare-deltas"></div>
      </div>`;
  }

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('evolution.network.title')}</div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.network.pedTitle')}</h3>
        <div class="subtitle">footway + pedestrian + path + living_street + steps + elevator</div>
        <div class="chart-wrap"><canvas id="c-ped-km"></canvas></div>
      </div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.network.allTitle')}</h3>
        <div class="subtitle">${i18n.t('evolution.network.allSubtitle')}</div>
        <div class="chart-wrap"><canvas id="c-all-km"></canvas></div>
      </div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.network.hwTitle')}</h3>
        <div class="subtitle">${i18n.t('evolution.network.hwSubtitle')}</div>
        <div class="chart-wrap"><canvas id="c-hw-km"></canvas></div>
      </div>
    </div>`;

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('evolution.quality.title')}</div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.quality.swTitle')}</h3>
        <div class="subtitle">${i18n.t('evolution.quality.swSubtitle')}</div>
        <div class="chart-wrap"><canvas id="c-sw-pct"></canvas></div>
      </div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.quality.xingTitle')}</h3>
        <div class="subtitle">${i18n.t('evolution.quality.xingSubtitle')}</div>
        <div class="chart-wrap"><canvas id="c-xing"></canvas></div>
      </div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.quality.accTitle')}</h3>
        <div class="subtitle">${i18n.t('evolution.quality.accSubtitle')}</div>
        <div class="chart-wrap"><canvas id="c-acc"></canvas></div>
      </div>
    </div>`;

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('evolution.footways.title')}</div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.footways.mixTitle')}</h3>
        <div class="subtitle">
          ${i18n.t('evolution.footways.mixSubtitle')}
        </div>
        <div class="chart-wrap"><canvas id="c-fw-mix"></canvas></div>
      </div>
    </div>`;

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('evolution.sidewalks.title')}</div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.sidewalks.mixTitle')}</h3>
        <div class="subtitle">${i18n.t('evolution.sidewalks.mixSubtitle')}</div>
        <div class="chart-wrap"><canvas id="c-sw-mix"></canvas></div>
      </div>

      <div class="chart-card">
        <h3>${i18n.t('evolution.sidewalks.byTypeTitle')}</h3>
        <div class="subtitle" id="sw-by-type-subtitle">
          ${i18n.t('evolution.sidewalks.byTypeSubtitle')}
        </div>
        <div class="chart-wrap" id="sw-by-type-chartwrap"><canvas id="c-sw-by-type"></canvas></div>
        <p id="sw-by-type-note" style="display:none; color:var(--text-muted); font-size:11px; padding: 8px 0 0;"></p>
      </div>
    </div>`;

  requestAnimationFrame(() => {
    if (showComparison) renderComparison(lastSnapshot, dailyEntry);
    setupPeriodControls(data);
  });
}

const PED_TYPES = ['footway', 'pedestrian', 'path', 'living_street', 'steps', 'elevator', 'track', 'bridleway', 'platform', 'corridor'];

function footwaySubtypeCounts(entry) {
  const total    = entry.footway_ways || 0;
  const sidewalk = entry.footway_sidewalk || 0;
  const crossing = entry.footway_crossing || 0;
  const link     = entry.footway_link || 0;
  const island   = entry.footway_traffic_island || 0;
  const hasSplit = entry.footway_other != null && entry.footway_no_subtag != null;
  const other = hasSplit ? entry.footway_other : 0;
  const noTag = hasSplit
    ? entry.footway_no_subtag
    : Math.max(0, total - sidewalk - crossing - link - island);
  return { sidewalk, crossing, link, island, other, noTag };
}

function renderComparison(lastSnapshot, dailyEntry) {
  const kmA = lastSnapshot.km_by_highway || {};
  const kmB = dailyEntry.km_by_highway || {};

  const allTypes = PED_TYPES.filter(t => (kmA[t] || 0) > 0 || (kmB[t] || 0) > 0);
  allTypes.sort((a, b) => ((kmB[b] || 0) + (kmA[b] || 0)) - ((kmB[a] || 0) + (kmA[a] || 0)));

  new Chart(document.getElementById('c-compare-hw'), {
    type: 'bar',
    data: {
      labels: allTypes,
      datasets: [
        {
          label: i18n.t('evolution.compare.snapshotOf', { date: fdate(lastSnapshot.date) }),
          data: allTypes.map(t => kmA[t] || 0),
          backgroundColor: C.gray,
          borderRadius: 3,
        },
        {
          label: i18n.t('evolution.compare.today', { date: fdate(dailyEntry.date) }),
          data: allTypes.map(t => kmB[t] || 0),
          backgroundColor: C.green,
          borderRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: c => tooltip(c.dataset.label, `${fkm(c.parsed.y)} km`),
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          beginAtZero: true,
          grid: { color: '#eee' },
          title: { display: true, text: 'km', font: { size: 10 } },
        },
      },
    },
  });

  const fwA = footwaySubtypeCounts(lastSnapshot);
  const fwB = footwaySubtypeCounts(dailyEntry);
  const fwLabels = ['sidewalk', 'crossing', 'link', 'traffic_island', i18n.t('evolution.series.other'), i18n.t('evolution.series.noTag')];
  const fwKeys   = ['sidewalk', 'crossing', 'link', 'island', 'other', 'noTag'];

  new Chart(document.getElementById('c-compare-fw'), {
    type: 'bar',
    data: {
      labels: fwLabels,
      datasets: [
        {
          label: i18n.t('evolution.compare.snapshotOf', { date: fdate(lastSnapshot.date) }),
          data: fwKeys.map(k => fwA[k]),
          backgroundColor: C.gray,
          borderRadius: 3,
        },
        {
          label: i18n.t('evolution.compare.today', { date: fdate(dailyEntry.date) }),
          data: fwKeys.map(k => fwB[k]),
          backgroundColor: C.cyan,
          borderRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: c => tooltip(c.dataset.label, `${fmt(c.parsed.y)} ways`),
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          beginAtZero: true,
          grid: { color: '#eee' },
          title: { display: true, text: 'ways', font: { size: 10 } },
        },
      },
    },
  });

  const grid = document.getElementById('compare-deltas');
  grid.innerHTML = '';
  for (const t of allTypes) {
    const before = kmA[t] || 0;
    const after  = kmB[t] || 0;
    const delta = after - before;

    let cls = 'neutral';
    if (delta > 0.05) cls = 'pos';
    else if (delta < -0.05) cls = 'neg';

    const showDelta = fsigned(delta) + ' km';

    grid.insertAdjacentHTML('beforeend', html`
      <div class="delta ${cls}">
        <div class="delta-label">${t}</div>
        <div class="delta-val">${fkm(after)} km</div>
        <div class="delta-sub">${i18n.t('evolution.deltas.since', { delta: showDelta, date: fdate(lastSnapshot.date) })}</div>
      </div>
    `);
  }
}

function setupPeriodControls(data) {
  const startInput = document.getElementById('period-start');
  const endInput   = document.getElementById('period-end');
  const resetBtn   = document.getElementById('period-reset');
  const sixMoBtn   = document.getElementById('period-6m');

  const minDate = data[0].date;
  const maxDate = data[data.length - 1].date;

  const apply = () => applyPeriod(data, minDate, maxDate);

  startInput.addEventListener('change', apply);
  endInput.addEventListener('change', apply);
  resetBtn.addEventListener('click', () => {
    startInput.value = minDate;
    endInput.value = maxDate;
    apply();
  });
  if (sixMoBtn) {
    sixMoBtn.addEventListener('click', () => {
      const sixMonthsAgo = monthsBefore(maxDate, 6);
      startInput.value = sixMonthsAgo > minDate ? sixMonthsAgo : minDate;
      endInput.value = maxDate;
      apply();
    });
  }

  apply();
}

function applyPeriod(data, minDate, maxDate) {
  const startInput = document.getElementById('period-start');
  const endInput   = document.getElementById('period-end');

  let start = startInput.value || minDate;
  let end   = endInput.value   || maxDate;

  if (start > end) {
    [start, end] = [end, start];
    startInput.value = start;
    endInput.value = end;
  }

  let filtered = data.filter(d => d.date >= start && d.date <= end);
  if (filtered.length === 0) {
    filtered = [data[data.length - 1]];
  }

  const labels = filtered.map(d => fmonth(d.date, d.type === 'daily'));
  const isFullRange = (start === minDate && end === maxDate);

  const info = document.getElementById('period-info');
  if (info) {
    info.textContent = isFullRange
      ? i18n.t('evolution.period.fullInfo', { count: filtered.length })
      : i18n.t('evolution.period.zoomInfo', { count: filtered.length });
  }

  renderDeltas(filtered[0], filtered[filtered.length - 1]);
  renderCharts(filtered, labels, !isFullRange);
  renderSidewalkByType(filtered[filtered.length - 1]);
}

function makeChart(id, config) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  if (chartInstances[id]) {
    chartInstances[id].destroy();
  }
  chartInstances[id] = new Chart(ctx, config);
}

function renderDeltas(first, last) {
  const titleEl = document.getElementById('deltas-title');
  if (titleEl) {
    titleEl.textContent = first.date === last.date
      ? i18n.t('evolution.deltas.at', { date: fdate(first.date) })
      : i18n.t('evolution.deltas.range', { from: fdate(first.date), to: fdate(last.date) });
  }

  const target = document.getElementById('deltas');
  target.innerHTML = '';

  const items = [
    { labelKey: 'evolution.deltas.pedNetwork',          key: 'ped_km',                  unit: 'km' },
    { labelKey: 'evolution.deltas.footwaySidewalk',     key: 'footway_sidewalk',        unit: '' },
    { labelKey: 'evolution.deltas.crossingNodes',       key: 'crossing_nodes',          unit: '' },
    { labelKey: 'evolution.deltas.crossingWays',        key: 'footway_crossing',        unit: '' },
    { labelKey: 'evolution.deltas.sidewalksDocumented', key: 'sidewalk_documented_pct', unit: '%' },
    { labelKey: 'evolution.deltas.sidewalksSeparate',   key: 'sidewalk_separate_pct',   unit: '%' },
    { labelKey: 'evolution.deltas.crossingTagged',      key: 'crossing_tagged_pct',     unit: '%' },
    { labelKey: 'evolution.deltas.tactilePaving',       key: 'tactile_paving_pct',      unit: '%' },
  ];

  for (const { labelKey, key, unit } of items) {
    const before = first[key];
    const after  = last[key];
    if (before == null || after == null) continue;
    const delta = after - before;
    let cls = 'neutral';
    if (delta > 0) cls = 'pos';
    else if (delta < 0) cls = 'neg';

    const showAfter = unit === '%'
      ? fpct(after)
      : fkm(after) + (unit ? ' ' + unit : '');
    const showDelta = unit === '%'
      ? i18n.t('evolution.deltas.points', { value: i18n.number(delta, { ...ONE_DECIMAL, signDisplay: 'exceptZero' }) })
      : fsigned(delta) + (unit ? ' ' + unit : '');

    target.insertAdjacentHTML('beforeend', html`
      <div class="delta ${cls}">
        <div class="delta-label">${i18n.t(labelKey)}</div>
        <div class="delta-val">${showAfter}</div>
        <div class="delta-sub">${i18n.t('evolution.deltas.since', { delta: showDelta, date: fdate(first.date) })}</div>
      </div>
    `);
  }
}

function pointStyles(data, color) {
  return {
    pointBackgroundColor: data.map(d => d.type === 'daily' ? C.orange : color),
    pointBorderColor:     data.map(d => d.type === 'daily' ? C.orange : color),
    pointRadius:          data.map(d => d.type === 'daily' ? 5 : 2.5),
    pointHoverRadius:     data.map(d => d.type === 'daily' ? 7 : 5),
  };
}

function lineOpts({ yTitle, percent, zoomed }) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'bottom' },
      tooltip: {
        callbacks: {
          label: c => tooltip(c.dataset.label, percent ? fpct(c.parsed.y) : fkm(c.parsed.y) + (yTitle ? ' ' + yTitle : '')),
        },
      },
    },
    scales: {
      x: { grid: { display: false } },
      y: {
        beginAtZero: percent ? false : !zoomed,
        max: percent ? 100 : undefined,
        grid: { color: '#eee' },
        title: yTitle ? { display: true, text: yTitle, font: { size: 10 } } : undefined,
      },
    },
  };
}

function stackedOpts(yTitle) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { position: 'bottom' } },
    scales: {
      x: { stacked: true, grid: { display: false } },
      y: {
        stacked: true,
        beginAtZero: true,
        grid: { color: '#eee' },
        title: yTitle ? { display: true, text: yTitle, font: { size: 10 } } : undefined,
      },
    },
  };
}

function renderCharts(data, labels, zoomed = false) {
  const series = (key) => data.map(d => d[key] ?? 0);
  const seriesFromKm = (k) => data.map(d => (d.km_by_highway || {})[k] ?? 0);

  makeChart('c-ped-km', {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: i18n.t('evolution.deltas.pedNetwork'),
        data: series('ped_km'),
        borderColor: C.green,
        backgroundColor: C.green + '22',
        fill: true,
        ...pointStyles(data, C.green),
      }],
    },
    options: lineOpts({ yTitle: 'km', zoomed }),
  });

  makeChart('c-all-km', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: i18n.t('evolution.series.pedestrian'), data: series('ped_km'),      borderColor: C.green,  backgroundColor: C.green + '22', fill: false, ...pointStyles(data, C.green) },
        { label: i18n.t('evolution.series.roads'), data: series('road_km'),     borderColor: C.red,    backgroundColor: C.red + '22',   fill: false, ...pointStyles(data, C.red) },
        { label: i18n.t('evolution.series.cycleway'), data: series('cycleway_km'), borderColor: C.blue,   backgroundColor: C.blue + '22',  fill: false, ...pointStyles(data, C.blue) },
      ],
    },
    options: lineOpts({ yTitle: 'km', zoomed }),
  });

  const HW_TYPES = ['footway', 'cycleway', 'residential', 'secondary', 'tertiary', 'primary'];
  const HW_COLORS = [C.green, C.blue, C.red, C.orange, C.cyan, C.purple];
  makeChart('c-hw-km', {
    type: 'line',
    data: {
      labels,
      datasets: HW_TYPES.map((hw, i) => ({
        label: hw,
        data: seriesFromKm(hw),
        borderColor: HW_COLORS[i],
        backgroundColor: HW_COLORS[i] + '22',
        fill: false,
        ...pointStyles(data, HW_COLORS[i]),
      })),
    },
    options: lineOpts({ yTitle: 'km', zoomed }),
  });

  const notDocumented = data.map(d => d.sidewalk_documented_pct != null
    ? Math.max(0, 100 - d.sidewalk_documented_pct)
    : null);

  makeChart('c-sw-pct', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: i18n.t('evolution.series.documentedAnyTag'), data: series('sidewalk_documented_pct'), borderColor: C.cyan,  backgroundColor: C.cyan  + '22', fill: false, ...pointStyles(data, C.cyan) },
        { label: 'Sidewalk:both=separate', data: series('sidewalk_separate_pct'), borderColor: C.green, backgroundColor: C.green + '22', fill: false, ...pointStyles(data, C.green) },
        { label: i18n.t('evolution.series.notDocumented'), data: notDocumented, borderColor: C.grayLine, backgroundColor: C.grayLine + '22', borderDash: [4, 3], fill: false, ...pointStyles(data, C.grayLine) },
      ],
    },
    options: lineOpts({ percent: true, zoomed }),
  });

  makeChart('c-xing', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: i18n.t('evolution.series.crossingNodes'), data: series('crossing_nodes'),    borderColor: C.cyan,   backgroundColor: C.cyan   + '22', fill: false, ...pointStyles(data, C.cyan) },
        { label: i18n.t('evolution.series.crossingWays'), data: series('footway_crossing'),  borderColor: C.green,  backgroundColor: C.green  + '22', fill: false, ...pointStyles(data, C.green) },
        { label: i18n.t('evolution.series.continuousCrossings'), data: series('crossing_continuous'), borderColor: C.purple, backgroundColor: C.purple + '22', fill: false, ...pointStyles(data, C.purple) },
      ],
    },
    options: lineOpts({ zoomed }),
  });

  makeChart('c-acc', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: i18n.t('evolution.series.footwaySurface'), data: series('footway_surface_pct'),    borderColor: C.cyan,   backgroundColor: C.cyan + '22',   fill: false, ...pointStyles(data, C.cyan) },
        { label: i18n.t('evolution.series.footwaySmoothness'), data: series('footway_smoothness_pct'), borderColor: C.blue,   backgroundColor: C.blue + '22',   fill: false, ...pointStyles(data, C.blue) },
        { label: i18n.t('evolution.series.crossingTactilePaving'), data: series('tactile_paving_pct'),     borderColor: C.green,  backgroundColor: C.green + '22',  fill: false, ...pointStyles(data, C.green) },
      ],
    },
    options: lineOpts({ percent: true, zoomed }),
  });

  const fwCountsSeries = data.map(footwaySubtypeCounts);
  const fwOtherArr = fwCountsSeries.map(c => c.other);
  const fwNoTagArr = fwCountsSeries.map(c => c.noTag);
  makeChart('c-fw-mix', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'footway=sidewalk',       data: series('footway_sidewalk'), backgroundColor: C.green,  borderColor: C.green,  fill: true },
        { label: 'footway=crossing',        data: series('footway_crossing'), backgroundColor: C.cyan,   borderColor: C.cyan,   fill: true },
        { label: 'footway=link',             data: series('footway_link'),     backgroundColor: C.purple, borderColor: C.purple, fill: true },
        { label: 'footway=traffic_island',   data: series('footway_traffic_island'), backgroundColor: C.orange, borderColor: C.orange, fill: true },
        { label: i18n.t('evolution.series.otherRecognised'), data: fwOtherArr,                 backgroundColor: '#999',   borderColor: '#888',  fill: true },
        { label: i18n.t('evolution.series.noTag'), data: fwNoTagArr,                backgroundColor: '#ddd',   borderColor: '#ccc',  fill: true },
      ],
    },
    options: stackedOpts(),
  });

  const swSepArr  = series('road_sidewalk_separate');
  const swYesArr  = series('road_sidewalk_yes_or_both');
  const swPartArr = series('road_sidewalk_partial');
  const swNoArr   = series('road_sidewalk_no_explicit');
  const swNoneArr = data.map(d => Math.max(0, (d.road_ways || 0)
    - (d.road_sidewalk_separate || 0)
    - (d.road_sidewalk_yes_or_both || 0)
    - (d.road_sidewalk_partial || 0)
    - (d.road_sidewalk_no_explicit || 0)));

  makeChart('c-sw-mix', {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'separate',        data: swSepArr,  backgroundColor: C.green,  borderColor: C.green,  fill: true },
        { label: 'yes / both',       data: swYesArr,  backgroundColor: C.cyan,   borderColor: C.cyan,   fill: true },
        { label: i18n.t('layer.sidewalk.partial'), data: swPartArr, backgroundColor: C.orange, borderColor: C.orange, fill: true },
        { label: i18n.t('evolution.series.noExplicit'), data: swNoArr,   backgroundColor: C.red,    borderColor: C.red,    fill: true },
        { label: i18n.t('evolution.series.noTag'), data: swNoneArr, backgroundColor: '#bbb',   borderColor: '#aaa',  fill: true },
      ],
    },
    options: stackedOpts(),
  });
}

const ROAD_TYPE_GROUPS = [
  { labelKey: 'evolution.roadType.residential', keys: ['residential', 'unclassified'] },
  { labelKey: 'evolution.roadType.tertiary',    keys: ['tertiary', 'tertiary_link'] },
  { labelKey: 'evolution.roadType.secondary',   keys: ['secondary', 'secondary_link'] },
  { labelKey: 'evolution.roadType.primary',     keys: ['primary', 'primary_link'] },
];

function renderSidewalkByType(point) {
  const wrap = document.getElementById('sw-by-type-chartwrap');
  const note = document.getElementById('sw-by-type-note');
  if (!wrap || !note) return;

  const byType = point && point.road_sidewalk_by_type;
  const hasData = byType && Object.keys(byType).length > 0;

  if (!hasData) {
    if (chartInstances['c-sw-by-type']) {
      chartInstances['c-sw-by-type'].destroy();
      delete chartInstances['c-sw-by-type'];
    }
    wrap.style.display = 'none';
    note.style.display = 'block';
    note.textContent = point
      ? i18n.t('evolution.sidewalks.noData', { date: fdate(point.date) })
      : i18n.t('evolution.sidewalks.noDataUndated');
    return;
  }

  wrap.style.display = '';
  note.style.display = 'none';

  const groups = ROAD_TYPE_GROUPS.map(g => {
    const agg = { total: 0, separate: 0, yes_or_both: 0, partial: 0, no_explicit: 0 };
    for (const k of g.keys) {
      const b = byType[k];
      if (!b) continue;
      agg.total       += b.total       || 0;
      agg.separate    += b.separate    || 0;
      agg.yes_or_both += b.yes_or_both || 0;
      agg.partial      += b.partial      || 0;
      agg.no_explicit += b.no_explicit || 0;
    }
    return { label: i18n.t(g.labelKey), ...agg };
  });

  const pct = (n, d) => d > 0 ? +(n / d * 100).toFixed(1) : 0;
  const labels     = groups.map(g => g.label);
  const sepPct     = groups.map(g => pct(g.separate, g.total));
  const yesPct     = groups.map(g => pct(g.yes_or_both, g.total));
  const partPct    = groups.map(g => pct(g.partial, g.total));
  const noPct      = groups.map(g => pct(g.no_explicit, g.total));
  const noTagPct   = groups.map((g, i) => Math.max(0, +(100 - sepPct[i] - yesPct[i] - partPct[i] - noPct[i]).toFixed(1)));

  makeChart('c-sw-by-type', {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'separate',        data: sepPct,   backgroundColor: C.green,  stack: 'sw' },
        { label: 'yes / both',       data: yesPct,   backgroundColor: C.cyan,   stack: 'sw' },
        { label: i18n.t('layer.sidewalk.partial'), data: partPct,  backgroundColor: C.orange, stack: 'sw' },
        { label: i18n.t('evolution.series.noExplicit'), data: noPct,    backgroundColor: C.red,    stack: 'sw' },
        { label: i18n.t('evolution.series.noTag'), data: noTagPct, backgroundColor: '#bbb',   stack: 'sw' },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: c => tooltip(c.dataset.label, fpct(c.parsed.y)),
            afterBody: items => {
              const g = groups[items[0].dataIndex];
              return i18n.t('evolution.roadType.total', { count: g.total });
            },
          },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: { stacked: true, beginAtZero: true, max: 100, grid: { color: '#eee' }, title: { display: true, text: '%', font: { size: 10 } } },
      },
    },
  });
}
