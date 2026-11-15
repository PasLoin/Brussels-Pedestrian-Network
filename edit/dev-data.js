import { lineLengthM } from "./geo.js";

export const DEV_SOURCE = "dev-sidewalk";
export const MAX_FILE_BYTES = 50 * 1024 * 1024;
export const ROAD_TYPES = new Set([
  "residential", "unclassified",
  "tertiary", "tertiary_link",
  "secondary", "secondary_link",
  "primary", "primary_link",
]);
export const MIN_LENGTH_M = 15;

export class DevDataError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function clean(value) {
  return value === undefined || value === null ? "" : String(value).trim().toLowerCase();
}

export function classifyEdgeSidewalk(sw, swLeft, swRight, swBoth) {
  if (swBoth) {
    if (swBoth === "separate") return "separate";
    if (swBoth === "yes" || swBoth === "both") return "yes";
    return "documented";
  }
  if (swLeft && swRight) {
    if (swLeft === "separate" && swRight === "separate") return "separate";
    return "documented";
  }
  if (sw) {
    if (sw === "separate") return "separate";
    if (sw === "both" || sw === "yes") return "yes";
    if (sw === "left" || sw === "right") return "partial";
    return "documented";
  }
  if (swLeft || swRight) return "partial";
  return "unknown";
}

export function sidewalkStatus(tags) {
  return classifyEdgeSidewalk(clean(tags.sidewalk), clean(tags["sidewalk:left"]), clean(tags["sidewalk:right"]), clean(tags["sidewalk:both"]));
}

export function parseOsmXml(text, Parser = globalThis.DOMParser) {
  const doc = new Parser().parseFromString(text, "application/xml");
  const root = doc.documentElement;
  if (!root || root.nodeName !== "osm" || doc.getElementsByTagName("parsererror").length) throw new DevDataError("notOsm");
  const nodes = new Map();
  const ways = [];
  let unsaved = false;
  let latest = "";
  for (const el of Array.from(root.children)) {
    if (el.nodeName !== "node" && el.nodeName !== "way" && el.nodeName !== "relation") continue;
    const id = Number(el.getAttribute("id"));
    if (!Number.isSafeInteger(id) || id <= 0 || el.hasAttribute("action")) unsaved = true;
    if (el.getAttribute("visible") === "false") continue;
    const stamp = el.getAttribute("timestamp") || "";
    if (stamp > latest) latest = stamp;
    if (el.nodeName === "node") {
      nodes.set(id, [Number(el.getAttribute("lon")), Number(el.getAttribute("lat"))]);
    } else if (el.nodeName === "way") {
      const tags = {};
      const refs = [];
      for (const child of Array.from(el.children)) {
        if (child.nodeName === "tag") tags[child.getAttribute("k")] = child.getAttribute("v");
        else if (child.nodeName === "nd") refs.push(Number(child.getAttribute("ref")));
      }
      ways.push({ id, version: Number(el.getAttribute("version")) || 0, tags, refs });
    }
  }
  if (unsaved) throw new DevDataError("unsaved");
  return { nodes, ways, latest };
}

export function sidewalkRoadsFromOsm({ nodes, ways }) {
  const features = [];
  for (const way of ways) {
    const highway = clean(way.tags.highway);
    if (!ROAD_TYPES.has(highway) || clean(way.tags.area) === "yes") continue;
    const coords = way.refs.map(ref => nodes.get(ref));
    if (coords.length < 2 || coords.some(c => !c || !Number.isFinite(c[0]) || !Number.isFinite(c[1]))) continue;
    const length = lineLengthM(coords);
    if (length < MIN_LENGTH_M) continue;
    features.push({
      type: "Feature",
      id: way.id,
      geometry: { type: "LineString", coordinates: coords },
      properties: {
        sw: sidewalkStatus(way.tags),
        name: clean(way.tags.name),
        osm_id: way.id,
        highway,
        length_m: Math.round(length * 10) / 10,
      },
    });
  }
  if (!features.length) throw new DevDataError("empty");
  return { type: "FeatureCollection", features };
}

export function devDataFromFile(text, name, Parser) {
  const parsed = parseOsmXml(text, Parser);
  const collection = sidewalkRoadsFromOsm(parsed);
  return { collection, meta: { name, count: collection.features.length, latest: parsed.latest } };
}

const DB_NAME = "bpn-dev-data";
const STORE = "exports";

function openDb(indexedDB) {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withStore(indexedDB, mode, fn) {
  const db = await openDb(indexedDB);
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req && req.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

export function createDevDataStore(indexedDB, env) {
  const key = `sidewalk.${env}`;
  const safe = async (fn, fallback) => {
    if (!indexedDB) return fallback;
    try { return await fn(); } catch { return fallback; }
  };
  return {
    save: data => safe(() => withStore(indexedDB, "readwrite", s => s.put(data, key)), undefined),
    load: () => safe(() => withStore(indexedDB, "readonly", s => s.get(key)), null),
    clear: () => safe(() => withStore(indexedDB, "readwrite", s => s.delete(key)), undefined),
  };
}
