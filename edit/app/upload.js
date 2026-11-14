import { i18n } from "../../map/i18n.js";
import { store } from "../../map/store.js";
import { isLoggedIn, logout } from "../auth.js";
import { MAX_TAG_LENGTH, buildChangesetTags, hashtagsValue, normalizeHashtags, sourceValue, splitList, tooLongFields } from "../changeset.js";
import { APP_NAME, APP_VERSION } from "../env.js";
import { errorKind, errorMessage } from "../errors.js";
import { choiceFromIntent } from "../intent.js";
import { closeEmptyChangesets, planUpload, uploadGroups, zonesFor } from "../osm.js";
import { queueView, tooLongMessage } from "../panel.js";
import { composeComment, describeGroup, indexCommunes } from "../places.js";

export function installUpload(ctx) {
  const { env, osm, storage, queue, state } = ctx;
  const queueEl = ctx.el.queue;
  const pendingEl = ctx.el.pending;
  let communes = [];
  let refreshSelected = null;

  fetch(new URL("../../communes.geojson", import.meta.url))
    .then(res => (res.ok ? res.json() : null))
    .then((data) => {
      communes = indexCommunes(data);
      if (state.plan) renderQueue();
    })
    .catch(() => {});

  function hashtagList() {
    return normalizeHashtags(state.form.hashtags.split(/[\s;,]+/).filter(Boolean));
  }

  function commentFor(group) {
    return composeComment(describeGroup(group.entries, communes), { remark: state.form.remark, hashtags: hashtagList() });
  }

  function planComments() {
    return state.plan ? state.plan.groups.map(commentFor) : [];
  }

  function refreshCommentPreviews() {
    planComments().forEach((text, i) => {
      const el = queueEl.querySelector(`[data-comment-group="${i}"]`);
      if (el) el.textContent = text;
    });
  }

  function formIssues() {
    const f = state.form;
    return tooLongFields({
      source: sourceValue([...f.sources, ...splitList(f.sourceOther)]),
      hashtags: hashtagsValue(hashtagList()),
    });
  }

  function refreshFormChecks() {
    const issues = formIssues();
    for (const key of ["source", "hashtags"]) {
      const el = queueEl.querySelector(`[data-field-error="${key}"]`);
      const issue = issues.find(i => i.key === key);
      if (el) el.textContent = issue ? tooLongMessage(issue, i18n.t) : "";
    }
    const send = queueEl.querySelector('[data-edit-action="send"]');
    if (send) send.disabled = issues.length > 0 || !state.user || state.busy;
  }

  function renderPending() {
    const count = queue.size();
    pendingEl.hidden = count === 0;
    pendingEl.textContent = count ? i18n.t("edit.mode.pending", { count }) : "";
  }

  function renderQueue() {
    const items = queue.list();
    renderPending();
    queueEl.innerHTML = html`${queueView({
      items,
      zones: zonesFor(items, env),
      maxZones: env.maxChangesetsPerUpload,
      tooLong: formIssues(),
      form: state.form,
      plan: state.plan,
      comments: planComments(),
      result: state.result,
      busy: state.busy,
      loggedIn: Boolean(state.user),
    }, i18n, env.webUrl, { ...env, maxTagLength: MAX_TAG_LENGTH })}`;
  }

  function changesetTags(group, changesetsCount) {
    const f = state.form;
    return buildChangesetTags({
      comment: commentFor(group),
      sources: [...f.sources, ...splitList(f.sourceOther)],
      hashtags: hashtagList(),
      reviewRequested: f.review,
      locale: i18n.lang,
      host: `${window.location.origin}${window.location.pathname}`,
      imageryUsed: [...(store.imageryUsed || [])],
      changesetsCount,
    });
  }

  async function freshChangesetTags(group) {
    const me = await osm.getUser("me");
    const count = me && me.changesets ? Number(me.changesets.count) : NaN;
    if (state.user && Number.isFinite(count)) state.user.changesetsCount = count;
    return changesetTags(group, count);
  }

  function dropFromQueue(dropped) {
    queue.remove(dropped.map(d => d.intent.wayId));
  }

  async function preparePlan() {
    const plan = await planUpload(osm, queue.list(), env);
    dropFromQueue(plan.dropped);
    if (state.detail.kind === "way" && plan.dropped.some(d => d.intent.wayId === state.detail.way.id)) refreshSelected = state.detail.way.id;
    return { ...plan, max: env.maxChangesetsPerUpload };
  }

  async function withBusy(task) {
    state.busy = true;
    renderQueue();
    try {
      await task();
    } finally {
      state.busy = false;
      renderQueue();
      ctx.syncQueuedState();
      if (state.detail.kind === "way") ctx.renderDetail();
      if (refreshSelected !== null) {
        const id = refreshSelected;
        refreshSelected = null;
        ctx.selectWay(id);
      }
    }
  }

  function failure(err) {
    return i18n.t("edit.result.failed", { message: errorMessage(err, i18n.t) });
  }

  function endSessionIfRevoked(err) {
    if (errorKind(err) !== "auth") return false;
    logout({ osm, storage });
    ctx.refreshAuth(errorMessage(err, i18n.t));
    return true;
  }

  async function onPlan() {
    state.result = null;
    await withBusy(async () => {
      try {
        state.plan = await preparePlan();
      } catch (err) {
        state.plan = null;
        state.result = { done: [], error: failure(err) };
        endSessionIfRevoked(err);
      }
    });
  }

  function tagsErrorMessage(err) {
    if (err.message === "source-required") return i18n.t("edit.upload.sourceRequired");
    const issues = formIssues();
    if (issues.length) return issues.map(issue => tooLongMessage(issue, i18n.t)).join(" ");
    const tooLong = /^tag-too-long:(.+)$/.exec(err.message || "");
    if (tooLong) return tooLong[1].split(",").map(key => tooLongMessage({ key, max: MAX_TAG_LENGTH }, i18n.t)).join(" ");
    return failure(err);
  }

  async function onSend() {
    if (state.busy || !state.user || !state.plan) return;
    if (!isLoggedIn({ osm, storage, env })) {
      state.plan = null;
      await ctx.refreshAuth(i18n.t("edit.upload.loginFirst"));
      return;
    }
    try {
      if (formIssues().length) throw new Error("tag-too-long");
      state.plan.groups.forEach(group => changesetTags(group, 0));
    } catch (err) {
      state.result = { done: [], error: tagsErrorMessage(err) };
      return renderQueue();
    }
    const announced = state.plan.groups.length;
    await withBusy(async () => {
      try {
        const plan = await preparePlan();
        if (plan.tooMany || plan.groups.length !== announced || plan.dropped.length) {
          state.plan = plan;
          state.result = { done: [], error: i18n.t("edit.plan.changed") };
          return;
        }
        state.plan = plan;
        const outcome = await uploadGroups({ osm, groups: plan.groups, tagsFor: freshChangesetTags, settings: env });
        queue.remove(outcome.done.flatMap(d => d.wayIds));
        dropFromQueue(outcome.dropped);
        const result = { done: outcome.done, failed: outcome.failed, conflictWayIds: [], closed: [], dropped: outcome.dropped, retried: outcome.retried };
        if (outcome.failed) {
          const err = { cause: outcome.failed.status, message: outcome.failed.message };
          result.failed = { ...outcome.failed, message: errorMessage(err, i18n.t) };
          result.conflictWayIds = outcome.failed.conflictWayIds || [];
          if (result.conflictWayIds.length) queue.remove(result.conflictWayIds);
          if (endSessionIfRevoked(err)) result.closed = [];
        }
        if ((outcome.failed && errorKind({ cause: outcome.failed.status }) !== "auth") || outcome.retried) {
          try {
            result.closed = await closeEmptyChangesets({ osm, uid: state.user.uid, createdBy: `${APP_NAME} ${APP_VERSION}` });
          } catch {}
        }
        state.plan = null;
        state.result = result;
        ctx.scheduleCandidates();
        const touched = new Set([...outcome.done.flatMap(d => d.wayIds), ...outcome.dropped.map(d => d.intent.wayId), ...result.conflictWayIds]);
        if (state.detail.kind === "way" && touched.has(state.detail.way.id)) refreshSelected = state.detail.way.id;
      } catch (err) {
        state.result = { done: [], error: failure(err) };
        endSessionIfRevoked(err);
      }
    });
  }

  function discardQueue() {
    queue.clear();
    state.plan = null;
    state.result = null;
    if (state.detail.kind === "way") state.detail = { ...state.detail, queued: null, choice: choiceFromIntent(null) };
    renderQueue();
    ctx.syncQueuedState();
  }

  queueEl.addEventListener("input", (e) => {
    const el = e.target;
    const f = state.form;
    if (el.name === "cs-remark") f.remark = el.value;
    else if (el.name === "cs-source-other") f.sourceOther = el.value;
    else if (el.name === "cs-hashtags") f.hashtags = el.value;
    else if (el.name === "cs-review") f.review = el.checked;
    else if (el.name === "cs-source") {
      f.sources = el.checked ? [...new Set([...f.sources, el.value])] : f.sources.filter(v => v !== el.value);
    }
    if (el.name === "cs-remark" || el.name === "cs-hashtags") refreshCommentPreviews();
    refreshFormChecks();
  });

  queueEl.addEventListener("click", async (e) => {
    const button = e.target.closest("[data-edit-action]");
    if (!button) return;
    const action = button.dataset.editAction;
    if (action === "dequeue") {
      queue.remove(Number(button.dataset.wayId));
      state.plan = null;
    } else if (action === "undo") {
      queue.undo();
      state.plan = null;
    } else if (action === "plan") {
      return onPlan();
    } else if (action === "send") {
      return onSend();
    } else {
      return;
    }
    if (state.detail.kind === "way") {
      const queued = queue.get(state.detail.way.id);
      state.detail = { ...state.detail, queued, choice: queued ? choiceFromIntent(queued) : state.detail.choice };
    }
    ctx.renderDetail();
    renderQueue();
    ctx.syncQueuedState();
  });

  Object.assign(ctx, { renderQueue, onPlan, discardQueue });
}
