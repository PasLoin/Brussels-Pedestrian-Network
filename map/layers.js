import { i18n } from "./i18n.js";

const ROAD_GRAY   = "#d5d5d5";
const ROAD_BORDER = "#aaaaaa";

export const BASE_STYLE_OVERRIDES = {
  "road_motorway":                    { "line-color": ROAD_GRAY },
  "road_motorway_casing":             { "line-color": ROAD_BORDER },
  "road_motorway_link":               { "line-color": ROAD_GRAY },
  "road_motorway_link_casing":        { "line-color": ROAD_BORDER },
  "road_trunk_primary":               { "line-color": ROAD_GRAY },
  "road_trunk_primary_casing":        { "line-color": ROAD_BORDER },
  "road_trunk_primary_link":          { "line-color": ROAD_GRAY },
  "road_secondary_tertiary":          { "line-color": ROAD_GRAY },
  "road_secondary_tertiary_casing":   { "line-color": ROAD_BORDER },
  "road_major_rail":                  { "line-color": ROAD_BORDER },
  "road_path_pedestrian":             { "line-color": ROAD_GRAY },
  "road_service_track":               { "line-color": ROAD_GRAY },
  "road_service_track_casing":        { "line-color": ROAD_BORDER },
  "road_minor":                       { "line-color": ROAD_GRAY },
  "road_minor_casing":                { "line-color": ROAD_BORDER },
  "road_link":                        { "line-color": ROAD_GRAY },
  "road_link_casing":                 { "line-color": ROAD_BORDER },
  "tunnel_path_pedestrian":           { "line-color": ROAD_GRAY },
  "tunnel_motorway":                  { "line-color": ROAD_GRAY },
  "tunnel_motorway_casing":           { "line-color": ROAD_BORDER },
  "tunnel_motorway_link":             { "line-color": ROAD_GRAY },
  "tunnel_motorway_link_casing":      { "line-color": ROAD_BORDER },
  "tunnel_trunk_primary":             { "line-color": ROAD_GRAY },
  "tunnel_trunk_primary_casing":      { "line-color": ROAD_BORDER },
  "tunnel_secondary_tertiary":        { "line-color": ROAD_GRAY },
  "tunnel_secondary_tertiary_casing": { "line-color": ROAD_BORDER },
  "tunnel_service_track":             { "line-color": ROAD_GRAY },
  "tunnel_service_track_casing":      { "line-color": ROAD_BORDER },
  "tunnel_minor":                     { "line-color": ROAD_GRAY },
  "tunnel_street_casing":             { "line-color": ROAD_BORDER },
  "tunnel_link":                      { "line-color": ROAD_GRAY },
  "tunnel_link_casing":               { "line-color": ROAD_BORDER },
  "bridge_path_pedestrian":           { "line-color": ROAD_GRAY },
  "bridge_path_pedestrian_casing":    { "line-color": ROAD_BORDER },
  "bridge_motorway":                  { "line-color": ROAD_GRAY },
  "bridge_motorway_casing":           { "line-color": ROAD_BORDER },
  "bridge_motorway_link":             { "line-color": ROAD_GRAY },
  "bridge_motorway_link_casing":      { "line-color": ROAD_BORDER },
  "bridge_trunk_primary":             { "line-color": ROAD_GRAY },
  "bridge_trunk_primary_casing":      { "line-color": ROAD_BORDER },
  "bridge_secondary_tertiary":        { "line-color": ROAD_GRAY },
  "bridge_secondary_tertiary_casing": { "line-color": ROAD_BORDER },
  "bridge_service_track":             { "line-color": ROAD_GRAY },
  "bridge_service_track_casing":      { "line-color": ROAD_BORDER },
  "bridge_street":                    { "line-color": ROAD_GRAY },
  "bridge_street_casing":             { "line-color": ROAD_BORDER },
  "bridge_link":                      { "line-color": ROAD_GRAY },
  "bridge_link_casing":               { "line-color": ROAD_BORDER },
};

