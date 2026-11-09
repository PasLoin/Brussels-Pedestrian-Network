const SMALL_SCREEN_QUERY = "(max-width: 600px)";
let legendAutoCollapsed = false;

export function isSmallScreen() {
  return window.matchMedia(SMALL_SCREEN_QUERY).matches;
}

export function setHeaderOpen(open) {
  const el = document.getElementById("header");
  el.classList.toggle("open", open);
  el.classList.toggle("closed", !open);
  document.getElementById("header-toggle").setAttribute("aria-expanded", open);
}

export function toggleHeader() {
  const open = !document.getElementById("header").classList.contains("open");
  setHeaderOpen(open);
  if (open && isSmallScreen()) {
    legendAutoCollapsed = false;
    setLegendOpen(false);
  }
}

export function setLegendOpen(open) {
  const el = document.getElementById("legend");
  el.classList.toggle("open", open);
  el.classList.toggle("closed", !open);
  document.getElementById("legend-toggle").setAttribute("aria-expanded", open);
  if (open && isSmallScreen()) setHeaderOpen(false);
}

export function toggleLegend() {
  legendAutoCollapsed = false;
  setLegendOpen(!document.getElementById("legend").classList.contains("open"));
}

export function showRoutePanel() {
  document.getElementById("route-panel").classList.add("visible");
  const legendOpen = document.getElementById("legend").classList.contains("open");
  if (legendOpen && isSmallScreen()) {
    setLegendOpen(false);
    legendAutoCollapsed = true;
  }
}

export function hideRoutePanel() {
  document.getElementById("route-panel").classList.remove("visible");
  if (legendAutoCollapsed) {
    legendAutoCollapsed = false;
    setLegendOpen(true);
  }
}

export function collapsePanelsOnSmallScreens() {
  if (isSmallScreen()) {
    setLegendOpen(false);
    setHeaderOpen(false);
  }
}
