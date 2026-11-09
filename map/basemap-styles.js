export const OSM_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
export const ZINNEKE_ATTRIBUTION = '<a href="https://github.com/PasLoin/ZinnekeTiles" target="_blank" rel="noopener">ZinnekeTiles</a> ' + OSM_ATTRIBUTION;
export const ZINNEKE_SOURCE_PREFIX = "zt-";
export const OVERLAY_SOURCES = ["pedestrian", "nav-route"];
export const WMS_SOURCE_PREFIX = "wms-";

export function pedestrianSource(url) {
  return { type: "vector", url, attribution: OSM_ATTRIBUTION };
}

export function wmsTileUrl(endpoint, layer, size = 256) {
  const params = new URLSearchParams({
    SERVICE: "WMS", VERSION: "1.3.0", REQUEST: "GetMap", FORMAT: "image/png", TRANSPARENT: "TRUE",
    LAYERS: layer, STYLES: "", CRS: "EPSG:3857", WIDTH: String(size), HEIGHT: String(size)
  });
  return `${endpoint}?${params}&BBOX={bbox-epsg-3857}`;
}

export function buildWmsStyle(bm) {
  const sources = {};
  const layers = [{ id: "wms-background", type: "background", paint: { "background-color": bm.background || "#dddddd" } }];
  for (const wms of bm.wms || []) {
    const id = WMS_SOURCE_PREFIX + wms.id;
    sources[id] = {
      type: "raster",
      tiles: [wmsTileUrl(wms.endpoint, wms.layer, wms.tileSize || 256)],
      tileSize: wms.tileSize || 256,
      ...(bm.bounds ? { bounds: bm.bounds } : {}),
      ...(wms.minzoom !== undefined ? { minzoom: wms.minzoom } : {}),
      maxzoom: wms.maxzoom ?? 21,
      attribution: bm.attribution
    };
    layers.push({ id, type: "raster", source: id, paint: { "raster-opacity": wms.opacity ?? 1, "raster-fade-duration": 0 } });
  }
  return { version: 8, name: bm.title, sources, layers };
}

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
