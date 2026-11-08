const LEVEL_VALUES_SEPARATOR = "|";

function formatLevels(p, i18n) {
  if (p.level_values == null) return "—";
  const untagged = i18n.t("popup.levels.untagged");
  const values = String(p.level_values).split(LEVEL_VALUES_SEPARATOR).map(v => v || untagged);
  const missing = String(p.level_missing ?? "");
  return missing ? i18n.t("popup.levels.missing", { values: values[0], level: missing }) : values.join(" ≠ ");
}

function popupTitle(color, text) {
  const sw = color ? `<span class="popup-swatch" style="--c:${color}"></span>` : "";
  return `<div class="popup-title">${sw}${text}</div>`;
}

function escapeHTML(str) {
  if (!str) return str;
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function htmlText(i18n) {
  return (key, vars) => escapeHTML(i18n.t(key, vars));
}

function measureText(i18n, value, options = { maximumFractionDigits: 1 }) {
  const number = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(number)) return value;
  return i18n.number(number, options);
}

function formatMeasure(i18n, value, options) {
  return escapeHTML(measureText(i18n, value, options));
}

function formatShare(i18n, value) {
  const number = Number(value ?? 0);
  if (value === "" || !Number.isFinite(number)) return `${escapeHTML(value)} %`;
  return escapeHTML(i18n.percent(number));
}

function popupRow(label, value) {
  return `<div class="popup-row"><span class="label">${label}</span><span class="value">${value}</span></div>`;
}

function formatWrongTagCrossing(p, i18n) {
  const tx = htmlText(i18n);
  const nid = parseInt(p.osm_id, 10) || 0;
  const wid = parseInt(p.way_osm_id, 10) || 0;
  const val = p.footway_value || "sidewalk";
  const objs = [nid > 0 ? `n${nid}` : "", wid > 0 ? `w${wid}` : ""].filter(Boolean).join(",");
  return `
    ${popupTitle("#dc2626", tx("popup.missingCrossing.wrongTagTitle", { value: val }))}
    ${popupRow(tx("popup.label.street"), escapeHTML(p.name || "—"))}
    ${popupRow(tx("popup.label.problem"), tx("popup.missingCrossing.wrongTagProblem", { value: val }))}
    ${nid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.node")}</span><span class="value">
      <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
    </span></div>` : ""}
    ${wid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.way")}</span><span class="value">
      <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
      · <a href="https://www.openstreetmap.org/edit?way=${wid}" target="_blank" rel="noopener">iD</a>
    </span></div>` : ""}
    ${objs ? `<div class="popup-row"><span class="label">${tx("popup.label.edit")}</span><span class="value">
      <a href="http://127.0.0.1:8111/load_object?objects=${objs}" target="_blank" rel="noopener">JOSM</a>
    </span></div>` : ""}
  `;
}

