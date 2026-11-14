export function lookTimeMs(lengthM, settings) {
  const proportional = Math.max(0, Number(lengthM) || 0) * settings.lookMsPerMeter;
  return Math.round(Math.min(settings.minLookMs, proportional));
}
