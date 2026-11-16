import csv
import json
import math

import numpy as np
import pytest

from pipeline import geo, roads

GRID = roads.Grid(width=120, height=120)  # 960 m x 960 m of 8 m pixels


def line(a, b, step=100.0):
    """Straight metre polyline from a to b with a point about every ``step`` metres."""
    n = max(2, math.ceil(math.dist(a, b) / step) + 1)
    return np.linspace(a, b, n)


def thrice(trips):
    """Repeat every trip three times (so each pixel reaches ``MIN_TRIPS``)."""
    return [t for t in trips for _ in range(3)]


def write_week(path, polylines):
    """Write a minimal week CSV with the given POLYLINE cells."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["TRIP_ID", "POLYLINE"])
        for i, cell in enumerate(polylines):
            w.writerow([i, cell])


def lonlat_line(n=12, step_m=100.0):
    """A west-to-east lon/lat trip inside the map, about 1.1 km long."""
    dlon = step_m / geo.M_LON
    return [[-8.61 + i * dlon, 41.15] for i in range(n)]


# trip loading


def test_parse_polyline():
    assert roads.parse_polyline("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]]
    assert roads.parse_polyline("not json") is None
    assert roads.parse_polyline('{"a": 1}') is None


def test_load_trips_filters_and_projects(tmp_path):
    good = lonlat_line()
    week = tmp_path / "week.csv"
    write_week(week, [json.dumps(good), "[]", "oops", json.dumps(good[:3])])
    trips = roads.load_trips(week)
    assert len(trips) == 1
    assert trips[0].shape == (len(good), 2)
    assert tuple(trips[0][0]) == pytest.approx(geo.proj(*good[0]))


# rasterizing


def test_trip_pixels_unique_and_connected():
    trip = line((10, 100), (700, 100))
    pix = roads.trip_pixels(trip, GRID)
    assert len(pix) == len(set(pix.tolist()))
    assert set(pix // GRID.width) == {12}  # y = 100 m is pixel row 12
    cols = np.sort(pix % GRID.width)
    assert cols[0] == 1 and cols[-1] == 87
    assert np.all(np.diff(cols) == 1)


def test_trip_pixels_stationary_trip_is_one_pixel():
    trip = np.array([[50.0, 50.0], [50.0, 50.0], [50.0, 50.0]])
    assert roads.trip_pixels(trip, GRID).tolist() == [6 * GRID.width + 6]


def test_pixel_counts_once_per_trip():
    slow = np.array([[100.0, 100.0], [101.0, 100.0], [102.0, 100.0], [101.0, 100.0]])
    counts = roads.count_trips([slow], GRID)
    assert counts.max() == 1
    assert counts[12, 12] == 1


def test_road_mask_needs_three_trips():
    trip = line((10, 100), (700, 100))
    two = roads.road_mask(roads.count_trips([trip, trip], GRID))
    three = roads.road_mask(roads.count_trips([trip, trip, trip], GRID))
    assert not two.any()
    assert three.sum() == 87
