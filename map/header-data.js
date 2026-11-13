import { i18n } from "./i18n.js";

export function loadHeaderData() {
  fetch(i18n.dataUrl("state.txt"))
    .then(r => r.text())
    .then(txt => {
      const fmtOpts = { dateStyle: "short", timeStyle: "short" };
      const jsonMatch = txt.match(/\{[\s\S]*?\}/);
      if (jsonMatch) {
        try {
          const state = JSON.parse(jsonMatch[0]);
          if (state.timestamp) {
            document.getElementById("osm-date").textContent =
              i18n.t("header.osmDate", { date: i18n.date(state.timestamp, fmtOpts) });
          }
        } catch (e) { console.warn("state.txt JSON parse error:", e); }
      }
      const buildMatch = txt.match(/build_timestamp=(.+)/);
      if (buildMatch) {
        document.getElementById("build-date").textContent =
          i18n.t("header.buildDate", { date: i18n.date(buildMatch[1].trim(), fmtOpts) });
      }
    })
    .catch(() => { document.getElementById("osm-date").textContent = i18n.t("header.osmDateUnknown"); });
}
