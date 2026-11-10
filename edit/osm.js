import { mergeBbox, spanM } from "./geo.js";
import { applyIntent, geometryUnchanged, preconditionsHold } from "./intent.js";

const GONE = new Set([404, 410]);

export async function readLiveWays(osm, ids) {
  const out = new Map();
  if (!ids.length) return out;
  try {
    for (const way of await osm.getFeatures("way", ids)) out.set(way.id, way);
    return out;
  } catch (err) {
    if (!GONE.has(err && err.cause)) throw err;
  }
  for (const id of ids) {
    try {
      const [way] = await osm.getFeature("way", id);
      out.set(id, way);
    } catch (err) {
      if (!GONE.has(err && err.cause)) throw err;
      out.set(id, null);
    }
  }
  return out;
}

export async function preflight(osm, intents) {
  const live = await readLiveWays(osm, intents.map(i => i.wayId));
  const ready = [];
  const dropped = [];
  for (const intent of intents) {
    const way = live.get(intent.wayId);
    if (!way || way.visible === false) dropped.push({ intent, reason: "deleted" });
    else if (!preconditionsHold(intent, way.tags)) dropped.push({ intent, reason: "already_fixed" });
    else if (!geometryUnchanged(intent, way)) dropped.push({ intent, reason: "geometry_changed" });
    else ready.push({ intent, way });
  }
  return { ready, dropped };
}

export function groupEntries(entries, { maxWaysPerChangeset, maxChangesetSpanM }) {
  const groups = [];
  for (const entry of entries) {
    const box = entry.intent.bbox;
    const target = groups.find(g => g.entries.length < maxWaysPerChangeset && spanM(mergeBbox(g.bbox, box)) <= maxChangesetSpanM);
    if (target) {
      target.entries.push(entry);
      target.bbox = mergeBbox(target.bbox, box);
    } else {
      groups.push({ entries: [entry], bbox: box });
    }
  }
  return groups;
}

export async function planUpload(osm, intents, settings) {
  const { ready, dropped } = await preflight(osm, intents);
  const groups = groupEntries(ready, settings);
  return { ready, dropped, groups, tooMany: groups.length > settings.maxChangesetsPerUpload };
}

export function buildDiff(group) {
  return {
    create: [],
    modify: group.entries.map(({ intent, way }) => ({
      type: "way",
      id: way.id,
      version: way.version,
      nodes: way.nodes,
      tags: applyIntent(way.tags, intent),
    })),
    delete: [],
  };
}

export function conflictWayId(err) {
  const message = String((err && err.message) || "");
  const conflict = (err && err.cause === 409) || /version mismatch/i.test(message);
  if (!conflict) return null;
  const match = message.match(/\bway\s+(\d+)/i);
  return match ? Number(match[1]) : null;
}

async function sendGroup(osm, group, tagsFor) {
  const result = await osm.uploadChangeset({ ...tagsFor(group) }, buildDiff(group));
  return Object.keys(result).map(Number);
}

function failure(index, group, err) {
  return {
    index,
    wayIds: group.entries.map(e => e.intent.wayId),
    conflictWayId: conflictWayId(err),
    status: err && err.cause,
    message: (err && err.message) || String(err),
  };
}

export async function uploadGroups({ osm, groups, tagsFor, retryOnConflict = true }) {
  const done = [];
  const dropped = [];
  let retried = 0;
  for (const [index, group] of groups.entries()) {
    try {
      done.push({ changesetIds: await sendGroup(osm, group, tagsFor), wayIds: group.entries.map(e => e.intent.wayId) });
      continue;
    } catch (err) {
      if (!retryOnConflict || conflictWayId(err) === null) return { done, dropped, retried, failed: failure(index, group, err) };
    }
    retried += 1;
    const fresh = await preflight(osm, group.entries.map(e => e.intent));
    dropped.push(...fresh.dropped);
    if (!fresh.ready.length) continue;
    const again = { ...group, entries: fresh.ready };
    try {
      done.push({ changesetIds: await sendGroup(osm, again, tagsFor), wayIds: again.entries.map(e => e.intent.wayId) });
    } catch (err) {
      return { done, dropped, retried, failed: failure(index, again, err) };
    }
  }
  return { done, dropped, retried, failed: null };
}

export async function closeEmptyChangesets({ osm, apiUrl, uid, createdBy, fetchImpl = fetch }) {
  const list = await osm.listChangesets({ user: uid });
  const stale = list.filter(c => c.open && c.changes_count === 0 && c.tags && c.tags.created_by === createdBy);
  const closed = [];
  for (const cs of stale) {
    const res = await fetchImpl(`${apiUrl}/api/0.6/changeset/${cs.id}/close`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${osm.getAuthToken()}` },
    });
    if (res.ok) closed.push(cs.id);
  }
  return closed;
}
