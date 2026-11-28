export const AUTH_KEY = "__osmAuth";
export const ENV_KEY = "bpn.authEnv";
export const PENDING_KEY = "bpn.authPending";
export const AUTH_CHANNEL = "osm-api-auth-complete";
export const TAB_KEY = "bpn.tabId";

function read(storage, key) {
  try { return storage.getItem(key); } catch { return null; }
}

function write(storage, key, value) {
  try { storage.setItem(key, value); } catch {}
}

function remove(storage, key) {
  try { storage.removeItem(key); } catch {}
}

export function guardEnvironment({ env, storage, osm }) {
  if (read(storage, AUTH_KEY) === null) {
    remove(storage, ENV_KEY);
    return false;
  }
  if (read(storage, ENV_KEY) === env) return false;
  osm.logout();
  remove(storage, AUTH_KEY);
  remove(storage, ENV_KEY);
  return true;
}

export function readPending(storage) {
  const raw = read(storage, PENDING_KEY);
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw);
    return value && typeof value === "object" ? value : null;
  } catch {
    return null;
  }
}

export function isPendingFresh(pending, now, ttlMs) {
  if (!pending || typeof pending.ts !== "number") return false;
  const age = now - pending.ts;
  return age >= 0 && age <= ttlMs;
}

export function tabId(session, random = () => Math.random().toString(36).slice(2)) {
  const known = read(session, TAB_KEY);
  if (known) return known;
  const fresh = random();
  write(session, TAB_KEY, fresh);
  return fresh;
}

export function markPending({ storage, env, apiUrl, now, tab }) {
  write(storage, PENDING_KEY, JSON.stringify({ env, apiUrl, ts: now, tab }));
}

export function consumePending({ storage, apiUrl, now, ttlMs }) {
  const pending = readPending(storage);
  remove(storage, PENDING_KEY);
  if (!pending) return "missing";
  if (pending.apiUrl !== apiUrl) return "mismatch";
  if (!isPendingFresh(pending, now, ttlMs)) return "expired";
  return "ok";
}

export function loginInProgress({ storage, now, ttlMs, tab }) {
  const pending = readPending(storage);
  return isPendingFresh(pending, now, ttlMs) && pending.tab !== tab;
}

export async function login({ osm, storage, env, tab, now = Date.now }) {
  if (loginInProgress({ storage, now: now(), ttlMs: env.authPendingTtlMs, tab })) throw new Error("login-pending");
  markPending({ storage, env: env.name, apiUrl: env.apiUrl, now: now(), tab });
  try {
    await osm.login({ mode: "popup", clientId: env.clientId, redirectUrl: env.redirectUrl, scopes: [...env.scopes] });
    write(storage, ENV_KEY, env.name);
  } finally {
    remove(storage, PENDING_KEY);
  }
}

export function readToken(storage) {
  const raw = read(storage, AUTH_KEY);
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw);
    return value && typeof value.accessToken === "string" && value.accessToken ? value.accessToken : null;
  } catch {
    return null;
  }
}

export function revokeUrl(env) {
  return `${env.webUrl}/oauth2/revoke`;
}

export function authorizedAppsUrl(env) {
  return `${env.webUrl}/oauth2/authorized_applications`;
}

export async function revokeToken({ token, env, fetchImpl }) {
  if (!token || !env || !env.clientId || !env.webUrl) return false;
  try {
    const response = await fetchImpl(revokeUrl(env), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ token, token_type_hint: "access_token", client_id: env.clientId }).toString(),
      credentials: "omit",
      referrerPolicy: "no-referrer",
    });
    return Boolean(response && response.ok);
  } catch {
    return false;
  }
}

export function ownsSession({ storage, env }) {
  return read(storage, ENV_KEY) === env;
}

export function foreignSession({ storage, env }) {
  const owner = read(storage, ENV_KEY);
  return owner !== null && owner !== env && read(storage, AUTH_KEY) !== null;
}

export async function logout({ osm, storage, env = null, fetchImpl = (...args) => fetch(...args) }) {
  if (env && foreignSession({ storage, env: env.name })) return "foreign";
  const token = env && read(storage, ENV_KEY) === env.name ? readToken(storage) : null;
  osm.logout();
  remove(storage, AUTH_KEY);
  remove(storage, ENV_KEY);
  if (!token) return "none";
  return (await revokeToken({ token, env, fetchImpl })) ? "revoked" : "failed";
}

export function isLoggedIn({ osm, storage, env }) {
  return read(storage, ENV_KEY) === env.name && osm.isLoggedIn();
}
