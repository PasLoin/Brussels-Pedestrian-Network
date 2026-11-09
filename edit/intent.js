import { hasSidewalkTag, isEditableCandidate } from "./whitelist.js";

export const SIDEWALK_VALUES = Object.freeze(["separate", "yes", "no"]);
export const SIDEWALK_KEY = /^sidewalk(?::|$)/;

export function tagsForChoice(left, right) {
  if (!SIDEWALK_VALUES.includes(left) || !SIDEWALK_VALUES.includes(right)) throw new Error("invalid-choice");
  return left === right ? { "sidewalk:both": left } : { "sidewalk:left": left, "sidewalk:right": right };
}

export function makeIntent({ way, left, right, bbox, lengthM, name, now = Date.now() }) {
  return {
    wayId: way.id,
    set: tagsForChoice(left, right),
    unset: [],
    preconditions: { highway: way.tags.highway, noSidewalkKeys: true },
    seenVersion: way.version,
    bbox,
    lengthM,
    name: name || way.tags.name || "",
    addedAt: now,
  };
}

export function preconditionsHold(intent, liveTags) {
  const tags = liveTags || {};
  if (tags.highway !== intent.preconditions.highway) return false;
  if (intent.preconditions.noSidewalkKeys && hasSidewalkTag(tags)) return false;
  return isEditableCandidate(tags);
}

export function applyIntent(tags, intent) {
  const touched = [...Object.keys(intent.set), ...intent.unset];
  const foreign = touched.filter(key => !SIDEWALK_KEY.test(key));
  if (foreign.length) throw new Error(`refusing to touch ${foreign.join(", ")}`);
  const out = { ...(tags || {}) };
  for (const key of intent.unset) delete out[key];
  Object.assign(out, intent.set);
  return out;
}
