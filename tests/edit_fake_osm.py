import base64
import copy
import gzip
import hashlib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

DEV_HOST = "master.apis.dev.openstreetmap.org"
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET,PUT,POST,DELETE",
}
JSON_HEADERS = {**CORS, "Content-Type": "application/json"}
TEXT_HEADERS = {**CORS, "Content-Type": "text/plain"}
XML_HEADERS = {**CORS, "Content-Type": "application/xml; charset=utf-8"}

ROUTES = [
    ("user", "GET", re.compile(r"/api/0\.6/user/details\.json")),
    ("map", "GET", re.compile(r"/api/0\.6/map\.json")),
    ("ways", "GET", re.compile(r"/api/0\.6/ways\.json")),
    ("nodes", "GET", re.compile(r"/api/0\.6/nodes\.json")),
    ("way_full", "GET", re.compile(r"/api/0\.6/way/(\d+)/full\.json")),
    ("way", "GET", re.compile(r"/api/0\.6/way/(\d+)\.json")),
    ("changesets", "GET", re.compile(r"/api/0\.6/changesets\.json")),
    ("create", "PUT", re.compile(r"/api/0\.6/changeset/create")),
    ("upload", "POST", re.compile(r"/api/0\.6/changeset/(\d+)/upload")),
    ("close", "PUT", re.compile(r"/api/0\.6/changeset/(\d+)/close")),
    ("revoke", "POST", re.compile(r"/oauth2/revoke")),
    ("authorize", "GET", re.compile(r"/oauth2/authorize")),
    ("token", "POST", re.compile(r"/oauth2/token")),
]


