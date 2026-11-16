import math
import random

import pytest

from pipeline import geo


def line(n=10, step_m=100.0, lon=-8.61, lat=41.15):
    """Straight west-to-east polyline of n points, step_m apart."""
    dlon = step_m / geo.M_LON
    return [[lon + i * dlon, lat] for i in range(n)]


def test_proj_unproj_roundtrip_and_corners():
    assert geo.proj(geo.LON0, geo.LAT0) == (0.0, 0.0)
    x, y = geo.proj(-8.6112, 41.1481)
    assert (x, y) == pytest.approx(geo.HOME, abs=2.0)
    lon, lat = geo.unproj(*geo.proj(-8.6, 41.2))
    assert (lon, lat) == pytest.approx((-8.6, 41.2))
    x, y = geo.proj(-8.5408, 41.0891)
    assert (x, y) == pytest.approx((geo.MAP_W_M, geo.MAP_H_M), abs=15.0)


def test_scale_constants_consistent():
    assert geo.M_LON == pytest.approx(geo.M_LAT * math.cos(math.radians(geo.LAT_REF)))  # noqa: SIM300
    assert geo.M_LAT == pytest.approx(6371000 * math.pi / 180)  # noqa: SIM300


def test_in_map():
    assert geo.in_map(-8.61, 41.15)
    assert not geo.in_map(-8.80, 41.15)
    assert not geo.in_map(-8.61, 41.30)
    assert not geo.in_map(-8.61, 41.05)


def test_haversine_known_pair():
    # one degree of latitude on a sphere of R = 6371 km
    assert geo.haversine(-8.6, 41.0, -8.6, 42.0) == pytest.approx(111.195, abs=0.01)
    # Aliados to Aeroporto, about 11.1 km
    d = geo.haversine(-8.6112, 41.1481, -8.6814, 41.2481)
    assert 12.0 < d < 13.5
    assert geo.haversine(-8.6, 41.1, -8.6, 41.1) == 0.0


def test_path_km():
    pts = line(11, 100.0)
    assert geo.path_km(pts) == pytest.approx(1.0, rel=0.01)
    assert geo.path_km([[-8.6, 41.1]]) == 0.0


def test_night_hour():
    assert [h for h in range(24) if geo.night_hour(h)] == [0, 1, 2, 3, 4, 5, 22, 23]


def test_fare_rounding_and_night():
    assert geo.fare(0.0, False) == 3.25
    assert geo.fare(10.0, False) == 8.25
    assert geo.fare(10.0, True) == 9.9
    # half-up: 3.25 + 0.5 * 0.01 = 3.255 -> 3.26 (binary float must not round it down)
    assert geo.fare(0.01, False) == 3.26
    assert geo.fare(0.03, False) == 3.27


def test_trip_ok_accepts_good_trip():
    assert geo.trip_ok(line(15, 100.0))


def test_trip_ok_point_count():
    assert not geo.trip_ok(line(3, 500.0))
    assert not geo.trip_ok(line(241, 100.0))
    assert geo.trip_ok(line(240, 20.0))  # 4.8 km, 240 points is allowed
    assert geo.trip_ok(line(4, 400.0))  # 1.2 km, minimum count


def test_trip_ok_bad_points():
    pts = line(15, 100.0)
    assert not geo.trip_ok(pts[:5] + [[-8.61]] + pts[6:])
    assert not geo.trip_ok(pts[:5] + [[-8.61, 41.15, 1.0]] + pts[6:])
    assert not geo.trip_ok(pts[:5] + [[-9.5, 41.15]] + pts[6:])
    assert not geo.trip_ok(pts[:5] + [[float("nan"), 41.15]] + pts[6:])
    assert not geo.trip_ok(pts[:5] + [["a", "b"]] + pts[6:])


def test_trip_ok_path_length():
    assert not geo.trip_ok(line(5, 150.0))  # 0.6 km
    assert geo.trip_ok(line(10, 100.0))  # 0.9 km


def back_and_forth(n, step_m=600.0):
    """East-west oscillation with a slow drift north: path is about (n - 1) * step_m."""
    dlon = step_m / geo.M_LON
    return [[-8.61 + (i % 2) * dlon, 41.15 + i * 10.0 / geo.M_LAT] for i in range(n)]


def test_trip_ok_long_path_limit():
    assert geo.trip_ok(back_and_forth(45))  # ~26.4 km
    assert not geo.trip_ok(back_and_forth(55))  # ~32.4 km


def test_trip_ok_step_limit():
    pts = line(15, 100.0)
    jump = pts[:7] + [[p[0] + 600.0 / geo.M_LON, p[1]] for p in pts[7:]]
    assert not geo.trip_ok(jump)
    ok = pts[:7] + [[p[0] + 500.0 / geo.M_LON, p[1]] for p in pts[7:]]
    assert geo.trip_ok(ok)


def test_trip_ok_loop_rejected():
    ring = [
        [-8.61 + 0.004 * math.cos(a), 41.15 + 0.004 * math.sin(a)]
        for a in [2 * math.pi * i / 20 for i in range(20)]
    ] + [[-8.606, 41.15]]
    assert geo.path_km(ring) > 0.8
    assert not geo.trip_ok(ring)


def test_rdp_straight_line_collapses():
    pts = [(float(i), 0.0) for i in range(20)]
    assert geo.rdp(pts, 1.0) == [(0.0, 0.0), (19.0, 0.0)]