function makePopupLayers({ flowColors, sidewalkStatuses, highwayLayers, elevatorColor, elevatorLayerIds }, i18n) {
  const tx = htmlText(i18n);
  const infraLabels = {
    pedestrian: tx("popup.infra.pedestrian"),
    road: tx("popup.infra.road"),
    cycleway_foot_yes: tx("popup.infra.cyclewayFootYes"),
    cycleway_no_foot: tx("popup.infra.cyclewayNoFoot"),
  };
  const sidewalkLabels = {
    separate: escapeHTML("sidewalk:both=separate"),
    yes: tx("popup.sidewalk.yes"),
    documented: tx("popup.sidewalk.documented"),
    partial: tx("popup.sidewalk.partial"),
    unknown: tx("popup.sidewalk.unknown"),
  };
  const reasonLabels = {
    value_mismatch: tx("popup.tactile.reason.valueMismatch"),
    incorrect_not_mixed: tx("popup.tactile.reason.incorrectNotMixed"),
  };
  const known = (labels, value) => Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : null;
  const hover = [
    {
      ids: ["sidewalk-gaps"],
      format: p => `
        ${popupTitle("#f59e0b", tx("layer.sidewalkGaps"))}
        ${popupRow(tx("popup.label.street"), escapeHTML(p.name || "—"))}
      `
    },
    {
      ids: ["footway-crossing-candidates"],
      format: p => `
        ${popupTitle("#7f1d1d", tx("layer.crossingCandidates"))}
        ${popupRow(tx("popup.label.crossedStreet"), escapeHTML(p.name || "—"))}
        ${popupRow(tx("popup.label.length"), `${formatMeasure(i18n, p.length_m)} m`)}
      `
    },
    {
      ids: ["sidewalk-roads"],
      format: p => {
        return `
          ${popupTitle((sidewalkStatuses.find(s => s.value === p.sw) || {}).color, tx("layer.sidewalkTags"))}
          ${popupRow(tx("popup.label.street"), escapeHTML(p.name || "—"))}
          ${popupRow(tx("popup.label.status"), known(sidewalkLabels, p.sw) || escapeHTML(p.sw || "?"))}
        `;
      }
    },
    {
      ids: ["flow-ped", "flow-cycleway", "flow-road"],
      format: p => `
        ${popupTitle(flowColors[p.infra_type], tx("popup.flow.title"))}
        ${popupRow(tx("popup.label.infrastructure"), known(infraLabels, p.infra_type) || escapeHTML(String(p.infra_type || "—").replace(/_/g, " ")))}
        ${popupRow("highway", escapeHTML(p.highway || "—"))}
        ${popupRow(tx("popup.label.relativeFlow"), formatShare(i18n, p.flow_pct))}
      `
    },
    {
      ids: highwayLayers.map(l => `highway-${l.id}`).concat(["highway-crossing"], elevatorLayerIds),
      format: p => {
        const entries = Object.entries(p).filter(([k]) => !k.startsWith("@") && k !== "tippecanoe");
        const isElevator = p.highway === "elevator" || p.amenity === "elevator";
        const titleColor = isElevator ? elevatorColor : ((highwayLayers.find(l => l.id === p.highway) || {}).color || "#15803d");
        return `
          ${popupTitle(titleColor, p.highway ? escapeHTML(p.highway) : isElevator ? "elevator" : tx("popup.label.infrastructure"))}
          ${entries.map(([k, v]) => `<div class="popup-row"><span class="label">${escapeHTML(k)}</span><span class="value">${escapeHTML(v)}</span></div>`).join("")}
        `;
      }
    },
  ];

  const click = [
    {
      ids: ["missing-crossings"],
      format: p => {
        if (p.type === "wrong_tag") return formatWrongTagCrossing(p, i18n);
        const isMissingWay = p.type === "missing_way";
        const nearM = (typeof p.nearest_tag_m === "number" && p.nearest_tag_m >= 0)
          ? p.nearest_tag_m : null;
        const radius = p.detect_radius || 3;
        const nid = parseInt(p.osm_id, 10) || 0;
        return `
          ${isMissingWay ? popupTitle("#f97316", tx("popup.missingCrossing.missingWayTitle")) : popupTitle("#eab308", tx("layer.missingCrossing.missingTag"))}
          ${popupRow(tx("popup.label.street"), escapeHTML(p.name || "—"))}
          ${popupRow(tx("popup.label.problem"), isMissingWay
            ? tx("popup.missingCrossing.missingWayProblem")
            : tx("popup.missingCrossing.missingTagProblem"))}
          ${nearM !== null && !isMissingWay ? popupRow(tx("popup.label.nearestCrossing"), `${formatMeasure(i18n, nearM)} m <span class="popup-note">${tx("popup.note.radius", { radius: measureText(i18n, radius) })}</span>`) : ""}
          ${nid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.node")}</span><span class="value">
            <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=n${nid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?node=${nid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
        `;
      }
    },
    {
      ids: ["footway-crossing-candidates"],
      format: p => {
        const wid = parseInt(p.osm_id, 10) || 0;
        return `
          ${popupTitle("#7f1d1d", tx("layer.crossingCandidates"))}
          ${popupRow(tx("popup.label.crossedStreet"), escapeHTML(p.name || "—"))}
          ${popupRow(tx("popup.label.length"), `${formatMeasure(i18n, p.length_m)} m`)}
          ${popupRow(tx("popup.label.problem"), tx("popup.crossingCandidate.problem"))}
          ${wid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.way")}</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?way=${wid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
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
        return `
          ${popupTitle("#a855f7", tx("layer.tactilePaving"))}
          ${popupRow(tx("popup.label.crossing"), `tactile_paving=${escapeHTML(p.crossing_tp || "?")}`)}
          ${popupRow(tx("popup.label.kerbSide", { side: 1 }), escapeHTML(p.kerb1_tp) || tx("popup.value.absent"))}
          ${sidesChecked === 2
            ? popupRow(tx("popup.label.kerbSide", { side: 2 }), escapeHTML(p.kerb2_tp) || tx("popup.value.absent"))
            : `<div class="popup-row"><span class="label">${tx("popup.label.kerbSide", { side: 2 })}</span><span class="value popup-note">${tx("popup.note.notChecked")}</span></div>`
          }
          ${popupRow(tx("popup.label.problem"), known(reasonLabels, p.reason) || escapeHTML(p.reason || "?"))}
          ${nid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.crossingNode")}</span><span class="value">
            <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=n${nid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?node=${nid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
          ${wid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.crossingWay")}</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}${pwid > 0 ? `,w${pwid}` : ""}" target="_blank" rel="noopener">JOSM</a>
          </span></div>` : ""}
          ${pwid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.adjacentWay")}</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${pwid}" target="_blank" rel="noopener">w${pwid}</a>
            <span class="popup-note">${tx("popup.note.sameCrossing")}</span>
          </span></div>` : ""}
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
        const pad = 0.0005;
        const w = Number(p.bbox_w) - pad, s = Number(p.bbox_s) - pad;
        const e = Number(p.bbox_e) + pad, n = Number(p.bbox_n) + pad;
        const hasBbox = [w, s, e, n].every(Number.isFinite);
        const selIds = ways.map(id => "w" + id).concat(nodeId > 0 ? ["n" + nodeId] : []);
        const select = selIds.length ? `&select=${selIds.join(",")}` : "";
        const josm = hasBbox
          ? `http://127.0.0.1:8111/load_and_zoom?left=${w.toFixed(6)}&right=${e.toFixed(6)}&top=${n.toFixed(6)}&bottom=${s.toFixed(6)}${select}`
          : null;
        const idLink = ways.length
          ? `https://www.openstreetmap.org/edit?way=${ways[0]}`
          : (hasBbox ? `https://www.openstreetmap.org/edit#map=19/${((s + n) / 2).toFixed(6)}/${((w + e) / 2).toFixed(6)}` : null);
        return `
          ${isLevel ? popupTitle("#ea580c", tx("layer.island.level")) : isUnjoined ? popupTitle("#db2777", tx("popup.island.unjoinedTitle")) : popupTitle("#0d9488", tx("popup.island.isolatedTitle"))}
          ${popupRow(tx("popup.label.problem"), isLevel
            ? tx("popup.island.levelProblem")
            : isUnjoined ? tx("popup.island.unjoinedProblem") : tx("popup.island.isolatedProblem"))}
          ${isLevel
            ? `${popupRow(tx("popup.label.levels"), escapeHTML(formatLevels(p, i18n)))}
          ${nodeId > 0 ? popupRow(tx("popup.label.node"), `<a href="https://www.openstreetmap.org/node/${nodeId}" target="_blank" rel="noopener">n${nodeId}</a>`) : ""}`
            : popupRow(tx("popup.label.gapToNetwork"), gap !== null ? `${formatMeasure(i18n, gap)} m` : "—")
          }
          ${popupRow(tx("popup.label.length"), `${formatMeasure(i18n, Math.round(Number(p.length_m) || 0))} m`)}
          ${popupRow(tx("popup.label.types"), escapeHTML(p.highways || "—"))}
          <div class="popup-row"><span class="label">${tx("popup.label.ways")}</span><span class="value">${ways.length
            ? ways.slice(0, 5).map(id => `<a href="https://www.openstreetmap.org/way/${id}" target="_blank" rel="noopener">w${id}</a>`).join(" ") + (ways.length > 5 ? ` +${ways.length - 5}` : "")
            : "—"
          }</span></div>
          ${josm || idLink ? `<div class="popup-row"><span class="label">${tx("popup.label.edit")}</span><span class="value">
            ${josm ? `<a href="${josm}" target="_blank" rel="noopener">JOSM</a>` : ""}
            ${josm && idLink ? " · " : ""}
            ${idLink ? `<a href="${idLink}" target="_blank" rel="noopener">iD</a>` : ""}
          </span></div>` : ""}
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
        return `
          ${isMissing ? popupTitle("#1e3a8a", tx("layer.kerb.missing")) : popupTitle("#7c2d12", tx("layer.kerb.untagged"))}
          ${popupRow(tx("popup.label.problem"), isMissing ? tx("popup.kerb.missingProblem") : tx("popup.kerb.untaggedProblem"))}
          ${cid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.crossing")}</span><span class="value">
            <a href="https://www.openstreetmap.org/node/${cid}" target="_blank" rel="noopener">n${cid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=n${cid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?node=${cid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
          ${!isMissing && kid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.kerb")}</span><span class="value">
            <a href="https://www.openstreetmap.org/node/${kid}" target="_blank" rel="noopener">n${kid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=n${kid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?node=${kid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
          ${wid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.crossingWay")}</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}${pwid > 0 ? `,w${pwid}` : ""}" target="_blank" rel="noopener">JOSM</a>
          </span></div>` : ""}
          ${pwid > 0 ? `<div class="popup-row"><span class="label">${tx("popup.label.adjacentWay")}</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${pwid}" target="_blank" rel="noopener">w${pwid}</a>
            <span class="popup-note">${tx("popup.note.sameCrossing")}</span>
          </span></div>` : ""}
        `;
      }
    },
  ];

  return { hover, click };
}

if (typeof module !== "undefined") {
  module.exports = { escapeHTML, popupTitle, formatMeasure, formatShare, formatWrongTagCrossing, formatLevels, makePopupLayers };
}
