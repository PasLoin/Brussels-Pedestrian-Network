if (typeof module !== "undefined" && module.exports) Object.assign(globalThis, require("./html.js"));

const LEVEL_VALUES_SEPARATOR = "|";
const OSM = "https://www.openstreetmap.org";
const JOSM = "http://127.0.0.1:8111";
const ID_EDITOR = `${OSM}/edit?editor=id`;

function formatLevels(p, i18n) {
  if (p.level_values == null) return "—";
  const untagged = i18n.t("popup.levels.untagged");
  const values = String(p.level_values).split(LEVEL_VALUES_SEPARATOR).map(v => v || untagged);
  const missing = String(p.level_missing ?? "");
  return missing ? i18n.t("popup.levels.missing", { values: values[0], level: missing }) : values.join(" ≠ ");
}

function popupTitle(color, text) {
  return html`<div class="popup-title">${color ? html`<span class="popup-swatch" style="--c:${color}"></span>` : ""}${text}</div>`;
}

function popupRow(label, value, valueClass = "value") {
  return html`<div class="popup-row"><span class="label">${label}</span><span class="${valueClass}">${value}</span></div>`;
}

function formatMeasure(i18n, value, options = { maximumFractionDigits: 1 }) {
  const number = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(number)) return value;
  return i18n.number(number, options);
}

function formatShare(i18n, value) {
  const number = Number(value ?? 0);
  if (value === "" || !Number.isFinite(number)) return `${value} %`;
  return i18n.percent(number);
}

function link(href, text) {
  return html`<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
}

function josmObjects(...objects) {
  return `${JOSM}/load_object?objects=${objects.filter(Boolean).join(",")}`;
}

function nodeLinks(id) {
  return html`${link(`${OSM}/node/${id}`, `n${id}`)} · ${link(josmObjects(`n${id}`), "JOSM")} · ${link(`${ID_EDITOR}&node=${id}`, "iD")}`;
}

function wayLinks(id) {
  return html`${link(`${OSM}/way/${id}`, `w${id}`)} · ${link(josmObjects(`w${id}`), "JOSM")} · ${link(`${ID_EDITOR}&way=${id}`, "iD")}`;
}

function crossingWayLinks(id, partnerId) {
  return html`${link(`${OSM}/way/${id}`, `w${id}`)} · ${link(josmObjects(`w${id}`, partnerId > 0 && `w${partnerId}`), "JOSM")}`;
}

function formatWrongTagCrossing(p, i18n) {
  const { t } = i18n;
  const nid = parseInt(p.osm_id, 10) || 0;
  const wid = parseInt(p.way_osm_id, 10) || 0;
  const val = p.footway_value || "sidewalk";
  const objs = [nid > 0 && `n${nid}`, wid > 0 && `w${wid}`].filter(Boolean);
  return html`
    ${popupTitle("#dc2626", t("popup.missingCrossing.wrongTagTitle", { value: val }))}
    ${popupRow(t("popup.label.street"), p.name || "—")}
    ${popupRow(t("popup.label.problem"), t("popup.missingCrossing.wrongTagProblem", { value: val }))}
    ${nid > 0 && popupRow(t("popup.label.node"), link(`${OSM}/node/${nid}`, `n${nid}`))}
    ${wid > 0 && popupRow(t("popup.label.way"), html`${link(`${OSM}/way/${wid}`, `w${wid}`)} · ${link(`${ID_EDITOR}&way=${wid}`, "iD")}`)}
    ${objs.length > 0 && popupRow(t("popup.label.edit"), link(josmObjects(...objs), "JOSM"))}
  `;
}

function islandEditLinks(p, ways, nodeId) {
  const pad = 0.0005;
  const w = Number(p.bbox_w) - pad, s = Number(p.bbox_s) - pad;
  const e = Number(p.bbox_e) + pad, n = Number(p.bbox_n) + pad;
  const hasBbox = [w, s, e, n].every(Number.isFinite);
  const selIds = ways.map(id => "w" + id).concat(nodeId > 0 ? ["n" + nodeId] : []);
  const select = selIds.length ? `&select=${selIds.join(",")}` : "";
  const josm = hasBbox
    ? `${JOSM}/load_and_zoom?left=${w.toFixed(6)}&right=${e.toFixed(6)}&top=${n.toFixed(6)}&bottom=${s.toFixed(6)}${select}`
    : null;
  const idLink = ways.length
    ? `${ID_EDITOR}&way=${ways[0]}`
    : (hasBbox ? `${ID_EDITOR}#map=19/${((s + n) / 2).toFixed(6)}/${((w + e) / 2).toFixed(6)}` : null);
  return [josm && link(josm, "JOSM"), idLink && link(idLink, "iD")].filter(Boolean);
}

