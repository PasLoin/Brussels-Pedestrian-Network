import { parseReviewZoom } from "./review.js";

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
    apiMeter: true,
    devData: true,
  }),
  prod: Object.freeze({
    name: "prod",
    apiUrl: "https://api.openstreetmap.org",
    webUrl: "https://www.openstreetmap.org",
    clientId: "",
    scopes: SCOPES,
    candidates: "pmtiles",
    apiMeter: false,
    devData: false,
  }),
});

export const APP_NAME = "BrusselsPedestrianNetwork";
export const APP_VERSION = "0.2.0";
export const OSM_API_VERSION = "4.0.1";
export const MAX_WAYS_PER_CHANGESET = 50;

export const SETTINGS = Object.freeze({
  editEnabled: false,
  autoQueue: true,
  autoAdvance: true,
  candidateMinZoom: 17,
  candidateFloorZoom: 15,
  maxCandidateAreaDeg2: 0.001,
  authPendingTtlMs: 5 * 60 * 1000,
  landingPage: "land.html",
  maxWaysPerChangeset: 50,
  maxChangesetSpanM: 1000,
  maxChangesetsPerUpload: 3,
  longWayWarningM: 200,
  maxNodeShiftM: 10,
  defaultHashtags: Object.freeze(["#BrusselsPedestrianNetwork"]),
  reviewZoom: null,
  apiMeterWarnPerMinute: 30,
  maxConcurrentApi: 2,
  reviewStepM: 5,
  reviewTtlMs: 12 * 60 * 60 * 1000,
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
  const zoom = new URL(doc.location.href).searchParams.get("review-zoom");
  const settings = zoom === null ? SETTINGS : { ...SETTINGS, reviewZoom: parseReviewZoom(zoom) };
  return resolveEnv(doc.documentElement.dataset.editEnv, doc.location.href, settings);
}
