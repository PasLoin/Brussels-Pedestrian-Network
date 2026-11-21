function membershipFilter(property, active, allCount) {
  if (active.size === 0) return ["==", ["get", property], "__none__"];
  if (active.size === allCount) return null;
  return ["in", ["get", property], ["literal", [...active]]];
}

function setFilterIfLayer(map, layerId, filter) {
  if (!map || !map.getLayer(layerId)) return false;
  map.setFilter(layerId, filter);
  return true;
}

function setVisibilityIfLayer(map, layerId, visible) {
  if (!map || !map.getLayer(layerId)) return false;
  map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
  return true;
}

function makeMembershipFilterUpdater(getMap, layerId, property, active, items) {
  return () => setFilterIfLayer(getMap(), layerId, membershipFilter(property, active, items.length));
}

if (typeof module !== "undefined") {
  module.exports = { membershipFilter, setFilterIfLayer, setVisibilityIfLayer, makeMembershipFilterUpdater };
}
