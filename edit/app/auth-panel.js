import { i18n } from "../../map/i18n.js";
import { isLoggedIn, login, loginInProgress, logout } from "../auth.js";
import { authView } from "../panel.js";

export function installAuthPanel(ctx) {
  const { env, osm, storage, tab, state } = ctx;
  const authEl = ctx.el.auth;

  function showAuth(view) {
    authEl.innerHTML = html`${authView(view, i18n)}`;
  }

  async function refreshAuth(message) {
    state.user = null;
    if (!env.editEnabled) showAuth({ kind: "disabled" });
    else if (!env.clientId) showAuth({ kind: "unconfigured" });
    else if (!isLoggedIn({ osm, storage, env })) {
      const pending = loginInProgress({ storage, now: Date.now(), ttlMs: env.authPendingTtlMs, tab });
      showAuth({ kind: pending ? "pending" : "anonymous", message });
    } else {
      try {
        const me = await osm.getUser("me");
        state.user = { uid: me.id, name: me.display_name, changesetsCount: me.changesets && me.changesets.count };
        showAuth({ kind: "logged", name: me.display_name });
      } catch {
        logout({ osm, storage });
        showAuth({ kind: "anonymous", message: i18n.t("edit.auth.expired") });
      }
    }
    ctx.renderQueue();
  }

  authEl.addEventListener("click", async (e) => {
    const action = e.target.closest("[data-edit-action]")?.dataset.editAction;
    if (action === "logout") {
      logout({ osm, storage });
      return refreshAuth();
    }
    if (action !== "login") return;
    showAuth({ kind: "waiting" });
    try {
      await login({ osm, storage, env, tab });
      await refreshAuth();
    } catch (err) {
      const message = err && err.message === "login-pending" ? i18n.t("edit.auth.pending") : i18n.t("edit.auth.failed");
      await refreshAuth(message);
    }
  });

  Object.assign(ctx, { refreshAuth });
}
