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

export const EMPTY_CHOICE = Object.freeze({ mode: "both", both: "", left: "", right: "" });

export function choiceFromIntent(intent) {
  if (!intent) return EMPTY_CHOICE;
  const both = intent.set["sidewalk:both"];
  if (both) return { mode: "both", both, left: both, right: both };
  return { mode: "sides", both: "", left: intent.set["sidewalk:left"] || "", right: intent.set["sidewalk:right"] || "" };
}

export function switchMode(choice, mode) {
  if (mode === "sides") return { ...choice, mode, left: choice.left || choice.both, right: choice.right || choice.both, both: "" };
  const both = choice.left && choice.left === choice.right ? choice.left : "";
  return { mode: "both", both, left: both, right: both };
}

export function chooseValue(choice, side, value) {
  if (!SIDEWALK_VALUES.includes(value)) throw new Error("invalid-choice");
  if (side === "both") {
    const next = choice.both === value ? "" : value;
    return { mode: "both", both: next, left: next, right: next };
  }
  if (side !== "left" && side !== "right") throw new Error("invalid-side");
  return { ...choice, mode: "sides", both: "", [side]: choice[side] === value ? "" : value };
}

export function completeChoice(choice) {
  if (choice.mode === "both") return choice.both ? { left: choice.both, right: choice.both } : null;
  return choice.left && choice.right ? { left: choice.left, right: choice.right } : null;
}
