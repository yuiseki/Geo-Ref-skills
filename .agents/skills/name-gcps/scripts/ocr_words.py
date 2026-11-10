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


LATIN_WORD = re.compile(r"^[A-Za-z][A-Za-z'\-]*[A-Za-z]$")


def join_phrases(words, gap=0.8, max_words=3):
    """Latin words next to each other on one tesseract line, as phrases of 2 to max_words words: English names
    are several words ("Oxford Street", "Charing Cross"), and tesseract returns each word on its own (London,
    2026-11-04). Every run of consecutive words is offered; the Nominatim lookup keeps only real names."""
    out = []
    by_line = {}
    for w in words:
        if LATIN_WORD.match(w["text"]):
            by_line.setdefault(w["line"], []).append(w)
    for ws in by_line.values():
        ws = sorted(ws, key=lambda w: w["col"])
        runs, run = [], [ws[0]]
        for w in ws[1:]:
            prev = run[-1]
            if (w["col"] - w["w"] / 2) - (prev["col"] + prev["w"] / 2) <= gap * max(prev["h"], w["h"], 1.0):
                run.append(w)
            else:
                runs.append(run)
                run = [w]
        runs.append(run)
        for run in runs:
            for i in range(len(run)):
                for j in range(i + 2, min(len(run), i + max_words) + 1):
                    m = _merge(run[i:j])
                    m["text"] = " ".join(w["text"] for w in run[i:j])
                    m["kind"] = "phrase"
                    out.append(m)
    return out


def join_chome(words, max_gap=1.6):
    """Japanese map labels are often two lines: a district name over its block number ("KANOCHO" over
    "3-CHOME"). The pair is far more specific than the name alone (Nominatim knows "Kanocho 3-chome" as one
    place, and "Kanocho" in many). Join a word with a chome line starting below it within max_gap line heights
    and overlapping it horizontally. Positions are those of the image tesseract read (before turning back)."""
    out = []
    names = [w for w in words if w["text"].isalpha() and not is_cjk(w["text"])]
    # the lower line is a block number, or another upper-case word of a name set on two lines (COVENT / GARDEN)
    lower = [w for w in words if CHOME.match(w["text"]) or (w["text"].isalpha() and w["text"].isupper() and len(w["text"]) >= 3)]
    for c in lower:
        best = None
        for n in names:
            if n is c or (not CHOME.match(c["text"]) and not n["text"].isupper()):
                continue
            dy = (c["row"] - c["h"] / 2) - (n["row"] + n["h"] / 2)
            overlap = min(n["col"] + n["w"] / 2, c["col"] + c["w"] / 2) - max(n["col"] - n["w"] / 2, c["col"] - c["w"] / 2)
            if -0.3 * n["h"] <= dy <= max_gap * max(n["h"], 1.0) and overlap > 0.3 * min(n["w"], c["w"]):
                if best is None or dy < best[0]:
                    best = (dy, n)
        if best:
            m = _merge([best[1], c])
            m["text"] = f"{best[1]['text']} {c['text']}"
            m["kind"] = "chome" if CHOME.match(c["text"]) else "stacked"
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
    # the image goes on stdin, not through a temporary file: a step stopped by its time limit is killed outright and
    # its TemporaryDirectory is never removed (60 directories, 3.3 GB of in.png left in /tmp, 2026-11-09)
    ok, png = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("could not encode the image for tesseract")
    r = subprocess.run(["tesseract", "stdin", "-", "-l", langs, "--psm", str(psm), "tsv"], input=png.tobytes(), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"tesseract failed: {r.stderr.decode(errors='replace')[-500:]}")
    return r.stdout.decode("utf-8", errors="replace")


def read_words(image_path, langs="jpn+eng", scale=2.0, psm=11, angles=(0.0,), modes=("grey", "colour"), tiles=None):
    """Read the image in each mode (grey, colour) at each angle; all readings are returned, tagged "mode".
    tiles=(w, h): read overlapping tiles of that size (in the image's pixels, half a tile apart) one by one instead
    of the whole image at once. On a busy map tesseract's layout analysis misses labels it reads in a small crop:
    a z14 Kanazawa map (2026-11-10) gave no "Kanazawa" read whole at scale 1, 2 or 3, and conf 82 in 300 x 200
    tiles at scale 1. Words are tagged "tile": true."""
    words = []
    for mode in modes:
        for x in _read_words(image_path, langs, scale, psm, angles, mode == "grey", tiles):
            x["mode"] = mode
            words.append(x)
    return words


def _read_tiles(view, langs, psm, tw, th):
    from concurrent.futures import ThreadPoolExecutor
    h, w = view.shape[:2]
    xs = list(range(0, max(1, w - tw) + 1, max(1, tw // 2)))
    ys = list(range(0, max(1, h - th) + 1, max(1, th // 2)))
    if xs[-1] + tw < w:
        xs.append(w - tw)
    if ys[-1] + th < h:
        ys.append(h - th)
    boxes = [(max(0, x), max(0, y)) for y in ys for x in xs]

    def one(b):
        x, y = b
        found = parse_tsv(_tesseract(view[y:y + th, x:x + tw], langs, psm))
        found += join_cjk(found) + join_chome(found) + join_phrases(found)
        for f in found:
            f["col"] += x
            f["row"] += y
            f["tile"] = True
        return found

    with ThreadPoolExecutor(4) as ex:
        return [f for part in ex.map(one, boxes) for f in part]


def _read_words(image_path, langs, scale, psm, angles, grey, tiles=None):
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
        if tiles:
            found = _read_tiles(view, langs, psm, int(round(tiles[0] * scale)), int(round(tiles[1] * scale)))
        else:
            found = parse_tsv(_tesseract(view, langs, psm))
            found += join_cjk(found) + join_chome(found) + join_phrases(found)
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
