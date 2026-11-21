import { i18n } from "./i18n.js";
import { store } from "./store.js";

export const SIDEWALK_STATUSES = [
  { value: "separate",   label: "separate",          color: "#22c55e" },
  { value: "yes",        label: "yes",               color: "#06b6d4" },
  { value: "documented", label: i18n.t("layer.sidewalk.documented"), color: "#22c55e" },
  { value: "partial",    label: i18n.t("layer.sidewalk.partial"),    color: "#f5700b" },
  { value: "unknown",    label: i18n.t("layer.sidewalk.unknown"),    color: "#b587c7" },
];
export const activeSidewalkStatuses = new Set(SIDEWALK_STATUSES.map(s => s.value));

export const updateSidewalkFilter = makeMembershipFilterUpdater(() => store.map, "sidewalk-roads", "sw", activeSidewalkStatuses, SIDEWALK_STATUSES);

export const MISSING_CROSSING_TYPES = [
  { value: "missing_way", label: i18n.t("layer.missingCrossing.missingWay"), color: "#f97316" },
  { value: "missing_tag", label: i18n.t("layer.missingCrossing.missingTag"), color: "#eab308" },
  { value: "wrong_tag",   label: i18n.t("layer.missingCrossing.wrongTag"),   color: "#dc2626" },
];
export const activeMissingTypes = new Set(MISSING_CROSSING_TYPES.map(t => t.value));

export const updateMissingCrossingsFilter = makeMembershipFilterUpdater(() => store.map, "missing-crossings", "type", activeMissingTypes, MISSING_CROSSING_TYPES);

export const KERB_ISSUE_TYPES = [
  { value: "kerb_missing",  label: i18n.t("layer.kerb.missing"),  color: "#1e3a8a" },
  { value: "kerb_untagged", label: i18n.t("layer.kerb.untagged"), color: "#7c2d12" },
];
export const activeKerbIssueTypes = new Set();

export const updateKerbIssuesFilter = makeMembershipFilterUpdater(() => store.map, "kerb-issues", "type", activeKerbIssueTypes, KERB_ISSUE_TYPES);

export const ISLAND_TYPES = [
  { value: "unjoined", label: i18n.t("layer.island.unjoined"), color: "#db2777" },
  { value: "isolated", label: i18n.t("layer.island.isolated"), color: "#0d9488" },
  { value: "level",    label: i18n.t("layer.island.level"),    color: "#ea580c" },
];
export const activeIslandTypes = new Set(ISLAND_TYPES.map(t => t.value));

export const updateIslandsFilter = makeMembershipFilterUpdater(() => store.map, "graph-islands", "type", activeIslandTypes, ISLAND_TYPES);

export function updateFlowFilter(rawValue) {
  const minPct = parseInt(rawValue, 10);
  document.getElementById("flow-threshold-val").textContent = i18n.percent(minPct, { maximumFractionDigits: 0 });
  if (!store.map) return;
  const baseFilter = ["==", ["get", "infra_type"], "road"];
  const filter = minPct > 0
    ? ["all", baseFilter, [">=", ["to-number", ["get", "flow_pct"], 0], minPct]]
    : baseFilter;
  setFilterIfLayer(store.map, "flow-road", filter);
}
