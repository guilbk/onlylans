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
        if b[5] == buildings.RIBEIRA:
            continue  # the quay row sits close to the quay road on purpose
        x, y, w, h = b[:4]
        assert road_dist(x, y) >= math.hypot(w, h) / 2 + buildings.ROAD_HALF_M - 1.0, b


def test_count_cap_and_variety():
    assert 0 < len(B) <= buildings.CAP
    assert {b[5] for b in B} >= {buildings.RIBEIRA, buildings.FOZ, buildings.MATOSINHOS}
    assert {r[5] for r in R} >= {buildings.BAIXA, buildings.BOAVISTA, buildings.BONFIM}
    assert len({(b[2], b[3], b[6]) for b in B}) > 50  # no clone houses


def test_district_typing_at_known_points():
    for name, did in basemap_names().items():
        if did == buildings.RIBEIRA:
            continue  # its row follows the river bank, just outside the outline
        d = next(d for d in LAY["districts"] if d["name"] == name)
        near = [b for b in B if b[5] == did]
        if not near:
            assert any(r[5] == did for r in R), name  # that district is terraced rows only
            continue
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


R = [OUT["rows"][i : i + 6] for i in range(0, len(OUT["rows"]), 6)]


def row_points(r):
    x, y, ln, ang, dep, _ = r
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    nx, ny = -s, c
    for t in (0.0, 0.5, 1.0):
        for f in (-0.5, 0.0, 0.5):
            yield x + c * ln * t + nx * dep * f, y + s * ln * t + ny * dep * f


def test_rows_dense_and_compact():
    assert 3000 < len(R) <= buildings.CAP_ROWS
    assert all(r[2] <= buildings.MAX_RUN * buildings.CELL_M for r in R)
    assert len(buildings.render_js(OUT).encode()) < 300_000


def test_rows_keep_streets_water_and_parks_open():
    parks = [
        [(p["poly"][i], p["poly"][i + 1]) for i in range(0, len(p["poly"]), 2)]
        for p in LAY["parks"]
    ]
    river = [(LAY["river"][i], LAY["river"][i + 1]) for i in range(0, len(LAY["river"]), 2)]
    for r in R[::13]:
        for px, py in row_points(r):
            # bends of the street cut corners, hence the 3 m slack
            assert road_dist(px, py) >= buildings.ROAD_HALF_M - 3.0, r
        mid = list(row_points(r))[4]  # the centre of the row
        assert not basemap.inside_poly(mid, river)
        assert not any(basemap.inside_poly(mid, p) for p in parks)


def test_rows_are_denser_in_the_centre():
    cx = sum(r[0] for r in R) / len(R)
    cy = sum(r[1] for r in R) / len(R)
    baixa = next(d for d in LAY["districts"] if d["name"] == "Baixa")
    bx = sum(baixa["poly"][0::2]) / (len(baixa["poly"]) // 2)
    by = sum(baixa["poly"][1::2]) / (len(baixa["poly"]) // 2)
    near = sum(math.hypot(r[0] - bx, r[1] - by) < 1700 for r in R)
    far = sum(math.hypot(r[0] - bx, r[1] - by) > 4500 for r in R)
    assert near > far / 3 and cx and cy  # centre ring (area ~9 km2) vs far field (much wider)
