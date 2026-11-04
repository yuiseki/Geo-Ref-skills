"""White out the United Nations name and the map reference number on a UN map before it is shown.

    uvx --with numpy --with opencv-python-headless python docs/examples/mask_un_marks.py image.png words.json out.png

The terms of use of the UN Geospatial maps (https://www.un.org/geospatial/en/mandates/public) allow a modified
map to be used as the basis of other work, on condition that the United Nations name and the map reference
number are removed; the result may be credited as "based on United Nations map". This removes, by the words
tesseract read on the map (words.json, as name-gcps keeps them):

- the words United and Nations, and the words of the reference number (Map, No., Rev., a four-digit number),
- the bottom band of the image, where the disclaimer and the reference number block are printed.

Check the result by eye: a word tesseract did not read is not removed.
"""

import json
import re
import sys

import cv2

# the name only, not the acronyms of missions and units (UNMO, UNPOL): tesseract reads those in some boxes and
# not in others, and a bare "UN" also comes from UNITY split in two
UN = re.compile(r"\bunited\b|\bnations\b", re.IGNORECASE)
# the reference number block ("Map No. 4133 Rev. 98", "Jan 2026"), looked for only near the foot: elsewhere
# tesseract finds four-digit numbers and "Map" in symbols and lines
REF = re.compile(r"^(map|no\.?|rev\.?|\d{4})$", re.IGNORECASE)  # not the scale bar's 10, 20
DISCLAIMER = re.compile(r"^(boundaries|designations|endorsement|acceptance|final|status)$", re.IGNORECASE)


def boxes(words, pad=3):
    out = []
    for w in words:
        t = w["text"].strip()
        if t and UN.search(t):
            out.append((int(w["col"] - w["w"] / 2 - pad), int(w["row"] - w["h"] / 2 - pad),
                        int(w["col"] + w["w"] / 2 + pad), int(w["row"] + w["h"] / 2 + pad)))
    return out


def main(image, words, out):
    img = cv2.imread(image)
    H = img.shape[0]
    for x0, y0, x1, y1 in boxes(json.load(open(words, encoding="utf-8"))):
        cv2.rectangle(img, (max(x0, 0), max(y0, 0)), (x1, y1), (255, 255, 255), -1)
    # the disclaimer and the reference number sit at the foot; clear from the top of the higher of them down,
    # whatever was read below it (the bottom 5.5 % when neither was read)
    ws = json.load(open(words, encoding="utf-8"))
    foot = [w for w in ws if w["row"] > 0.9 * H and w["conf"] >= 60]
    tops = [w["row"] - w["h"] / 2 for w in foot
            if DISCLAIMER.match(w["text"].strip(".,")) or REF.match(w["text"].strip(".,")) or UN.search(w["text"])]
    top = (min(tops) if tops else (1 - 0.055) * H) - 3
    img[int(top):, :] = 255
    cv2.imwrite(out, img)


if __name__ == "__main__":
    main(*sys.argv[1:4])
