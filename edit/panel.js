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
      <button type="button" class="header-btn" data-edit-action="logout">${t("edit.auth.logout")}</button>
    `;
  }
  if (state.kind === "waiting") {
    return html`
      <p class="edit-note">${t("edit.auth.waiting")}</p>
      <button type="button" class="header-btn" data-edit-action="login">${t("edit.auth.retry")}</button>
    `;
  }
  return html`
    ${state.message && html`<p class="edit-note">${state.message}</p>`}
    <button type="button" class="header-btn" data-edit-action="login"${state.kind === "pending" ? html` disabled` : ""}>
      ${state.kind === "pending" ? t("edit.auth.pending") : t("edit.auth.login")}
    </button>
  `;
}

export function statusView(state, i18n) {
  const { t } = i18n;
  if (state.kind === "zoom") return t("edit.status.zoomIn", { zoom: state.minZoom });
  if (state.kind === "tooBig") return t("edit.error.tooBig");
  if (state.kind === "loading") return t("edit.status.loading");
  if (state.kind === "error") return t("edit.status.error", { message: state.message || "" });
  if (state.kind === "ready") return t("edit.status.candidates", { count: state.count });
  return "";
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

function chips(side, selected, i18n) {
  const { t } = i18n;
  return html`
    <div class="edit-chips" role="group">
      ${SIDE_VALUES.map(v => html`<button type="button" class="edit-chip${v === selected ? " active" : ""}" data-edit-action="choose" data-side="${side}" data-value="${v}" aria-pressed="${v === selected ? "true" : "false"}" title="${valueLabel(v, t)}">${v}</button>`)}
    </div>
  `;
}

export function tagSummary(set) {
  return Object.entries(set).map(([k, v]) => `${k}=${v}`).join(" · ");
}

export function editFormView(state, i18n, settings = {}) {
  const { t } = i18n;
  const choice = state.choice || { mode: "both", both: "", left: "", right: "" };
  const sides = choice.mode === "sides";
  const complete = sides ? Boolean(choice.left && choice.right) : Boolean(choice.both);
  return html`
    <div class="edit-form">
      ${state.longWay && html`<p class="edit-warn">${t("edit.form.longWay", { length: Math.round(state.lengthM) })}</p>`}
      ${sides
        ? html`
          <p class="edit-help">${t("edit.form.direction")}</p>
          <div class="edit-side edit-side-left"><span class="edit-swatch"></span>${t("edit.form.left")}</div>
          ${chips("left", choice.left, i18n)}
          <div class="edit-side edit-side-right"><span class="edit-swatch"></span>${t("edit.form.right")}</div>
          ${chips("right", choice.right, i18n)}
          <button type="button" class="edit-link" data-edit-action="mode" data-mode="both">${t("edit.form.sameSides")}</button>`
        : html`
          <div class="edit-side">${t("edit.form.both")}</div>
          ${chips("both", choice.both, i18n)}
          <button type="button" class="edit-link" data-edit-action="mode" data-mode="sides">${t("edit.form.differentSides")}</button>`}
      ${!settings.autoQueue && html`
        <button type="button" class="header-btn" data-edit-action="queue"${complete ? "" : html` disabled`}>${state.queued ? t("edit.form.update") : t("edit.form.add")}</button>`}
      ${state.queued && html`
        <p class="edit-ok edit-queued">${t("edit.form.queued", { tags: tagSummary(state.queued.set) })}
          <button type="button" class="edit-link" data-edit-action="unqueue">${t("edit.form.unqueue")}</button></p>`}
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
  return html`
    <div class="edit-result">
      ${ids.length > 0 && html`<p class="edit-ok">${t("edit.result.sent", { count: ids.length })}
        ${ids.map((id, i) => html`${i > 0 ? " · " : " "}<a href="${`${webUrl}/changeset/${id}`}" target="_blank" rel="noopener">${id}</a>`)}</p>`}
      ${result.retried > 0 && html`<p class="edit-help">${t("edit.result.retried", { count: result.retried })}</p>`}
      ${(result.dropped || []).map(d => html`<p class="edit-note">${wayLabel(d.intent)} : ${dropReason(d, t)}</p>`)}
      ${result.conflictWayId && html`<p class="edit-note">${t("edit.result.conflict", { way: `w${result.conflictWayId}` })}</p>`}
      ${result.failed && !result.conflictWayId && html`<p class="edit-note">${t("edit.result.failed", { message: result.failed.message })}</p>`}
      ${result.closed && result.closed.length > 0 && html`<p class="edit-help">${t("edit.result.closedEmpty", { count: result.closed.length })}</p>`}
      ${result.error && html`<p class="edit-note">${result.error}</p>`}
    </div>
  `;
}

function uploadFormView(state, i18n, settings) {
  const { t } = i18n;
  const f = state.form;
  const blocked = !state.loggedIn || state.busy;
  return html`
    <div class="edit-upload">
      <label class="edit-field">${t("edit.upload.remark")}
        <input type="text" name="cs-remark" maxlength="120" value="${f.remark}" placeholder="${t("edit.upload.remarkPlaceholder")}">
      </label>
      <p class="edit-help">${t("edit.upload.commentHelp")}</p>
      <fieldset class="edit-field">
        <legend>${t("edit.upload.source")}</legend>
        ${settings.sourcePresets.map(v => html`<label class="edit-check"><input type="checkbox" name="cs-source" value="${v}"${f.sources.includes(v) ? html` checked` : ""}> ${v}</label>`)}
        <input type="text" name="cs-source-other" value="${f.sourceOther}" placeholder="${t("edit.upload.sourceOther")}">
      </fieldset>
      <label class="edit-field">${t("edit.upload.hashtags")}
        <input type="text" name="cs-hashtags" value="${f.hashtags}">
      </label>
      <label class="edit-check"><input type="checkbox" name="cs-review"${f.review ? html` checked` : ""}> ${t("edit.upload.review")}</label>
      ${!state.loggedIn && html`<p class="edit-help">${t("edit.upload.loginFirst")}</p>`}
      <div class="edit-actions">
        <button type="button" class="header-btn" data-edit-action="plan"${state.busy ? html` disabled` : ""}>${t("edit.upload.prepare")}</button>
        ${state.plan && !state.plan.tooMany && state.plan.groups.length > 0 && html`
          <button type="button" class="header-btn edit-send" data-edit-action="send"${blocked ? html` disabled` : ""}>${t("edit.upload.send", { count: state.plan.groups.length })}</button>`}
      </div>
    </div>
  `;
}

export function queueView(state, i18n, webUrl, settings) {
  const { t } = i18n;
  const items = state.items;
  return html`
    <h3>${t("edit.queue.title", { count: items.length })}</h3>
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
