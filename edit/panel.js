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

function dropReason(reason, t) {
  if (reason === "deleted") return t("edit.plan.deleted");
  if (reason === "already_fixed") return t("edit.plan.alreadyFixed");
  return t("edit.plan.modifiedMeanwhile");
}

function sideSelect(name, label, selected, i18n) {
  const { t } = i18n;
  return html`
    <label class="edit-side edit-side-${name}">
      <span class="edit-swatch"></span>${label}
      <select name="sw-${name}">
        <option value=""${selected ? "" : html` selected`}>${t("edit.form.choose")}</option>
        ${SIDE_VALUES.map(v => html`<option value="${v}"${v === selected ? html` selected` : ""}>${valueLabel(v, t)}</option>`)}
      </select>
    </label>
  `;
}

function sidesOf(intent) {
  if (!intent) return { left: "", right: "" };
  if (intent.set["sidewalk:both"]) return { left: intent.set["sidewalk:both"], right: intent.set["sidewalk:both"] };
  return { left: intent.set["sidewalk:left"] || "", right: intent.set["sidewalk:right"] || "" };
}

export function tagSummary(set) {
  return Object.entries(set).map(([k, v]) => `${k}=${v}`).join(" · ");
}

export function editFormView(state, i18n) {
  const { t } = i18n;
  const { left, right } = sidesOf(state.queued);
  return html`
    <div class="edit-form">
      ${state.longWay && html`<p class="edit-warn">${t("edit.form.longWay", { length: Math.round(state.lengthM) })}</p>`}
      <p class="edit-help">${t("edit.form.direction")}</p>
      ${sideSelect("left", t("edit.form.left"), left, i18n)}
      ${sideSelect("right", t("edit.form.right"), right, i18n)}
      ${state.formError && html`<p class="edit-note">${state.formError}</p>`}
      <button type="button" class="header-btn" data-edit-action="queue">${state.queued ? t("edit.form.update") : t("edit.form.add")}</button>
    </div>
  `;
}

export function detailView(state, i18n, webUrl) {
  const { t } = i18n;
  if (!state || state.kind === "none") return html``;
  if (state.kind === "loading") return html`<p>${t("edit.detail.loading")}</p>`;
  if (state.kind === "error") return html`<p class="edit-note">${t("edit.detail.error", { message: state.message || "" })}</p>`;
  const way = state.way;
  const tags = Object.entries(way.tags || {}).sort(([a], [b]) => a.localeCompare(b));
  return html`
    <div class="edit-way">
      <div class="edit-row"><span class="label">${t("popup.label.way")}</span><span class="value">${osmLink(webUrl, "way", way.id)}</span></div>
      <div class="edit-row"><span class="label">${t("edit.detail.version")}</span><span class="value">${way.version}</span></div>
      <div class="edit-row"><span class="label">${t("edit.detail.lastEdit")}</span><span class="value">${way.user || "?"} · ${way.timestamp ? i18n.date(way.timestamp, { dateStyle: "short", timeStyle: "short" }) : "?"}</span></div>
      <p class="${state.editable ? "edit-ok" : "edit-note"}">${state.editable ? t("edit.detail.editable") : t("edit.detail.alreadyFixed")}</p>
      ${state.editable && editFormView(state, i18n)}
      <table class="edit-tags">
        <tbody>${tags.map(([k, v]) => html`<tr><th scope="row">${k}</th><td>${v}</td></tr>`)}</tbody>
      </table>
    </div>
  `;
}

function wayLabel(intent) {
  return intent.name ? `${intent.name} (w${intent.wayId})` : `w${intent.wayId}`;
}

function planView(plan, i18n) {
  const { t } = i18n;
  if (!plan) return "";
  return html`
    <div class="edit-plan">
      ${plan.dropped.map(d => html`<p class="edit-note">${wayLabel(d.intent)} : ${dropReason(d.reason, t)}</p>`)}
      ${plan.tooMany
        ? html`<p class="edit-note">${t("edit.plan.tooMany", { count: plan.groups.length, max: plan.max })}</p>`
        : plan.groups.length > 0 && html`<p>${t("edit.plan.changesets", { count: plan.groups.length, ways: plan.ready.length })}</p>`}
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
      <label class="edit-field">${t("edit.upload.comment")}
        <textarea name="cs-comment" rows="2" maxlength="200">${f.comment}</textarea>
      </label>
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
    ${planView(state.plan, i18n)}
    ${resultView(state.result, i18n, webUrl)}
  `;
}