def test_rdp_keeps_corner():
    pts = [(float(i), 0.0) for i in range(10)] + [(9.0, float(i)) for i in range(1, 10)]
    out = geo.rdp(pts, 1.0)
    assert out == [(0.0, 0.0), (9.0, 0.0), (9.0, 9.0)]


def test_rdp_tolerance_and_short_input():
    pts = [(0.0, 0.0), (5.0, 0.5), (10.0, 0.0)]
    assert geo.rdp(pts, 1.0) == [(0.0, 0.0), (10.0, 0.0)]
    assert geo.rdp(pts, 0.1) == pts
    assert geo.rdp([(1.0, 1.0)], 1.0) == [(1.0, 1.0)]
    assert geo.rdp([(1.0, 1.0), (2.0, 2.0)], 1.0) == [(1.0, 1.0), (2.0, 2.0)]


def test_is_point_accepts_only_finite_pairs():
    assert geo.is_point([-8.6, 41.1])
    assert geo.is_point((1, 2))
    assert not geo.is_point([1.0])
    assert not geo.is_point([1.0, 2.0, 3.0])
    assert not geo.is_point("ab")
    assert not geo.is_point([True, 1.0])
    assert not geo.is_point([math.nan, 1.0])
    assert not geo.is_point([math.inf, 1.0])
    assert not geo.is_point(None)


def test_seg_dist_projects_onto_the_segment_and_clamps_at_the_ends():
    a, b = (0.0, 0.0), (10.0, 0.0)
    assert geo._seg_dist((5.0, 3.0), a, b) == pytest.approx(3.0)
    assert geo._seg_dist((-3.0, 4.0), a, b) == pytest.approx(5.0)
    assert geo._seg_dist((13.0, 4.0), a, b) == pytest.approx(5.0)
    assert geo._seg_dist((3.0, 4.0), a, a) == pytest.approx(5.0)  # zero-length segment


LON0, LAT0 = -8.61, 41.15
DLAT = 0.0027  # about 300 m, below the 625 m step limit


def north_line(n=8):
    """A straight north-going polyline of n points, about 300 m apart."""
    return [[LON0, LAT0 + i * DLAT] for i in range(n)]


def zigzag(n, leg=30):
    """n points going north and south in legs of ``leg`` steps (long path, short straight)."""
    out = []
    for i in range(n):
        k = i % (2 * leg)
        out.append([LON0, LAT0 + (k if k <= leg else 2 * leg - k) * DLAT])
    return out


@pytest.mark.parametrize(
    ("pts", "rule"),
    [
        (north_line(), None),
        ("not a list", geo.RULE_BAD_JSON),
        (None, geo.RULE_BAD_JSON),
        ([], geo.RULE_POINTS),
        (north_line(3), geo.RULE_POINTS),
        (north_line(241), geo.RULE_POINTS),
        ([*north_line(4)[:3], [LON0, "x"]], geo.RULE_BOUNDS),
        ([*north_line(4)[:3], [-9.5, LAT0]], geo.RULE_BOUNDS),
        ([*north_line(4)[:3], [LON0]], geo.RULE_BOUNDS),
        ([*north_line(4)[:3], [True, LAT0]], geo.RULE_BOUNDS),
        (
            [[LON0, LAT0], [LON0, LAT0 + 0.0027], [LON0, LAT0 + 0.0135], [LON0, LAT0 + 0.0162]],
            geo.RULE_STEP,
        ),
        ([[LON0, LAT0 + i * 0.0001] for i in range(6)], geo.RULE_LENGTH),
        (zigzag(120), geo.RULE_LENGTH),
        (
            [[LON0, LAT0], [LON0, LAT0 + DLAT], [LON0 + 0.003, LAT0 + DLAT], [LON0 + 0.003, LAT0]],
            geo.RULE_STRAIGHT,
        ),
    ],
)
def test_reject_reason_cases(pts, rule):
    """Each synthetic polyline is rejected by exactly the expected first rule."""
    assert geo.reject_reason(pts) == rule


def test_trip_ok_is_no_reject_reason_on_random_polylines():
    rng = random.Random(7)
    for _ in range(400):
        n = rng.choice([2, 4, 6, 20, 60, 250])
        step = rng.choice([0.0002, 0.001, 0.003, 0.007])
        lon, lat = LON0 + rng.uniform(-0.02, 0.02), LAT0 + rng.uniform(-0.02, 0.02)
        pts = []
        for _i in range(n):
            lon += rng.uniform(-step, step)
            lat += rng.uniform(-step, step)
            pts.append([lon, lat])
        assert geo.trip_ok(pts) == (geo.reject_reason(pts) is None)


def test_decode_path_keeps_map_units_by_default_and_scales_to_metres():
    order = [10, 100, 200, 103, 202, [1, 0, 2, 2], 45, 1.0, 4.5, 0, 0, 0]
    assert geo.decode_path(order) == [(100, 200), (101, 200), (103, 202)]
    assert geo.decode_path(order, 2.5) == [(250.0, 500.0), (252.5, 500.0), (257.5, 505.0)]
    assert geo.decode_path([0, 5, 6, 5, 6, [], 0, 1, 1, 0, 0, 0]) == [(5, 6)]
    assert geo.decode_path([0, 5, 6, 5, 6, [1], 0, 1, 1, 0, 0, 0]) == [(5, 6)]  # odd tail ignored
