"""Fetch NATO APP-6 unit symbols (frame and icon, SVG) from Wikimedia Commons into a directory, with their credits.

    python scripts/fetch_symbols.py --out symbols_dir

Writes <arm>.svg for each arm in SYMBOLS and sources.json (title, licence, artist, url of each file). The files are
not kept in this repository: most are CC BY-SA 4.0, so a picture that uses them carries the credit that
render_units.py writes from sources.json. Commons answers 429 to fast callers: a User-Agent that names the project,
a pause between requests and a growing wait after a 429.
"""

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

PREFIX = "Military Symbol - Friendly Unit (Solid Light 1.5x1 Frame)- "
SYMBOLS = {
    "infantry": "Infantry (NATO APP-6)",
    "medical": "Medical (NATO APP-6)",
    "engineer": "Military Engineers - Engineer Resources (NATO APP-6)",
    "signal": "Signals or Communication (NATO APP-6)",
    "military police": "Military Police (NATO APP-6)",
    "artillery": "Artillery (NATO APP-6)",
    "aviation": "Aviation (NATO APP-6)",
    "headquarters": "Headquarters Unit (NATO APP-6)",
}
UA = {"User-Agent": "Geo-Ref-skills research (github.com/yuiseki/Geo-Ref-skills)"}
API = "https://commons.wikimedia.org/w/api.php?"


def get(url, tries=6, wait=60):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(wait * (i + 1))


def credit(info):
    """(licence, artist) of a Commons imageinfo record, the artist's markup removed."""
    m = info["extmetadata"]
    return m["LicenseShortName"]["value"], re.sub(r"<[^>]+>", "", m["Artist"]["value"]).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pause", type=float, default=8.0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    src_p = out / "sources.json"
    src = json.loads(src_p.read_text(encoding="utf-8")) if src_p.exists() else {}
    for arm, t in SYMBOLS.items():
        if arm in src and (out / f"{arm.replace(' ', '_')}.svg").exists():
            continue
        title = "File:" + PREFIX + t + ".svg"
        q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo",
                                    "iiprop": "url|extmetadata", "format": "json"})
        page = next(iter(json.loads(get(API + q))["query"]["pages"].values()))
        if "imageinfo" not in page:
            print(arm, "missing on Commons")
            continue
        info = page["imageinfo"][0]
        time.sleep(a.pause)
        try:
            svg = get(info["url"].split("?")[0])
        except urllib.error.HTTPError as e:
            print(arm, "not fetched:", e.code, "(run again later; the others are kept)")
            continue
        (out / f"{arm.replace(' ', '_')}.svg").write_bytes(svg)
        lic, artist = credit(info)
        src[arm] = {"title": title, "licence": lic, "artist": artist,
                    "url": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))}
        src_p.write_text(json.dumps(src, indent=1, ensure_ascii=False), encoding="utf-8")
        print(arm, lic, artist)
        time.sleep(a.pause)


if __name__ == "__main__":
    main()
