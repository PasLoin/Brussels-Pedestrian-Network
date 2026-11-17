import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def coverage_dir():
    value = os.environ.get("BROWSER_COVERAGE_DIR")
    return Path(value) if value else None


def local_file(url, origin):
    if not url.startswith(origin):
        return None
    path = urlparse(url).path.lstrip("/")
    candidate = (ROOT / path).resolve()
    if candidate.suffix != ".js" or not candidate.is_file() or ROOT not in candidate.parents:
        return None
    return candidate


class PageCoverage:
    def __init__(self, context, page, origin):
        self.origin = origin
        self.done = False
        self.cdp = context.new_cdp_session(page)
        self.cdp.send("Profiler.enable")
        self.start()

    def start(self):
        self.cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})

    def save(self, target, final=True):
        if self.done:
            return
        if final:
            self.done = True
        try:
            entries = self.cdp.send("Profiler.takePreciseCoverage")["result"]
        except Exception:
            return
        kept = []
        for entry in entries:
            path = local_file(entry["url"], self.origin)
            if path:
                kept.append({**entry, "url": path.as_uri()})
        if kept:
            target.mkdir(parents=True, exist_ok=True)
            (target / f"browser-{uuid.uuid4().hex}.json").write_text(json.dumps({"result": kept}), encoding="utf-8")


def track(context, page, origin):
    target = coverage_dir()
    if target is None:
        return None
    coverage = PageCoverage(context, page, origin)
    original_close = page.close

    def close(*args, **kwargs):
        coverage.save(target)
        return original_close(*args, **kwargs)

    def before_leaving(navigate):
        def wrapped(*args, **kwargs):
            coverage.save(target, final=False)
            return navigate(*args, **kwargs)
        return wrapped

    page.close = close
    page.reload = before_leaving(page.reload)
    page.goto = before_leaving(page.goto)
    return lambda: coverage.save(target)
