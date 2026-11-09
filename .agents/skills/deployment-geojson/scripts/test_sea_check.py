# uvx --with pytest pytest scripts/test_sea_check.py
import io
import json
import sys
import urllib.error

import pytest

import sea_check as S


def land_at(*lands):
    """A reverse geocoder with land only at the given (lat, lon) cells of 0.05 degrees."""
    cells = {(round(a / 0.05), round(o / 0.05)) for a, o in lands}

    def reverse(lat, lon):
        return (round(lat / 0.05), round(lon / 0.05)) in cells
    return reverse


def test_a_point_on_land_is_not_sea():
    assert not S.is_sea(5.0, -4.0, land_at((5.0, -4.0)))


def test_a_point_in_open_water_is_sea():
    assert S.is_sea(3.7, -3.9, land_at((5.4, -4.0)))


def test_a_point_a_little_off_the_coast_is_not_sea():
    # a unit on a coastal town's dot may fall a few hundred metres into the water: land within a cell of it
    assert not S.is_sea(5.0, -4.0, land_at((5.0, -3.95)))


def test_the_filter_drops_sea_points_and_counts_them(tmp_path):
    fc = {"type": "FeatureCollection", "mission": "UNOCI", "map_date": "20060905",
          "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-4.0, 5.0]}, "properties": {}},
                       {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-3.9, 3.7]}, "properties": {}}]}
    out, dropped = S.filter_sea(fc, land_at((5.0, -4.0)))
    assert len(out["features"]) == 1 and dropped == 1
    assert out["features"][0]["geometry"]["coordinates"] == [-4.0, 5.0]


class FakeServer:
    """Stands in for urlopen: answers from a dict of (lat, lon) -> JSON body or an HTTP status, and records the URLs."""

    def __init__(self, answers):
        self.answers, self.urls, self.agents = answers, [], []

    def __call__(self, req, timeout=None):
        self.urls.append(req.full_url)
        self.agents.append(req.get_header("User-agent"))
        q = dict(p.split("=") for p in req.full_url.split("?")[1].split("&"))
        a = self.answers.get((float(q["lat"]), float(q["lon"])), {"error": "Unable to geocode"})
        if isinstance(a, int):
            raise urllib.error.HTTPError(req.full_url, a, "x", {}, None)
        return io.BytesIO(json.dumps(a).encode())


def test_land_water_and_404(monkeypatch):
    srv = FakeServer({(5.0, -4.0): {"address": {"country": "CI"}}, (3.7, -3.9): 404})
    monkeypatch.setattr(S.urllib.request, "urlopen", srv)
    rev = S.nominatim_land("http://n", {})
    assert rev(5.0, -4.0) is True
    assert rev(3.7, -3.9) is False      # 404: no land
    assert rev(1.0, 1.0) is False       # {"error": ...}: no land


def test_a_cell_is_asked_once(monkeypatch):
    srv = FakeServer({(5.0, -4.0): {"address": {}}})
    monkeypatch.setattr(S.urllib.request, "urlopen", srv)
    cache = {}
    rev = S.nominatim_land("http://n", cache)
    rev(5.0, -4.0); rev(5.01, -4.01); rev(5.0, -4.0)
    assert len(srv.urls) == 1 and cache == {"100,-80": True}


def test_the_request_names_itself_and_asks_country_zoom(monkeypatch):
    # the server refuses Python's default User-Agent (403)
    srv = FakeServer({})
    monkeypatch.setattr(S.urllib.request, "urlopen", srv)
    S.nominatim_land("http://n", {})(5.0, -4.0)
    assert srv.agents == [S.USER_AGENT] and "zoom=5" in srv.urls[0]


def test_a_server_error_is_not_read_as_sea(monkeypatch):
    monkeypatch.setattr(S.urllib.request, "urlopen", FakeServer({(5.0, -4.0): 500}))
    with pytest.raises(urllib.error.HTTPError):
        S.nominatim_land("http://n", {})(5.0, -4.0)


def test_a_cache_given_is_used_without_asking(monkeypatch):
    srv = FakeServer({})
    monkeypatch.setattr(S.urllib.request, "urlopen", srv)
    assert S.nominatim_land("http://n", {"100,-80": True})(5.0, -4.0) is True and srv.urls == []


def test_main_writes_to_out_and_leaves_src_alone(tmp_path, monkeypatch):
    src, out = tmp_path / "src", tmp_path / "out"; src.mkdir()
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-4.0, 5.0]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-3.9, 3.7]}, "properties": {}}]}
    (src / "a.geojson").write_text(json.dumps(fc))
    (src / "summary.jsonl").write_text("{}\n")
    before = (src / "a.geojson").read_bytes()
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"100,-80": True}))   # land only at Abidjan's cell
    monkeypatch.setattr(S.urllib.request, "urlopen", FakeServer({}))
    monkeypatch.setattr(sys, "argv", ["sea_check.py", "--src", str(src), "--out", str(out), "--nominatim", "http://n", "--cache", str(cache)])
    S.main()
    assert (src / "a.geojson").read_bytes() == before
    assert len(json.loads((out / "a.geojson").read_text())["features"]) == 1
    assert not (out / "summary.jsonl").exists()
    assert len(json.loads(cache.read_text())) > 1


def test_the_sea_check_is_recorded_in_the_file():
    fc = {"type": "FeatureCollection", "checks": {"hull_margin": 0.3}, "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-3.9, 3.7]}, "properties": {}}]}
    out, dropped = S.filter_sea(fc, land_at((5.0, -4.0)))
    assert dropped == 1 and out["checks"] == {"hull_margin": 0.3, "sea": {"cell_deg": 0.05, "dropped": 1}}
    assert fc["checks"] == {"hull_margin": 0.3}
