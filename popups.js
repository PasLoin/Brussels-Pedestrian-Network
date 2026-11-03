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

function formatWrongTagCrossing(p) {
  const nid = parseInt(p.osm_id, 10) || 0;
  const wid = parseInt(p.way_osm_id, 10) || 0;
  const val = p.footway_value || "sidewalk";
  const objs = [nid > 0 ? `n${nid}` : "", wid > 0 ? `w${wid}` : ""].filter(Boolean).join(",");
  return `
    ${popupTitle("#dc2626", `Traversée taguée footway=${escapeHTML(val)}`)}
    <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
    <div class="popup-row"><span class="label">Problème</span><span class="value">Le way qui traverse la route au nœud crossing porte footway=${escapeHTML(val)} au lieu de footway=crossing</span></div>
    ${nid > 0 ? `<div class="popup-row"><span class="label">Nœud</span><span class="value">
      <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
    </span></div>` : ""}
    ${wid > 0 ? `<div class="popup-row"><span class="label">Way</span><span class="value">
      <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
      · <a href="https://www.openstreetmap.org/edit?way=${wid}" target="_blank" rel="noopener">iD</a>
    </span></div>` : ""}
    ${objs ? `<div class="popup-row"><span class="label">Éditer</span><span class="value">
      <a href="http://127.0.0.1:8111/load_object?objects=${objs}" target="_blank" rel="noopener">JOSM</a>
    </span></div>` : ""}
  `;
}