function makePopupLayers({ flowColors, sidewalkStatuses, highwayLayers, elevatorColor, elevatorLayerIds, editHere = () => false }, i18n) {
  const { t } = i18n;
  const infraLabels = {
    pedestrian: t("popup.infra.pedestrian"),
    road: t("popup.infra.road"),
    cycleway_foot_yes: t("popup.infra.cyclewayFootYes"),
    cycleway_no_foot: t("popup.infra.cyclewayNoFoot"),
  };
  const sidewalkLabels = {
    separate: "sidewalk:both=separate",
    yes: t("popup.sidewalk.yes"),
    documented: t("popup.sidewalk.documented"),
    partial: t("popup.sidewalk.partial"),
    unknown: t("popup.sidewalk.unknown"),
  };
  const reasonLabels = {
    value_mismatch: t("popup.tactile.reason.valueMismatch"),
    incorrect_not_mixed: t("popup.tactile.reason.incorrectNotMixed"),
  };
  const known = (labels, value) => Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : null;
  const absent = t("popup.value.absent");

  const hover = [
    {
      ids: ["sidewalk-gaps"],
      format: p => html`
        ${popupTitle("#f59e0b", t("layer.sidewalkGaps"))}
        ${popupRow(t("popup.label.street"), p.name || "—")}
      `
    },
    {
      ids: ["footway-crossing-candidates"],
      format: p => html`
        ${popupTitle("#7f1d1d", t("layer.crossingCandidates"))}
        ${popupRow(t("popup.label.crossedStreet"), p.name || "—")}
        ${popupRow(t("popup.label.length"), `${formatMeasure(i18n, p.length_m)} m`)}
      `
    },
    {
      ids: ["sidewalk-roads"],
      format: p => html`
        ${popupTitle((sidewalkStatuses.find(s => s.value === p.sw) || {}).color, t("layer.sidewalkTags"))}
        ${popupRow(t("popup.label.street"), p.name || "—")}
        ${popupRow(t("popup.label.status"), known(sidewalkLabels, p.sw) || p.sw || "?")}
      `
    },
    {
      ids: ["flow-ped", "flow-cycleway", "flow-road"],
      format: p => html`
        ${popupTitle(flowColors[p.infra_type], t("popup.flow.title"))}
        ${popupRow(t("popup.label.infrastructure"), known(infraLabels, p.infra_type) || String(p.infra_type || "—").replace(/_/g, " "))}
        ${popupRow("highway", p.highway || "—")}
        ${popupRow(t("popup.label.relativeFlow"), formatShare(i18n, p.flow_pct))}
      `
    },
    {
      ids: highwayLayers.map(l => `highway-${l.id}`).concat(["highway-crossing"], elevatorLayerIds),
      format: p => {
        const entries = Object.entries(p).filter(([k]) => !k.startsWith("@") && k !== "tippecanoe");
        const isElevator = p.highway === "elevator" || p.amenity === "elevator";
        const titleColor = isElevator ? elevatorColor : ((highwayLayers.find(l => l.id === p.highway) || {}).color || "#15803d");
        return html`
          ${popupTitle(titleColor, p.highway || (isElevator ? "elevator" : t("popup.label.infrastructure")))}
          ${entries.map(([k, v]) => popupRow(k, v))}
        `;
      }
    },
  ];

  const click = [
    {
      ids: ["sidewalk-roads"],
      format: p => {
        const wid = parseInt(p.osm_id, 10) || 0;
        const length = Number(p.length_m);
        return html`
          ${popupTitle((sidewalkStatuses.find(s => s.value === p.sw) || {}).color, t("layer.sidewalkTags"))}
          ${popupRow(t("popup.label.street"), p.name || "—")}
          ${popupRow(t("popup.label.status"), known(sidewalkLabels, p.sw) || p.sw || "?")}
          ${popupRow("highway", p.highway || "—")}
          ${Number.isFinite(length) && length > 0 && popupRow(t("popup.label.length"), `${formatMeasure(i18n, Math.round(length))} m`)}
          ${wid > 0 && popupRow(t("popup.label.way"), editHere(p)
            ? html`${wayLinks(wid)} · <button type="button" class="popup-edit" data-bpn-edit-way="${wid}">${t("popup.editHere")}</button>`
            : wayLinks(wid))}
        `;
      }
    },
    {
      ids: ["missing-crossings"],
      format: p => {
        if (p.type === "wrong_tag") return formatWrongTagCrossing(p, i18n);
        const isMissingWay = p.type === "missing_way";
        const nearM = (typeof p.nearest_tag_m === "number" && p.nearest_tag_m >= 0) ? p.nearest_tag_m : null;
        const radius = p.detect_radius || 3;
        const nid = parseInt(p.osm_id, 10) || 0;
        return html`
          ${isMissingWay ? popupTitle("#f97316", t("popup.missingCrossing.missingWayTitle")) : popupTitle("#eab308", t("layer.missingCrossing.missingTag"))}
          ${popupRow(t("popup.label.street"), p.name || "—")}
          ${popupRow(t("popup.label.problem"), isMissingWay ? t("popup.missingCrossing.missingWayProblem") : t("popup.missingCrossing.missingTagProblem"))}
          ${nearM !== null && !isMissingWay && popupRow(t("popup.label.nearestCrossing"),
            html`${formatMeasure(i18n, nearM)} m <span class="popup-note">${t("popup.note.radius", { radius: formatMeasure(i18n, radius) })}</span>`)}
          ${nid > 0 && popupRow(t("popup.label.node"), nodeLinks(nid))}
        `;
      }
    },
    {
      ids: ["footway-crossing-candidates"],
      format: p => {
        const wid = parseInt(p.osm_id, 10) || 0;
        return html`
          ${popupTitle("#7f1d1d", t("layer.crossingCandidates"))}
          ${popupRow(t("popup.label.crossedStreet"), p.name || "—")}
          ${popupRow(t("popup.label.length"), `${formatMeasure(i18n, p.length_m)} m`)}
          ${popupRow(t("popup.label.problem"), t("popup.crossingCandidate.problem"))}
          ${wid > 0 && popupRow(t("popup.label.way"), editHere(p)
            ? html`${wayLinks(wid)} · <button type="button" class="popup-edit" data-bpn-edit-way="${wid}">${t("popup.editHere")}</button>`
            : wayLinks(wid))}
        `;
      }
    },
    {
      ids: ["tactile-paving-issues"],
      format: p => {
        const nid = parseInt(p.osm_id, 10) || 0;
        const wid = parseInt(p.way_osm_id, 10) || 0;
        const pwid = parseInt(p.partner_way_osm_id, 10) || 0;
        const sidesChecked = parseInt(p.sides_checked, 10) || 2;
        return html`
          ${popupTitle("#a855f7", t("layer.tactilePaving"))}
          ${popupRow(t("popup.label.crossing"), `tactile_paving=${p.crossing_tp || "?"}`)}
          ${popupRow(t("popup.label.kerbSide", { side: 1 }), p.kerb1_tp || absent)}
          ${sidesChecked === 2
            ? popupRow(t("popup.label.kerbSide", { side: 2 }), p.kerb2_tp || absent)
            : popupRow(t("popup.label.kerbSide", { side: 2 }), t("popup.note.notChecked"), "value popup-note")}
          ${popupRow(t("popup.label.problem"), known(reasonLabels, p.reason) || p.reason || "?")}
          ${nid > 0 && popupRow(t("popup.label.crossingNode"), nodeLinks(nid))}
          ${wid > 0 && popupRow(t("popup.label.crossingWay"), crossingWayLinks(wid, pwid))}
          ${pwid > 0 && popupRow(t("popup.label.adjacentWay"),
            html`${link(`${OSM}/way/${pwid}`, `w${pwid}`)} <span class="popup-note">${t("popup.note.sameCrossing")}</span>`)}
        `;
      }
    },
    {
      ids: ["graph-islands"],
      format: p => {
        const isUnjoined = p.type === "unjoined";
        const isLevel = p.type === "level";
        const nodeId = parseInt(p.node_id, 10) || 0;
        const ways = String(p.way_ids || "").split(",").map(w => parseInt(w, 10)).filter(w => w > 0);
        const gap = (typeof p.gap_m === "number" && p.gap_m >= 0) ? p.gap_m : null;
        const editLinks = islandEditLinks(p, ways, nodeId);
        const wayList = ways.length
          ? html`${ways.slice(0, 5).map((id, i) => html`${i > 0 ? " " : ""}${link(`${OSM}/way/${id}`, `w${id}`)}`)}${ways.length > 5 ? ` +${ways.length - 5}` : ""}`
          : "—";
        return html`
          ${isLevel ? popupTitle("#ea580c", t("layer.island.level")) : isUnjoined ? popupTitle("#db2777", t("popup.island.unjoinedTitle")) : popupTitle("#0d9488", t("popup.island.isolatedTitle"))}
          ${popupRow(t("popup.label.problem"), isLevel ? t("popup.island.levelProblem") : isUnjoined ? t("popup.island.unjoinedProblem") : t("popup.island.isolatedProblem"))}
          ${isLevel
            ? html`${popupRow(t("popup.label.levels"), formatLevels(p, i18n))}
          ${nodeId > 0 && popupRow(t("popup.label.node"), link(`${OSM}/node/${nodeId}`, `n${nodeId}`))}`
            : popupRow(t("popup.label.gapToNetwork"), gap !== null ? `${formatMeasure(i18n, gap)} m` : "—")}
          ${popupRow(t("popup.label.length"), `${formatMeasure(i18n, Math.round(Number(p.length_m) || 0))} m`)}
          ${popupRow(t("popup.label.types"), p.highways || "—")}
          ${popupRow(t("popup.label.ways"), wayList)}
          ${editLinks.length > 0 && popupRow(t("popup.label.edit"), editLinks.map((l, i) => html`${i > 0 ? " · " : ""}${l}`))}
        `;
      }
    },
    {
      ids: ["kerb-issues"],
      format: p => {
        const isMissing = p.type === "kerb_missing";
        const cid = parseInt(p.crossing_osm_id, 10) || 0;
        const wid = parseInt(p.way_osm_id, 10) || 0;
        const kid = parseInt(p.kerb_osm_id, 10) || 0;
        const pwid = parseInt(p.partner_way_osm_id, 10) || 0;
        return html`
          ${isMissing ? popupTitle("#1e3a8a", t("layer.kerb.missing")) : popupTitle("#7c2d12", t("layer.kerb.untagged"))}
          ${popupRow(t("popup.label.problem"), isMissing ? t("popup.kerb.missingProblem") : t("popup.kerb.untaggedProblem"))}
          ${cid > 0 && popupRow(t("popup.label.crossing"), nodeLinks(cid))}
          ${!isMissing && kid > 0 && popupRow(t("popup.label.kerb"), nodeLinks(kid))}
          ${wid > 0 && popupRow(t("popup.label.crossingWay"), crossingWayLinks(wid, pwid))}
          ${pwid > 0 && popupRow(t("popup.label.adjacentWay"),
            html`${link(`${OSM}/way/${pwid}`, `w${pwid}`)} <span class="popup-note">${t("popup.note.sameCrossing")}</span>`)}
        `;
      }
    },
  ];

  const asText = entries => entries.map(entry => ({ ...entry, format: p => String(entry.format(p)) }));
  return { hover: asText(hover), click: asText(click) };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { escapeHTML, popupTitle, formatMeasure, formatShare, formatWrongTagCrossing, formatLevels, makePopupLayers };
}
