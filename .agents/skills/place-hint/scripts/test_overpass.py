# uvx --with pytest pytest scripts/test_overpass.py
import json

import pytest

import overpass


def test_query_names_the_element_and_caches(tmp_path):
    calls = []

    def fake(url, data, timeout=90):
        calls.append(data)
        return json.dumps({"elements": [{"type": "node", "lat": 51.5, "lon": -0.13}]}).encode()

    c = overpass.Client(tmp_path, pause=0, fetch=fake)
    a = c.named_near('Regent "Street"', 51.51, -0.139, 3000)
    b = c.named_near('Regent "Street"', 51.51, -0.139, 3000)
    assert a == b and len(a) == 1 and len(calls) == 1
    q = calls[0]
    assert 'nwr["name"="Regent \\"Street\\""](around:3000,51.51,-0.139)' in q and "out geom" in q
    assert "[timeout:60]" in q


def test_refuses_public_servers(tmp_path):
    with pytest.raises(ValueError):
        overpass.Client(tmp_path, base="https://overpass-api.de/api/interpreter")
