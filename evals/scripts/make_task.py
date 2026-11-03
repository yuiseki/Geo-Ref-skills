"""Make a georeferencing task with a known answer from raster tiles.

    python scripts/make_task.py --style osm-liberty --center 139.7528 35.6852 --zoom 15 --size 900 700 \
        --distortion projective --strength 0.5 --seed 1 --task-out tmp/tasks/t1 --truth-out tmp/truth/t1

The task image is drawn so that task pixel (col, row) shows global pixel D(col, row) at the zoom, where D is a
homography (corner convention on both sides). The agent gets <task-out>/image.png and <task-out>/hint.json.
<truth-out>/truth.json holds D and must not be given to the agent.

Distortions, all centred on the image centre:
    similarity  rotation and uniform scale
    affine      plus shear and a different scale on each axis
    projective  plus perspective (as in a photograph taken at an angle)
strength (0..1) scales the largest rotation (45 deg), log scale (0.3), shear and aspect (0.2), perspective (0.3).
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import tiles
import webmercator as wm

KINDS = ("similarity", "affine", "projective")


def distortion(kind, strength, W, H, rng):
    if kind not in KINDS:
        raise ValueError(f"unknown distortion {kind}; use one of {KINDS}")
    s = float(strength)
    th = np.radians(rng.uniform(-45, 45) * s)
    sc = float(np.exp(rng.uniform(-0.3, 0.3) * s))
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    A = sc * R
    params = {"kind": kind, "strength": s, "rotation_deg": float(np.degrees(th)), "scale": sc}
    if kind in ("affine", "projective"):
        shear = rng.uniform(-0.2, 0.2) * s
        aspect = float(np.exp(rng.uniform(-0.2, 0.2) * s))
        A = A @ np.array([[aspect, shear], [0.0, 1.0 / aspect]])
        params.update(shear=float(shear), aspect=aspect)
    K = np.eye(3)
    K[:2, :2] = A
    if kind == "projective":
        p = rng.uniform(-0.3, 0.3, 2) * s / max(W, H)
        K[2, :2] = p
        params["perspective"] = p.tolist()
    return K, params


def apply_h(M, p):
    q = np.column_stack([p, np.ones(len(p))]) @ M.T
    return q[:, :2] / q[:, 2:]


def make(style, center, zoom, size, kind, strength, seed, cache, task_out, truth_out, margin=0.5,
         tile_size=256, base=tiles.DEFAULT_BASE, offline=False, interp="linear", max_tiles=400):
    rng = np.random.default_rng(seed)
    W, H = size
    K, params = distortion(kind, strength, W, H, rng)
    cx, cy = (float(v) for v in wm.lonlat_to_global_px(center[0], center[1], zoom, tile_size))
    # D = translate(centre) @ K @ translate(-image centre): task corner coords to global corner coords
    D = np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1.0]]) @ K @ np.array([[1, 0, -W / 2], [0, 1, -H / 2], [0, 0, 1.0]])
    corners = np.array([[0, 0], [W, 0], [W, H], [0, H]], float)
    fp = apply_h(D, corners)
    img, ox, oy, stats = tiles.mosaic(style, zoom, fp[:, 0].min() - 2, fp[:, 1].min() - 2,
                                      fp[:, 0].max() + 2, fp[:, 1].max() + 2, cache, tile_size, base, offline, max_tiles)
    # cv2 indexes pixel centres: task index (i, j) is corner coord (i + .5, j + .5); mosaic index = global - o - .5
    M = np.array([[1, 0, -ox - 0.5], [0, 1, -oy - 0.5], [0, 0, 1.0]]) @ D @ np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1.0]])
    flag = {"linear": cv2.INTER_LINEAR, "nearest": cv2.INTER_NEAREST}[interp]
    task = cv2.warpPerspective(img, M, (W, H), flags=flag | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(255, 0, 255))
    src = apply_h(M, np.column_stack([np.mgrid[0:W, 0:H][0].ravel(), np.mgrid[0:W, 0:H][1].ravel()]))
    if src.min() < -0.5 or src[:, 0].max() > img.shape[1] - 0.5 or src[:, 1].max() > img.shape[0] - 0.5:
        raise RuntimeError("task pixels fall outside the fetched mosaic")

    lon, lat = wm.global_px_to_lonlat(fp[:, 0], fp[:, 1], zoom, tile_size)
    w, e, s_, n = lon.min(), lon.max(), lat.min(), lat.max()
    ew, ns = (e - w) * margin, (n - s_) * margin
    fw, fs = rng.uniform(0.1, 0.9, 2)  # the footprint is not centred in the hint
    hint_bbox = [w - ew * fw, s_ - ns * fs, e + ew * (1 - fw), n + ns * (1 - fs)]

    task_out, truth_out = Path(task_out), Path(truth_out)
    task_out.mkdir(parents=True, exist_ok=True)
    truth_out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(task).save(task_out / "image.png")
    hint = {"image": "image.png", "width": W, "height": H, "bbox": [float(v) for v in hint_bbox], "zoom": zoom,
            "tile_size": tile_size, "style": style, "tile_base": base}
    (task_out / "hint.json").write_text(json.dumps(hint, indent=2), encoding="utf-8")
    truth = {"width": W, "height": H, "zoom": zoom, "tile_size": tile_size, "style": style,
             "center": list(center), "seed": seed, "distortion": params,
             "task_px_to_global_px": D.tolist(),
             "footprint_lonlat": [[float(a), float(b)] for a, b in zip(lon, lat)], "tiles": stats}
    (truth_out / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return task, hint, truth


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--style", required=True)
    ap.add_argument("--center", type=float, nargs=2, required=True, metavar=("LON", "LAT"))
    ap.add_argument("--zoom", type=int, required=True)
    ap.add_argument("--size", type=int, nargs=2, default=[900, 700], metavar=("W", "H"))
    ap.add_argument("--distortion", choices=KINDS, default="similarity")
    ap.add_argument("--strength", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--margin", type=float, default=0.5, help="hint bbox is this fraction larger on each axis")
    ap.add_argument("--cache", default="tmp/tiles")
    ap.add_argument("--task-out", required=True)
    ap.add_argument("--truth-out", required=True)
    ap.add_argument("--tile-size", type=int, default=256, choices=[256, 512])
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    _, hint, truth = make(a.style, a.center, a.zoom, a.size, a.distortion, a.strength, a.seed, a.cache,
                          a.task_out, a.truth_out, a.margin, a.tile_size, offline=a.offline)
    print(json.dumps({"hint": hint["bbox"], "distortion": truth["distortion"], "tiles": truth["tiles"]}))


if __name__ == "__main__":
    main()
