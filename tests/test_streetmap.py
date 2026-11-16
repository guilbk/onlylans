"""Tests for pipeline.streetmap."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from pipeline import streetmap


def test_edge_points_includes_end_nodes() -> None:
    nodes = [0, 0, 10, 10, 20, 0]
    assert streetmap.edge_points(nodes, [0, 2, [5, 5]]) == [0, 0, 5, 5, 20, 0]


def test_edge_score_reads_density() -> None:
    dens = np.zeros((10, 10), dtype=np.uint8)
    dens[5, 5] = 200
    assert streetmap.edge_score([50, 50, 51, 51], dens, 10.0) == 200.0
    assert streetmap.edge_score([], dens, 10.0) == 0.0


def test_classify_ranks_by_score() -> None:
    scores = [float(i) for i in range(100)]
    cls = streetmap.classify(scores)
    assert cls[99] == 0 and cls[90] == 0 and cls[89] == 1
    assert cls[0] == 2
    assert cls.count(0) == 10 and cls.count(1) == 30 and cls.count(2) == 60


def test_build_without_density_uses_length() -> None:
    roads = {
        "unit_m": 2.5,
        "nodes": [0, 0, 100, 0, 200, 0],
        "edges": [[0, 1, []], [1, 2, [150, 5, 160, 9]]],
    }
    out = streetmap.build(roads, None, 6000.0)
    assert out["unit_m"] == 2.5
    assert sum(len(c) for c in out["classes"]) == 2
    assert out["classes"][1][0] == [100, 0, 150, 5, 160, 9, 200, 0]


def test_main_writes_json(tmp_path: Path) -> None:
    roads = tmp_path / "roads.json"
    roads.write_text(
        json.dumps({"unit_m": 2.5, "nodes": [0, 0, 8, 8], "edges": [[0, 1, []]]}), encoding="utf-8"
    )
    out = tmp_path / "sm.json"
    assert (
        streetmap.main(
            ["--roads", str(roads), "--streets", str(tmp_path / "no.png"), "--out", str(out)]
        )
        == 0
    )
    assert len(json.loads(out.read_text(encoding="utf-8"))["classes"]) == 3
