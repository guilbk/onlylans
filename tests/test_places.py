import math
import random

import numpy as np

from pipeline import geo, places

UNIT = 5


def order(t, x_m, y_m):
    """Compact order stub: only t and the pickup in map units are read by places."""
    return [t, round(x_m / UNIT), round(y_m / UNIT)]


def around(rng, cx, cy, spread, n, t_lo=0, t_hi=7199):
    return [
        order(rng.randint(t_lo, t_hi), rng.gauss(cx, spread), rng.gauss(cy, spread))
        for _ in range(n)
    ]


def background(rng, n=200):
    """Pickups spread evenly in time and over a 6 x 6 km area around the centre."""
    return [
        order(rng.randint(0, 7199), rng.uniform(5000, 11000), rng.uniform(9000, 15000))
        for _ in range(n)
    ]


def test_place_name_levels():
    x, y = geo.proj(-8.6112, 41.1481)
    assert places.place_name(x, y) == "Aliados"
    assert places.place_name(x, y) == "Aliados"
    # about 1.5 km north of Boavista: not within 900 m, within 2500 m
    bx, by = geo.proj(-8.6340, 41.1620)
    assert places.place_name(bx - 1500, by) == "район Boavista"
    assert places.place_name(bx - 900 - 100, by).startswith("район")
    assert places.place_name(0.0, 0.0) == "околиця"


def test_place_table_matches_contract():
    assert len(places.PLACES) == 22
    assert len({p[0] for p in places.PLACES}) == 22
    assert places.PLACES[0] == ("Aliados", -8.6112, 41.1481)


def test_planted_cluster_gives_hotspot_at_right_place():
    rng = random.Random(1)
    cx, cy = geo.proj(-8.5835, 41.1618)  # Estadio do Dragao
    orders = background(rng) + around(rng, cx, cy, 120.0, 150)
    hot, _ = places.hot_and_surges(orders, UNIT)
    assert 1 <= len(hot) <= 10
    top = max(hot, key=lambda h: h["w"])
    assert math.hypot(top["x"] * UNIT - cx, top["y"] * UNIT - cy) < 200
    assert top["name"] == "Estádio do Dragão"
    assert top["w"] > 0.35
    assert hot[0] == top  # strongest peak first


def test_hotspots_are_separated_and_shares_valid():
    rng = random.Random(2)
    orders = background(rng, 600)
    hot, _ = places.hot_and_surges(orders, UNIT)
    assert 6 <= len(hot) <= 10
    for i, a in enumerate(hot):
        assert 0 < a["w"] <= 1 and set(a) == {"x", "y", "w", "name"}
        for b in hot[i + 1 :]:
            # centres are re-centred means, so allow a margin below the 1200 m peak spacing
            assert math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * UNIT > 400


def test_find_peaks_rules():
    grid = np.zeros((38, 30))
    grid[5, 5] = 10.0
    grid[5, 6] = 9.0  # same neighbourhood as the first peak
    grid[20, 20] = 5.0
    peaks = places.find_peaks(grid)
    assert peaks == [(2750.0, 2750.0), (10250.0, 10250.0)]
    dense = np.ones((38, 30))
    assert len(places.find_peaks(dense)) <= places.HOT_MAX
    assert places.find_peaks(np.zeros((38, 30))) == []


def test_empty_orders():
    assert places.hot_and_surges([], UNIT) == ([], [])


def test_planted_burst_gives_surge_in_right_window():
    rng = random.Random(3)
    sx, sy = geo.proj(-8.6094, 41.1511)  # Trindade
    burst = around(rng, sx, sy, 100.0, 40, t_lo=3000, t_hi=3300)
    orders = [
        order(
            rng.randint(0, 7199),
            *geo.proj(-8.61 + rng.uniform(-0.01, 0.01), 41.15 + rng.uniform(-0.01, 0.01)),
        )
        for _ in range(300)
    ] + burst
    hot, surges = places.hot_and_surges(orders, UNIT)
    assert surges
    best = max(surges, key=lambda s: s["n"])
    assert best["t0"] <= 3000 and best["t1"] >= 3300 and best["t1"] - best["t0"] == 750
    assert math.hypot(best["x"] * UNIT - sx, best["y"] * UNIT - sy) < 400
    assert best["n"] >= 40 and best["r"] == 140 and best["name"] == "Trindade"


def test_surge_constraints():
    rng = random.Random(4)
    orders = background(rng, 800) + around(rng, 7000, 11000, 150.0, 30, 1000, 1400)
    _, surges = places.hot_and_surges(orders, UNIT)
    assert len(surges) <= 6
    for s in surges:
        assert s["t0"] >= 150 and s["t1"] <= 7200 and s["t0"] % 150 == 0 and s["n"] >= 4
        assert set(s) == {"x", "y", "r", "t0", "t1", "n", "name"}
    for i, a in enumerate(surges):
        for b in surges[i + 1 :]:
            assert a["t1"] <= b["t0"] or b["t1"] <= a["t0"]
    assert surges == sorted(surges, key=lambda s: s["t0"])


def test_relaxed_thresholds_kick_in():
    # a mild burst (4 pickups in a window, under n >= 5) is found only by the relaxed pass
    rng = random.Random(5)
    base = [
        order(t, 8000 + rng.uniform(-300, 300), 12000 + rng.uniform(-300, 300))
        for t in range(200, 7200, 800)
    ]  # 9 pickups, one per 800 s
    extra = [order(4010 + i * 30, 8000, 12000) for i in range(3)]
    xy = places.pickups_m(base + extra, UNIT)
    assert places.pick_surges(xy, places.SURGE_MIN_RATE, places.SURGE_MIN_N, UNIT) == []
    relaxed = places.surges(xy, UNIT)
    assert relaxed and relaxed[0]["t0"] <= 4010 and relaxed[0]["t1"] > 4130


def test_deterministic():
    rng = random.Random(6)
    orders = background(rng, 300) + around(rng, 8000, 12000, 100.0, 30, 2000, 2300)
    assert places.hot_and_surges(orders, UNIT) == places.hot_and_surges(orders, UNIT)
