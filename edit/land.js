import { AUTH_CHANNEL, consumePending } from "./auth.js";
import { envFromDocument } from "./env.js";

const env = envFromDocument(document);
const params = new URLSearchParams(window.location.search);

function show(id) {
  document.getElementById("land-working").hidden = true;
  document.getElementById(`land-${id}`).hidden = false;
}

function handBack() {
  const channel = new BroadcastChannel(AUTH_CHANNEL);
  channel.postMessage(window.location.href);
  channel.close();
}

if (!params.has("code") && !params.has("error")) {
  show("nocode");
} else {
  const verdict = consumePending({ storage: window.localStorage, apiUrl: env.apiUrl, now: Date.now(), ttlMs: env.authPendingTtlMs });
  if (verdict !== "ok") {
    show(verdict);
  } else if (params.has("error")) {
    handBack();
    show("denied");
  } else {
    handBack();
    show("ok");
    window.close();
  }
}
