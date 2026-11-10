# uvx --with pytest pytest scripts/test_fetch_symbols.py
import fetch_symbols as fs


def test_every_symbol_title_names_the_friendly_light_frame():
    assert all(t.endswith(")") for t in fs.SYMBOLS.values())
    assert fs.PREFIX.startswith("Military Symbol - Friendly Unit (Solid Light")


def test_credit_strips_the_artist_markup():
    info = {"extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:CdnMCG">CdnMCG</a>'}}}
    assert fs.credit(info) == ("CC BY-SA 4.0", "CdnMCG")
