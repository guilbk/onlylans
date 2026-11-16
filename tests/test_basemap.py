import json
from pathlib import Path

from pipeline import basemap, geo

DATA = Path("game/game_data.json")
W, H = 15000, 19000


def pairs(flat):
    return list(zip(flat[0::2], flat[1::2], strict=True))


def test_projection_matches_geo():
    assert basemap.to_m(geo.LON0 + 0.01, geo.LAT0 - 0.01) == geo.proj(
        geo.LON0 + 0.01, geo.LAT0 - 0.01
    )


def test_clip_poly_to_map():
    out = basemap.clip_poly(
        [(-100.0, -100.0), (200.0, -100.0), (200.0, 200.0), (-100.0, 200.0)], 150, 120
    )
    assert out
    assert all(0 <= x <= 150 and 0 <= y <= 120 for x, y in out)
    assert basemap.clip_poly([(-9.0, -9.0), (-5.0, -9.0), (-5.0, -5.0)], 10, 10) == []


def test_everything_inside_the_map():
    layer = basemap.build(DATA)
    shapes = [layer["river"], layer["sea"]] + [p["poly"] for p in layer["parks"]]
    shapes += [d["poly"] for d in layer["districts"]] + [b["line"] for b in layer["bridges"]]
    for s in shapes:
        assert s
        assert all(0 <= x <= W and 0 <= y <= H for x, y in pairs(s))


def test_counts():
    layer = basemap.build(DATA)
    assert len(layer["parks"]) >= 4
    assert len(layer["bridges"]) == 5
    assert len(layer["districts"]) == 7


def test_bridges_cross_the_river():
    layer = basemap.build(DATA)
    river = pairs(layer["river"])
    for b in layer["bridges"]:
        (x0, y0), (x1, y1) = pairs(b["line"])
        mid = ((x0 + x1) / 2, (y0 + y1) / 2)
        assert basemap.inside_poly(mid, river), b["name"]
        assert not basemap.inside_poly((x0, y0), river)
        assert not basemap.inside_poly((x1, y1), river)


def test_district_labels_do_not_overlap():
    ds = basemap.build(DATA)["districts"]
    for i, a in enumerate(ds):
        for b in ds[i + 1 :]:
            wa = len(a["name"]) * basemap.LABEL_CHAR_PX / 2
            wb = len(b["name"]) * basemap.LABEL_CHAR_PX / 2
            dx = abs(a["x"] - b["x"]) * basemap.LABEL_K
            dy = abs(a["y"] - b["y"]) * basemap.LABEL_K
            assert dx >= wa + wb or dy >= basemap.LABEL_H_PX, (a["name"], b["name"])


def test_deterministic_and_main(tmp_path):
    a = basemap.render_js(basemap.build(DATA))
    assert a == basemap.render_js(basemap.build(DATA))
    assert "not from the UCI" in a
    out = tmp_path / "b.js"
    assert basemap.main(["--data", str(DATA), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == a
    obj = json.loads(a.split("PG.basemap = ", 1)[1].rsplit(";", 1)[0])
    assert obj["source"] == basemap.SOURCE
