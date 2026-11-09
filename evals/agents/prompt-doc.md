You are given a document (a PDF page) that contains a map among other content. Find the map in it and georeference it: find, for pixels of the map, their longitude and latitude.

Everything is in {{WORKDIR}}. Work only there; do not read anything outside it.

- The document: {{WORKDIR}}/task/document.pdf
- What you are told about it: {{WORKDIR}}/task/hint.json
{{HINT_TEXT}}
- Pixel coordinates in your answer are pixels of the whole page drawn at the dpi in hint.json (page_px is that page's width and height): origin at the top left corner of the page, x to the right as col, y down as row. Put your control points on the map, not elsewhere on the page.

Reference map tiles are served at https://tile.yuiseki.net/styles/osm-liberty/<z>/<x>/<y>.png (Web Mercator, 256 px; the map in the document may be drawn in another style). A geocoder (Nominatim) is at https://nominatim.yuiseki.net (send a User-Agent header). Do not call any other OpenStreetMap server (nominatim.openstreetmap.org, tile.openstreetmap.org, overpass-api.de).

{{#SKILLS}}
This directory holds skills for this work. Read {{WORKDIR}}/AGENTS.md first, then open the SKILL.md of each skill in {{WORKDIR}}/.agents/skills/ that looks relevant before deciding the steps, and follow them.
{{/SKILLS}}

Write your answer to {{WORKDIR}}/answer.json, in this form (method is one of affine, projective, poly2, poly3, and it is the transform fitted to your control points that is scored, over the map's area):

```json
{"status": "ok", "image": {"width": PAGE_W, "height": PAGE_H}, "method": "projective", "crs": "EPSG:4326",
 "gcps": [{"col": c, "row": r, "lon": x, "lat": y}, ...]}
```

If you cannot georeference the map reliably, write instead {"status": "failed", "reason": "..."}. A wrong answer is worse than a declared failure.

You have {{MINUTES}} minutes; the run is cut off then, and only answer.json is graded. Use at most 8 CPU threads.
