You are given a United Nations peacekeeping deployment map (a PDF). It shows the military units of the mission as symbols (frames with the unit's arm, size marks above, the contributing country beside them), each tied to a place on the map. Turn the map into geographic data: the longitude and latitude of each unit.

Everything is in {{WORKDIR}}. Work only there; do not read anything outside it.

- The map: {{WORKDIR}}/task/map.pdf
{{HINT_TEXT}}

A geocoder (Nominatim) is at https://nominatim.yuiseki.net (send a User-Agent header) and map tiles at https://tile.yuiseki.net/styles/osm-liberty/<z>/<x>/<y>.png. Do not call any other OpenStreetMap server (nominatim.openstreetmap.org, tile.openstreetmap.org, overpass-api.de).

{{#SKILLS}}
This directory holds skills for this work. Read {{WORKDIR}}/AGENTS.md first, then open the SKILL.md of each skill in {{WORKDIR}}/.agents/skills/ that looks relevant before deciding the steps, and follow them.
{{/SKILLS}}

Write your answer to {{WORKDIR}}/answer.geojson: a GeoJSON FeatureCollection with one Point feature (WGS 84 longitude, latitude) per unit on the map, with what you read of the unit in its properties (for example the country label and the abbreviation inside the frame). Units whose position you cannot determine are left out, not guessed.

If you cannot georeference the map reliably, write instead {"status": "failed", "reason": "..."} to answer.geojson. A wrong position is worse than a missing one.

You have {{MINUTES}} minutes; the run is cut off then, and only answer.geojson is graded. Use at most 8 CPU threads.
