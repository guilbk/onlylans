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


# graph building


def skeleton_graph(trips, grid=GRID):
    """Run the raster steps up to the unpruned graph."""
    mask = roads.close_mask(roads.road_mask(roads.count_trips(trips, grid)))
    return roads.skeleton_to_graph(roads.thin_mask(mask), grid.cell_m)


def edge_lengths(graph):
    """Sorted edge lengths in metres."""
    return sorted(d["len"] for *_, d in graph.edges(data=True))


def plus_trips():
    """Five trips forming a plus with 350 m arms around (480, 480), three copies each."""
    c = 480.0
    arms = [
        line((c - 350, c), (c, c)),
        line((c, c), (c + 350, c)),
        line((c, c - 350), (c, c)),
        line((c, c), (c, c + 350)),
        line((c - 350, c), (c + 350, c)),
    ]
    return thrice(arms)


def test_plus_has_five_nodes_and_four_edges():
    graph = skeleton_graph(plus_trips())
    assert graph.number_of_nodes() == 5
    assert graph.number_of_edges() == 4
    for length in edge_lengths(graph):
        assert length == pytest.approx(350.0, abs=GRID.cell_m)
    degrees = sorted(d for _, d in graph.degree)
    assert degrees == [1, 1, 1, 1, 4]


def test_edge_polyline_runs_from_node_a_to_node_b():
    graph = skeleton_graph(plus_trips())
    for *_, data in graph.edges(data=True):
        pts = roads.oriented(data, data["a"])
        assert pts[0] == graph.nodes[data["a"]]["pos"]
        assert pts[-1] == graph.nodes[data["b"]]["pos"]
        assert roads.oriented(data, data["b"])[0] == pts[-1]
        assert roads.polyline_length(pts) == pytest.approx(data["len"])


def test_ring_without_junction_gets_a_node():
    c, r = 480.0, 200.0
    t = np.linspace(0, 2 * np.pi, 80)
    ring = np.column_stack([c + r * np.cos(t), c + r * np.sin(t)])
    graph = skeleton_graph(thrice([ring]))
    assert graph.number_of_nodes() == 1
    assert graph.number_of_edges() == 1
    (length,) = edge_lengths(graph)
    assert length == pytest.approx(2 * np.pi * r, rel=0.1)


# spur pruning and components


def tee_trips(spur_m, x0=80.0, x1=880.0, y=480.0):
    """A horizontal road with a vertical spur of ``spur_m`` metres up from its middle."""
    mid = (x0 + x1) / 2
    road = line((x0, y), (x1, y))
    spur = line((mid, y), (mid, y - spur_m), step=10.0)
    return thrice([road, spur])


def pruned(trips):
    """Unpruned graph, pruned in place, and returned."""
    graph = skeleton_graph(trips)
    roads.prune_spurs(graph)
    return graph


def test_short_spur_is_pruned():
    graph = pruned(tee_trips(20.0))
    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1
    (length,) = edge_lengths(graph)
    assert length == pytest.approx(800.0, abs=2 * GRID.cell_m)


def test_long_spur_is_kept():
    graph = pruned(tee_trips(80.0))
    assert graph.number_of_nodes() == 4
    assert graph.number_of_edges() == 3
    lengths = edge_lengths(graph)
    assert lengths[0] == pytest.approx(80.0, abs=2 * GRID.cell_m)
    assert lengths[1:] == pytest.approx([400.0, 400.0], abs=2 * GRID.cell_m)


def test_pruning_repeats_until_no_spur_is_left():
    # A 30 m spur on a 30 m spur's neighbour: removing the first leaves a new dead end.
    graph = pruned(tee_trips(30.0) + thrice([line((440, 440), (440, 470), step=10.0)]))
    assert graph.number_of_nodes() == 2
    assert all(d > 0 for _, d in graph.degree)


def test_contract_chains_merges_a_degree_two_node():
    graph = skeleton_graph(thrice([line((80, 480), (480, 480)), line((480, 480), (880, 480))]))
    roads.contract_chains(graph)
    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 1


def test_largest_component_keeps_the_longer_piece():
    big = line((80, 200), (880, 200))
    small = line((80, 700), (330, 700))
    graph = skeleton_graph(thrice([big, small]))
    assert graph.number_of_edges() == 2
    kept = roads.largest_component(graph)
    assert kept.number_of_edges() == 1
    (length,) = edge_lengths(kept)
    assert length == pytest.approx(800.0, abs=2 * GRID.cell_m)


def test_build_graph_drops_chords_and_small_pieces():
    road = line((80, 200), (880, 200))
    stray = line((80, 700), (330, 700))
    once = [line((100, 900), (800, 900))]  # a single trip: below MIN_TRIPS
    graph, kept = roads.build_graph([*thrice([road, stray]), *once], GRID)
    assert graph.number_of_edges() == 1
    assert kept == 101 + 32  # pixel columns 10..110 and 10..41


