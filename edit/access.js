const UID = /^[1-9]\d{0,11}$/;
const WRITE_METHODS = new Set(["PUT", "POST", "DELETE", "PATCH"]);

export class EditNotAllowedError extends Error {
  constructor(url) {
    super(`OSM API write blocked, this account is not allowed to edit during the beta: ${url}`);
    this.name = "EditNotAllowedError";
  }
}

export function parseAllowedUids(text) {
  const uids = [];
  for (const token of String(text ?? "").split(/[\s,;]+/)) {
    if (!UID.test(token)) continue;
    const uid = Number(token);
    if (!uids.includes(uid)) uids.push(uid);
  }
  return Object.freeze(uids);
}

export function accessFromDataset(dataset = {}) {
  const restricted = dataset.editAllowlist === "on";
  return Object.freeze({ restricted, uids: restricted ? parseAllowedUids(dataset.editAllowedUids) : Object.freeze([]) });
}

export function isAllowedUid(access, uid) {
  if (!access || !access.restricted) return true;
  const value = Number(uid);
  return Number.isSafeInteger(value) && value > 0 && access.uids.includes(value);
}

export function isApiWrite(url, method, apiUrl) {
  if (typeof url !== "string" || !url.startsWith(apiUrl)) return false;
  let path;
  try { path = new URL(url).pathname; } catch { return false; }
  return path.startsWith("/api/") && WRITE_METHODS.has(String(method || "GET").toUpperCase());
}

export function guardWrites(fetchImpl, { apiUrl, allowed }) {
  return (input, init) => {
    const url = typeof input === "string" ? input : input && input.url;
    const method = (init && init.method) || (input && typeof input !== "string" && input.method) || "GET";
    if (isApiWrite(url, method, apiUrl) && !allowed()) return Promise.reject(new EditNotAllowedError(url));
    return fetchImpl(input, init);
  };
}

export function installWriteGuard(target, options) {
  const original = target.fetch.bind(target);
  target.fetch = guardWrites(original, options);
  return () => { target.fetch = original; };
}
