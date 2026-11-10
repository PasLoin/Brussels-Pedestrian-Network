export const DOCK_POSITIONS = Object.freeze(["right", "left", "bottom"]);
export const DOCK_KEY = "bpn.dockPosition";

export function readDockPosition(storage) {
  try {
    const value = storage.getItem(DOCK_KEY);
    return DOCK_POSITIONS.includes(value) ? value : "right";
  } catch {
    return "right";
  }
}

export function freeRect(canvas, dock, position, gap = 12) {
  const rect = { left: 0, top: 0, right: canvas.width, bottom: canvas.height };
  if (!dock) return rect;
  if (position === "right") rect.right = Math.max(rect.left + 1, dock.left - gap);
  else if (position === "left") rect.left = Math.min(rect.right - 1, dock.right + gap);
  else if (position === "bottom") rect.bottom = Math.max(rect.top + 1, dock.top - gap);
  return rect;
}

export function recenterOffset(canvas, free, box, margin = 40) {
  const visible = box.minX >= free.left + margin && box.maxX <= free.right - margin
    && box.minY >= free.top + margin && box.maxY <= free.bottom - margin;
  if (visible) return null;
  return [(free.left + free.right) / 2 - canvas.width / 2, (free.top + free.bottom) / 2 - canvas.height / 2];
}
