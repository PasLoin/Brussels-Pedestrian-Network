import { i18n } from "./i18n.js";
import { ELEVATOR_COLOR, ELEVATOR_LAYER_IDS, HIGHWAY_LAYERS } from "./layers.js";
import {
  ISLAND_TYPES, KERB_ISSUE_TYPES, MISSING_CROSSING_TYPES, SIDEWALK_STATUSES,
  activeIslandTypes, activeKerbIssueTypes, activeMissingTypes, activeSidewalkStatuses,
  updateIslandsFilter, updateKerbIssuesFilter, updateMissingCrossingsFilter, updateSidewalkFilter,
} from "./type-filters.js";

export function buildLegend(map) {
  const legendEl = document.getElementById("legend-content");
  const addSection = (txt) => {
    const s = document.createElement("div");
    s.className = "legend-section";
    s.textContent = txt;
    legendEl.appendChild(s);
  };

  const makeItem = ({ layerId, label, color, color2, swatchType = "line", dashed = false, onToggle = null, linkedLayerIds = [] }) => {
    const item = document.createElement("div");
    item.className = "legend-item";
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");

    const swatch = document.createElement("div");
    swatch.className = `legend-${swatchType}`;
    if (color2) {
      swatch.classList.add(swatchType === "dot" ? "gradient-dot" : "gradient");
      swatch.style.setProperty("--c1", color);
      swatch.style.setProperty("--c2", color2);
    } else if (dashed) {
      swatch.classList.add("dashed");
      swatch.style.setProperty("--c", color);
    } else {
      swatch.style.background = color;
    }
    const lbl = document.createElement("span");
    lbl.className = "legend-label";
    lbl.textContent = label;
    item.append(swatch, lbl);

    const updateState = (byUser = false, notify = true) => {
      const isHidden = map.getLayoutProperty(layerId, "visibility") === "none";
      item.classList.toggle("hidden", isHidden);
      item.setAttribute("aria-pressed", !isHidden);
      if (onToggle && notify) onToggle(!isHidden, byUser);
    };
    updateState();

    const toggle = () => {
      const v = map.getLayoutProperty(layerId, "visibility") === "none" ? "visible" : "none";
      map.setLayoutProperty(layerId, "visibility", v);
      linkedLayerIds.forEach(id => map.setLayoutProperty(id, "visibility", v));
      updateState(true);
    };
    item.onclick = toggle;
    item.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
    item.sync = () => updateState(false, false);
    return item;
  };

  const makeKerbTypeItem = ({ type, label, color }) => {
    const item = document.createElement("div");
    item.className = "legend-item";
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");

    const swatch = document.createElement("div");
    swatch.className = "legend-dot";
    swatch.style.background = color;

    const lbl = document.createElement("span");
    lbl.className = "legend-label";
    lbl.textContent = label;
    item.append(swatch, lbl);

    const updateState = () => {
      const isActive = activeKerbIssueTypes.has(type);
      item.classList.toggle("hidden", !isActive);
      item.setAttribute("aria-pressed", isActive);
    };
    updateState();

    const toggle = () => {
      if (activeKerbIssueTypes.has(type)) activeKerbIssueTypes.delete(type);
      else activeKerbIssueTypes.add(type);
      updateState();
      setVisibilityIfLayer(map, "kerb-issues", activeKerbIssueTypes.size > 0);
      updateKerbIssuesFilter();
    };
    item.onclick = toggle;
    item.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
    return item;
  };

  const makeSubFilter = ({ items, activeSet, dataKey, updateFn, parentSub, layerId, parentItem }) => {
    const header = document.createElement("div");
    header.className = "legend-sub-header";
    header.innerHTML = html`<span>${i18n.t("legend.filterByType")}</span>`;

    const resetBtn = document.createElement("button");
    resetBtn.className = "legend-sub-reset";
    resetBtn.type = "button";

    const isLayerVisible = () => map.getLayoutProperty(layerId, "visibility") !== "none";

    const refresh = () => {
      const shown = isLayerVisible();
      parentSub.querySelectorAll(".legend-sub-item").forEach(el => {
        const on = shown && activeSet.has(el.dataset[dataKey]);
        el.classList.toggle("hidden", !on);
        el.setAttribute("aria-pressed", on);
      });
      resetBtn.textContent = shown && activeSet.size === items.length
        ? i18n.t("legend.deselectAll") : i18n.t("legend.selectAll");
    };

    const apply = () => {
      const visible = activeSet.size > 0;
      if (visible !== isLayerVisible()) {
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
        parentItem.sync();
      }
      updateFn();
      refresh();
    };

    resetBtn.onclick = (e) => {
      e.stopPropagation();
      const allOn = isLayerVisible() && activeSet.size === items.length;
      activeSet.clear();
      if (!allOn) items.forEach(it => activeSet.add(it.value));
      apply();
    };
    header.appendChild(resetBtn);
    parentSub.appendChild(header);

    items.forEach(it => {
      const item = document.createElement("div");
      item.className = "legend-sub-item";
      item.dataset[dataKey] = it.value;
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");

      const dot = document.createElement("div");
      dot.className = "legend-sub-dot";
      dot.style.background = it.color;

      const lbl = document.createElement("span");
      lbl.className = "legend-sub-label";
      lbl.textContent = it.label;

      item.append(dot, lbl);

      const toggle = (e) => {
        e.stopPropagation();
        if (!isLayerVisible()) activeSet.clear();
        if (activeSet.has(it.value)) activeSet.delete(it.value);
        else activeSet.add(it.value);
        apply();
      };
      item.onclick = toggle;
      item.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } };
      parentSub.appendChild(item);
    });

    refresh();
    return { refresh };
  };

  const addFilteredLayer = ({ layerId, label, color, color2, swatchType, items, activeSet, dataKey, updateFn }) => {
    const sub = document.createElement("div");
    sub.className = "legend-sub";
    let filter = null;
    const parentItem = makeItem({
      layerId, label, color, color2, swatchType,
      onToggle: (isVisible, byUser) => {
        if (isVisible && byUser) {
          items.forEach(it => activeSet.add(it.value));
          updateFn();
        }
        if (filter) filter.refresh();
      }
    });
    legendEl.appendChild(parentItem);
    filter = makeSubFilter({ items, activeSet, dataKey, updateFn, parentSub: sub, layerId, parentItem });
    legendEl.appendChild(sub);
  };

  addSection(i18n.t("legend.section.routing"));
  legendEl.appendChild(makeItem({ layerId: "flow-ped",      label: i18n.t("layer.flow.pedestrian"), color: "#bbf7d0", color2: "#14532d" }));
  legendEl.appendChild(makeItem({ layerId: "flow-cycleway",  label: i18n.t("layer.flow.cycleway"), color: "#bfdbfe", color2: "#3b0764" }));
  legendEl.appendChild(makeItem({ layerId: "flow-road",      label: i18n.t("layer.flow.road"), color: "#fdba74", color2: "#450a0a" }));

  addSection(i18n.t("legend.section.quality"));
  legendEl.appendChild(makeItem({ layerId: "sidewalk-gaps", label: i18n.t("layer.sidewalkGaps"), color: "#f59e0b", dashed: true }));
  legendEl.appendChild(makeItem({ layerId: "footway-crossing-candidates", label: i18n.t("layer.crossingCandidates"), color: "#7f1d1d", dashed: true }));
  legendEl.appendChild(makeItem({ layerId: "tactile-paving-issues", label: i18n.t("layer.tactilePaving"), color: "#a855f7", swatchType: "dot" }));

  KERB_ISSUE_TYPES.forEach(t => {
    legendEl.appendChild(makeKerbTypeItem({ type: t.value, label: t.label, color: t.color }));
  });

  addFilteredLayer({
    layerId:   "missing-crossings",
    label:     i18n.t("layer.missingCrossings"),
    color:     "#f97316",
    swatchType: "dot",
    items:     MISSING_CROSSING_TYPES,
    activeSet: activeMissingTypes,
    dataKey:   "type",
    updateFn:  updateMissingCrossingsFilter,
  });

  addFilteredLayer({
    layerId:   "graph-islands",
    label:     i18n.t("layer.islands"),
    color:     "#db2777",
    color2:    "#0d9488",
    items:     ISLAND_TYPES,
    activeSet: activeIslandTypes,
    dataKey:   "islandType",
    updateFn:  updateIslandsFilter,
  });

  addFilteredLayer({
    layerId:   "sidewalk-roads",
    label:     i18n.t("layer.sidewalkTags"),
    color:     "#9ca3af",
    color2:    "#15803d",
    items:     SIDEWALK_STATUSES,
    activeSet: activeSidewalkStatuses,
    dataKey:   "status",
    updateFn:  updateSidewalkFilter,
  });

  addSection(i18n.t("legend.section.network"));
  HIGHWAY_LAYERS.forEach(l => legendEl.appendChild(makeItem({ layerId: `highway-${l.id}`, label: l.label, color: l.color, dashed: l.dash })));
  legendEl.appendChild(makeItem({
    layerId: ELEVATOR_LAYER_IDS[0], linkedLayerIds: ELEVATOR_LAYER_IDS.slice(1),
    label: i18n.t("layer.elevator"), color: ELEVATOR_COLOR, swatchType: "dot",
  }));
}
