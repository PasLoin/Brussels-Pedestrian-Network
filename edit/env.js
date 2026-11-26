import { accessFromDataset } from "./access.js";
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
    landingPage: "land.html",
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
    landingPage: "beta-land.html",
    candidates: "pmtiles",
    apiMeter: true,
    devData: false,
  }),
});

export const APP_NAME = "BrusselsPedestrianNetwork";
export const APP_VERSION = "0.2.0";
export const OSM_API_JS_VERSION = "4.0.1";
export const APP_URL = "https://github.com/PasLoin/Brussels-Pedestrian-Network";
export const USER_AGENT = `${APP_NAME}/${APP_VERSION} (+${APP_URL})`;
export const MAX_WAYS_PER_CHANGESET = 50;
export const MAX_CONCURRENT_API = 2;

export const SETTINGS = Object.freeze({
  editEnabled: true,
  autoQueue: true,
  autoAdvance: true,
  candidateMinZoom: 17,
  candidateFloorZoom: 15,
  candidateReuseMs: 5 * 60 * 1000,
  wayReuseMs: 4 * 60 * 1000,
  maxCandidateAreaDeg2: 0.001,
  authPendingTtlMs: 5 * 60 * 1000,
  maxWaysPerChangeset: 50,
  maxChangesetSpanM: 1000,
  maxChangesetsPerUpload: 3,
  longWayWarningM: 200,
  maxNodeShiftM: 10,
  defaultHashtags: Object.freeze(["#BrusselsPedestrianNetwork"]),
  reviewZoom: 18.7,
  fitMinZoom: 17,
  fitMaxZoom: 19,
  editBasemaps: Object.freeze(["urbis-ortho"]),
  editRequiredLayers: Object.freeze(["highway-pedestrian", "highway-footway", "highway-path"]),
  editOptionalLayers: Object.freeze(["sidewalk-roads"]),
  minLookMs: 3000,
  lookMsPerMeter: 30,
  lookMode: "warn",
  lookHistory: 10,
  lookQuickTolerance: 5,
  paceWindowMs: 60 * 1000,
  paceMaxMeters: 1200,
  paceBlockMeters: 1800,
  paceRepeatMs: 5 * 60 * 1000,
  paceCooldownMs: 20 * 1000,
  mapCallsPerMinute: 25,
  pauseAfter509Ms: 5 * 60 * 1000,
  apiMeterWarnPerMinute: 30,
  maxConcurrentApi: 1,
  reviewStepM: 5,
  reviewTtlMs: 12 * 60 * 60 * 1000,
  sourcePresets: Object.freeze(["survey", "local_knowledge", "streetlevel imagery", "aerial imagery"]),
});

export const OPEN_ACCESS = Object.freeze({ restricted: false, uids: Object.freeze([]) });

export function resolveEnv(name, pageUrl, settings = SETTINGS, access = OPEN_ACCESS) {
  if (!Object.prototype.hasOwnProperty.call(ENVS, name)) throw new Error(`unknown edit environment: ${name}`);
  return Object.freeze({
    ...ENVS[name],
    ...settings,
    maxWaysPerChangeset: Math.min(settings.maxWaysPerChangeset, MAX_WAYS_PER_CHANGESET),
    maxConcurrentApi: Math.max(1, Math.min(settings.maxConcurrentApi, MAX_CONCURRENT_API)),
    redirectUrl: new URL(ENVS[name].landingPage, pageUrl).href,
    access,
  });
}

export function envFromDocument(doc = document) {
  const zoom = new URL(doc.location.href).searchParams.get("review-zoom");
  const settings = zoom === null ? SETTINGS : { ...SETTINGS, reviewZoom: parseReviewZoom(zoom) };
  const dataset = doc.documentElement.dataset;
  return resolveEnv(dataset.editEnv, doc.location.href, settings, accessFromDataset(dataset));
}
