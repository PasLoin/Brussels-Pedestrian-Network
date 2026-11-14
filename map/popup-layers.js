import { i18n } from "./i18n.js";
import { ELEVATOR_COLOR, ELEVATOR_LAYER_IDS, FLOW_COLORS, HIGHWAY_LAYERS } from "./layers.js";
import { SIDEWALK_STATUSES } from "./type-filters.js";

export const { hover: HOVER_LAYERS, click: CLICK_LAYERS } = makePopupLayers({
  flowColors: FLOW_COLORS,
  sidewalkStatuses: SIDEWALK_STATUSES,
  highwayLayers: HIGHWAY_LAYERS,
  elevatorColor: ELEVATOR_COLOR,
  elevatorLayerIds: ELEVATOR_LAYER_IDS,
  editHere: p => Boolean(window.BPNEdit && window.BPNEdit.canEdit(p)),
}, i18n);
