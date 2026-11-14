import { distanceM, mergeBbox, spanM } from "./geo.js";
import { applyIntent, geometryUnchanged, preconditionsHold } from "./intent.js";

const GONE = new Set([404, 410]);
const NODE_CHUNK = 500;

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

export async function readLiveNodes(osm, ids) {
  const out = new Map();
  const unique = [...new Set(ids)];
  for (let i = 0; i < unique.length; i += NODE_CHUNK) {
    for (const node of await osm.getFeatures("node", unique.slice(i, i + NODE_CHUNK))) out.set(node.id, node);
  }
  return out;
}

export function largestShiftM(intent, way, liveNodes) {
  let worst = 0;
  const present = new Set(way.nodes || []);
  for (const [id, lon, lat] of intent.nodeCoords || []) {
    const node = liveNodes.get(id);
    if (!present.has(id) || !node || node.visible === false) continue;
    worst = Math.max(worst, distanceM([lon, lat], [node.lon, node.lat]));
  }
  return worst;
}

export async function preflight(osm, intents, { maxNodeShiftM = Infinity } = {}) {
  const live = await readLiveWays(osm, intents.map(i => i.wayId));
  const candidates = [];
  const dropped = [];
  for (const intent of intents) {
    const way = live.get(intent.wayId);
    if (!way || way.visible === false) dropped.push({ intent, reason: "deleted" });
    else if (!preconditionsHold(intent, way.tags)) dropped.push({ intent, reason: "already_fixed" });
    else if (!geometryUnchanged(intent, way)) dropped.push({ intent, reason: "geometry_changed" });
    else candidates.push({ intent, way });
  }
  const watched = candidates.flatMap(({ intent }) => (intent.nodeCoords || []).map(([id]) => id));
  const liveNodes = Number.isFinite(maxNodeShiftM) && watched.length ? await readLiveNodes(osm, watched) : new Map();
  const ready = [];
  for (const entry of candidates) {
    const shiftM = largestShiftM(entry.intent, entry.way, liveNodes);
    if (shiftM > maxNodeShiftM) dropped.push({ intent: entry.intent, reason: "node_moved", shiftM });
    else ready.push(entry);
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

export function zonesFor(intents, settings) {
  return groupEntries(intents.filter(i => i && Array.isArray(i.bbox)).map(intent => ({ intent })), settings).length;
}

export function queueRoom(intents, candidate, settings) {
  const max = settings.maxChangesetsPerUpload;
  const others = intents.filter(i => i.wayId !== candidate.wayId);
  const before = zonesFor(others, settings);
  const after = zonesFor([...others, candidate], settings);
  return { zones: before, after, max, fits: after <= max };
}

export async function planUpload(osm, intents, settings) {
  const { ready, dropped } = await preflight(osm, intents, settings);
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

export function isConflict(err) {
  return Boolean(err) && err.cause === 409;
}

export function changedSince(entries, live) {
  return entries
    .filter(({ way }) => {
      const now = live.get(way.id);
      return !now || now.visible === false || now.version !== way.version;
    })
    .map(({ way }) => way.id);
}

async function sendGroup(osm, group, tagsFor) {
  const tags = await tagsFor(group);
  const result = await osm.uploadChangeset({ ...tags }, buildDiff(group));
  return Object.keys(result).map(Number);
}

async function conflictingWays(osm, group) {
  try {
    return changedSince(group.entries, await readLiveWays(osm, group.entries.map(e => e.way.id)));
  } catch {
    return [];
  }
}

function failure(index, group, err, conflictWayIds = []) {
  return {
    index,
    wayIds: group.entries.map(e => e.intent.wayId),
    conflictWayIds,
    status: err && err.cause,
    message: (err && err.message) || String(err),
  };
}

async function sent(osm, group, tagsFor) {
  return { changesetIds: await sendGroup(osm, group, tagsFor), wayIds: group.entries.map(e => e.intent.wayId) };
}

export async function uploadGroups({ osm, groups, tagsFor, retryOnConflict = true, settings = {} }) {
  const done = [];
  const dropped = [];
  let retried = 0;
  for (const [index, group] of groups.entries()) {
    let firstError;
    try {
      done.push(await sent(osm, group, tagsFor));
      continue;
    } catch (err) {
      firstError = err;
    }
    if (!isConflict(firstError)) return { done, dropped, retried, failed: failure(index, group, firstError) };
    if (!retryOnConflict) return { done, dropped, retried, failed: failure(index, group, firstError, await conflictingWays(osm, group)) };
    const fresh = await preflight(osm, group.entries.map(e => e.intent), settings);
    const moved = changedSince(group.entries, new Map(fresh.ready.map(e => [e.way.id, e.way])));
    if (!fresh.dropped.length && !moved.length) return { done, dropped, retried, failed: failure(index, group, firstError) };
    retried += 1;
    dropped.push(...fresh.dropped);
    if (!fresh.ready.length) continue;
    const again = { ...group, entries: fresh.ready };
    try {
      done.push(await sent(osm, again, tagsFor));
    } catch (err) {
      const conflicts = isConflict(err) ? await conflictingWays(osm, again) : [];
      return { done, dropped, retried, failed: failure(index, again, err, conflicts) };
    }
  }
  return { done, dropped, retried, failed: null };
}

export async function closeEmptyChangesets({ osm, uid, createdBy }) {
  const list = await osm.listChangesets({ user: uid });
  const stale = list.filter(c => c.open && c.changes_count === 0 && c.tags && c.tags.created_by === createdBy);
  const closed = [];
  for (const cs of stale) {
    try {
      await osm.closeChangeset(cs.id);
      closed.push(cs.id);
    } catch {}
  }
  return closed;
}
