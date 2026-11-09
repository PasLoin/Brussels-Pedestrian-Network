export const ZINNEKE_ATTRIBUTION = '<a href="https://github.com/PasLoin/ZinnekeTiles" target="_blank" rel="noopener">ZinnekeTiles</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
export const ZINNEKE_SOURCE_PREFIX = "zt-";
export const OVERLAY_SOURCES = ["pedestrian", "nav-route"];

export function mergeLibertyStyle(libertyStyle, localStyle, overrides) {
  const allowedIds = new Set(Object.keys(overrides));
  const localPaintById = new Map(
    ((localStyle && localStyle.layers) || []).filter(l => allowedIds.has(l.id)).map(l => [l.id, l.paint || {}])
  );
  return {
    ...libertyStyle,
    layers: (libertyStyle.layers || []).map(layer => {
      const localPaint = localPaintById.get(layer.id) || {};
      const layerOverrides = overrides[layer.id] || {};
      return { ...layer, paint: { ...(layer.paint || {}), ...localPaint, ...layerOverrides } };
    }),
  };
}

export function adaptZinnekeStyle(style, bm) {
  const hideSources = new Set(bm.hideSources || []);
  const hideLayers = bm.hideLayers || [];
  const isHidden = layer => hideSources.has(layer.source) || hideLayers.some(pattern =>
    pattern.endsWith("*") ? layer.id.startsWith(pattern.slice(0, -1)) : layer.id === pattern);
  const layers = (style.layers || []).filter(layer => !isHidden(layer));
  const usedSources = new Set(layers.map(layer => layer.source).filter(Boolean));
  const sources = {};
  for (const [id, src] of Object.entries(style.sources || {})) {
    if (!usedSources.has(id)) continue;
    const copy = { ...src, attribution: ZINNEKE_ATTRIBUTION };
    if (copy.url && /\.pmtiles$/.test(copy.url)) copy.url = "pmtiles://" + new URL(copy.url, bm.url).href;
    sources[ZINNEKE_SOURCE_PREFIX + id] = copy;
  }
  return {
    ...style,
    sources,
    layers: layers.map(layer => {
      const out = { ...layer };
      if (out.source) out.source = ZINNEKE_SOURCE_PREFIX + out.source;
      if (out.layout && out.layout["icon-image"]) {
        out.layout = { ...out.layout, visibility: "none" };
        delete out.layout["icon-image"];
      }
      return out;
    }),
  };
}

export function keepOverlays(prev, next) {
  const sources = { ...next.sources };
  for (const id of OVERLAY_SOURCES) {
    if (prev && prev.sources && prev.sources[id]) sources[id] = prev.sources[id];
  }
  const overlayLayers = ((prev && prev.layers) || []).filter(l => OVERLAY_SOURCES.includes(l.source));
  return { ...next, sources, layers: [...next.layers, ...overlayLayers] };
}
