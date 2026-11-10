const DEV_API = "https://master.apis.dev.openstreetmap.org";
const SCOPES = Object.freeze(["read_prefs", "write_api"]);

export const ENVS = Object.freeze({
  dev: Object.freeze({
    name: "dev",
    apiUrl: DEV_API,
    webUrl: DEV_API,
    clientId: "5KoHVvJ44fBlMmDP5qSQxN5N_UJGWCX18-e5aIfzO0Q",
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

export const APP_NAME = "BrusselsPedestrianNetwork";
export const APP_VERSION = "0.2.0";
export const OSM_API_VERSION = "4.0.1";
export const MAX_WAYS_PER_CHANGESET = 50;

export const SETTINGS = Object.freeze({
  editEnabled: true,
  autoQueue: true,
  candidateMinZoom: 17,
  authPendingTtlMs: 5 * 60 * 1000,
  landingPage: "land.html",
  maxWaysPerChangeset: 50,
  maxChangesetSpanM: 1000,
  maxChangesetsPerUpload: 3,
  longWayWarningM: 200,
  maxNodeShiftM: 0,
  defaultHashtags: Object.freeze(["#BrusselsPedestrianNetwork"]),
  sourcePresets: Object.freeze(["survey", "local_knowledge", "streetlevel imagery", "aerial imagery"]),
});

export function resolveEnv(name, pageUrl, settings = SETTINGS) {
  if (!Object.prototype.hasOwnProperty.call(ENVS, name)) throw new Error(`unknown edit environment: ${name}`);
  return Object.freeze({
    ...ENVS[name],
    ...settings,
    maxWaysPerChangeset: Math.min(settings.maxWaysPerChangeset, MAX_WAYS_PER_CHANGESET),
    redirectUrl: new URL(settings.landingPage, pageUrl).href,
  });
}

export function envFromDocument(doc = document) {
  return resolveEnv(doc.documentElement.dataset.editEnv, doc.location.href);
}