export const HIGHWAY_LAYERS = [
  { id: "living_street", label: i18n.t("layer.highway.livingStreet"), color: "#16a34a", width: 3,   dash: false, hidden: true },
  { id: "pedestrian",    label: i18n.t("layer.highway.pedestrian"),   color: "#15803d", width: 3,   dash: false, hidden: true },
  { id: "footway",       label: i18n.t("layer.highway.footway"),      color: "#22c55e", width: 2,   dash: false, hidden: true },
  { id: "cycleway",      label: i18n.t("layer.highway.cycleway"),     color: "#0000ff", width: 2.5, dash: false, hidden: true },
  { id: "path",          label: i18n.t("layer.highway.path"),         color: "#86efac", width: 1.5, dash: true,  hidden: true },
  { id: "steps",         label: i18n.t("layer.highway.steps"),        color: "#166534", width: 2,   dash: true,  hidden: true },
  { id: "track",         label: i18n.t("layer.highway.track"),        color: "#a16207", width: 1.5, dash: true, hidden: true },
  { id: "platform",      label: i18n.t("layer.highway.platform"),     color: "#64748b", width: 2.5, dash: false, hidden: true },
];

export const ELEVATOR_COLOR = "#4338ca";
export const ELEVATOR_LAYER_IDS = ["highway-elevator", "highway-elevator-line"];
const IS_ELEVATOR = ["any", ["==", ["get", "highway"], "elevator"], ["==", ["get", "amenity"], "elevator"]];

const FLOW_PCT = ["to-number", ["get", "flow_pct"], 0];

export const FLOW_COLORS = {
  pedestrian: "#16a34a",
  road: "#ef4444",
  cycleway_foot_yes: "#2563eb",
  cycleway_no_foot: "#7c3aed",
};

