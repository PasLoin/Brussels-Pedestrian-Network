function osmLink(webUrl, type, id) {
  return html`<a href="${`${webUrl}/${type}/${id}`}" target="_blank" rel="noopener">${type === "way" ? "w" : "n"}${id}</a>`;
}

export function authView(state, i18n) {
  const { t } = i18n;
  if (state.kind === "disabled") return html`<p class="edit-note">${t("edit.auth.disabled")}</p>`;
  if (state.kind === "unconfigured") return html`<p class="edit-note">${t("edit.auth.unconfigured")}</p>`;
  if (state.kind === "logged") {
    return html`
      <p>${t("edit.auth.loggedAs", { name: state.name || "?" })}</p>
      <button type="button" class="btn" data-edit-action="logout">${t("edit.auth.logout")}</button>
    `;
  }
  if (state.kind === "waiting") {
    return html`
      <p class="edit-note">${t("edit.auth.waiting")}</p>
      <button type="button" class="btn" data-edit-action="login">${t("edit.auth.retry")}</button>
    `;
  }
  return html`
    ${state.message && html`<p class="edit-note">${state.message}</p>`}
    <button type="button" class="btn" data-edit-action="login"${state.kind === "pending" ? html` disabled` : ""}>
      ${state.kind === "pending" ? t("edit.auth.pending") : t("edit.auth.login")}
    </button>
  `;
}

export function statusView(state, i18n) {
  const { t } = i18n;
  if (state.kind === "zoom" && state.kept > 0) return t("edit.status.zoomKept", { zoom: state.minZoom, count: state.kept });
  if (state.kind === "zoom") return t("edit.status.zoomIn", { zoom: state.minZoom });
  if (state.kind === "tooBig") return t("edit.error.tooBig");
  if (state.kind === "loading") return t("edit.status.loading");
  if (state.kind === "error") return t("edit.status.error", { message: state.message || "" });
  if (state.kind === "ready") return t("edit.status.candidates", { count: state.count });
  if (state.kind === "noMatch") return t("edit.status.noMatch");
  if (state.kind === "splitOnDev") return t("edit.status.splitOnDev", { count: state.count });
  return "";
}

const METER_KINDS = ["map", "wayFull", "way", "ways", "nodes", "changesetCreate", "upload", "changesetClose", "changesets", "user", "oauth", "other"];
const METER_PATHS = {
  map: "map", wayFull: "way/…/full", way: "way/…", ways: "ways", nodes: "nodes", changesetCreate: "changeset/create",
  upload: "changeset/…/upload", changesetClose: "changeset/…/close", changesets: "changesets", user: "user/details", oauth: "oauth2/token", other: "…",
};

export function meterView(stats, i18n, settings = {}) {
  const { t } = i18n;
  if (!stats) return "";
  const warnMinute = stats.lastMinute > (settings.apiMeterWarnPerMinute || 30);
  const warnFlight = stats.peakInFlight > 2;
  const statuses = Object.entries(stats.byStatus);
  return html`<details class="edit-meter">
    <summary class="${warnMinute || warnFlight ? "edit-warn" : ""}">${t("edit.meter.summary", { total: stats.total, minute: stats.lastMinute })}</summary>
    <table class="edit-tags">
      ${METER_KINDS.filter(k => stats.byKind[k]).map(k => html`<tr><th><code>${METER_PATHS[k]}</code></th><td>${stats.byKind[k]}</td></tr>`)}
    </table>
    <p>${t("edit.meter.peakMinute", { count: stats.peakPerMinute })}</p>
    <p class="${warnFlight ? "edit-warn" : ""}">${t("edit.meter.peakInFlight", { count: stats.peakInFlight })}</p>
    <p>${t("edit.meter.peakWaiting", { count: stats.peakWaiting || 0 })}</p>
    ${warnFlight && html`<p class="edit-help">${t("edit.meter.warnInFlight")}</p>`}
    ${warnMinute && html`<p class="edit-help">${t("edit.meter.warnMinute", { count: settings.apiMeterWarnPerMinute || 30 })}</p>`}
    ${statuses.length > 0 && html`<p>${t("edit.meter.failures", { list: statuses.map(([code, n]) => `${code} × ${n}`).join(", ") })}</p>`}
    <p class="edit-help">${t("edit.meter.since", { date: i18n.date(stats.since, { dateStyle: "short", timeStyle: "short" }) })}</p>
    <button type="button" class="edit-link" data-edit-action="meter-reset">${t("edit.meter.reset")}</button>
  </details>`;
}

