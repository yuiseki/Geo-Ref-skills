"""What may be published of a GeoJSON derived from a peacekeeping map, and how it is marked.

A work derived from a United Nations map is published as "Based on United Nations map", with the map's reference
number removed (the date, the mission acronym and the unit names may stay), the SHA-256 of the source PDF and the
commit of the tool that read it, and a plain statement that nothing is guaranteed. (The owner's reading of the UN terms,
2026-11-05.)
"""
import re
import hashlib
import subprocess
from pathlib import Path

BASED_ON = "Based on United Nations map"
DISCLAIMER = ("Derived automatically from a United Nations map by software that uses no LLM or VLM. ABSOLUTELY NO WARRANTY: "
              "positions, unit names, sizes and arms may be wrong, and no accuracy is guaranteed. Not an official United Nations "
              "product and not endorsed by the United Nations.")
SHORT = "ABSOLUTELY NO WARRANTY: this point may be wrong."
DROP = ("map", "title", "panel")  # the file stem and the title carry the reference number


def out_name(mission, date, sha256):
    return f"{mission or 'UNKNOWN'}_{date}_{sha256[:12]}.geojson"


def reference_numbers(*names):
    """Runs of four or five digits in file names or titles ('MONUSCO_4412_R60': 4412), the form of the UN map numbers."""
    return sorted({m for n in names if n for m in re.findall(r"(?<!\d)\d{4,5}(?!\d)", n)})


def publishable(features, sha256, commit, date, mission, references=(), checks=None):
    """checks: what was applied to choose the points (the hull margin, later the sea and town checks), kept with them."""
    fs = []
    for f in features:
        p = {k: v for k, v in f["properties"].items() if k not in DROP}
        p["no_warranty"] = SHORT
        fs.append({"type": "Feature", "geometry": f["geometry"], "properties": p})
    fc = {"type": "FeatureCollection", "based_on": BASED_ON, "disclaimer": DISCLAIMER, "mission": mission, "map_date": date,
          "source_sha256": sha256, "tool": "https://github.com/yuiseki/Geo-Ref-skills", "tool_commit": commit, "features": fs}
    if checks is not None:
        fc = {**{k: v for k, v in fc.items() if k != "features"}, "checks": checks, "features": fs}
    import json
    text = json.dumps(fc, ensure_ascii=False)
    for ref in references:
        if re.search(r"(?<!\d)" + re.escape(ref) + r"(?!\d)", text):
            raise ValueError(f"reference number {ref} is still in the output")
    return fc


def files_hash(paths):
    """sha256 over the tool's files (path and content, in order), for a copy of the skills that is not in git."""
    h = hashlib.sha256()
    for root in map(Path, paths):
        for f in sorted(p for p in ([root] if root.is_file() else root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts):
            h.update(str(f.relative_to(root.parent)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def tool_commit(paths, repo):
    """The commit that holds the tool as it is run; refuses if the files are untracked or changed. A copy of the
    skills outside git (no git, or no repository: an agent's workdir in a container) is named by the hash of the
    tool's files instead, as unversioned-sha256:<hex>."""
    import shutil
    inside = shutil.which("git") and subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo,
                                                    capture_output=True, text=True).stdout.strip() == "true"
    if not inside:
        return "unversioned-sha256:" + files_hash(paths)
    st = subprocess.run(["git", "status", "--porcelain", "--", *map(str, paths)], cwd=repo, capture_output=True, text=True).stdout
    if st.strip():
        raise RuntimeError("commit the tool first, its commit hash goes into the output:\n" + st)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