function makePopupLayers({ flowColors, sidewalkStatuses, highwayLayers, elevatorColor, elevatorLayerIds }) {
  const hover = [
    {
      ids: ["sidewalk-gaps"],
      format: p => `
        ${popupTitle("#f59e0b", "Trottoir d'un seul côté")}
        <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
      `
    },
    {
      ids: ["footway-crossing-candidates"],
      format: p => `
        ${popupTitle("#7f1d1d", "Traversée sans footway=crossing ?")}
        <div class="popup-row"><span class="label">Rue traversée</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
        <div class="popup-row"><span class="label">Longueur</span><span class="value">${escapeHTML(p.length_m)} m</span></div>
      `
    },
    {
      ids: ["sidewalk-roads"],
      format: p => {
        const swLabels = {
          separate:   "sidewalk:both=separate",
          yes:        "sidewalk=yes, à mapper en separate",
          documented: "Deux côtés documentés",
          partial:    "Un seul côté documenté",
          unknown:    "Aucun tag sidewalk"
        };
        return `
          ${popupTitle((sidewalkStatuses.find(s => s.value === p.sw) || {}).color, "Tags sidewalk")}
          <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
          <div class="popup-row"><span class="label">Statut</span><span class="value">${escapeHTML(swLabels[p.sw] || p.sw || "?")}</span></div>
        `;
      }
    },
    {
      ids: ["flow-ped", "flow-cycleway", "flow-road"],
      format: p => `
        ${popupTitle(flowColors[p.infra_type], "Flux simulé")}
        <div class="popup-row"><span class="label">Infrastructure</span><span class="value">${escapeHTML((p.infra_type || "—").replace(/_/g, " "))}</span></div>
        <div class="popup-row"><span class="label">highway</span><span class="value">${escapeHTML(p.highway || "—")}</span></div>
        <div class="popup-row"><span class="label">Flux relatif</span><span class="value">${escapeHTML(p.flow_pct) || 0} %</span></div>
      `
    },
    {
      ids: highwayLayers.map(l => `highway-${l.id}`).concat(["highway-crossing"], elevatorLayerIds),
      format: p => {
        const entries = Object.entries(p).filter(([k]) => !k.startsWith("@") && k !== "tippecanoe");
        const isElevator = p.highway === "elevator" || p.amenity === "elevator";
        const titleColor = isElevator ? elevatorColor : ((highwayLayers.find(l => l.id === p.highway) || {}).color || "#15803d");
        return `
          ${popupTitle(titleColor, escapeHTML(p.highway || (isElevator ? "elevator" : "Infrastructure")))}
          ${entries.map(([k, v]) => `<div class="popup-row"><span class="label">${escapeHTML(k)}</span><span class="value">${escapeHTML(v)}</span></div>`).join("")}
        `;
      }
    },
  ];

  const click = [
    {
      ids: ["missing-crossings"],
      format: p => {
        if (p.type === "wrong_tag") return formatWrongTagCrossing(p);
        const isMissingWay = p.type === "missing_way";
        const nearM = (typeof p.nearest_tag_m === "number" && p.nearest_tag_m >= 0)
          ? p.nearest_tag_m : null;
        const radius = p.detect_radius || 3;
        const nid = parseInt(p.osm_id, 10) || 0;
        return `
          ${isMissingWay ? popupTitle("#f97316", "Traversée non mappée") : popupTitle("#eab308", "Tag footway=crossing absent")}
          <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
          <div class="popup-row"><span class="label">Problème</span><span class="value">${isMissingWay
            ? "Aucune footway connectée au nœud"
            : "Footway connectée mais sans tag footway=crossing"
          }</span></div>
          ${nearM !== null && !isMissingWay ? `<div class="popup-row"><span class="label">footway=crossing le plus proche</span><span class="value">${nearM} m <span class="popup-note">(rayon ${radius} m)</span></span></div>` : ""}
          ${nid > 0 ? `<div class="popup-row"><span class="label">Nœud</span><span class="value">
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
          ${popupTitle("#7f1d1d", "Traversée sans footway=crossing ?")}
          <div class="popup-row"><span class="label">Rue traversée</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
          <div class="popup-row"><span class="label">Longueur</span><span class="value">${escapeHTML(p.length_m)} m</span></div>
          <div class="popup-row"><span class="label">Problème</span><span class="value">Relie un trottoir de chaque côté d'une route mais n'a pas le tag footway=crossing</span></div>
          ${wid > 0 ? `<div class="popup-row"><span class="label">Way</span><span class="value">
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
        const reasonLabels = {
          value_mismatch:       "tactile_paving du kerb différent de celui du crossing",
          incorrect_not_mixed:  "incorrect attendu : un kerb yes + un kerb no",
        };
        return `
          ${popupTitle("#a855f7", "Bande podotactile incohérente")}
          <div class="popup-row"><span class="label">Crossing</span><span class="value">tactile_paving=${escapeHTML(p.crossing_tp || "?")}</span></div>
          <div class="popup-row"><span class="label">Kerb côté 1</span><span class="value">${escapeHTML(p.kerb1_tp) || "absent"}</span></div>
          ${sidesChecked === 2
            ? `<div class="popup-row"><span class="label">Kerb côté 2</span><span class="value">${escapeHTML(p.kerb2_tp) || "absent"}</span></div>`
            : `<div class="popup-row"><span class="label">Kerb côté 2</span><span class="value popup-note">non vérifié : la way s'arrête au nœud crossing</span></div>`
          }
          <div class="popup-row"><span class="label">Problème</span><span class="value">${escapeHTML(reasonLabels[p.reason] || p.reason || "?")}</span></div>
          ${nid > 0 ? `<div class="popup-row"><span class="label">Nœud crossing</span><span class="value">
            <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=n${nid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?node=${nid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
          ${wid > 0 ? `<div class="popup-row"><span class="label">Way crossing</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}${pwid > 0 ? `,w${pwid}` : ""}" target="_blank" rel="noopener">JOSM</a>
          </span></div>` : ""}
          ${pwid > 0 ? `<div class="popup-row"><span class="label">Way contiguë</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${pwid}" target="_blank" rel="noopener">w${pwid}</a>
            <span class="popup-note">(même traversée que la précédente)</span>
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
          ${isLevel ? popupTitle("#ea580c", "Discontinuité de niveau") : isUnjoined ? popupTitle("#db2777", "Jonction manquante") : popupTitle("#0d9488", "Îlot isolé du réseau")}
          <div class="popup-row"><span class="label">Problème</span><span class="value">${isLevel
            ? "Escalier (steps) dont le level=* ne recouvre pas celui d'un chemin directement raccordé : liaison théoriquement non praticable"
            : isUnjoined
              ? "Touche presque le réseau principal mais ne partage aucun nœud avec lui"
              : "Groupe de chemins sans aucune liaison avec le réseau principal"
          }</span></div>
          ${isLevel
            ? `<div class="popup-row"><span class="label">Niveaux</span><span class="value">${escapeHTML(p.levels || "—")}</span></div>
          ${nodeId > 0 ? `<div class="popup-row"><span class="label">Nœud</span><span class="value"><a href="https://www.openstreetmap.org/node/${nodeId}" target="_blank" rel="noopener">n${nodeId}</a></span></div>` : ""}`
            : `<div class="popup-row"><span class="label">Écart au réseau</span><span class="value">${gap !== null ? gap + " m" : "—"}</span></div>`
          }
          <div class="popup-row"><span class="label">Longueur</span><span class="value">${Math.round(Number(p.length_m) || 0)} m</span></div>
          <div class="popup-row"><span class="label">Types</span><span class="value">${escapeHTML(p.highways || "—")}</span></div>
          <div class="popup-row"><span class="label">Ways</span><span class="value">${ways.length
            ? ways.slice(0, 5).map(id => `<a href="https://www.openstreetmap.org/way/${id}" target="_blank" rel="noopener">w${id}</a>`).join(" ") + (ways.length > 5 ? ` +${ways.length - 5}` : "")
            : "—"
          }</span></div>
          ${josm || idLink ? `<div class="popup-row"><span class="label">Éditer</span><span class="value">
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
          ${isMissing ? popupTitle("#1e3a8a", "Kerb absent") : popupTitle("#7c2d12", "Kerb sans tactile_paving")}
          <div class="popup-row"><span class="label">Problème</span><span class="value">${isMissing
            ? "Aucun nœud barrier=kerb trouvé à cette extrémité"
            : "Kerb présent mais sans tag tactile_paving"
          }</span></div>
          ${cid > 0 ? `<div class="popup-row"><span class="label">Crossing</span><span class="value">
            <a href="https://www.openstreetmap.org/node/${cid}" target="_blank" rel="noopener">n${cid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=n${cid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?node=${cid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
          ${!isMissing && kid > 0 ? `<div class="popup-row"><span class="label">Kerb</span><span class="value">
            <a href="https://www.openstreetmap.org/node/${kid}" target="_blank" rel="noopener">n${kid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=n${kid}" target="_blank" rel="noopener">JOSM</a>
            · <a href="https://www.openstreetmap.org/edit?node=${kid}" target="_blank" rel="noopener">iD</a>
          </span></div>` : ""}
          ${wid > 0 ? `<div class="popup-row"><span class="label">Way crossing</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
            · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}${pwid > 0 ? `,w${pwid}` : ""}" target="_blank" rel="noopener">JOSM</a>
          </span></div>` : ""}
          ${pwid > 0 ? `<div class="popup-row"><span class="label">Way contiguë</span><span class="value">
            <a href="https://www.openstreetmap.org/way/${pwid}" target="_blank" rel="noopener">w${pwid}</a>
            <span class="popup-note">(même traversée que la précédente)</span>
          </span></div>` : ""}
        `;
      }
    },
  ];

  return { hover, click };
}

if (typeof module !== "undefined") {
  module.exports = { escapeHTML, popupTitle, formatWrongTagCrossing, makePopupLayers };
}
