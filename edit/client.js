export function authorizationHeader(osm) {
  const config = osm.getConfig() || {};
  if (config.authHeader) return config.authHeader;
  const token = osm.getAuthToken();
  return token ? `Bearer ${token}` : "";
}

export async function apiError(response) {
  let text = "";
  try { text = await response.text(); } catch {}
  const error = new Error(`OSM API: ${text}`);
  error.cause = response.status;
  return error;
}

export function createClient(osm, fetchImpl = (...args) => fetch(...args)) {
  return Object.freeze({
    ...osm,
    async closeChangeset(id) {
      const { apiUrl } = osm.getConfig();
      const response = await fetchImpl(`${apiUrl}/api/0.6/changeset/${encodeURIComponent(id)}/close`, {
        method: "PUT",
        headers: { Authorization: authorizationHeader(osm) },
      });
      if (!response.ok) throw await apiError(response);
    },
  });
}