export const PEDESTRIAN_LAYERS = [
  ...HIGHWAY_LAYERS.map(({ id, color, width, dash, hidden }) => ({
    id: `highway-${id}`, type: "line", source: "pedestrian", "source-layer": "highways",
    filter: ["==", ["get", "highway"], id],
    layout: { "line-cap": "round", "line-join": "round", visibility: hidden ? "none" : "visible" },
    paint: {
      "line-color": color,
      "line-width": ["interpolate", ["linear"], ["zoom"], 8, width * 0.4, 14, width, 18, width * 2.5],
      "line-opacity": 0.9,
      ...(dash ? { "line-dasharray": [3, 3] } : {})
    }
  })),
  {
    id: "highway-crossing", type: "circle", source: "pedestrian", "source-layer": "highways",
    filter: ["==", ["get", "highway"], "crossing"],
    layout: { visibility: "none" },
    paint: {
      "circle-color": "#15803d",
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 16, 4],
      "circle-stroke-color": "#15803d", "circle-stroke-width": 1
    }
  },
  {
    id: "highway-elevator-line", type: "line", source: "pedestrian", "source-layer": "highways",
    filter: ["all", ["==", ["geometry-type"], "LineString"], IS_ELEVATOR],
    layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": ELEVATOR_COLOR,
      "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 16, 4, 18, 7],
      "line-opacity": 0.9
    }
  },
  {
    id: "highway-elevator", type: "circle", source: "pedestrian", "source-layer": "highways",
    filter: ["all", ["==", ["geometry-type"], "Point"], IS_ELEVATOR],
    layout: { visibility: "none" },
    paint: {
      "circle-color": ELEVATOR_COLOR,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2, 14, 3.5, 18, 7],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 9, 0.5, 16, 1.5]
    }
  },
  {
    id: "flow-ped", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["==", ["get", "infra_type"], "pedestrian"],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["interpolate", ["linear"], FLOW_PCT, 0, "#bbf7d0", 50, "#16a34a", 100, "#14532d"],
      "line-width": ["interpolate", ["linear"], ["zoom"],
        10, ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 3],
        16, ["interpolate", ["linear"], FLOW_PCT, 0, 1,   100, 8]
      ],
      "line-opacity": 0.85
    }
  },
  {
    id: "flow-cycleway", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["in", ["get", "infra_type"], ["literal", ["cycleway_no_foot", "cycleway_foot_yes"]]],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["match", ["get", "infra_type"],
        "cycleway_foot_yes", ["interpolate", ["linear"], FLOW_PCT, 0, "#bfdbfe", 50, "#2563eb", 100, "#1e3a5f"],
        ["interpolate", ["linear"], FLOW_PCT, 0, "#ede9fe", 50, "#7c3aed", 100, "#3b0764"]
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"],
        10, ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 3],
        16, ["interpolate", ["linear"], FLOW_PCT, 0, 1,   100, 8]
      ],
      "line-opacity": 0.85
    }
  },
  {
    id: "flow-road", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["==", ["get", "infra_type"], "road"],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["interpolate", ["linear"], FLOW_PCT,
        0, "#fdba74", 20, "#f97316", 40, "#ef4444", 60, "#dc2626", 80, "#991b1b", 100, "#450a0a"
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"],
        10, ["match", ["get", "highway"],
          ["primary",   "primary_link"],   ["interpolate", ["linear"], FLOW_PCT, 0, 1.4, 100, 7.0],
          ["secondary", "secondary_link"], ["interpolate", ["linear"], FLOW_PCT, 0, 1.1, 100, 5.5],
          ["tertiary",  "tertiary_link"],  ["interpolate", ["linear"], FLOW_PCT, 0, 0.9, 100, 4.5],
          ["residential","unclassified"],  ["interpolate", ["linear"], FLOW_PCT, 0, 0.7, 100, 3.5],
          ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 2.5]
        ],
        16, ["match", ["get", "highway"],
          ["primary",   "primary_link"],   ["interpolate", ["linear"], FLOW_PCT, 0, 3.0, 100, 15.0],
          ["secondary", "secondary_link"], ["interpolate", ["linear"], FLOW_PCT, 0, 2.4, 100, 12.0],
          ["tertiary",  "tertiary_link"],  ["interpolate", ["linear"], FLOW_PCT, 0, 1.9, 100,  9.5],
          ["residential","unclassified"],  ["interpolate", ["linear"], FLOW_PCT, 0, 1.4, 100,  7.5],
          ["interpolate", ["linear"], FLOW_PCT, 0, 1.0, 100,  5.5]
        ]
      ],
      "line-opacity": 0.8
    }
  },
  {
    id: "sidewalk-gaps", type: "line", source: "pedestrian", "source-layer": "sidewalk_gaps",
    minzoom: 12, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": "#f59e0b",
      "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2, 16, 6],
      "line-opacity": 0.85,
      "line-dasharray": [4, 3]
    }
  },
  {
    id: "sidewalk-roads", type: "line", source: "pedestrian", "source-layer": "sidewalk_roads",
    minzoom: 13, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": ["match", ["get", "sw"],
        "separate",   "#22c55e",
        "yes",        "#06b6d4",
        "documented", "#22c55e",
        "partial",    "#f5700b",
        "unknown",    "#b587c7",
        "#9ca3af"
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"], 13, 2, 16, 5, 18, 8],
      "line-opacity": ["match", ["get", "sw"], "unknown", 0.45, 0.85]
    }
  },
  {
    id: "missing-crossings", type: "circle", source: "pedestrian",
    "source-layer": "missing_crossings",
    minzoom: 12,
    layout: { visibility: "none" },
    paint: {
      "circle-color": ["match", ["get", "type"],
        "missing_way", "#f97316",
        "missing_tag", "#eab308",
        "wrong_tag",   "#dc2626",
        "#f97316"
      ],
      "circle-radius": 12,
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
      "circle-opacity": 0.9,
    }
  },
  {
    id: "footway-crossing-candidates", type: "line", source: "pedestrian",
    "source-layer": "footway_crossing_candidates",
    minzoom: 13, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": "#7f1d1d",
      "line-width": ["interpolate", ["linear"], ["zoom"], 13, 3, 16, 7, 18, 10],
      "line-opacity": 0.9,
      "line-dasharray": [1, 2]
    }
  },
  {
    id: "tactile-paving-issues", type: "circle", source: "pedestrian",
    "source-layer": "tactile_paving_issues",
    minzoom: 13, layout: { visibility: "none" },
    paint: {
      "circle-color": "#a855f7",
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 4, 16, 9],
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
      "circle-opacity": 0.9,
    }
  },
  {
    id: "graph-islands", type: "line", source: "pedestrian",
    "source-layer": "graph_islands",
    minzoom: 12, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": ["match", ["get", "type"],
        "unjoined", "#db2777",
        "isolated", "#0d9488",
        "level",    "#ea580c",
        "#0d9488"
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"], 12, 3, 16, 7, 18, 10],
      "line-opacity": 0.9
    }
  },
  {
    id: "kerb-issues", type: "circle", source: "pedestrian",
    "source-layer": "kerb_issues",
    minzoom: 13, layout: { visibility: "none" },
    paint: {
      "circle-color": ["match", ["get", "type"],
        "kerb_missing",  "#1e3a8a",
        "kerb_untagged", "#7c2d12",
        "#1e3a8a"
      ],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 4, 16, 9],
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
      "circle-opacity": 0.9,
    }
  },
];
