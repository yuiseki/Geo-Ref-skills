# uvx --with pytest pytest scripts/test_nominatim.py
import json
import os

import pytest

import nominatim


def test_caches_answers_and_sends_one_request_per_query(tmp_path):
    calls = []

    def fake(url, timeout=30):
        calls.append(url)
        return json.dumps([{"lat": "36.56", "lon": "136.65", "display_name": "Kanazawa"}]).encode()

    c = nominatim.Client(tmp_path, pause=0, fetch=fake)
    a = c.search("Kanazawa", countrycodes="jp")
    b = c.search("Kanazawa", countrycodes="jp")
    assert a == b and len(calls) == 1
    assert "countrycodes=jp" in calls[0] and "format=jsonv2" in calls[0]
    assert (c.requests, c.cached) == (1, 1)


def test_empty_answers_are_cached_but_errors_are_not(tmp_path):
    state = {"n": 0}

    def flaky(url, timeout=30):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("HTTP 502")
        return b"[]"

    c = nominatim.Client(tmp_path, pause=0, fetch=flaky)
    with pytest.raises(RuntimeError):
        c.search("Nowhere")
    assert c.search("Nowhere") == []
    assert c.search("Nowhere") == [] and state["n"] == 2


def test_refuses_the_public_server(tmp_path):
    with pytest.raises(ValueError):
        nominatim.Client(tmp_path, base="https://nominatim.openstreetmap.org")


def test_user_agent_names_the_tool():
    assert "Geo-Ref-skills" in nominatim.USER_AGENT


@pytest.mark.skipif(os.environ.get("GEOREF_NETWORK") != "1", reason="set GEOREF_NETWORK=1 to call the server")
def test_real_search(tmp_path):
    r = nominatim.Client(tmp_path).search("金沢市", countrycodes="jp", limit=3)
    assert r and abs(float(r[0]["lat"]) - 36.56) < 0.3
