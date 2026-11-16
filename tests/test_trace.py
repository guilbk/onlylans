"""Tests for pipeline/trace.py: the grid, projection and sampling shared by streets and roads."""

import csv
import json

import numpy as np
import pytest

from pipeline import geo, trace

GRID = trace.Grid(width=100, height=100, cell_m=10.0)  # 1 km x 1 km of 10 m pixels


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


def test_map_grid_covers_the_map():
    g = trace.map_grid(5.0)
    assert (g.width, g.height, g.cell_m) == (3000, 3800, 5.0)
    g = trace.map_grid(7.0)
    assert g.width * 7 >= geo.MAP_W_M and g.height * 7 >= geo.MAP_H_M
    assert (g.width - 1) * 7 < geo.MAP_W_M and (g.height - 1) * 7 < geo.MAP_H_M


def test_parse_polyline():
    assert trace.parse_polyline("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]]
    assert trace.parse_polyline("not json") is None
    assert trace.parse_polyline('{"a": 1}') is None


def test_project_trip_gives_metres():
    pts = lonlat_line(3)
    arr = trace.project_trip(pts)
    assert arr.shape == (3, 2) and arr.dtype == np.float64
    assert tuple(arr[0]) == pytest.approx(geo.proj(*pts[0]))
    assert arr[1, 0] - arr[0, 0] == pytest.approx(100.0, abs=0.5)  # 100 m east per step


def test_load_trips_filters_with_trip_ok(tmp_path):
    good = lonlat_line()
    week = tmp_path / "week.csv"
    write_week(week, [json.dumps(good), json.dumps(lonlat_line(n=2)), "oops", "[]"])
    trips = trace.load_trips(week)
    assert len(trips) == 1 and trips[0].shape == (len(good), 2)


def test_sample_polyline_spacing_and_ends():
    s = trace.sample_polyline(trip((0, 0), (100, 0)), 10.0)
    assert np.allclose(s[0], (0, 0)) and np.allclose(s[-1], (100, 0))
    assert np.max(np.hypot(*np.diff(s, axis=0).T)) <= 10.0 + 1e-9


def test_sample_polyline_keeps_vertices():
    s = trace.sample_polyline(trip((0, 0), (33, 0), (33, 40)), 10.0)
    assert any(np.allclose(p, (33, 0)) for p in s)
    assert np.allclose(s[-1], (33, 40))


def test_sample_polyline_single_point():
    assert trace.sample_polyline(trip((5, 5)), 10.0).shape == (1, 2)


def test_straight_line_lights_the_right_pixels():
    # horizontal line at y = 255 m (row 25) from x = 100 m to x = 400 m (cols 10..40)
    idx = trace.trip_pixels(trip((100, 255), (400, 255)), GRID, clip=False)
    rows, cols = np.divmod(idx, GRID.width)
    assert set(rows) == {25}
    assert set(cols) == set(range(10, 41))


def test_diagonal_line_is_connected():
    idx = trace.trip_pixels(trip((5, 5), (505, 505)), GRID, clip=False)
    rows, cols = np.divmod(idx, GRID.width)
    order = np.argsort(cols, kind="stable")
    steps = np.abs(np.diff(rows[order])) + np.abs(np.diff(cols[order]))
    assert len(idx) >= 50 and steps.max() <= 2
    assert idx.min() == 0 and idx.max() == 50 * GRID.width + 50


@pytest.mark.parametrize("clip", [False, True])
def test_trip_pixels_unique_and_sorted(clip):
    # a trip that doubles back over itself still lists each pixel once
    idx = trace.trip_pixels(trip((100, 255), (400, 255), (100, 255)), GRID, clip=clip)
    assert len(idx) == len(set(idx.tolist()))
    assert idx.tolist() == sorted(idx.tolist())


def test_stationary_trip_is_one_pixel():
    idx = trace.trip_pixels(trip((55, 55), (55, 55), (55, 55)), GRID, clip=True)
    assert idx.tolist() == [5 * GRID.width + 5]


def test_drop_removes_samples_off_the_map():
    idx = trace.trip_pixels(trip((-500, 55), (500, 55)), GRID, clip=False)
    rows, cols = np.divmod(idx, GRID.width)
    assert set(rows) == {5} and cols.min() == 0 and cols.max() == 50


def test_clip_moves_samples_to_the_edge_pixel():
    idx = trace.trip_pixels(trip((-500, 55), (500, 55)), GRID, clip=True)
    rows, cols = np.divmod(idx, GRID.width)
    assert set(rows) == {5} and set(cols) == set(range(0, 51))
    off = trace.trip_pixels(trip((-500, -500), (-400, -400)), GRID, clip=True)
    assert off.tolist() == [0]
    assert trace.trip_pixels(trip((-500, -500), (-400, -400)), GRID, clip=False).size == 0
