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

export function boxOf(points) {
  const xs = points.map(p => p.x);
  const ys = points.map(p => p.y);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

export function boxVisible(free, box, margin = 0) {
  return box.minX >= free.left + margin && box.maxX <= free.right - margin
    && box.minY >= free.top + margin && box.maxY <= free.bottom - margin;
}

export function fitPadding(canvas, free, margin = 40) {
  const room = Math.min(free.right - free.left, free.bottom - free.top);
  const m = Math.max(0, Math.min(margin, Math.floor(room / 4)));
  return {
    left: Math.max(0, free.left) + m,
    top: Math.max(0, free.top) + m,
    right: Math.max(0, canvas.width - free.right) + m,
    bottom: Math.max(0, canvas.height - free.bottom) + m,
  };
}
