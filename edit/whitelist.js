export const WHITELIST = Object.freeze([
  Object.freeze({ key: "highway", values: Object.freeze(["residential"]) }),
]);

export function hasSidewalkTag(tags) {
  return Object.keys(tags || {}).some(key => key === "sidewalk" || key.startsWith("sidewalk:"));
}

export function matchesWhitelist(tags, whitelist = WHITELIST) {
  const t = tags || {};
  return whitelist.some(rule => rule.values.includes(t[rule.key]));
}

export function isEditableCandidate(tags, whitelist = WHITELIST) {
  return matchesWhitelist(tags, whitelist) && !hasSidewalkTag(tags);
}