const SIDE_VALUES = ["separate", "yes", "no"];

function valueLabel(value, t) {
  if (value === "separate") return t("edit.value.separate");
  if (value === "yes") return t("edit.value.yes");
  return t("edit.value.no");
}

function dropReason(drop, t) {
  const reason = drop.reason;
  if (reason === "deleted") return t("edit.plan.deleted");
  if (reason === "node_moved") return t("edit.plan.nodeMoved", { distance: Math.round(drop.shiftM) });
  if (reason === "already_fixed") return t("edit.plan.alreadyFixed");
  if (reason === "geometry_changed") return t("edit.plan.geometryChanged");
  return t("edit.plan.modifiedMeanwhile");
}

function chips(side, selected, i18n, locked = false) {
  const { t } = i18n;
  return html`
    <div class="edit-chips" role="group">
      ${SIDE_VALUES.map(v => html`<button type="button" class="edit-chip${v === selected ? " active" : ""}" data-edit-action="choose" data-side="${side}" data-value="${v}" aria-pressed="${v === selected ? "true" : "false"}" title="${valueLabel(v, t)}"${locked ? html` disabled` : ""}><u>${v[0]}</u>${v.slice(1)}</button>`)}
    </div>
  `;
}

export function editLock(state) {
  if (state.fitting) return "moving";
  if (state.basemapOk === false) return "basemap";
  if (state.seenWhole === false) return "hidden";
  if (state.review && !state.review.done) return "detail";
  if (state.paceLeftMs > 0 && !state.queued) return "pace";
  if (state.lookLeftMs > 0 && !state.queued && state.lookMode === "block") return "look";
  if (state.room && !state.room.fits && !state.queued) return "full";
  return null;
}

function lockView(lock, state, i18n) {
  const { t } = i18n;
  if (lock === "moving") return html`<p class="edit-help" role="status">${t("edit.form.fitting")}</p>`;
  if (lock === "basemap") {
    return html`<div class="edit-lock" role="status">
      <p class="edit-warn">${t("edit.form.needOrtho")}</p>
      <button type="button" class="btn" data-edit-action="basemap">${t("edit.form.showOrtho")}</button>
    </div>`;
  }
  if (lock === "pace") {
    return html`<div class="edit-lock" role="status">
      <p class="edit-warn">${t("edit.form.paceCooldown", { count: Math.ceil(state.paceLeftMs / 1000) })}</p>
    </div>`;
  }
  if (lock === "look") {
    return html`<p class="edit-help edit-look" role="status">${t("edit.form.lookTime", { count: Math.ceil(state.lookLeftMs / 1000) })}</p>`;
  }
  if (lock === "hidden") {
    return html`<div class="edit-lock" role="status">
      <p class="edit-warn">${t("edit.form.notVisible")}</p>
      <button type="button" class="btn" data-edit-action="fit">${t("edit.form.showWhole")}</button>
    </div>`;
  }
  if (lock === "detail") {
    return html`<div class="edit-lock" role="status">
      <p class="edit-warn">${t("edit.form.reviewDetail", { zoom: i18n.number(state.review.zoom, { maximumFractionDigits: 1 }), percent: state.review.percent })}</p>
      <progress class="edit-progress" max="100" value="${state.review.percent}"></progress>
      <button type="button" class="btn" data-edit-action="review-next">${t("edit.form.reviewNext")}</button>
    </div>`;
  }
  if (lock === "full") {
    return html`<div class="edit-lock" role="status">
      <p class="edit-warn">${t("edit.form.queueFull", { count: state.room.after, max: state.room.max })}</p>
      <button type="button" class="btn" data-edit-action="plan">${t("edit.upload.prepare")}</button>
    </div>`;
  }
  return "";
}

export function tagSummary(set) {
  return Object.entries(set).map(([k, v]) => `${k}=${v}`).join(" · ");
}

