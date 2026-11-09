const DEV_API = "https://master.apis.dev.openstreetmap.org";
const SCOPES = Object.freeze(["read_prefs", "write_api"]);

export const ENVS = Object.freeze({
  dev: Object.freeze({
    name: "dev",
    apiUrl: DEV_API,
    webUrl: DEV_API,
    clientId: "",
    scopes: SCOPES,
    candidates: "live",
  }),
  prod: Object.freeze({
    name: "prod",
    apiUrl: "https://api.openstreetmap.org",
    webUrl: "https://www.openstreetmap.org",
    clientId: "",
    scopes: SCOPES,
    candidates: "pmtiles",
  }),
});

export const SETTINGS = Object.freeze({
  editEnabled: true,
  candidateMinZoom: 17,
  authPendingTtlMs: 5 * 60 * 1000,
  landingPage: "land.html",
});

export function resolveEnv(name, pageUrl, settings = SETTINGS) {
  if (!Object.prototype.hasOwnProperty.call(ENVS, name)) throw new Error(`unknown edit environment: ${name}`);
  return Object.freeze({
    ...ENVS[name],
    ...settings,
    redirectUrl: new URL(settings.landingPage, pageUrl).href,
  });
}

export function envFromDocument(doc = document) {
  return resolveEnv(doc.documentElement.dataset.editEnv, doc.location.href);
}
