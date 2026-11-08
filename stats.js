const i18n = I18N.fromDocument();
Chart.defaults.color = '#6b7077';
Chart.defaults.borderColor = '#d4d6d9';
Chart.defaults.font.family = "system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
Chart.defaults.plugins.legend.labels.padding = 12;

const C = {
  green: '#2d8a4e', red: '#c0392b', orange: '#c27d2a',
  yellow: '#eab308', blue: '#2563eb', purple: '#6c3bbd',
  cyan: '#0e7490', gray: '#999',
};
const INFRA_C = { pedestrian: C.green, road: C.red, cycleway_foot_yes: C.blue, cycleway_no_foot: C.purple };
const INFRA_L = {
  pedestrian: i18n.t('stats.infra.pedestrian'),
  road: i18n.t('stats.infra.road'),
  cycleway_foot_yes: i18n.t('stats.infra.cyclewayFootYes'),
  cycleway_no_foot: i18n.t('stats.infra.cyclewayNoFoot'),
};
const SW_C = { separate: C.green, yes: C.cyan, documented: C.green, partial: C.orange, unknown: '#aaa' };
const SW_L = {
  separate: 'separate',
  yes: 'yes',
  documented: i18n.t('stats.sidewalk.documented'),
  partial: i18n.t('stats.sidewalk.partial'),
  unknown: i18n.t('stats.sidewalk.unknown'),
};

const ONE_DECIMAL = { minimumFractionDigits: 1, maximumFractionDigits: 1 };
const TWO_DECIMALS = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
const fmt = v => v != null ? i18n.number(v) : '—';
const fkm = v => v != null ? i18n.number(v, { maximumFractionDigits: 1 }) : '—';
const fpct = v => v != null ? i18n.percent(v, ONE_DECIMAL) : '—';
const fdec = (v, options) => v != null ? i18n.number(v, options) : '—';


const LINK_SLOT = '\u0001';
function withLink(text, link) {
  const [before, after = ''] = text.split(LINK_SLOT);
  return html`${before}${link}${after}`;
}
const tooltip = (label, value) => i18n.t('common.chart.tooltip', { label, value });

fetch(i18n.dataUrl('state.txt')).then(r => r.text()).then(txt => {
  const m = txt.match(/build_timestamp=(.+)/);
  if (m) {
    document.getElementById('build-date').textContent =
      i18n.t('header.buildDate', { date: i18n.date(m[1].trim(), { dateStyle: 'short', timeStyle: 'short' }) });
  }
}).catch(() => {});

fetch(i18n.dataUrl('stats.json'))
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(render)
  .catch(e => { document.getElementById('loading').textContent = i18n.t('common.error', { message: String(e) }); });


function computeCompleteness(s) {
  const swRoad = s.sidewalk_roads || {};
  const swPct  = swRoad.pct_by_status || {};
  const gaps   = s.sidewalk_gaps || {};
  const mc     = s.missing_crossings || {};
  const net    = s.network || {};

  const sidewalkDocPct = clamp(
    (swPct.separate || 0) + (swPct.yes || 0) + (swPct.documented || 0) + (swPct.partial || 0) * 0.5,
    0, 100,
  );

  const sidewalkSepPct = clamp((swRoad.separate_all_sides || {}).pct || 0, 0, 100);

  const nNodes = mc.crossing_nodes_found || 0;
  const nMissingWay = mc.missing_crossing_way || 0;
  const crossingConnPct = nNodes > 0
    ? clamp((1 - nMissingWay / nNodes) * 100, 0, 100)
    : 100;

  const nMissingTag = mc.missing_crossing_tag || 0;
  const nWrongTag = mc.wrong_crossing_tag || 0;
  const crossingTagPct = nNodes > 0
    ? clamp((1 - (nMissingWay + nMissingTag + nWrongTag) / nNodes) * 100, 0, 100)
    : 100;

  const bothKm = gaps.both_length_km || 0;
  const gapKm  = gaps.gap_length_km || 0;
  const continuityPct = (bothKm + gapKm) > 0
    ? clamp(bothKm / (bothKm + gapKm) * 100, 0, 100)
    : 0;

  const global = (sidewalkDocPct + sidewalkSepPct + crossingConnPct + crossingTagPct + continuityPct) / 5;

  return {
    global: Math.round(global * 10) / 10,
    subs: [
      { labelKey: 'stats.indicator.sidewalkTags.label',       hintKey: 'stats.indicator.sidewalkTags.hint',       pct: sidewalkDocPct },
      { labelKey: 'stats.indicator.sidewalkSeparate.label',   hintKey: 'stats.indicator.sidewalkSeparate.hint',   pct: sidewalkSepPct },
      { labelKey: 'stats.indicator.crossingsConnected.label', hintKey: 'stats.indicator.crossingsConnected.hint', pct: crossingConnPct },
      { labelKey: 'stats.indicator.crossingsTagged.label',    hintKey: 'stats.indicator.crossingsTagged.hint',    pct: crossingTagPct },
      { labelKey: 'stats.indicator.continuity.label',         hintKey: 'stats.indicator.continuity.hint',         pct: continuityPct },
    ],
  };
}

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

