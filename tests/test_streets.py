import csv
import io
import json

import numpy as np
import pytest
from PIL import Image

from pipeline import geo, streets

GRID = streets.Grid(width=100, height=100, cell_m=10.0)  # 1 km x 1 km of 10 m pixels


def trip(*pts):
    """A metre polyline from (x, y) tuples."""
    return np.array(pts, dtype=np.float64)


def lonlat_line(n=12, step_m=100.0):
    """A west-to-east lon/lat trip inside the map, about 1.1 km long."""
    dlon = step_m / geo.M_LON
    return [[-8.61 + i * dlon, 41.15] for i in range(n)]


def write_week(path, polylines):
    """Write a minimal week CSV with the given POLYLINE cells."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["TRIP_ID", "POLYLINE"])
        for i, cell in enumerate(polylines):
            w.writerow([i, cell])


def decode(png):
    """Decode PNG bytes into an RGBA array."""
    return np.array(Image.open(io.BytesIO(png)).convert("RGBA"))


# grid


def test_map_grid_covers_map():
    g = streets.map_grid(5.0)
    assert (g.width, g.height) == (3000, 3800)
    g = streets.map_grid(7.0)
    assert g.width * 7 >= geo.MAP_W_M and g.height * 7 >= geo.MAP_H_M
    assert (g.width - 1) * 7 < geo.MAP_W_M and (g.height - 1) * 7 < geo.MAP_H_M


# sampling and rasterizing


def test_sample_polyline_spacing_and_ends():
    s = streets.sample_polyline(trip((0, 0), (100, 0)), 10.0)
    assert np.allclose(s[0], (0, 0)) and np.allclose(s[-1], (100, 0))
    assert np.max(np.hypot(*np.diff(s, axis=0).T)) <= 10.0 + 1e-9


def test_sample_polyline_keeps_vertices():
    s = streets.sample_polyline(trip((0, 0), (33, 0), (33, 40)), 10.0)
    assert any(np.allclose(p, (33, 0)) for p in s)
    assert np.allclose(s[-1], (33, 40))


def test_sample_polyline_single_point():
    assert streets.sample_polyline(trip((5, 5)), 10.0).shape == (1, 2)


def test_straight_line_lights_the_right_pixels():
    # horizontal line at y = 255 m (row 25) from x = 100 m to x = 400 m (cols 10..40)
    idx = streets.trip_pixels(trip((100, 255), (400, 255)), GRID)
    rows, cols = np.divmod(idx, GRID.width)
    assert set(rows) == {25}
    assert set(cols) == set(range(10, 41))


def test_diagonal_line_is_connected():
    idx = streets.trip_pixels(trip((5, 5), (505, 505)), GRID)
    rows, cols = np.divmod(idx, GRID.width)
    order = np.argsort(cols, kind="stable")
    steps = np.abs(np.diff(rows[order])) + np.abs(np.diff(cols[order]))
    assert len(idx) >= 50 and steps.max() <= 2
    assert idx.min() == 0 and idx.max() == 50 * GRID.width + 50


def test_trip_pixels_unique_and_sorted():
    # a trip that doubles back over itself still lists each pixel once
    idx = streets.trip_pixels(trip((100, 255), (400, 255), (100, 255)), GRID)
    assert len(idx) == len(set(idx.tolist()))
    assert idx.tolist() == sorted(idx.tolist())


def test_trip_pixels_drops_outside_samples():
    idx = streets.trip_pixels(trip((-500, 55), (500, 55)), GRID)
    rows, cols = np.divmod(idx, GRID.width)
    assert set(rows) == {5} and cols.min() == 0 and cols.max() == 50


def test_accumulate_counts_a_trip_once_per_pixel():
    t = trip((100, 255), (400, 255), (100, 255))  # out and back
    counts = streets.accumulate([t], GRID)
    assert counts.max() == 1.0
    assert int(counts.sum()) == 31


def test_accumulate_sums_different_trips():
    a = trip((100, 255), (400, 255))
    b = trip((300, 255), (600, 255))
    counts = streets.accumulate([a, b, a], GRID)
    assert counts[25, 10] == 2.0  # only a (twice)
    assert counts[25, 35] == 3.0  # a twice and b once
    assert counts[25, 55] == 1.0  # only b
    assert counts[24, 35] == 0.0 and counts.shape == (100, 100)


# tone map


def test_clip_level_uses_lit_pixels_only():
    counts = np.zeros((10, 10), dtype=np.float32)
    assert streets.clip_level(counts) == 1.0
    counts[0, :5] = [1, 2, 3, 4, 100]
    assert streets.clip_level(counts, 100.0) == 100.0
    assert streets.clip_level(counts, 0.0) == 1.0


def test_tone_map_monotonic_and_bounded():
    counts = np.arange(0, 500, dtype=np.float32).reshape(1, -1)
    tone = streets.tone_map(counts, 50.0)[0]
    assert tone[0] == 0.0
    assert np.all(np.diff(tone) >= 0)
    assert tone.min() >= 0.0 and tone.max() <= 1.0
    assert tone[50] == pytest.approx(1.0) and tone[400] == pytest.approx(1.0)


def test_tone_map_is_concave():
    tone = streets.tone_map(np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32), 10.0)[0]
    assert np.all(np.diff(np.diff(tone)) < 0)


# colour and PNG


def test_to_alpha_range_and_zero():
    tone = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
    a = streets.to_alpha(tone)
    assert a.dtype == np.uint8 and a[0, 0] == 0
    assert a[0, 2] == round(streets.STREET_ALPHA * 255)
    assert a[0, 0] <= a[0, 1] <= a[0, 2]


def test_encode_png_roundtrip_colour_and_alpha():
    alpha = np.zeros((6, 8), dtype=np.uint8)
    alpha[2, 3], alpha[4, 5] = 77, 12
    rgba = decode(streets.encode_png(alpha))
    assert rgba.shape == (6, 8, 4)
    assert np.array_equal(rgba[..., 3], alpha)
    assert tuple(rgba[2, 3, :3]) == streets.STREET_RGB


def test_encode_png_is_deterministic():
    alpha = (np.arange(400) % 70).astype(np.uint8).reshape(20, 20)
    assert streets.encode_png(alpha) == streets.encode_png(alpha.copy())


# render and size budget


def test_render_png_size_matches_resolution_and_is_deterministic():
    trips = [streets.project_trip(lonlat_line())]
    a = streets.render_png(trips, 50.0)
    assert a == streets.render_png(trips, 50.0)
    img = Image.open(io.BytesIO(a))
    assert img.size == (300, 380)
    rgba = decode(a)
    assert rgba[..., 3].max() > 0 and (rgba[..., 3] == 0).sum() > 0.9 * 300 * 380


def test_fits_budget():
    assert streets.fits_budget(1000, 1000)
    assert not streets.fits_budget(1001, 1000)
    assert streets.fits_budget(streets.MAX_BYTES)
    assert not streets.fits_budget(streets.MAX_BYTES + 1)


def test_next_m_per_px():
    assert streets.next_m_per_px(5.0, 8.0) == 6.0
    assert streets.next_m_per_px(7.5, 8.0) is None
    assert streets.next_m_per_px(8.0, 8.0) is None


def test_build_within_budget_keeps_resolution_when_it_fits():
    trips = [streets.project_trip(lonlat_line())]
    data, used = streets.build_within_budget(trips, 20.0, budget=10**9, limit=30.0)
    assert used == 20.0 and streets.fits_budget(len(data), 10**9)


def test_build_within_budget_coarsens_until_it_fits():
    trips = [streets.project_trip(lonlat_line())]
    size20 = len(streets.render_png(trips, 20.0))
    data, used = streets.build_within_budget(trips, 20.0, budget=size20 - 1, limit=40.0)
    assert used > 20.0 and len(data) < size20


def test_build_within_budget_stops_at_limit():
    trips = [streets.project_trip(lonlat_line())]
    data, used = streets.build_within_budget(trips, 20.0, budget=1, limit=22.0)
    assert used == 22.0 and not streets.fits_budget(len(data), 1)


# loading and CLI


def test_parse_polyline():
    assert streets.parse_polyline("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]]
    assert streets.parse_polyline("not json") is None
    assert streets.parse_polyline('{"a": 1}') is None


def test_project_trip_matches_geo_proj():
    out = streets.project_trip([[-8.6112, 41.1481], [-8.60, 41.15]])
    assert out.shape == (2, 2)
    assert tuple(out[0]) == pytest.approx(geo.proj(-8.6112, 41.1481))


def test_load_trips_filters_with_trip_ok(tmp_path):
    week = tmp_path / "week.csv"
    write_week(
        week,
        [json.dumps(lonlat_line()), json.dumps(lonlat_line(n=2)), "garbage", "[]"],
    )
    trips = streets.load_trips(week)
    assert len(trips) == 1 and trips[0].shape == (12, 2)


def test_main_writes_png_and_is_deterministic(tmp_path, capsys):
    week = tmp_path / "week.csv"
    write_week(week, [json.dumps(lonlat_line())] * 3)
    out1, out2 = tmp_path / "a.png", tmp_path / "sub" / "b.png"
    assert streets.main(["--week", str(week), "--out", str(out1), "--m-per-px", "50"]) == 0
    assert streets.main(["--week", str(week), "--out", str(out2), "--m-per-px", "50"]) == 0
    assert out1.read_bytes() == out2.read_bytes()
    assert Image.open(out1).size == (300, 380)
    assert "3 trips" in capsys.readouterr().out


def test_main_missing_week_and_bad_resolution(tmp_path, capsys):
    out = tmp_path / "x.png"
    assert streets.main(["--week", str(tmp_path / "nope.csv"), "--out", str(out)]) == 1
    week = tmp_path / "week.csv"
    write_week(week, [json.dumps(lonlat_line())])
    assert streets.main(["--week", str(week), "--out", str(out), "--m-per-px", "0"]) == 1
    assert not out.exists()
    assert "week file not found" in capsys.readouterr().err