# JSON output


def curvy_graph():
    """Pruned graph of a plus whose horizontal road bends, for the encoder tests."""
    t = np.linspace(0, 1, 60)
    wave = np.column_stack([80 + 800 * t, 480 + 60 * np.sin(2 * np.pi * t)])
    cross = line((480, 100), (480, 860))
    graph, _ = roads.build_graph(thrice([wave, cross]), GRID)
    return graph


def test_encode_roads_follows_the_contract():
    doc = roads.encode_roads(curvy_graph(), 6.0)
    assert list(doc) == ["v", "unit_m", "nodes", "edges"]
    assert doc["v"] == 1
    assert doc["unit_m"] == 2.5
    xy = list(zip(doc["nodes"][0::2], doc["nodes"][1::2], strict=True))
    assert all(isinstance(v, int) for v in doc["nodes"])
    assert xy == sorted(xy, key=lambda p: (p[1], p[0]))
    keys = [(a, b) for a, b, _ in doc["edges"]]
    assert keys == sorted(keys)
    for a, b, flat in doc["edges"]:
        assert 0 <= a <= b < len(xy)
        assert len(flat) % 2 == 0
        assert all(isinstance(v, int) for v in flat)


def test_encoded_edges_are_connected_and_in_metres_units():
    doc = roads.encode_roads(curvy_graph(), 6.0)
    n = len(doc["nodes"]) // 2
    seen = {0}
    todo = [0]
    while todo:
        cur = todo.pop()
        for a, b, _ in doc["edges"]:
            for u, v in ((a, b), (b, a)):
                if u == cur and v not in seen:
                    seen.add(v)
                    todo.append(v)
    assert len(seen) == n
    assert roads.total_km(doc) == pytest.approx((800 + 760) / 1000, rel=0.1)


def test_larger_tolerance_gives_fewer_points():
    graph = curvy_graph()
    fine = roads.encode_roads(graph, 1.0)
    coarse = roads.encode_roads(graph, 20.0)
    count = lambda doc: sum(len(e[2]) for e in doc["edges"])  # noqa: E731
    assert count(coarse) < count(fine)


def test_json_round_trips_and_is_compact():
    doc = roads.encode_roads(curvy_graph(), 6.0)
    payload = roads.dumps_roads(doc)
    assert b" " not in payload and b"\n" not in payload
    assert json.loads(payload) == doc


def test_output_is_deterministic():
    trips = thrice([line((80, 480), (880, 480)), line((480, 100), (480, 860))])

    def run():
        graph, _ = roads.build_graph(trips, GRID)
        return roads.encode_within_budget(graph)[0]

    assert run() == run()


def test_budget_raises_tolerance_step_by_step():
    graph = curvy_graph()
    _, tol, _ = roads.encode_within_budget(graph)
    assert tol == roads.DP_START_M
    payload, tol, _ = roads.encode_within_budget(graph, max_bytes=1)
    assert tol == roads.DP_MAX_M
    assert len(payload) > 1
    sizes = {t: len(roads.dumps_roads(roads.encode_roads(graph, float(t)))) for t in range(6, 11)}
    limit = sizes[8]
    payload, tol, _ = roads.encode_within_budget(graph, max_bytes=limit)
    assert len(payload) <= limit
    assert tol <= 8.0
    assert tol == roads.DP_START_M or sizes[int(tol) - 1] > limit


# debug image and command line


def test_draw_debug_writes_a_png(tmp_path):
    doc = roads.encode_roads(curvy_graph(), 6.0)
    out = tmp_path / "sub" / "debug.png"
    roads.draw_debug(doc, GRID, out)
    from PIL import Image

    img = Image.open(out)
    assert img.size == (GRID.width, GRID.height)
    assert np.asarray(img).max() == 255


def test_main_writes_roads_json(tmp_path, monkeypatch, capsys):
    trips = thrice([line((80, 480), (880, 480)), line((480, 100), (480, 860))])
    monkeypatch.setattr(roads, "load_trips", lambda path: trips)
    monkeypatch.setattr(roads, "map_grid", lambda: GRID)
    out = tmp_path / "roads.json"
    debug = tmp_path / "debug.png"
    argv = ["--week", "unused.csv", "--out", str(out), "--debug", str(debug)]
    assert roads.main(argv) == 0
    doc = json.loads(out.read_bytes())
    assert len(doc["nodes"]) // 2 == 5
    assert len(doc["edges"]) == 4
    assert debug.exists()
    assert "nodes: 5" in capsys.readouterr().out


def test_main_reports_empty_map(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(roads, "load_trips", lambda path: [])
    monkeypatch.setattr(roads, "map_grid", lambda: GRID)
    argv = ["--out", str(tmp_path / "r.json"), "--debug", str(tmp_path / "d.png")]
    assert roads.main(argv) == 1
    assert "no road" in capsys.readouterr().out
