# K8 gate
- node tools/roads_test.mjs --roads data/work/roads.json: 273/273; real roads (2981 nodes, 4011 edges) 1000 routes, avg 0.047 ms, max 0.199 ms, 0 null
- synthetic 2000-node grid: 1000 routes, max 0.23 ms; A* equals Dijkstra on 120 node pairs
- build with game/roads.json (local, not committed) + smoke: SMOKE OK (k8); PG.roads.enabled true in the browser
- files changed: game/src/js/12_roads.js, tools/roads_test.mjs, GATE.md; no lockfiles/CI/hooks touched
