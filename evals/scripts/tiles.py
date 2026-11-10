"""Fetch raster XYZ tiles with a local cache and stitch them into one image.

Tiles are cached at <cache>/<style>/<tile_size>/<z>/<x>/<y>.png and never fetched twice.
A missing tile, a non-PNG answer or a tile of the wrong size is an error, never a blank.
"""

import io
import os
import threading
import math
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_BASE = "https://tile.yuiseki.net/styles"
USER_AGENT = "Geo-Ref-skills (+https://github.com/yuiseki/Geo-Ref-skills)"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def tile_url(base, style, z, x, y, tile_size=256):
    if tile_size == 256:
        return f"{base}/{style}/{z}/{x}/{y}.png"
    return f"{base}/{style}/{tile_size}/{z}/{x}/{y}.png"


def cache_path(cache, style, z, x, y, tile_size=256):
    return Path(cache) / style / str(tile_size) / str(z) / str(x) / f"{y}.png"


def _download(url, retries=3, timeout=120):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.status != 200:
                    raise RuntimeError(f"HTTP {r.status} for {url}")
            if not body.startswith(PNG_MAGIC):
                raise RuntimeError(f"not a PNG from {url}: {body[:40]!r}")
            return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(f"404 for {url}") from e
            last = e
        except Exception as e:  # network errors are retried, then raised
            last = e
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last!r}")


def get_tile(style, z, x, y, cache, tile_size=256, base=DEFAULT_BASE, offline=False, stats=None):
    p = cache_path(cache, style, z, x, y, tile_size)
    if p.exists():
        data = p.read_bytes()
        if stats is not None:
            stats["cached"] += 1
    elif offline:
        raise FileNotFoundError(f"tile not in cache and offline: {p}")
    else:
        data = _download(tile_url(base, style, z, x, y, tile_size))
        p.parent.mkdir(parents=True, exist_ok=True)
        # a name of this process's own: two runs side by side fetch the same tile, and with one shared ".part"
        # the second rename found the file already moved (2026-11-10)
        tmp = p.with_name(f"{p.stem}.{os.getpid()}.{threading.get_ident()}.part")
        tmp.write_bytes(data)
        tmp.replace(p)
        if stats is not None:
            stats["fetched"] += 1
    img = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
    if img.shape[:2] != (tile_size, tile_size):
        raise ValueError(f"tile {p} is {img.shape[:2]}, expected {tile_size}")
    return img


def mosaic(style, z, x0, y0, x1, y1, cache, tile_size=256, base=DEFAULT_BASE, offline=False, max_tiles=400):
    """Image covering global pixels [floor(x0), ceil(x1)) x [floor(y0), ceil(y1)) at zoom z.

    Returns (image, ox, oy, stats): image[j, i] is global pixel (ox + i, oy + j).
    """
    n = tile_size * 2**z
    ox, oy = math.floor(x0), math.floor(y0)
    ex, ey = math.ceil(x1), math.ceil(y1)
    if ox < 0 or oy < 0 or ex > n or ey > n or ex <= ox or ey <= oy:
        raise ValueError(f"window {ox},{oy}-{ex},{ey} is outside the world (0..{n}) or empty")
    tx0, ty0 = ox // tile_size, oy // tile_size
    tx1, ty1 = (ex - 1) // tile_size, (ey - 1) // tile_size
    count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    if count > max_tiles:
        raise ValueError(f"{count} tiles needed, more than max_tiles={max_tiles}")
    stats = {"cached": 0, "fetched": 0}
    big = np.zeros(((ty1 - ty0 + 1) * tile_size, (tx1 - tx0 + 1) * tile_size, 3), np.uint8)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            t = get_tile(style, z, tx, ty, cache, tile_size, base, offline, stats)
            big[(ty - ty0) * tile_size:(ty - ty0 + 1) * tile_size, (tx - tx0) * tile_size:(tx - tx0 + 1) * tile_size] = t
    if stats["cached"] + stats["fetched"] != count:
        raise RuntimeError(f"stitched {stats} tiles, expected {count}")
    cx, cy = ox - tx0 * tile_size, oy - ty0 * tile_size
    return big[cy:cy + (ey - oy), cx:cx + (ex - ox)].copy(), ox, oy, stats
