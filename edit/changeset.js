import { APP_NAME, APP_VERSION, OSM_API_VERSION } from "./env.js";

const MAX_TAG_LENGTH = 255;

export function splitList(text) {
  return String(text || "").split(/[;,\n]/).map(s => s.trim()).filter(Boolean);
}

export function normalizeHashtags(values) {
  const out = [];
  for (const raw of values) {
    const tag = raw.replace(/\s+/g, "").replace(/^#*/, "#");
    if (tag.length > 1 && !out.some(t => t.toLowerCase() === tag.toLowerCase())) out.push(tag);
  }
  return out;
}

export function uniqueValues(values) {
  const out = [];
  for (const v of values.map(x => String(x).trim()).filter(Boolean)) if (!out.includes(v)) out.push(v);
  return out;
}

export function commentWithHashtags(comment, hashtags) {
  const base = String(comment || "").trim();
  const missing = hashtags.filter(h => !base.toLowerCase().split(/\s+/).includes(h.toLowerCase()));
  return [base, ...missing].filter(Boolean).join(" ");
}

export function buildChangesetTags({
  comment, sources, hashtags = [], reviewRequested = false, locale, host, imageryUsed = [], changesetsCount,
}) {
  const sourceList = uniqueValues(sources || []);
  if (!sourceList.length) throw new Error("source-required");
  const tagList = normalizeHashtags(hashtags);
  const fullComment = commentWithHashtags(comment, tagList);
  if (!String(comment || "").trim()) throw new Error("comment-required");
  const tags = {
    created_by: `${APP_NAME} ${APP_VERSION}`,
    osm_api_js_version: OSM_API_VERSION,
    comment: fullComment,
    source: sourceList.join(";"),
  };
  const imagery = uniqueValues(imageryUsed);
  if (imagery.length) tags.imagery_used = imagery.join(";");
  if (locale) tags.locale = locale;
  if (tagList.length) tags.hashtags = tagList.join(";");
  if (host) tags.host = host;
  if (Number.isFinite(changesetsCount)) tags.changesets_count = String(changesetsCount);
  if (reviewRequested) tags.review_requested = "yes";
  const tooLong = Object.entries(tags).filter(([, v]) => v.length > MAX_TAG_LENGTH).map(([k]) => k);
  if (tooLong.length) throw new Error(`tag-too-long:${tooLong.join(",")}`);
  return tags;
}
