import math

import numpy as np

from pipeline import basemap, buildings

SEGS = np.array(buildings.load_segments(buildings.ROADS_DEFAULT))
LAY = basemap.build(buildings.DATA_DEFAULT)
OUT = buildings.build()
B = [OUT["b"][i : i + 8] for i in range(0, len(OUT["b"]), 8)]


def road_dist(x, y):
    x0, y0, x1, y1 = SEGS.T
    dx, dy = x1 - x0, y1 - y0
    ln = np.maximum(dx * dx + dy * dy, 1e-9)
    t = np.clip(((x - x0) * dx + (y - y0) * dy) / ln, 0, 1)
    return float(np.hypot(x - x0 - t * dx, y - y0 - t * dy).min())


def test_no_building_overlaps_a_road():
    for b in B[::7]:  # every 7th: brute force over all segments
        x, y, w, h = b[:4]
        assert road_dist(x, y) >= math.hypot(w, h) / 2 + buildings.ROAD_HALF_M - 1.0, b


def test_count_cap_and_variety():
    assert 0 < len(B) <= buildings.CAP
    assert {b[5] for b in B} >= {buildings.RIBEIRA, buildings.BAIXA, buildings.BOAVISTA}
    assert len({(b[2], b[3], b[6]) for b in B}) > 50  # no clone houses


def test_district_typing_at_known_points():
    for name, did in basemap_names().items():
        d = next(d for d in LAY["districts"] if d["name"] == name)
        near = [b for b in B if b[5] == did]
        assert near, name
        poly = [(d["poly"][i], d["poly"][i + 1]) for i in range(0, len(d["poly"]), 2)]
        inside = sum(basemap.inside_poly((b[0], b[1]), poly) for b in near)
        assert inside >= 0.95 * len(near), name  # whole-metre rounding at the edges


def basemap_names():
    return {k: v for k, v in buildings.NAMES.items() if k in {d["name"] for d in LAY["districts"]}}


def test_no_buildings_in_water():
    for key in ("river", "sea"):
        p = LAY[key]
        poly = [(p[i], p[i + 1]) for i in range(0, len(p), 2)]
        assert not any(basemap.inside_poly((b[0], b[1]), poly) for b in B[::5])


def test_deterministic_bytes():
    assert buildings.render_js(buildings.build()) == buildings.render_js(OUT)
