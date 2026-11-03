"""A small client for the self-hosted Nominatim, with an on-disk cache.

    c = Client("tmp/nominatim"); c.search("Kanazawa", countrycodes="jp")

The server blocks the default Python User-Agent (HTTP 403, checked 2026-11-03), so every request names this
tool. Requests go one at a time with a pause between them. Answers, including empty ones, are cached by query,
so a name is fetched once. A failed request raises; it is never cached and never read as "no such place".
Never point this at the public nominatim.openstreetmap.org.
"""

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://nominatim.yuiseki.net"
USER_AGENT = "Geo-Ref-skills (+https://github.com/yuiseki/Geo-Ref-skills)"


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} for {url}")
        return r.read()


class Client:
    def __init__(self, cache, base=BASE, pause=0.5, fetch=http_get):
        if "openstreetmap.org" in base:
            raise ValueError("use the self-hosted Nominatim, not the public one")
        self.cache = Path(cache)
        self.base, self.pause, self.fetch = base.rstrip("/"), pause, fetch
        self.requests = self.cached = 0
        self._last = 0.0

    def search(self, q, limit=10, countrycodes=None, namedetails=False):
        params = {"q": q, "format": "jsonv2", "limit": str(limit)}
        if namedetails:
            params["namedetails"] = "1"
        if countrycodes:
            params["countrycodes"] = countrycodes
        url = f"{self.base}/search?{urllib.parse.urlencode(params)}"
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        p = self.cache / f"{key}.json"
        if p.exists():
            self.cached += 1
            return json.loads(p.read_text(encoding="utf-8"))["result"]
        wait = self.pause - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        body = self.fetch(url)
        self._last = time.time()
        self.requests += 1
        result = json.loads(body)
        if not isinstance(result, list):
            raise RuntimeError(f"unexpected answer for {url}: {str(result)[:200]}")
        self.cache.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": url, "result": result}, ensure_ascii=False), encoding="utf-8")
        return result
