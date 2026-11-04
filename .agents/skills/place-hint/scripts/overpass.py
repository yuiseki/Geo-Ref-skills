"""A small client for the self-hosted Overpass API, with an on-disk cache.

    c = Client("tmp/overpass"); c.named_near("Regent Street", 51.511, -0.139, 3000)

Returns the `out geom` elements carrying exactly that name within radius metres of a point. Every request
names this tool; requests go one at a time with a pause; answers, empty ones included, are cached; a failure
raises and is never cached. The request timeout is kept well below the server's own limit: a request asking
for the server's whole budget is refused as "too busy" (seen 2026-08-27). Its data is a snapshot (2025-09 as of
2026-11), so it can disagree with the tiles. Never point this at a public Overpass instance.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://overpass.yuiseki.net/api/interpreter"
USER_AGENT = "Geo-Ref-skills (+https://github.com/yuiseki/Geo-Ref-skills)"
PUBLIC = ("overpass-api.de", "overpass.kumi.systems", "openstreetmap", "overpass.private.coffee")


def http_post(url, data, timeout=90):
    req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": data}).encode(),
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class Client:
    BUSY = {429, 502, 503, 504}

    def __init__(self, cache, base=BASE, pause=0.2, fetch=http_post, sleep=time.sleep, retries=4):
        if any(p in base for p in PUBLIC):
            raise ValueError("use the self-hosted Overpass, not a public one")
        self.cache = Path(cache)
        self.base, self.pause, self.fetch, self.sleep, self.retries = base, pause, fetch, sleep, retries
        self.requests = self.cached = 0
        self._last = 0.0

    def named_near(self, name, lat, lon, radius_m):
        esc = name.replace("\\", "\\\\").replace('"', '\\"')
        q = f'[out:json][timeout:60];nwr["name"="{esc}"](around:{int(radius_m)},{lat:.6g},{lon:.7g});out geom;'
        key = hashlib.sha256(q.encode("utf-8")).hexdigest()[:24]
        p = self.cache / f"{key}.json"
        if p.exists():
            self.cached += 1
            return json.loads(p.read_text(encoding="utf-8"))["elements"]
        wait = self.pause - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(self.retries):
            try:
                body = self.fetch(self.base, q)
                break
            except urllib.error.HTTPError as e:
                if e.code not in self.BUSY or attempt == self.retries - 1:
                    raise
                self.sleep(2 ** (attempt + 1))
        self._last = time.time()
        self.requests += 1
        d = json.loads(body)
        if "elements" not in d:
            raise RuntimeError(f"unexpected Overpass answer: {str(d)[:200]}")
        if d.get("remark") and "runtime error" in d["remark"]:
            raise RuntimeError(f"Overpass: {d['remark'][:200]}")
        self.cache.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"query": q, "elements": d["elements"]}, ensure_ascii=False), encoding="utf-8")
        return d["elements"]
