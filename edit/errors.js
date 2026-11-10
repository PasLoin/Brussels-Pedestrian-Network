export function errorKind(err) {
  const status = err && err.cause;
  const message = String((err && err.message) || "");
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 429) return "rateLimit";
  if (status === 509) return "bandwidth";
  if (status === 503 || /database offline|read-only|readonly/i.test(message)) return "maintenance";
  if (status === 400 && /too many nodes|bounding box|bbox/i.test(message)) return "tooBig";
  if (typeof status === "number" && status >= 500) return "server";
  if (typeof status !== "number" && (err instanceof TypeError || /failed to fetch|networkerror|load failed|network/i.test(message))) return "network";
  return "unknown";
}

export function errorMessage(err, t) {
  const kind = errorKind(err);
  if (kind === "auth") return t("edit.error.auth");
  if (kind === "forbidden") return t("edit.error.forbidden");
  if (kind === "rateLimit") return t("edit.error.rateLimit");
  if (kind === "bandwidth") return t("edit.error.bandwidth");
  if (kind === "maintenance") return t("edit.error.maintenance");
  if (kind === "tooBig") return t("edit.error.tooBig");
  if (kind === "server") return t("edit.error.server");
  if (kind === "network") return t("edit.error.network");
  return t("edit.error.unknown", { message: String((err && err.message) || err || "").replace(/^OSM API:\s*/, "") || "?" });
}
