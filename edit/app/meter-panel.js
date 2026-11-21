import { i18n } from "../../map/i18n.js";
import { meterView } from "../panel.js";

export function installMeterPanel(ctx) {
  const { env, meter } = ctx;
  const meterEl = ctx.el.meter;
  let meterFrame = 0;

  function renderMeter() {
    if (!meter || meterFrame) return;
    meterFrame = requestAnimationFrame(() => {
      meterFrame = 0;
      const open = Boolean(meterEl.querySelector("details[open]"));
      meterEl.innerHTML = html`${meterView(meter.stats(), i18n, env)}`;
      if (open) meterEl.querySelector("details").open = true;
    });
  }

  if (meter) {
    meter.onChange(renderMeter);
    renderMeter();
    setInterval(renderMeter, 15000);
    meterEl.addEventListener("click", (e) => {
      if (e.target.closest("[data-edit-action=meter-reset]")) meter.reset();
    });
  }
}
