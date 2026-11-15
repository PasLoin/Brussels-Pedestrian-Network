const VALUE_KEYS = Object.freeze({ s: "separate", y: "yes", n: "no" });

export function isTypingTarget(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName.toUpperCase();
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable === true;
}

export function shortcutFor(event) {
  if (!event || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return null;
  if (isTypingTarget(event.target)) return null;
  const key = event.key;
  if (key === "ArrowRight") return { type: "next" };
  if (key === "Escape") return { type: "deselect" };
  if (typeof key !== "string" || key.length !== 1) return null;
  const lower = key.toLowerCase();
  if (VALUE_KEYS[lower]) return { type: "value", value: VALUE_KEYS[lower] };
  if (lower === "d") return { type: "mode", mode: "sides" };
  if (lower === "b") return { type: "mode", mode: "both" };
  if (lower === "p") return { type: "skip" };
  return null;
}

export function sideForValue(choice) {
  if (choice.mode !== "sides") return "both";
  if (!choice.left) return "left";
  if (!choice.right) return "right";
  return "left";
}