export function editFormView(state, i18n, settings = {}) {
  const { t } = i18n;
  const choice = state.choice || { mode: "both", both: "", left: "", right: "" };
  const sides = choice.mode === "sides";
  const complete = sides ? Boolean(choice.left && choice.right) : Boolean(choice.both);
  const lock = editLock(state);
  const locked = Boolean(lock);
  return html`
    <div class="edit-form${locked ? " locked" : ""}">
      ${lockView(lock, state, i18n)}
      ${state.lookLeftMs > 0 && !state.queued && state.lookMode !== "block" && state.lookHasty && !lock && html`<p class="edit-help edit-look" role="status">${t("edit.form.lookTime", { count: Math.ceil(state.lookLeftMs / 1000) })}</p>`}
      ${state.tooFast && !lock && html`<p class="edit-warn" role="alert">${t("edit.form.tooFast")}</p>`}
      ${sides
        ? html`
          <p class="edit-help">${t("edit.form.direction")}</p>
          <div class="edit-side edit-side-left"><span class="edit-swatch"></span>${t("edit.form.left")}</div>
          ${chips("left", choice.left, i18n, locked)}
          <div class="edit-side edit-side-right"><span class="edit-swatch"></span>${t("edit.form.right")}</div>
          ${chips("right", choice.right, i18n, locked)}
          <button type="button" class="edit-link" data-edit-action="mode" data-mode="both">${t("edit.form.sameSides")} <kbd>b</kbd></button>`
        : html`
          <div class="edit-side">${t("edit.form.both")}</div>
          ${chips("both", choice.both, i18n, locked)}
          <button type="button" class="edit-link" data-edit-action="mode" data-mode="sides">${t("edit.form.differentSides")} <kbd>d</kbd></button>`}
      ${!settings.autoQueue && html`
        <button type="button" class="btn" data-edit-action="queue"${complete && !locked ? "" : html` disabled`}>${state.queued ? t("edit.form.update") : t("edit.form.add")}</button>`}
      ${state.queued && html`
        <p class="edit-ok edit-queued">${t("edit.form.queued", { tags: tagSummary(state.queued.set) })}
          <button type="button" class="edit-link" data-edit-action="unqueue">${t("edit.form.unqueue")}</button></p>`}
      <div class="edit-step">
        <button type="button" class="edit-link" data-edit-action="skip">${t("edit.form.skip")} <kbd>p</kbd></button>
        <button type="button" class="edit-link" data-edit-action="next">${t("edit.form.next")} <kbd>→</kbd></button>
      </div>
      <details class="edit-shortcuts"><summary>${t("edit.form.shortcutsTitle")}</summary><p class="edit-help">${t("edit.form.shortcuts")}</p></details>
    </div>
  `;
}

export function navView(state, i18n) {
  const { t } = i18n;
  return html`
    <div class="edit-nav">
      ${state.candidates > 0 && !state.selected && html`<button type="button" class="edit-link" data-edit-action="next">${t("edit.nav.next")} <kbd>→</kbd></button>`}
      ${state.skipped > 0 && html`<span class="edit-help">${t("edit.nav.skipped", { count: state.skipped })}
        <button type="button" class="edit-link" data-edit-action="reset-skipped">${t("edit.nav.resetSkipped")}</button></span>`}
      ${state.hint && html`<p class="edit-help">${state.hint}</p>`}
    </div>
  `;
}

export function detailView(state, i18n, webUrl, settings = {}) {
  const { t } = i18n;
  if (!state || state.kind === "none") return html``;
  if (state.kind === "loading") return html`<p>${t("edit.detail.loading")}</p>`;
  if (state.kind === "gone") return html`<p class="edit-note">${t("edit.detail.gone", { way: `w${state.wayId}` })}</p>`;
  if (state.kind === "error") return html`<p class="edit-note">${t("edit.detail.error", { message: state.message || "" })}</p>`;
  const way = state.way;
  const tags = Object.entries(way.tags || {}).sort(([a], [b]) => a.localeCompare(b));
  return html`
    <div class="edit-way">
      <div class="edit-row"><span class="label">${t("popup.label.way")}</span><span class="value">${osmLink(webUrl, "way", way.id)}</span></div>
      <div class="edit-row"><span class="label">${t("edit.detail.version")}</span><span class="value">${way.version}</span></div>
      <div class="edit-row"><span class="label">${t("edit.detail.lastEdit")}</span><span class="value">${way.user || "?"} · ${way.timestamp ? i18n.date(way.timestamp, { dateStyle: "short", timeStyle: "short" }) : "?"}</span></div>
      <p class="${state.editable ? "edit-ok" : "edit-note"}">${state.editable ? t("edit.detail.editable") : t("edit.detail.alreadyFixed")}</p>
      ${state.editable && editFormView(state, i18n, settings)}
      <table class="edit-tags">
        <tbody>${tags.map(([k, v]) => html`<tr><th scope="row">${k}</th><td>${v}</td></tr>`)}</tbody>
      </table>
    </div>
  `;
}

