"""Words on an image with their positions, read by the tesseract command.

    python scripts/ocr_words.py image.png [--langs jpn+eng] [--scale 2]

Prints JSON lines {"text", "conf", "col", "row", "w", "h", "angle", "kind"}: col and row are the centre in the
original image's pixels (corner convention). The image is enlarged by --scale first, which helps small map labels;
positions are divided back. With --angles, the image is also read turned by each angle (a map may be rotated and
tesseract reads level text only) and positions are turned back. tesseract's sparse mode returns Japanese one
character at a time, so characters on one tesseract line that touch are also joined into "kind": "joined" items, and a name with
a "N-CHOME" line under it into a "kind": "chome" item. The image is read both in grey and in colour, since tesseract finds different names in each. tesseract must be installed with the languages asked for; if it is missing or
fails, this raises instead of returning no words.
"""

import argparse
import csv
import re
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2


import numpy as np

CJK = set(range(0x3040, 0x3100)) | set(range(0x3400, 0xA000))


def is_cjk(t):
    return bool(t) and all(ord(ch) in CJK for ch in t)


def parse_tsv(text, scale=1.0):
    words = []
    for row in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        t = (row.get("text") or "").strip()
        if not t or float(row["conf"]) < 0:
            continue
        x, y, w, h = (float(row[k]) / scale for k in ("left", "top", "width", "height"))
        words.append({"text": t, "conf": float(row["conf"]), "col": x + w / 2, "row": y + h / 2, "w": w, "h": h,
                      "line": (row["block_num"], row["par_num"], row["line_num"]), "kind": "word"})
    return words


def join_cjk(words, gap=0.6):
    """Join CJK characters that sit next to each other on one tesseract line (gap in character heights).
    The joined item's confidence is the lowest of its characters."""
    out = []
    by_line = {}
    for w in words:
        if is_cjk(w["text"]):
            by_line.setdefault(w["line"], []).append(w)
    for ws in by_line.values():
        ws = sorted(ws, key=lambda w: w["col"])
        run = [ws[0]]
        for w in ws[1:]:
            prev = run[-1]
            size = max(prev["h"], w["h"], 1.0)
            if (w["col"] - w["w"] / 2) - (prev["col"] + prev["w"] / 2) <= gap * size:
                run.append(w)
            else:
                if len(run) > 1:
                    out.append(_merge(run))
                run = [w]
        if len(run) > 1:
            out.append(_merge(run))
    return out


CHOME = re.compile(r"^\d{1,2}-CHOME$", re.IGNORECASE)


def join_chome(words, max_gap=1.6):
    """Japanese map labels are often two lines: a district name over its block number ("KANOCHO" over
    "3-CHOME"). The pair is far more specific than the name alone (Nominatim knows "Kanocho 3-chome" as one
    place, and "Kanocho" in many). Join a word with a chome line starting below it within max_gap line heights
    and overlapping it horizontally. Positions are those of the image tesseract read (before turning back)."""
    out = []
    names = [w for w in words if w["text"].isalpha() and not is_cjk(w["text"])]
    for c in (w for w in words if CHOME.match(w["text"])):
        best = None
        for n in names:
            dy = (c["row"] - c["h"] / 2) - (n["row"] + n["h"] / 2)
            overlap = min(n["col"] + n["w"] / 2, c["col"] + c["w"] / 2) - max(n["col"] - n["w"] / 2, c["col"] - c["w"] / 2)
            if -0.3 * n["h"] <= dy <= max_gap * max(n["h"], 1.0) and overlap > 0.3 * min(n["w"], c["w"]):
                if best is None or dy < best[0]:
                    best = (dy, n)
        if best:
            m = _merge([best[1], c])
            m["text"] = f"{best[1]['text']} {c['text']}"
            m["kind"] = "chome"
            out.append(m)
    return out


def _merge(run):
    x0 = min(w["col"] - w["w"] / 2 for w in run)
    x1 = max(w["col"] + w["w"] / 2 for w in run)
    y0 = min(w["row"] - w["h"] / 2 for w in run)
    y1 = max(w["row"] + w["h"] / 2 for w in run)
    return {"text": "".join(w["text"] for w in run), "conf": min(w["conf"] for w in run), "col": (x0 + x1) / 2,
            "row": (y0 + y1) / 2, "w": x1 - x0, "h": y1 - y0, "line": run[0]["line"], "kind": "joined"}


def _tesseract(img, langs, psm):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "in.png"
        cv2.imwrite(str(p), img)
        r = subprocess.run(["tesseract", str(p), "-", "-l", langs, "--psm", str(psm), "tsv"],
                           capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"tesseract failed: {r.stderr[-500:]}")
    return r.stdout


def read_words(image_path, langs="jpn+eng", scale=2.0, psm=11, angles=(0.0,), modes=("grey", "colour")):
    """Read the image in each mode (grey, colour) at each angle; all readings are returned, tagged "mode"."""
    words = []
    for mode in modes:
        for x in _read_words(image_path, langs, scale, psm, angles, mode == "grey"):
            x["mode"] = mode
            words.append(x)
    return words


def _read_words(image_path, langs, scale, psm, angles, grey):
    if shutil.which("tesseract") is None:
        raise FileNotFoundError("tesseract is not installed")
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE if grey else cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(image_path)
    # both grey and colour by default: on a Kobe osm-liberty map (2026-11-04) tesseract read different names
    # in each (colour: KANOCHO, KAIGANDOR; grey: NINOMIYACHO, KAWASAKICHO, ONOHAMACHO), 22 and 11 names, 31 together
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    h, w = img.shape[:2]
    words = []
    for ang in angles:
        if ang:
            M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
            c = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], float) @ M.T
            M[:, 2] -= c.min(axis=0)
            size = np.ceil(c.max(axis=0) - c.min(axis=0)).astype(int)
            view = cv2.warpAffine(img, M, (int(size[0]), int(size[1])), borderValue=255 if img.ndim == 2 else (255, 255, 255))
            Mi = cv2.invertAffineTransform(M)
        else:
            view, Mi = img, None
        found = parse_tsv(_tesseract(view, langs, psm))
        found += join_cjk(found) + join_chome(found)
        for x in found:
            if Mi is not None:
                x["col"], x["row"] = (Mi @ np.array([x["col"], x["row"], 1.0])).tolist()
            x["col"] /= scale
            x["row"] /= scale
            x["w"] /= scale
            x["h"] /= scale
            x["angle"] = float(ang)
            x["line"] = list(x["line"])
            words.append(x)
    return words


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--langs", default="jpn+eng")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--angles", type=float, nargs="*", default=[0.0])
    a = ap.parse_args()
    for w in read_words(a.image, a.langs, a.scale, angles=a.angles):
        print(json.dumps(w, ensure_ascii=False))


if __name__ == "__main__":
    main()
