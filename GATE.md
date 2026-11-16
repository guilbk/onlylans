# K8 gate
- node tools/roads_test.mjs --roads data/work/roads.json: 273/273; real roads (2981 nodes, 4011 edges) 1000 routes, avg 0.047 ms, max 0.199 ms, 0 null
- synthetic 2000-node grid: 1000 routes, max 0.23 ms; A* equals Dijkstra on 120 node pairs
- build with game/roads.json (local, not committed) + smoke: SMOKE OK (k8); PG.roads.enabled true in the browser
- files changed: game/src/js/12_roads.js, tools/roads_test.mjs, GATE.md; no lockfiles/CI/hooks touched

# P3 gate (data report)
- `ruff check pipeline tests tools && python tools/check_py.py && pytest -q`: all passed, 122 tests (38 in tests/test_report.py)
- `python -m pipeline.report --week <real week.csv>`: wrote docs/STATS.md and docs/img/{hours,shifts,heatmap}.png in 3.4 s; a second run into another folder is byte-identical
- size: STATS.md 7.1 KB + PNGs 201 KB, about 208 KB (limit 600 KB)
- cross-check on real data: trips passing trip_ok inside the 28 shift windows = 10105 = sum of orders in game_data.json; valid trips 26802 = shifts.load_trips; rows 32833, rejected 6031
- not run: tools/lang_share.py (belongs to P2, not on this branch); no UI to look at (images viewed by eye: hours, shifts, heatmap)
- files changed: pipeline/report.py, tests/test_report.py, docs/STATS.md, docs/img/*.png, GATE.md (section appended); no lockfiles/CI/hooks touched