function wayLabel(intent) {
  return intent.name ? `${intent.name} (w${intent.wayId})` : `w${intent.wayId}`;
}

function planView(plan, comments, i18n) {
  const { t } = i18n;
  if (!plan) return "";
  return html`
    <div class="edit-plan">
      ${plan.dropped.map(d => html`<p class="edit-note">${wayLabel(d.intent)} : ${dropReason(d, t)}</p>`)}
      ${plan.tooMany
        ? html`<p class="edit-note">${t("edit.plan.tooMany", { count: plan.groups.length, max: plan.max })}</p>`
        : plan.groups.length > 0 && html`<p>${t("edit.plan.changesets", { count: plan.groups.length, ways: plan.ready.length })}</p>
          <ol class="edit-comments">
            ${(comments || []).map((text, i) => html`<li><span class="edit-help">${t("edit.plan.comment", { n: i + 1 })}</span><br><span data-comment-group="${i}">${text}</span></li>`)}
          </ol>`}
    </div>
  `;
}

function resultView(result, i18n, webUrl) {
  const { t } = i18n;
  if (!result) return "";
  const ids = result.done.flatMap(d => d.changesetIds);
  const conflicts = result.conflictWayIds || [];
  return html`
    <div class="edit-result">
      ${ids.length > 0 && html`<p class="edit-ok">${t("edit.result.sent", { count: ids.length })}
        ${ids.map((id, i) => html`${i > 0 ? " · " : " "}<a href="${`${webUrl}/changeset/${id}`}" target="_blank" rel="noopener">${id}</a>`)}</p>`}
      ${result.retried > 0 && html`<p class="edit-help">${t("edit.result.retried", { count: result.retried })}</p>`}
      ${(result.dropped || []).map(d => html`<p class="edit-note">${wayLabel(d.intent)} : ${dropReason(d, t)}</p>`)}
      ${conflicts.length > 0 && html`<p class="edit-note">${t("edit.result.conflict", { count: conflicts.length, way: conflicts.map(id => `w${id}`).join(", ") })}</p>`}
      ${result.failed && !conflicts.length && html`<p class="edit-note">${t("edit.result.failed", { message: result.failed.message })}</p>`}
      ${result.closed && result.closed.length > 0 && html`<p class="edit-help">${t("edit.result.closedEmpty", { count: result.closed.length })}</p>`}
      ${result.error && html`<p class="edit-note">${result.error}</p>`}
    </div>
  `;
}

export function tooLongMessage(issue, t) {
  if (issue.key === "source") return t("edit.upload.sourceTooLong", { length: issue.length, max: issue.max });
  if (issue.key === "hashtags") return t("edit.upload.hashtagsTooLong", { length: issue.length, max: issue.max });
  return t("edit.upload.tagTooLong", { key: issue.key, max: issue.max });
}

function fieldError(key, issues, t) {
  const issue = (issues || []).find(i => i.key === key);
  return html`<p class="edit-note" data-field-error="${key}" aria-live="polite">${issue ? tooLongMessage(issue, t) : ""}</p>`;
}

