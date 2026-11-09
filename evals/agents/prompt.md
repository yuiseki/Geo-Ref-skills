You are given a map image to georeference: find, for pixels of the image, their longitude and latitude.

Everything is in {{WORKDIR}}. Work only there; do not read anything outside it.

- The map: {{WORKDIR}}/task/image.png
- What you are told about it: {{WORKDIR}}/task/hint.json
{{HINT_TEXT}}

Reference map tiles are served at https://tile.yuiseki.net/styles/osm-liberty/<z>/<x>/<y>.png (Web Mercator, 256 px; the map image may be drawn in another style). A geocoder (Nominatim) is at https://nominatim.yuiseki.net (send a User-Agent header). Do not call any other OpenStreetMap server (nominatim.openstreetmap.org, tile.openstreetmap.org, overpass-api.de).

{{#SKILLS}}
This directory holds skills for this work. Read {{WORKDIR}}/AGENTS.md first, then open the SKILL.md of each skill in {{WORKDIR}}/.agents/skills/ that looks relevant before deciding the steps, and follow them.
{{/SKILLS}}

Write your answer to {{WORKDIR}}/answer.json, in this form (pixel coordinates have the origin at the top left corner of the image, x to the right as col, y down as row; method is one of affine, projective, poly2, poly3, and it is the transform fitted to your control points that is scored):

```json
{"status": "ok", "image": {"width": W, "height": H}, "method": "projective", "crs": "EPSG:4326",
 "gcps": [{"col": c, "row": r, "lon": x, "lat": y}, ...]}
```

If you cannot georeference the map reliably, or what you find contradicts the hint, write instead {"status": "failed", "reason": "..."}. A wrong answer is worse than a declared failure.

You have {{MINUTES}} minutes; the run is cut off then, and only answer.json is graded. Use at most 8 CPU threads.