function barClass(pct) {
  if (pct >= 75) return 'good';
  if (pct >= 50) return '';
  if (pct >= 25) return 'warn';
  return 'bad';
}


function render(s) {
  const el = document.getElementById('main');
  el.innerHTML = '';

  const net = s.network || {};
  const graph = s.graph || {};
  const swRoad = s.sidewalk_roads || {};
  const gaps = s.sidewalk_gaps || {};
  const routing = s.routing || {};
  const od = s.od_sampling || {};
  const mc = s.missing_crossings || {};
  const catD = net.km_by_category || {};

  const comp = computeCompleteness(s);
  const r = 60, circ = 2 * Math.PI * r;
  const filled = (comp.global / 100) * circ;
  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('stats.completeness.title')}</div>
      <div class="section-intro">${withLink(i18n.t('stats.completeness.intro', { link: LINK_SLOT }), html`<a href="./about.html#indicators">${i18n.t('stats.completeness.methodologyLink')}</a>`)}</div>
      <div class="completeness">
        <div class="gauge">
          <svg viewBox="0 0 140 140">
            <circle class="gauge-bg" cx="70" cy="70" r="${r}"></circle>
            <circle class="gauge-fg" cx="70" cy="70" r="${r}"
                    stroke-dasharray="${filled} ${circ}"></circle>
          </svg>
          <div class="gauge-num">
            <div class="v">${fdec(comp.global, ONE_DECIMAL)}</div>
            <div class="u">${i18n.t('stats.completeness.outOf100')}</div>
          </div>
        </div>
        <div class="sub-scores" id="sub-scores"></div>
      </div>
    </div>`;

  if (mc.crossing_nodes_found != null) {
    const total = mc.crossing_nodes_found || 0;
    const taggedOk = total - (mc.missing_crossing_way || 0) - (mc.missing_crossing_tag || 0) - (mc.wrong_crossing_tag || 0);
    el.innerHTML += html`
      <div class="section">
        <div class="section-title">${i18n.t('stats.crossings.title')}</div>
        <div class="section-intro">${i18n.t('stats.crossings.intro')}</div>
        <div class="kpi-grid">
          <div class="kpi">
            <div class="kpi-label">${i18n.t('stats.crossings.nodes')}</div>
            <div class="kpi-val">${fmt(total)}</div>
            <div class="kpi-sub">${i18n.t('stats.crossings.nodesSub')}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">${i18n.t('stats.crossings.ok')}</div>
            <div class="kpi-val">${fmt(taggedOk)}</div>
            <div class="kpi-sub">${fpct(total > 0 ? taggedOk / total * 100 : 0)}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">${i18n.t('stats.crossings.missingWay')}</div>
            <div class="kpi-val" style="color:#f97316">${fmt(mc.missing_crossing_way || 0)}</div>
            <div class="kpi-sub">${i18n.t('stats.crossings.missingWaySub')}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">${i18n.t('stats.crossings.missingTag')}</div>
            <div class="kpi-val" style="color:#eab308">${fmt(mc.missing_crossing_tag || 0)}</div>
            <div class="kpi-sub">${i18n.t('stats.crossings.missingTagSub')}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">${i18n.t('stats.crossings.wrongTag')}</div>
            <div class="kpi-val" style="color:#dc2626">${fmt(mc.wrong_crossing_tag || 0)}</div>
            <div class="kpi-sub">${i18n.t('stats.crossings.wrongTagSub')}</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">${i18n.t('stats.crossings.continuous')}</div>
            <div class="kpi-val">${fmt(mc.crossing_continuous || 0)}</div>
            <div class="kpi-sub">crossing:continuous=yes</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">${i18n.t('stats.crossings.excluded')}</div>
            <div class="kpi-val"><span class="small">${fmt(mc.on_excluded_way || 0)}</span></div>
            <div class="kpi-sub">service / cycleway / track</div>
          </div>
        </div>
        <div class="charts">
          <div class="chart-card">
            <h3>${i18n.t('stats.crossings.chart')}</h3>
            <div class="chart-wrap"><canvas id="c-mc"></canvas></div>
          </div>
        </div>
      </div>`;
  }

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('stats.network.title')}</div>
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.network.totalLength')}</div>
          <div class="kpi-val">${fkm(net.total_km)} <span class="kpi-unit">km</span></div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.network.nodes')}</div>
          <div class="kpi-val">${fmt(graph.nodes)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.network.edges')}</div>
          <div class="kpi-val">${fmt(graph.edges)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.network.pedestrian')}</div>
          <div class="kpi-val">${fkm(catD.pedestrian)} <span class="kpi-unit">km</span></div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.network.roads')}</div>
          <div class="kpi-val">${fkm(catD.road)} <span class="kpi-unit">km</span></div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.network.cycleways')}</div>
          <div class="kpi-val">${fkm((catD.cycleway_foot_yes || 0) + (catD.cycleway_no_foot || 0))} <span class="kpi-unit">km</span></div>
          <div class="kpi-sub">${i18n.t('stats.network.cyclewaysSub', { footYes: fkm(catD.cycleway_foot_yes), noFoot: fkm(catD.cycleway_no_foot) })}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.network.density')}</div>
          <div class="kpi-val">${catD.road > 0 ? fdec(catD.pedestrian / catD.road, TWO_DECIMALS) : '—'}</div>
          <div class="kpi-sub">${i18n.t('stats.network.densitySub')}</div>
        </div>
      </div>
      <div class="charts">
        <div class="chart-card">
          <h3>${i18n.t('stats.network.chartCategory')}</h3>
          <div class="chart-wrap"><canvas id="c-cat"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>${i18n.t('stats.network.chartHighway')}</h3>
          <div class="chart-wrap"><canvas id="c-hw"></canvas></div>
        </div>
      </div>
    </div>`;

  const byS = swRoad.by_status || {};
  const pctS = swRoad.pct_by_status || {};
  const docPct = (pctS.separate || 0) + (pctS.yes || 0) + (pctS.documented || 0);

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('stats.sidewalkTags.title')}</div>
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.sidewalkTags.segments')}</div>
          <div class="kpi-val">${fmt(swRoad.total_road_ways)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.sidewalkTags.documented')}</div>
          <div class="kpi-val">${fpct(docPct)}</div>
          <div class="kpi-sub">${i18n.t('stats.sidewalkTags.documentedSub')}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.sidewalkTags.partial')}</div>
          <div class="kpi-val">${fpct(pctS.partial)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.sidewalkTags.untagged')}</div>
          <div class="kpi-val">${fpct(pctS.unknown)}</div>
        </div>
      </div>
      <div class="charts">
        <div class="chart-card">
          <h3>${i18n.t('stats.sidewalkTags.chartCount')}</h3>
          <div class="chart-wrap"><canvas id="c-sw-n"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>${i18n.t('stats.sidewalkTags.chartKm')}</h3>
          <div class="chart-wrap"><canvas id="c-sw-km"></canvas></div>
        </div>
      </div>
    </div>`;

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('stats.spatial.title')}</div>
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.spatial.analysed')}</div>
          <div class="kpi-val">${fmt(gaps.roads_analysed)}</div>
          <div class="kpi-sub">${i18n.t('stats.spatial.excluded', { count: gaps.skipped_no_sidewalk ?? 0 })}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.spatial.bothSides')}</div>
          <div class="kpi-val">${fmt(gaps.both_sides)}</div>
          <div class="kpi-sub">${fkm(gaps.both_length_km)} km</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.spatial.oneSide')}</div>
          <div class="kpi-val">${fmt(gaps.one_side_gap)}</div>
          <div class="kpi-sub">${fkm(gaps.gap_length_km)} km</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.spatial.noSide')}</div>
          <div class="kpi-val">${fmt(gaps.neither_side)}</div>
          <div class="kpi-sub">${fkm(gaps.neither_length_km)} km</div>
        </div>
      </div>
      <div class="charts">
        <div class="chart-card">
          <h3>${i18n.t('stats.spatial.chartResult')}</h3>
          <div class="chart-wrap"><canvas id="c-gap"></canvas></div>
        </div>
        <div class="chart-card">
          <h3>${i18n.t('stats.spatial.chartFootways')}</h3>
          <div class="chart-wrap"><canvas id="c-fw-filter"></canvas></div>
        </div>
      </div>
    </div>`;

  el.innerHTML += html`
    <div class="section">
      <div class="section-title">${i18n.t('stats.simulation.title')}</div>
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.simulation.trips')}</div>
          <div class="kpi-val">${fmt(routing.routed_trips)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.simulation.avgDistance')}</div>
          <div class="kpi-val">${routing.avg_distance_m != null ? fdec(routing.avg_distance_m / 1000, TWO_DECIMALS) : '—'} <span class="kpi-unit">km</span></div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.simulation.odPoints')}</div>
          <div class="kpi-val">${fmt(od.od_points)}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">${i18n.t('stats.simulation.computeTime')}</div>
          <div class="kpi-val">${routing.routing_time_s != null ? fdec(routing.routing_time_s, ONE_DECIMAL) : '—'} <span class="kpi-unit">s</span></div>
        </div>
      </div>
    </div>`;

  const subEl = document.getElementById('sub-scores');
  for (const sub of comp.subs) {
    subEl.insertAdjacentHTML('beforeend', html`
      <div class="sub-score">
        <div class="row-top">
          <span class="label">${i18n.t(sub.labelKey)} <span style="color:#aaa;font-weight:400">${i18n.t(sub.hintKey)}</span></span>
          <span class="v">${fpct(sub.pct)}</span>
        </div>
        <div class="bar"><div class="bar-fill ${barClass(sub.pct)}" style="width:${sub.pct}%"></div></div>
      </div>
    `);
  }

  requestAnimationFrame(() => renderCharts(s));
}

function renderCharts(s) {
  const net = s.network || {};
  const swRoad = s.sidewalk_roads || {};
  const gaps = s.sidewalk_gaps || {};
  const mc = s.missing_crossings || {};

  const dOpts = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: 'right' } },
  };
  const bOpts = u => ({
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false } },
      y: { grid: { color: '#eee' }, title: { display: true, text: u, font: { size: 10 } } },
    },
  });

  if (mc.crossing_nodes_found != null) {
    const total = mc.crossing_nodes_found || 0;
    const tagOk = total - (mc.missing_crossing_way || 0) - (mc.missing_crossing_tag || 0) - (mc.wrong_crossing_tag || 0);
    const ctx = document.getElementById('c-mc');
    if (ctx) {
      new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: [i18n.t('stats.crossings.ok'), i18n.t('stats.crossings.missingWay'), i18n.t('stats.crossings.missingTag'), i18n.t('stats.crossings.wrongTag')],
          datasets: [{
            data: [tagOk, mc.missing_crossing_way || 0, mc.missing_crossing_tag || 0, mc.wrong_crossing_tag || 0],
            backgroundColor: [C.green, '#f97316', C.yellow, '#dc2626'],
            borderWidth: 0,
          }],
        },
        options: { ...dOpts, plugins: { ...dOpts.plugins, tooltip: { callbacks: { label: c => tooltip(c.label, fmt(c.raw)) } } } },
      });
    }
  }

  const catD = net.km_by_category || {};
  const ck = Object.keys(catD);
  if (ck.length) {
    new Chart(document.getElementById('c-cat'), {
      type: 'doughnut',
      data: {
        labels: ck.map(k => INFRA_L[k] || k),
        datasets: [{ data: ck.map(k => catD[k]), backgroundColor: ck.map(k => INFRA_C[k] || C.gray), borderWidth: 0 }],
      },
      options: { ...dOpts, plugins: { ...dOpts.plugins, tooltip: { callbacks: { label: c => tooltip(c.label, fkm(c.raw) + ' km') } } } },
    });
  }

  const hwD = net.km_by_highway || {};
  const hk = Object.keys(hwD).slice(0, 12);
  if (hk.length) {
    const hwC = k => ['footway','pedestrian','path','living_street','steps'].includes(k) ? C.green : k === 'cycleway' ? C.blue : C.red;
    new Chart(document.getElementById('c-hw'), {
      type: 'bar',
      data: {
        labels: hk.map(k => k),
        datasets: [{ data: hk.map(k => hwD[k]), backgroundColor: hk.map(hwC), borderRadius: 3, borderSkipped: false }],
      },
      options: { ...bOpts('km'), indexAxis: 'y' },
    });
  }

  const swK = ['separate', 'yes', 'documented', 'partial', 'unknown'];
  const byS = swRoad.by_status || {};
  new Chart(document.getElementById('c-sw-n'), {
    type: 'bar',
    data: {
      labels: swK.map(k => SW_L[k]),
      datasets: [{ data: swK.map(k => byS[k] || 0), backgroundColor: swK.map(k => SW_C[k]), borderRadius: 3, borderSkipped: false }],
    },
    options: bOpts(i18n.t('stats.sidewalkTags.segmentsAxis')),
  });

  const kmS = swRoad.km_by_status || {};
  new Chart(document.getElementById('c-sw-km'), {
    type: 'bar',
    data: {
      labels: swK.map(k => SW_L[k]),
      datasets: [{ data: swK.map(k => kmS[k] || 0), backgroundColor: swK.map(k => SW_C[k]), borderRadius: 3, borderSkipped: false }],
    },
    options: bOpts('km'),
  });

  if (gaps.both_sides != null) {
    new Chart(document.getElementById('c-gap'), {
      type: 'doughnut',
      data: {
        labels: [i18n.t('stats.spatial.bothSides'), i18n.t('stats.spatial.oneSide'), i18n.t('stats.spatial.noSide')],
        datasets: [{ data: [gaps.both_sides || 0, gaps.one_side_gap || 0, gaps.neither_side || 0], backgroundColor: [C.green, C.orange, C.red], borderWidth: 0 }],
      },
      options: { ...dOpts, plugins: { ...dOpts.plugins, tooltip: { callbacks: { label: c => tooltip(c.label, fmt(c.raw)) } } } },
    });
  }

  const fwF = gaps.footway_filter || {};
  if (fwF.kept != null) {
    new Chart(document.getElementById('c-fw-filter'), {
      type: 'doughnut',
      data: {
        labels: ['sidewalk', 'link', 'crossing', 'traffic_island', 'pedestrian', 'cycleway (foot)'],
        datasets: [{
          data: [
            fwF.kept_sidewalk || 0,
            fwF.kept_link || 0,
            fwF.kept_crossing || 0,
            fwF.kept_traffic_island || 0,
            fwF.kept_pedestrian || 0,
            fwF.kept_cycleway_foot || 0,
          ],
          backgroundColor: [C.green, C.purple, C.cyan, C.orange, C.blue, C.yellow],
          borderWidth: 0,
        }],
      },
      options: { ...dOpts, plugins: { ...dOpts.plugins, tooltip: { callbacks: { label: c => tooltip(c.label, fmt(c.raw)) } } } },
    });
  }
}
