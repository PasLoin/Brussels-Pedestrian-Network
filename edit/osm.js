import { mergeBbox, spanM } from "./geo.js";
import { applyIntent, preconditionsHold } from "./intent.js";

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

export async function uploadGroups({ osm, groups, tags }) {
  const done = [];
  for (const [index, group] of groups.entries()) {
    const wayIds = group.entries.map(e => e.intent.wayId);
    try {
      const result = await osm.uploadChangeset({ ...tags }, buildDiff(group));
      done.push({ changesetIds: Object.keys(result).map(Number), wayIds });
    } catch (err) {
      return {
        done,
        failed: { index, wayIds, conflictWayId: conflictWayId(err), status: err && err.cause, message: (err && err.message) || String(err) },
      };
    }
  }
  return { done, failed: null };
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
