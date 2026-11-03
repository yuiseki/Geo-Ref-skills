"""Build a georeferenced reference image from XYZ raster tiles.

    python scripts/fetch_reference.py --style osm-liberty --zoom 15 \
        --bbox 139.74 35.67 139.77 35.70 --cache tmp/tiles --out tmp/ref

Writes <out>/reference.png and <out>/reference.json. In reference.json, `geotransform` is the GDAL
six-number transform from pixel (column, row) of reference.png (corner convention: pixel (0, 0) is the
top-left corner of the top-left pixel) to EPSG:3857 metres.
"""

import argparse
import json
from pathlib import Path

from PIL import Image

import tiles
import webmercator as wm


def build(style, zoom, bbox, cache, out, tile_size=256, base=tiles.DEFAULT_BASE, offline=False, max_tiles=400):
    w, s, e, n = bbox
    if not (w < e and s < n):
        raise ValueError(f"bbox must be west south east north with west < east and south < north: {bbox}")
    x0, y0 = wm.lonlat_to_global_px(w, n, zoom, tile_size)
    x1, y1 = wm.lonlat_to_global_px(e, s, zoom, tile_size)
    img, ox, oy, stats = tiles.mosaic(style, zoom, float(x0), float(y0), float(x1), float(y1), cache,
                                      tile_size, base, offline, max_tiles)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out / "reference.png")
    mx0, my0 = wm.global_px_to_mercator(ox, oy, zoom, tile_size)
    res = 2.0 * wm.ORIGIN / wm.world_px(zoom, tile_size)
    meta = {
        "style": style,
        "zoom": zoom,
        "tile_size": tile_size,
        "tile_base": base,
        "crs": "EPSG:3857",
        "width": int(img.shape[1]),
        "height": int(img.shape[0]),
        "origin_global_px": [int(ox), int(oy)],
        "geotransform": [float(mx0), res, 0.0, float(my0), 0.0, -res],
        "requested_bbox": [w, s, e, n],
        "tiles": stats,
    }
    (out / "reference.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--style", required=True)
    ap.add_argument("--zoom", type=int, required=True)
    ap.add_argument("--bbox", type=float, nargs=4, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    ap.add_argument("--cache", default="tmp/tiles")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tile-size", type=int, default=256, choices=[256, 512])
    ap.add_argument("--base", default=tiles.DEFAULT_BASE)
    ap.add_argument("--offline", action="store_true", help="use only cached tiles")
    ap.add_argument("--max-tiles", type=int, default=400)
    a = ap.parse_args()
    meta = build(a.style, a.zoom, a.bbox, a.cache, a.out, a.tile_size, a.base, a.offline, a.max_tiles)
    print(json.dumps({k: meta[k] for k in ("width", "height", "geotransform", "tiles")}))


if __name__ == "__main__":
    main()