function uploadFormView(state, i18n, settings) {
  const { t } = i18n;
  const f = state.form;
  const invalid = (state.tooLong || []).length > 0;
  const blocked = !state.loggedIn || state.busy || invalid;
  return html`
    <div class="edit-upload">
      <label class="edit-field">${t("edit.upload.remark")}
        <input type="text" name="cs-remark" maxlength="120" value="${f.remark}" placeholder="${t("edit.upload.remarkPlaceholder")}">
      </label>
      <p class="edit-help">${t("edit.upload.commentHelp")}</p>
      <fieldset class="edit-field">
        <legend>${t("edit.upload.source")}</legend>
        ${settings.sourcePresets.map(v => html`<label class="edit-check"><input type="checkbox" name="cs-source" value="${v}"${f.sources.includes(v) ? html` checked` : ""}> ${v}</label>`)}
        <input type="text" name="cs-source-other" maxlength="${settings.maxTagLength || 255}" value="${f.sourceOther}" placeholder="${t("edit.upload.sourceOther")}">
        ${fieldError("source", state.tooLong, t)}
      </fieldset>
      <label class="edit-field">${t("edit.upload.hashtags")}
        <input type="text" name="cs-hashtags" maxlength="${settings.maxTagLength || 255}" value="${f.hashtags}">
      </label>
      ${fieldError("hashtags", state.tooLong, t)}
      <label class="edit-check"><input type="checkbox" name="cs-review"${f.review ? html` checked` : ""}> ${t("edit.upload.review")}</label>
      ${!state.loggedIn && html`<p class="edit-help">${t("edit.upload.loginFirst")}</p>`}
      <div class="edit-actions">
        <button type="button" class="btn" data-edit-action="plan"${state.busy ? html` disabled` : ""}>${t("edit.upload.prepare")}</button>
        ${state.plan && !state.plan.tooMany && state.plan.groups.length > 0 && html`
          <button type="button" class="btn btn-primary edit-send" data-edit-action="send"${blocked ? html` disabled` : ""}>${t("edit.upload.send", { count: state.plan.groups.length })}</button>`}
      </div>
    </div>
  `;
}

function zonesView(state, i18n) {
  const { t } = i18n;
  if (!state.items.length || !Number.isFinite(state.zones) || !Number.isFinite(state.maxZones)) return "";
  const full = state.zones >= state.maxZones;
  return html`<p class="${full ? "edit-warn" : "edit-help"}" data-queue-zones>${t("edit.queue.zones", { count: state.zones, max: state.maxZones })}${full ? html` ${t("edit.queue.full")}` : ""}</p>`;
}

export function queueView(state, i18n, webUrl, settings) {
  const { t } = i18n;
  const items = state.items;
  return html`
    <h3>${t("edit.queue.title", { count: items.length })}</h3>
    ${zonesView(state, i18n)}
    ${items.length === 0 && html`<p class="edit-help">${t("edit.queue.empty")}</p>`}
    ${items.length > 0 && html`
      <ul class="edit-queue">
        ${items.map(i => html`<li>
          <span><strong>${wayLabel(i)}</strong><br><span class="edit-help">${tagSummary(i.set)}</span></span>
          <button type="button" class="edit-link" data-edit-action="dequeue" data-way-id="${i.wayId}">${t("edit.queue.remove")}</button>
        </li>`)}
      </ul>
      <button type="button" class="edit-link" data-edit-action="undo">${t("edit.queue.undo")}</button>
      ${uploadFormView(state, i18n, settings)}
    `}
    ${state.busy && html`<p class="edit-help">${t("edit.upload.busy")}</p>`}
    ${planView(state.plan, state.comments, i18n)}
    ${resultView(state.result, i18n, webUrl)}
  `;
}

function devDataError(state, t) {
  if (state.error === "notOsm") return t("edit.data.errorNotOsm");
  if (state.error === "unsaved") return t("edit.data.errorUnsaved");
  if (state.error === "empty") return t("edit.data.errorEmpty");
  if (state.error === "tooBig") return t("edit.data.errorTooBig", { size: state.size || 0 });
  return t("edit.data.errorRead");
}

export function devDataView(state, i18n) {
  const { t } = i18n;
  return html`<section class="edit-data" aria-labelledby="edit-data-title">
    <h3 id="edit-data-title">${t("edit.data.title")}</h3>
    ${state.active
      ? html`<p class="edit-ok">${t("edit.data.active", { count: state.active.count, name: state.active.name })}</p>
        ${state.active.latest && html`<p class="edit-help">${t("edit.data.latest", { date: i18n.date(state.active.latest, { dateStyle: "short", timeStyle: "short" }) })}</p>`}`
      : html`<p class="edit-help">${t("edit.data.help")}</p>`}
    ${state.loading && html`<p role="status">${t("edit.data.loading", { name: state.loading })}</p>`}
    ${state.error && html`<p class="edit-warn" role="alert">${devDataError(state, t)}</p>`}
    <div class="edit-actions">
      <button type="button" class="btn" data-edit-action="data-load"${state.loading ? html` disabled` : ""}>${state.active ? t("edit.data.replace") : t("edit.data.load")}</button>
      ${state.active && html`<button type="button" class="edit-link" data-edit-action="data-reset">${t("edit.data.reset")}</button>`}
    </div>
  </section>`;
}