class FakeOsm:
    def __init__(self, user_id=77, display_name="Testeur", changesets_count=12):
        self.user = {"id": user_id, "display_name": display_name, "changesets": {"count": changesets_count}}
        self.nodes = {}
        self.ways = {}
        self.deleted = set()
        self.changesets = {}
        self.next_changeset = 5000
        self.calls = []
        self.referers = []
        self.uploads = []
        self.creates = []
        self.closed = []
        self.revoked = []
        self.oauth_answer = "approve"
        self.authorizations = []
        self.exchanges = []
        self.issued_token = "fresh-token"
        self.authorization_headers = []
        self.faults = []
        self.lock = threading.Lock()
        self.conflict_text = None

    def add_node(self, node_id, lon, lat):
        self.nodes[node_id] = {"type": "node", "id": node_id, "lon": lon, "lat": lat, "version": 1, "visible": True}

    def add_way(self, way_id, node_coords, tags, version=1):
        ids = []
        for i, (lon, lat) in enumerate(node_coords):
            nid = way_id * 100 + i
            self.add_node(nid, lon, lat)
            ids.append(nid)
        self.ways[way_id] = {"type": "way", "id": way_id, "version": version, "nodes": ids, "tags": dict(tags),
                             "user": "mapper", "timestamp": "2026-11-09T10:00:00Z", "visible": True}
        return ids

    def edit_way(self, way_id, tags=None, nodes=None):
        way = self.ways[way_id]
        if tags is not None:
            way["tags"] = dict(tags)
        if nodes is not None:
            way["nodes"] = list(nodes)
        way["version"] += 1

    def move_node(self, node_id, lon, lat):
        self.nodes[node_id]["lon"] = lon
        self.nodes[node_id]["lat"] = lat
        self.nodes[node_id]["version"] += 1

    def delete_way(self, way_id):
        self.deleted.add(way_id)
        self.ways[way_id]["version"] += 1

    def inject(self, endpoint, status=None, body="", abort=False, after=False, delay=0.0, times=1, skip=0, hook=None):
        if delay:
            raise ValueError("a server-side delay blocks the test thread itself, so the page is never observed while waiting; hold the response in the page with hold_api() instead")
        self.faults.append({"endpoint": endpoint, "status": status, "body": body, "abort": abort,
                            "after": after, "delay": delay, "times": times, "skip": skip, "hook": hook})

    def count(self, endpoint):
        return sum(1 for name, _ in self.calls if name == endpoint)

    def _fault(self, endpoint):
        for fault in self.faults:
            if fault["endpoint"] != endpoint or fault["times"] <= 0:
                continue
            if fault["skip"] > 0:
                fault["skip"] -= 1
                continue
            fault["times"] -= 1
            return fault
        return None

    def _way_json(self, way_id):
        way = copy.deepcopy(self.ways[way_id])
        if way_id in self.deleted:
            way["visible"] = False
            way["nodes"] = []
            way["tags"] = {}
        return way

    def handle(self, route):
        req = route.request
        parsed = urlparse(req.url)
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=CORS)
        for name, method, pattern in ROUTES:
            match = pattern.fullmatch(parsed.path)
            if match and req.method == method:
                break
        else:
            return route.fulfill(status=404, body="Not found", headers=TEXT_HEADERS)
        with self.lock:
            self.calls.append((name, req.url))
            self.referers.append(req.headers.get("referer"))
            fault = self._fault(name)
        if fault and fault["hook"]:
            with self.lock:
                fault["hook"](self)
        if fault and fault["delay"]:
            time.sleep(fault["delay"])
        if fault and not fault["after"]:
            if fault["abort"]:
                return route.abort("internetdisconnected")
            if fault["status"]:
                return route.fulfill(status=fault["status"], body=fault["body"], headers=TEXT_HEADERS)
        with self.lock:
            status, body, headers = getattr(self, f"_{name}")(req, parsed, match)
        if fault and fault["after"] and fault["abort"]:
            return route.abort("internetdisconnected")
        return route.fulfill(status=status, body=body, headers=headers)

    def _user(self, req, parsed, match):
        self.authorization_headers.append(req.headers.get("authorization"))
        return 200, json.dumps({"user": self.user}), JSON_HEADERS

    def _map(self, req, parsed, match):
        w, s, e, n = (float(v) for v in parse_qs(parsed.query)["bbox"][0].split(","))
        inside = {nid for nid, nd in self.nodes.items() if w <= nd["lon"] <= e and s <= nd["lat"] <= n}
        ways = [self._way_json(wid) for wid in self.ways if wid not in self.deleted and inside & set(self.ways[wid]["nodes"])]
        node_ids = {nid for way in ways for nid in way["nodes"]} | inside
        elements = [self.nodes[nid] for nid in sorted(node_ids)] + ways
        return 200, json.dumps({"elements": elements}), JSON_HEADERS

    def _ways(self, req, parsed, match):
        ids = [int(v) for v in parse_qs(parsed.query)["ways"][0].split(",")]
        if any(i not in self.ways for i in ids):
            return 404, "", TEXT_HEADERS
        return 200, json.dumps({"elements": [self._way_json(i) for i in ids]}), JSON_HEADERS

    def _nodes(self, req, parsed, match):
        ids = [int(v) for v in parse_qs(parsed.query)["nodes"][0].split(",")]
        if any(i not in self.nodes for i in ids):
            return 404, "", TEXT_HEADERS
        return 200, json.dumps({"elements": [self.nodes[i] for i in ids]}), JSON_HEADERS

    def _way(self, req, parsed, match):
        way_id = int(match.group(1))
        if way_id not in self.ways:
            return 404, "", TEXT_HEADERS
        if way_id in self.deleted:
            return 410, "", TEXT_HEADERS
        return 200, json.dumps({"elements": [self._way_json(way_id)]}), JSON_HEADERS

    def _way_full(self, req, parsed, match):
        status, body, headers = self._way(req, parsed, match)
        if status != 200:
            return status, body, headers
        way = self._way_json(int(match.group(1)))
        return 200, json.dumps({"elements": [self.nodes[n] for n in way["nodes"]] + [way]}), JSON_HEADERS

    def _changesets(self, req, parsed, match):
        uid = int(parse_qs(parsed.query).get("user", ["0"])[0])
        items = [{"id": cid, "open": cs["open"], "changes_count": cs["changes"], "tags": cs["tags"]}
                 for cid, cs in sorted(self.changesets.items()) if cs["uid"] == uid]
        return 200, json.dumps({"changesets": items}), JSON_HEADERS

    @staticmethod
    def _body(req):
        raw = req.post_data_buffer or b""
        if (req.headers.get("content-encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8")

    def _create(self, req, parsed, match):
        xml = self._body(req)
        tags = {t.get("k"): t.get("v") for t in ET.fromstring(xml).iter("tag")}
        self.next_changeset += 1
        cid = self.next_changeset
        self.changesets[cid] = {"open": True, "changes": 0, "tags": tags, "uid": self.user["id"]}
        self.creates.append({"id": cid, "tags": tags})
        self.user["changesets"]["count"] += 1
        return 200, str(cid), TEXT_HEADERS

    def _upload(self, req, parsed, match):
        cid = int(match.group(1))
        xml = self._body(req)
        root = ET.fromstring(xml)
        modified = []
        for way in root.iter("way"):
            wid = int(way.get("id"))
            provided = int(way.get("version"))
            if wid in self.deleted:
                return 410, f"The way with the id {wid} has already been deleted", TEXT_HEADERS
            current = self.ways[wid]["version"]
            if provided != current:
                text = self.conflict_text or f"Version mismatch: Provided {provided}, server had: {current} of Way {wid}"
                return 409, text, TEXT_HEADERS
            modified.append((wid, {t.get("k"): t.get("v") for t in way.iter("tag")}, [int(nd.get("ref")) for nd in way.iter("nd")]))
        for wid, tags, nds in modified:
            self.ways[wid]["tags"] = tags
            self.ways[wid]["nodes"] = nds
            self.ways[wid]["version"] += 1
        self.changesets[cid]["changes"] += len(modified)
        self.uploads.append({"changeset": cid, "xml": xml, "ways": [m[0] for m in modified]})
        result = "".join(f'<way old_id="{w}" new_id="{w}" new_version="{self.ways[w]["version"]}"/>' for w, _, _ in modified)
        return 200, f'<?xml version="1.0"?><diffResult version="0.6">{result}</diffResult>', XML_HEADERS

    def _close(self, req, parsed, match):
        cid = int(match.group(1))
        if cid in self.changesets:
            self.changesets[cid]["open"] = False
        self.closed.append(cid)
        return 200, "", TEXT_HEADERS

    def _authorize(self, req, parsed, match):
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        code = f"code-{len(self.authorizations) + 1}"
        self.authorizations.append({**query, "code": code})
        state = query.get("state", "")
        if self.oauth_answer == "deny":
            target = f"{query['redirect_uri']}?error=access_denied&error_description=The+user+denied&state={state}"
        elif self.oauth_answer == "wrong_state":
            target = f"{query['redirect_uri']}?code={code}&state=forged"
        else:
            target = f"{query['redirect_uri']}?code={code}&state={state}"
        return 302, "", {**CORS, "Location": target}

    def _token(self, req, parsed, match):
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        grant = next((a for a in self.authorizations if a["code"] == query.get("code")), None)
        verifier = query.get("code_verifier", "")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        checks = {
            "known_code": grant is not None,
            "grant_type": query.get("grant_type") == "authorization_code",
            "client_id": grant is not None and query.get("client_id") == grant.get("client_id"),
            "redirect_uri": grant is not None and query.get("redirect_uri") == grant.get("redirect_uri"),
            "pkce": grant is not None and grant.get("code_challenge_method") == "S256" and challenge == grant.get("code_challenge"),
        }
        self.exchanges.append({"query": query, "checks": checks})
        if not all(checks.values()) or self.oauth_answer == "bad_grant":
            return 400, json.dumps({"error": "invalid_grant", "error_description": "The provided authorization grant is invalid"}), JSON_HEADERS
        body = {"access_token": self.issued_token, "token_type": "Bearer", "scope": grant.get("scope", ""), "created_at": 1763200000}
        return 200, json.dumps(body), JSON_HEADERS

    def _revoke(self, req, parsed, match):
        form = {k: v[0] for k, v in parse_qs(self._body(req)).items()}
        self.revoked.append({"form": form, "content_type": req.headers.get("content-type", "")})
        return 200, "{}", JSON_HEADERS

    def open_changesets(self):
        return [cid for cid, cs in self.changesets.items() if cs["open"]]
