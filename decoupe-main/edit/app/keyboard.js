import { shortcutFor, sideForValue } from "../shortcuts.js";
import { switchMode } from "../intent.js";

export function installKeyboard(ctx) {
  let pendingKeys = [];

  function runEditKey(action) {
    const d = ctx.state.detail;
    if (d.kind !== "way" || !d.editable) return;
    if (action.type === "value") {
      ctx.applyValue(sideForValue(d.choice), action.value);
    } else if (action.type === "mode" && !ctx.editBlocked()) {
      ctx.state.detail = { ...d, choice: switchMode(d.choice, action.mode) };
      ctx.renderDetail();
    }
  }

  function replayPendingKeys() {
    const keys = pendingKeys;
    pendingKeys = [];
    const wayId = ctx.state.detail.kind === "way" ? ctx.state.detail.way.id : null;
    for (const key of keys) {
      if (ctx.state.detail.kind !== "way" || ctx.state.detail.way.id !== wayId || ctx.editBlocked()) return;
      runEditKey(key);
    }
  }

  function clearPendingKeys() {
    pendingKeys = [];
  }

  document.addEventListener("keydown", (e) => {
    if (!ctx.active) return;
    const action = shortcutFor(e);
    if (!action) return;
    const d = ctx.state.detail;
    const editing = d.kind === "way" && d.editable;
    if ((action.type === "value" || action.type === "mode") && ctx.isWidening()) return;
    if ((action.type === "value" || action.type === "mode") && editing && d.fitting) {
      pendingKeys.push(action);
      return;
    }
    if (action.type === "next") {
      e.preventDefault();
      e.stopPropagation();
      ctx.selectNext();
    } else if (action.type === "deselect") {
      if (d.kind !== "none") ctx.deselect();
    } else if (action.type === "skip") {
      if (d.kind === "way") ctx.skipSelected();
    } else if ((action.type === "value" || action.type === "mode") && editing) {
      runEditKey(action);
    }
  }, true);

  Object.assign(ctx, { replayPendingKeys, clearPendingKeys });
}
