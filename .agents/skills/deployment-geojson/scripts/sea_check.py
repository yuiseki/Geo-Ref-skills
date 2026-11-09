"""Drop the points of deployment GeoJSON that lie in the sea, by asking a Nominatim for land.

    python scripts/sea_check.py --src <geojson dir> --out <new dir> [--nominatim https://nominatim.yuiseki.net] [--cache cache.json]

A unit stack in the water of a map (a table, a legend, an off-shore box) is placed by the map's model as if it were
land; UNOCI 2006 put units in the Gulf of Guinea, 100 km off Abidjan. The gates and the hull cannot see it. A point is in
the sea when neither it nor its four neighbours 0.05 degree away (about 5 km) has land: a unit on a coastal town's dot may
fall a few hundred metres into the water, which is not an error. Use a Nominatim of your own, never a public server.
Files are written to --out; the ones given are not changed. A line per file says how many points were dropped, and each
file records the check in its provenance ("checks": {"sea": {"cell_deg": 0.05, "dropped": n}}). Moved here from
un-pko-deployments (2026-11-09) so that the checks that choose the points live with the tools that make them.
"""
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STEP = 0.05
USER_AGENT = "geo-ref-skills-sea-check"  # the self-hosted server refuses Python's default User-Agent (403)


def is_sea(lat, lon, reverse):
    """reverse(lat, lon) -> whether there is land there. Sea if there is none at the point nor at its four neighbours."""
    return not any(reverse(lat + dy, lon + dx) for dy, dx in ((0, 0), (STEP, 0), (-STEP, 0), (0, STEP), (0, -STEP)))


def filter_sea(fc, reverse):
    """The collection without its sea points, and how many were dropped."""
    keep, dropped = [], 0
    for f in fc["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        if is_sea(lat, lon, reverse):
            dropped += 1
        else:
            keep.append(f)
    checks = {**fc.get("checks", {}), "sea": {"cell_deg": STEP, "dropped": dropped}}
    return {**{k: v for k, v in fc.items() if k != "features"}, "checks": checks, "features": keep}, dropped


def nominatim_land(base, cache, path=None):
    """A reverse(lat, lon) that asks base for the country at 0.05 degree cells, remembering the answers in cache."""
    def reverse(lat, lon):
        key = f"{round(lat / STEP)},{round(lon / STEP)}"
        if key not in cache:
            url = f"{base}/reverse?" + urllib.parse.urlencode(
                {"lat": round(round(lat / STEP) * STEP, 4), "lon": round(round(lon / STEP) * STEP, 4), "format": "jsonv2", "zoom": 5})
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                cache[key] = "error" not in d
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                cache[key] = False
            if path and len(cache) % 200 == 0:
                Path(path).write_text(json.dumps(cache))
        return cache[key]
    return reverse


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nominatim", default="https://nominatim.yuiseki.net")
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    cache = json.loads(Path(a.cache).read_text()) if a.cache and Path(a.cache).exists() else {}
    reverse = nominatim_land(a.nominatim, cache, a.cache)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for f in sorted(Path(a.src).glob("*.geojson")):
        fc, dropped = filter_sea(json.loads(f.read_text()), reverse)
        (out / f.name).write_text(json.dumps(fc, ensure_ascii=False))
        total += dropped
        if dropped:
            print(f"{f.name}: dropped {dropped} of {dropped + len(fc['features'])}", flush=True)
    if a.cache:
        Path(a.cache).write_text(json.dumps(cache))
    print(f"dropped {total} sea points", flush=True)


if __name__ == "__main__":
    main()
