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
      <table class="edit-tags">
        <tbody>${tags.map(([k, v]) => html`<tr><th scope="row">${k}</th><td>${v}</td></tr>`)}</tbody>
      </table>
    </div>
  `;
}
