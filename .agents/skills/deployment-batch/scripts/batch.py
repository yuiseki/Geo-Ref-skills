"""Georeference a directory of peacekeeping deployment map PDFs, newest first, one line per PDF in results.jsonl (resumable).

    python scripts/batch.py --src pdfs --out work [--min-year 2017] [--limit N] [--missions missions.json] [--only a.pdf ...]

Per PDF: map candidates (the map and its inset frames), then for the first three by rank and every vector frame among
the first eight, name-gcps (text layer, else OCR) with an affine and then a projective model, and the gates, then the
same with graticule-gcps (the latitude and longitude ticks of the frame) for a crop of a PDF. It stops at
the first candidate and method that pass every gate; then the other panels (the first four by rank and every frame) are
tried too, so that the insets have their own control points. Gates are never loosened here. Each step runs under its own memory
and CPU cap, so a PDF that runs out of memory fails alone.

work/results.jsonl: one line per PDF: file, mission, date, title, stage (ok, failed, candidates, error), and what was tried.
work/runs/<pdf stem>/: candidates, words, answers and gate results of that PDF (what deployment_geojson.py reads).
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
ROOT = SKILLS.parents[1]
UVX = ["uvx", "--with", "numpy", "--with", "opencv-python-headless", "--with", "pypdfium2", "--with", "pillow", "--with", "pyproj", "python"]
# every step in its own capped scope: one PDF that runs out of memory fails alone, not the batch
CAP = ["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=8G", "-p", "MemorySwapMax=0", "-p", "CPUQuota=400%", "--"]

# mission acronym -> the countries its map can show (Nominatim country codes), so that a troop contributor's name on the
# map (BANGLADESH beside a unit) is not taken for a place in Bangladesh
MISSIONS = {
    "MINURSO": "eh,ma,mr,dz", "MINUSCA": "cf,cm,td,sd,ss,cd,cg", "MINUSMA": "ml,mr,dz,ne,bf,ci,gn,sn",
    "MONUSCO": "cd,cg,ao,zm,tz,bi,rw,ug,ss,cf", "MONUC": "cd,cg,ao,zm,tz,bi,rw,ug,sd,cf", "UNDOF": "sy,il,lb,jo",
    "UNFICYP": "cy", "UNIFIL": "lb,il,sy", "UNISFA": "sd,ss", "UNMIK": "xk,rs,mk,al,me", "UNMISS": "ss,sd,et,ke,ug,cd,cf",
    "UNOMIG": "ge,ru", "UNMIL": "lr,sl,gn,ci", "UNOCI": "ci,lr,gn,ml,bf,gh", "UNAMID": "sd,td,cf,ly,eg,ss",
    "UNAMSIL": "sl,gn,lr", "UNIOSIL": "sl,gn,lr", "UNMIS": "sd,ss,td,cf,et,er,eg,ly,ke,ug,cd", "UNMOGIP": "in,pk",
    "UNAMA": "af,pk,ir,tm,uz,tj,cn", "ONUB": "bi,rw,tz,cd", "UNMIT": "tl,id", "UNMISET": "tl,id", "MINUSTAH": "ht,do",
    "MINUJUSTH": "ht,do", "MINURCAT": "td,cf,sd", "UNTSO": "il,lb,sy,eg,jo,ps", "UNMEE": "er,et,dj,sd",
    "UNMIN": "np,in,cn", "UNSMIS": "sy,lb,jo,iq,tr,il", "UNMOP": "hr,me,ba", "UNIKOM": "iq,kw,sa",
    "UNAMI": "iq,sy,tr,ir,kw,sa,jo", "UNMOT": "tj,af,uz,kg,cn", "UNITAMS": "sd"}

# the UTM zone of a mission's maps that are gridded in metres without printing the zone (graticule-gcps)
UTM_ZONES = {"UNIFIL": "36N"}


def mission_of(*texts):
    """The first mission acronym found as a whole word in the texts (a title, then the file name, then the page text)."""
    for t in texts:
        for m in re.findall(r"[A-Za-z]+", t or ""):
            if m.upper() in MISSIONS:
                return m.upper()
    return None


def pdf_date(created, modified):
    """YYYYMMDD from a PDF date ('D:20250601120000+00'00'): the creation date, else the modification date, else 00000000."""
    for k in (created, modified):
        m = re.match(r"D:(\d{8,14})", k or "")
        if m:
            return m.group(1)[:8]
    return "00000000"


def to_try(cands, first=3, total=8):
    """Indices of the candidates to try: the first three by rank, and every vector frame among the first eight."""
    return [k for k, c in enumerate(cands[:total]) if k < first or c["from"].get("frame")]


def run(cmd, log):
    with open(log, "a") as f:
        return subprocess.run(CAP + cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=1800).returncode


def gates(answer):
    r = subprocess.run(CAP + ["uvx", "--with", "numpy", "python", str(SKILLS / "georef-gates/scripts/check_gcps.py"), str(answer)],
                       cwd=ROOT, capture_output=True, text=True)
    return json.loads(r.stdout)


def attempt(pdf, mission, d, cs, k, tried):
    """name-gcps (affine, then projective) and the gates on candidate k; if that does not pass and the candidate is cut
    from a PDF, graticule-gcps the same way (UNDOF's maps of the Golan: few towns a gazetteer places, a frame
    ticked every 5 minutes). Returns the passing result, else None."""
    c = cs[k]
    img = d / "cands" / c["file"]
    pdf_crop = c["from"].get("kind") == "rendered" and "box_px" in c["from"] and c.get("dpi")
    extra = ["--pdf", str(pdf), "--page", str(c.get("page", 1)), "--dpi", str(c["dpi"]), "--box-px", *map(str, c["from"]["box_px"])] if pdf_crop else []

    def names(ans, method):
        return UVX + [str(SKILLS / "name-gcps/scripts/name_gcps.py"), str(img), "--out", str(ans), "--method", method,
                      "--cache", str(d.parent / "nominatim-cache"), "--words", str(d / f"words.c{k + 1}.json")] \
            + (["--countrycodes", MISSIONS[mission]] if mission in MISSIONS else []) + extra, d / "name_gcps.log"

    def graticule(ans, method):
        return UVX + [str(SKILLS / "graticule-gcps/scripts/graticule_gcps.py"), str(pdf), "--page", str(c.get("page", 1)),
                      "--dpi", str(c.get("dpi")), "--box-px", *map(str, c["from"].get("box_px", [])), "--out", str(ans),
                      "--method", method] + (["--utm-zone", UTM_ZONES[mission]] if mission in UTM_ZONES else []), \
            d / "graticule_gcps.log"

    for tool, step in (("name-gcps", names), ("graticule-gcps", graticule)):
        if tool == "graticule-gcps" and not pdf_crop:
            break
        for method in ("affine", "projective"):
            # the graticule's answer has its own name: a declared failure must not overwrite the names' answer
            key = method if tool == "name-gcps" else f"grid_{method}"
            ans = d / f"answer.c{k + 1}.{key}.json"
            run(*step(ans, method))
            if not ans.exists():
                tried.append({"cand": k + 1, "method": method, "from": tool, "why": "error"})
                break
            a = json.loads(ans.read_text())
            if a["status"] != "ok":
                tried.append({"cand": k + 1, "method": method, "from": tool, "why": a.get("reason")})
                break  # a declared failure does not depend on the method
            g = gates(ans)
            (d / f"gates.c{k + 1}.{key}.json").write_text(json.dumps(g))
            failed = [x["name"] for x in g["gates"] if not x["passed"]]
            loo = next((x.get("max_px") for x in g["gates"] if x["name"] == "loo_residual"), None)
            tried.append({"cand": k + 1, "method": method, "from": tool, "gcps": len(a["gcps"]), "failed": failed,
                          "loo": loo, "words_from": a["tool"].get("words_from")})
            if g["passed"]:
                return {"stage": "ok", "cand": k + 1, "method": method, "answer": key, "gcps": len(a["gcps"]), "loo": loo,
                        "words_from": a["tool"].get("words_from"), "gcps_from": tool}
    return None


def one(pdf, mission, d):
    d.mkdir(parents=True, exist_ok=True)
    cj = d / "cands" / "candidates.json"
    if not cj.exists():
        run(UVX + [str(SKILLS / "document-maps/scripts/map_candidates.py"), str(pdf), "--out", str(d / "cands")], d / "cands.log")
    if not cj.exists():
        return {"stage": "candidates", "why": "no candidates"}
    cs = json.loads(cj.read_text())["candidates"]
    tried, found = [], None
    for k in to_try(cs):
        found = attempt(pdf, mission, d, cs, k, tried)
        if found:
            break
    if not found:
        return {"stage": "failed", "tried": tried}
    # a map that passed: its insets (the other panels) too, each kept if it passes alone, since a unit in an inset is
    # placed by the inset's own control points (MONUSCO 2023 to 2024: three quarters of the units are in the insets)
    for k in to_try(cs, first=4, total=len(cs)):
        if k + 1 != found["cand"] and cs[k]["from"].get("kind") == "rendered" and not list(d.glob(f"answer.c{k + 1}.*.json")):
            attempt(pdf, mission, d, cs, k, tried)
    return {**found, "tried": tried}


def main():
    import pypdfium2 as pdfium
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-year", type=int, default=0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--missions", default=None, help="a JSON object, file name -> mission acronym, where the PDF itself does not say")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    given = json.loads(Path(a.missions).read_text()) if a.missions else {}
    recs = []
    for f in sorted(Path(a.src).glob("*.pdf")):
        if a.only and f.name not in a.only:
            continue
        try:
            m = pdfium.PdfDocument(str(f)).get_metadata_dict()
        except Exception:
            m = {}
        recs.append({"file": f.name, "title": m.get("Title"), "date": pdf_date(m.get("CreationDate"), m.get("ModDate")),
                     "mission": given.get(f.name) or mission_of(m.get("Title"), f.stem)})
    recs = [r for r in recs if int(r["date"][:4]) >= a.min_year]
    recs.sort(key=lambda r: r["date"], reverse=True)
    res_p = out / "results.jsonl"
    done = {json.loads(l)["file"] for l in open(res_p)} if res_p.exists() else set()
    n = 0
    for r in recs:
        if r["file"] in done:
            continue
        if a.limit is not None and n >= a.limit:
            break
        try:
            res = one(Path(a.src) / r["file"], r["mission"], out / "runs" / Path(r["file"]).stem)
        except Exception as e:
            res = {"stage": "error", "why": repr(e)[:300]}
        line = {**r, **res}
        with open(res_p, "a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(json.dumps({k: line.get(k) for k in ("file", "mission", "date", "stage", "cand", "method", "gcps", "loo")}), flush=True)
        n += 1


if __name__ == "__main__":
    main()
