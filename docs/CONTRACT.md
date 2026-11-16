# 7 ланосів — CONTRACT

Single source of truth for formats, units, rules, events and file ownership. **Frozen** after the
skeleton commit; changes go only through Kyrylo. Code and comments in English, UI text in Ukrainian
(gender-neutral for the player).

## §0 The game, and data vs game model

«7 ланосів»: a browser taxi game on the Porto taxi trips of UCI dataset 339 (CC BY 4.0), one week of
May 2014. The player is **Ріїн Гіслінг**, a taxi driver. One real 2-hour shift lasts 180 real seconds
(time ×40), with ×3 fast mode and pause. Orders on the map are the real trips of that shift.
The player races: all real drivers of the shift (live rank «#37 з 212»), the **ghost** (best real driver
of the shift, lilac car replaying its real route), and the **7 Lanos** (7 AI rivals, §13).

| Data (computed by our Python from the raw archive) | Game model (invented by us) |
|---|---|
| trips, drivers, routes, the ghost, the ranking, median / top 10 %, hotspots, demand waves (surges), the road graph | fare 3.25 + 0.50 €/km (×1.2 at night), time ×40, pin lead and radius, tips, combo, passenger kinds, the 7 AI rivals, medals |

The «Про дані» screen says which is which. Hero: our own drawn character; never a photo or likeness of
a real actor, no film stills, quotes or music, no car brand logos. The game works offline (one HTML file)
and on a phone in portrait. Campaign: 28 shifts, Mon 12.05 – Sun 18.05.2014, slots 08–10, 12–14, 17–19,
22–24 (Saturday's night is the real Sun 00–02); a shift opens with bronze on the one before (tier 1).

Tiers: 0 = playable on real data; 1 = 7 Lanos, preview + two-step tap, tips/combo, effects, sound, roads,
demand waves, campaign, hints; 2 = missions (only if all green).

## §1 Repo layout, ownership, commands, branches

```
docs/CONTRACT.md  docs/DATA.md  docs/DEMO.md  README.md  pyproject.toml  requirements.txt
.gitignore  .claude/settings.json
data/porto/porto_uci.zip.part00..05   data/work/ (ignored: porto_uci.zip, train.csv.zip, week.csv, ...)
pipeline/   tests/   tools/
game/src/index.html  game/src/css/NN_name.css  game/src/js/NN_name.js
game/fixture/mini.json  game/game_data.json  game/roads.json  game/streets.png  game/index.html (ignored)
dist/7-lanosiv.html (committed at the freeze)   test-screenshots/ (ignored)
```

| File | Piece / owner |
|---|---|
| docs/CONTRACT.md, .gitignore, pyproject.toml, requirements.txt, .claude/settings.json, pipeline/__init__.py, tests/.gitkeep | K0 skeleton (Kyrylo) |
| pipeline/raw.py, pipeline/week.py, tests/test_raw.py, tests/test_week.py | Y1 (Yaroslav) |
| pipeline/roads.py, tests/test_roads.py, game/roads.json | Y2 (Yaroslav) |
| pipeline/geo.py, pipeline/shifts.py, pipeline/places.py, tests/test_geo.py, tests/test_shifts.py, tests/test_places.py, game/game_data.json | K1 |
| game/src/index.html, game/src/css/00_base.css, game/src/js/00_core.js, game/src/js/99_boot.js, pipeline/build_game.py, tools/smoke.py, tools/check_py.py, tools/make_fixture.py, game/fixture/mini.json, tests/test_build_game.py, tests/test_check_py.py | K2 |
| game/src/js/10_data.js, game/src/js/20_engine.js, tools/engine_test.mjs | K3 (K6 owns 20_engine.js and engine_test.mjs from wave 2) |
| game/src/js/40_render.js, game/src/css/40_render.css, game/src/js/70_input.js | K4 |
| game/src/js/50_hud.js, game/src/css/50_hud.css, game/src/js/65_screens.js, game/src/css/65_screens.css | K5 (K9 owns 65_screens.* from wave 2) |
| game/src/js/25_ai.js | K6 |
| game/src/js/22_rules.js, game/src/js/45_fx.js, game/src/css/45_fx.css | K7 |
| game/src/js/12_roads.js, tools/roads_test.mjs | K8 |
| game/src/js/60_progress.js | K9 |
| game/src/js/28_radio.js, game/src/css/28_radio.css | K10 |
| game/src/js/42_orders.js, game/src/css/42_orders.css | K11 |
| game/src/js/30_audio.js, game/src/js/35_audio_wire.js, game/src/css/30_audio.css, tools/audio_demo.html | A1 (Artem) |
| pipeline/balance.py, tests/test_balance.py | A2 (Artem) |
| README.md (whole file after the skeleton), docs/DEMO.md | A3 (Artem) |
| docs/DATA.md; quality pass over pipeline/, tests/, tools/*.py (except balance) | Y3 (Yaroslav) |
| dist/7-lanosiv.html | hub, at the freeze |

Window rule: T+1:50–2:40 pipeline/, tests/ and tools/*.py belong to Y3 only.

Commands (from the repo root, venv active):

| Step | Command |
|---|---|
| raw → week | `python -m pipeline.week [--root .] [--out data/work/week.csv]` (~75 s) |
| week → shifts | `python -m pipeline.shifts --week data/work/week.csv [--out game/game_data.json]` |
| roads | `python -m pipeline.roads [--week data/work/week.csv] [--out game/roads.json]` |
| balance | `python -m pipeline.balance [--data ...] [--strategy value,nearest] [--lag 120,200,300] [--diff easy,normal,hard] [--shifts 0,5] [--json out.json]` |
| build | `python -m pipeline.build_game [...]` (§6) |
| fixture | `python tools/make_fixture.py [--out game/fixture/mini.json]` |

Branches: `main` = integration (only Kyrylo merges and pushes); `feat/<piece>` per piece
(`feat/y1-week`, `feat/y2-roads`, `feat/y3-quality`, `feat/a1-audio`, `feat/a2-balance`, `feat/a3-docs`,
`feat/k<N>-...`); `int/c1` = main + K3 + K4 + K5 for integrated gates. Merges are `--no-ff`. Commits as the
person, no AI attribution anywhere.
Gates: Python `ruff check pipeline tests tools && python tools/check_py.py && pytest -q`;
JS `node tools/engine_test.mjs` and `python tools/smoke.py game/index.html`; per merge
`git log main..<branch> -i -E --grep='co-authored|claude|generated with|anthropic'` prints nothing.

**Language share (hard rule).** Python is **≥ 50 %** of the repo's code by bytes, as GitHub's language bar
counts it (Python against JavaScript + CSS + HTML; JSON, Markdown and `data/` do not count; `dist/` is marked
`linguist-generated` in `.gitattributes`). Anything that can be computed offline lives in Python (`pipeline/`,
`tools/*.py`); browser JS only plays the game and stays lean (no dead code, no duplicated helpers).
`python tools/lang_share.py` prints the share and exits 1 below 50 %; it is part of the Python gate.

## §2 Raw data

Source: UCI Machine Learning Repository dataset 339, «Taxi Service Trajectory — Prediction Challenge,
ECML PKDD 2015», CC BY 4.0, https://archive.ics.uci.edu/dataset/339. Archive in git:
`data/porto/porto_uci.zip.part00` … `part05` (concatenate in sorted order → `porto_uci.zip`):
size **534065916** bytes, SHA-256 `a33e2a5e145607ae2bad0db5d21b7548c88b7e0f9db1ce15839f24c4c61f8c76`.
The outer zip holds `train.csv.zip` (member `train.csv`, ~1.9 GB, 1,710,670 data rows) and unused files
(test trajectories, solutions). `train.csv` is streamed, never written to disk.

| Column | Meaning |
|---|---|
| TRIP_ID | string id (unique) |
| CALL_TYPE | `A` dispatch-centre call, `B` taxi stand, `C` street hail |
| ORIGIN_CALL | int customer id for `A`, else `NA` |
| ORIGIN_STAND | int stand id for `B`, else `NA` |
| TAXI_ID | int driver id |
| TIMESTAMP | unix seconds, trip start |
| DAY_TYPE | `A` normal, `B` holiday, `C` day before holiday |
| MISSING_DATA | `True` if GPS stream has gaps, else `False` (we drop `True`) |
| POLYLINE | JSON `[[lon,lat],...]`, one point per 15 s; `[]` possible |

`data/work/week.csv`: same header and columns, rows with TIMESTAMP in the campaign window and
MISSING_DATA `False` (~32.8 thousand rows). Campaign window: Mon 12.05.2014 00:00 (inclusive) to
Mon 19.05.2014 00:00 (exclusive), zone **Europe/Lisbon** (UTC+1 in May); function
`campaign_window() -> tuple[int, int]` in `pipeline/week.py` returns unix seconds.

## §3 Map and `pipeline/geo.py` (frozen API)

Projection: local equirectangular on a sphere of R = 6 371 000 m, scale parallel `LAT_REF = 41.15`
(central Porto). Map frame: origin (0, 0) = north-west corner of the map at lon −8.72, lat 41.26;
**x grows east, y grows south** (canvas orientation), unit = metre.

```
M_LAT = 111194.92664455874   # m per degree latitude
M_LON = 83728.60524645654    # m per degree longitude = M_LAT * cos(41.15 deg)
x = (lon + 8.72) * M_LON      y = (41.26 - lat) * M_LAT
lon = x / M_LON - 8.72        lat = 41.26 - y / M_LAT
```

Map size `MAP_W_M = 15000`, `MAP_H_M = 19000` (lon −8.72 … −8.5408, lat 41.26 … 41.0891; Porto, Gaia,
Matosinhos, Foz, airport; the Douro is inside). Constants in geo.py: `LON0 = -8.72`, `LAT0 = 41.26`,
`LAT_REF = 41.15`, `MAP_W_M`, `MAP_H_M`, `HOME_LON = -8.6112`, `HOME_LAT = 41.1481` (Aliados),
`HOME = (9110.0, 12443.0)` metres = player start. Reference points: airport (3232, 1323), Aliados = HOME.

| Function | Signature | Notes |
|---|---|---|
| `proj` | `proj(lon: float, lat: float) -> tuple[float, float]` | lon/lat → metres in map frame |
| `unproj` | `unproj(x: float, y: float) -> tuple[float, float]` | metres → (lon, lat) |
| `in_map` | `in_map(lon: float, lat: float) -> bool` | 0 ≤ x ≤ MAP_W_M and 0 ≤ y ≤ MAP_H_M |
| `haversine` | `haversine(lon1, lat1, lon2, lat2) -> float` | great-circle **km**, R = 6371 |
| `path_km` | `path_km(pts: Sequence[Sequence[float]]) -> float` | km along a lon/lat polyline (sum of haversine) |
| `trip_ok` | `trip_ok(pts: Sequence[Sequence[float]]) -> bool` | lon/lat points, filters below |
| `rdp` | `rdp(pts: Sequence[tuple[float, float]], tol_m: float) -> list[tuple[float, float]]` | Ramer–Douglas–Peucker on **metres**; keeps first and last |
| `night_hour` | `night_hour(hour: int) -> bool` | night = local hour 22…23 or 0…5 |
| `fare` | `fare(km: float, night: bool) -> float` | `(3.25 + 0.50·km) × (1.2 if night else 1)`, rounded half-up to 2 decimals (`floor(x·100 + 0.5)/100`) |

`trip_ok` rejects a trip unless **all** hold: (1) 4 ≤ number of points ≤ 240 (45 s … 60 min);
(2) every point is a 2-element lon/lat pair and `in_map`; (3) 0.8 ≤ `path_km` ≤ 30.0;
(4) no step between consecutive points exceeds 625 m (= 150 km/h in 15 s);
(5) straight distance first→last ≥ 0.3 km (drops loops that return to the start).
Night for a trip = `night_hour` of the **local pickup hour** (Europe/Lisbon).

## §4 `game/game_data.json`

Deterministic (sorted, `json.dumps(separators=(",", ":"), ensure_ascii=False)`), ≤ 5 MB, one line.
Map unit: `unit_m` = **5** metres (K1 may raise it to 10 only if the file exceeds 5 MB; consumers always
read `unit_m`). All x, y, r are **integers in map units**, same frame as §3 (÷ unit_m).

```
{"version":1,"unit_m":5,"bounds":[0,0,3000,3800],"generated":"2014-05-12/2014-05-19 UCI339",
 "shifts":[ ... 28 ... ]}
```

Top level: `version` (1), `unit_m` (int m), `bounds` `[x0, y0, x1, y1]` in units (`[0,0,MAP_W_M/unit_m,
MAP_H_M/unit_m]`), `generated` (string, no timestamp so output is deterministic), `shifts` (array).

Shift object (index in `shifts` = campaign index 0..27: `mon-am, mon-lunch, mon-pm, mon-night, tue-am, …,
sun-night`; Saturday's night is `sat-night` = the real Sun 18.05 00:00–02:00):

| Field | Type | Meaning |
|---|---|---|
| `id` | str | `<day>-<slot>`, day ∈ mon tue wed thu fri sat sun, slot ∈ am lunch pm night |
| `name` | str | Ukrainian name (K1 brief table) |
| `day` | str | «понеділок, 12 травня 2014» (`sat-night`: «з суботи на неділю, 18 травня 2014») |
| `slot` | str | `am` / `lunch` / `pm` / `night` (§9) |
| `start_local` | str | `"2014-05-12 08:00"` Europe/Lisbon |
| `start_hour` | int | 8 / 12 / 17 / 22; `sat-night` = 0 |
| `difficulty` | int 1..5 | quintile of the average percentile of (ghost.total/median, −orders per driver, pickup spread) |
| `nDrivers` | int | = `len(taxis)` = `len(ranking)` |
| `orders` | array | compact order arrays, sorted by `t`, ties by TRIP_ID |
| `taxis` | int[] | TAXI_ID of each real driver, parallel to `ranking` |
| `ranking` | float[] | per real driver total € (sum of fares of that driver's orders), sorted descending, ties by TAXI_ID |
| `ghost` | `{taxi, total, orders}` | `taxi` = index into `taxis` (always 0 = best), `total` = `ranking[0]`, `orders` = indices into `orders` of the ghost's trips, ascending |
| `median` | float | median of `ranking` (mean of the two middle values if even) |
| `top10` | float | `ranking[max(0, ceil(0.10·nDrivers) − 1)]` (value at the 10 % mark) |
| `speed_by_hour` | float[24] | km/h by **local hour of day 0..23**; see below |
| `detour` | float | median road/straight ratio of this shift's orders, clamped 1.1…1.8, 3 decimals |
| `hot` | array | `{x, y, w, name}` hotspots (units; `w` 0..1 share of pickups); `[]` in v0 |
| `surges` | array | `{x, y, r, t0, t1, n, name}`; `x, y, r` in units, `t0, t1` game s in [150, 7200], `n` pickups; `[]` in v0 |

**Order array** (all fields in this fixed order; ints unless noted):
`[t, x0, y0, x1, y1, pts, d, km, fare, c, stand, taxi]`

| Idx | Name | Meaning |
|---|---|---|
| 0 | `t` | pickup time, game s from shift start, 0..7199 (TIMESTAMP − shift start) |
| 1,2 | `x0,y0` | pickup point, map units (first GPS point) |
| 3,4 | `x1,y1` | drop-off point, map units (last GPS point) |
| 5 | `pts` | flattened **deltas**: `[dx1,dy1,dx2,dy2,…]`, point *i* = point *i−1* + delta, point 0 = (x0,y0); `n = len/2 + 1` points, last = (x1,y1); point *i* is reached at ride time `15·i` s. Every GPS point is kept (no simplification) |
| 6 | `d` | ride duration s = `15 × (n − 1)` |
| 7 | `km` | `path_km` of the lon/lat polyline, 2 decimals (float) |
| 8 | `fare` | `fare(km, night)` € (float, §3) |
| 9 | `c` | call type 0 = A, 1 = B, 2 = C |
| 10 | `stand` | ORIGIN_STAND, 0 if none |
| 11 | `taxi` | index into `taxis` / `ranking` |

Inclusion rule: a trip is in the shift iff it passes `trip_ok` and its start (TIMESTAMP, unix s) is in
`[start, start + 7200)` where `start` = unix seconds of `start_local` in Europe/Lisbon. Warn (do not fail)
if a shift has < 150 orders.

Computation: **ranking** = per TAXI_ID the sum of `fare` over its orders in the shift (money counts at
pickup, like the player). **ghost** = the driver with the highest total. **median**, **top10** from the
ranking. **speed_by_hour**: over *all* week trips passing `trip_ok`, group by local hour of the trip start;
per hour the median of `km / (d / 3600)`, clamped 12…60 and rounded to 1 decimal; an hour with < 30 trips
uses the overall median. The same array is stored in every shift. **detour**: median of
`km / haversine(first, last)` over the shift's orders whose straight distance ≥ 0.5 km. **hot / surges**:
K1 brief (`pipeline/places.py`), names from §9.

## §5 `game/roads.json`

`{"v":1,"unit_m":2.5,"nodes":[x0,y0,x1,y1,...],"edges":[[a,b,[x,y,...]],...]}` compact, ≤ 400 KB.
`nodes` flat ints in **2.5-m units** of the §3 frame (so ×2.5 → metres), sorted by (y, x); `edges`: `a`, `b`
node indices, third item = flat interior points (without the end nodes) in the same units, in direction
a→b; edges sorted by (a, b); one connected component, undirected. Optional `game/streets.png`: a
transparent PNG of the whole map, 1 px = 10 m (1500 × 1900), light cool-blue lines; used by the renderer
as the street glow if present.

## §6 Build, gates, test hooks

`python -m pipeline.build_game [--src game/src] [--data PATH] [--roads game/roads.json] [--out game/index.html]`
(`main(argv)`; exit 0 ok, 1 build error). `--data` default: `game/game_data.json` if it exists, else
`game/fixture/mini.json`. `--roads` default `game/roads.json`; a missing roads or `game/streets.png` file is
skipped silently. Template `game/src/index.html` contains `/*__CSS__*/` (inside `<style>`),
`<!--__DATA__-->`, `<!--__JS__-->`, each replaced **exactly once** (else error).

| Placeholder | Replaced by |
|---|---|
| `/*__CSS__*/` | all `game/src/css/*.css`, sorted by file name, concatenated |
| `<!--__DATA__-->` | `<script type="application/json" id="game-data">…</script>`, then (if present) `<script type="application/json" id="roads-data">…</script>`, then (if present) `<img id="streets-png" hidden src="data:image/png;base64,…">` |
| `<!--__JS__-->` | one `<script>` per `game/src/js/*.js`, sorted by file name; data comes first in the document |

JSON data is inlined with `</` escaped as `<\/`. A JS file containing the text `</script` (case-insens.)
fails the build. Output is one self-contained offline HTML.

Test hooks: `window.__porto = {PG}` (set by 99_boot). Pins: `PG.render.pins` = `[{o, px, py, r, reach}]` in
CSS px relative to `#map`. State: `PG.engine.G`, `PG.screen`.

`tools/smoke.py <html> [--tag T] [--width 390] [--height 844] [--browser PATH]` (Playwright bundled Chromium,
headless; if Playwright or its browser is missing print «run: python -m playwright install chromium» and
exit 2). Steps, each a hard assert:

1. Open `file://<abs html>`, collect `console` errors and `pageerror`s (zero allowed). Wait for `window.__porto`.
2. `#menu` visible; `#shiftList` has ≥ 1 `[id^="shift-"]`. Screenshot `test-screenshots/smoke-<tag>-menu.png`.
3. Click the first `[id^="shift-"]`; wait until `PG.screen === 'play'` and `PG.engine.G` exists, not over.
4. Wait (≤ 5 s real; stepping `PG.engine.step(60)` up to 40 times if no pin yet) for a pin with `reach === true`
   in `PG.render.pins`; mouse-click at `#map` box + (px, py). Assert `G.mode === 'pickup'` (or `'ride'`).
5. Money rises: step `PG.engine.step(10)` until `G.tot` > value before the click (≤ 300 s of game time).
   Screenshot `…-play.png`.
6. Step `PG.engine.step(600)` until `G.over`; wait ≤ 5 s for `#result` visible. Screenshot `…-result.png`.
7. Assert zero console errors again. `--tag` (default `x`) only names the screenshots.

Exit codes: 0 pass, 1 failed assert / console error, 2 usage, missing file or missing Playwright.
`tools/check_py.py [paths…]` (default `pipeline tools`): AST check; lists each module without a docstring and
each function without a docstring or without annotations on all parameters (except self/cls) and the
return; exit 1 if any; tests/ is not checked.
`tools/make_fixture.py`: `--out`, deterministic (seed 7), schema of §4, 1 shift `fix-am` «Тестова зміна»,
25 taxis, 120 trips in the central 5 × 5 km, 3 `hot`, 1 `surge` with `t0` = 150.

Node tests: `node tools/engine_test.mjs [--data PATH]` (default `game/fixture/mini.json`),
`node tools/roads_test.mjs [--roads PATH]`.
No-AI-attribution check on every merge: `git log main..<branch> -i -E --grep='co-authored|claude|generated with|anthropic'`.

## §7 Python rules

Python ≥ 3.11. Full type hints, a docstring on every module/class/function (Google style; say units). One
job per function, ≤ ~40 lines. CLI modules: `def main(argv: list[str] | None = None) -> int` with
`argparse`, and `if __name__ == "__main__": raise SystemExit(main())`. No work at import time. Pure
functions + pytest. `pathlib` for paths; no bare `except`; no `print` in library functions (print only in
`main`). Named module constants for magic numbers. Deterministic output (sorted keys, no timestamps).
Ruff config lives in pyproject.toml (line length 100; E,F,W,I,UP,B,SIM,D; Google docstrings; tests exempt
from D).

## §8 JS rules and modules

Plain scripts, **one IIFE per file**, no imports: `(function (root) { const PG = root.PG = root.PG || {}; … })(typeof window !== 'undefined' ? window : globalThis);`.
Core modules (data, engine, rules, ai, roads, radio logic) are **DOM-free** and run in node. No per-frame
allocations (reuse objects/arrays, pool particles). Exception: `10_data.js` reads `#game-data` at load (if
`PG.DATA` is undefined). Modules do not call each other's DOM; they talk through `PG.bus`.
UI text Ukrainian.

| File | Global | Role |
|---|---|---|
| 00_core.js | `PG.bus`, `PG.C`, `PG.util`, `PG.REDUCED` | events, constants (§9), helpers |
| 10_data.js | `PG.data` | §10 |
| 12_roads.js | `PG.roads` | §5 graph, A* |
| 20_engine.js | `PG.engine` | §11 |
| 22_rules.js | `PG.rules` | §13 |
| 25_ai.js | `PG.ai` | 7 rivals |
| 28_radio.js | `PG.radio` | surge announcements, hotspot glow |
| 30_audio.js | `PG.audio` | WebAudio synth (A1) |
| 35_audio_wire.js | — | bus → audio (subscribes at load) |
| 40_render.js | `PG.render` | map canvas, pins |
| 42_orders.js | `PG.orders` | preview, two-step tap |
| 45_fx.js | `PG.fx` | effects |
| 50_hud.js | `PG.hud` | HUD |
| 60_progress.js | `PG.progress` | save, unlocks, hints |
| 65_screens.js | `PG.screens`, `PG.screen` | menu, about, result |
| 70_input.js | `PG.input` | pointer, keys |
| 99_boot.js | — | init order, frame loop, `window.__porto` |

`PG.bus = {on(ev, fn), off(ev, fn), emit(ev, payload)}`; a throwing listener is caught and `console.error`ed.
`PG.util`: `eur(x) -> "€12,40"` (comma decimal, 2 digits); `plural(n, one, few, many) -> string` (Ukrainian:
1 / 2–4 / 5–20 rules); `mins(sec) -> "12 хв"`; `clock(startHour, tGame) -> "08:42"` (local clock of the
shift: `startHour·3600 + tGame` s). `PG.REDUCED` = prefers-reduced-motion (false in node).

**Init order** in 99_boot (`PG[name] && PG[name].init && PG[name].init()`, each only if present):
`progress, render, hud, audio, radio, orders, fx, screens, input` (progress first; hud before audio so
`#hud-extra` exists; screens then input last). `data`, `roads`, `engine`, `rules`, `ai`, `audio_wire` need no
init (rules and wire subscribe at load; `PG.ai.init(G)` runs per game). Boot owns the frame loop (rAF): `dt`
real s capped at 0.1; if `PG.screen === 'play'` and `G` exists and not over and not paused:
`PG.engine.step(dt × BASE_SCALE × (G.fast ? FAST : 1))`; then `PG.bus.emit('frame', {now, dt})`,
`PG.render.draw(now)`, `PG.hud.update(now)` (if present). Pauses when the tab is hidden.

**Module APIs** (exact names; each module owns its file, others only call these):

| Global | API |
|---|---|
| `PG.render` | `{init(), draw(now), P(x, y) -> {x, y} (metres → CSS px, reused object), screenToWorld(px, py) -> {x, y}, pins, view {cx, cy, scale}, onDraw(fn(ctx, now), z), drawsRivals: true}` |
| `PG.input` | `{init()}`; tap → `PG.orders.tap(o)` if present else `startPickup` / `bookNext`; hover → `PG.orders.hover(o\|null)`; map tap → `cruiseTo`; keys Space pause, F fast, Esc menu; first gesture → `PG.audio.unlock()` |
| `PG.hud` | `{init(), update(now)}` |
| `PG.screens` | `{init(), setScreen(name), showMenu(), start(idx), showResult(r)}`; `PG.screen` ∈ menu/about/play/result |
| `PG.orders` | `{init(), hover(o\|null), tap(o), selected}` |
| `PG.radio` | `{init(), update(G), surges, phase}` |
| `PG.roads` | `{enabled, route(x0, y0, x1, y1) -> {xs, ys, n, len}\|null, pointAt(path, f, out) -> {x, y, k, hx, hy}, stats()}` (metres; null = go straight) |
| `PG.rules` | `{kindOf(o), leadK(o)}` |
| `PG.ai` | `{RIVALS, DIFF, PERS, init(G), tick(G, t0, t1), onPlayerCommit(G, o)}` |
| `PG.fx` | `{init()}` (draws through `PG.render.onDraw`, z ≥ 0) |
| `PG.audio` | `{init(), unlock(), play(name, opts), music {start(mood), setIntensity(0..1), stop()}, engine {set(speed01)}, setVolume({master, music, sfx}), setMuted(bool), getSettings()}` |

**DOM mount points** (ids). `index.html` (K2) creates, empty: `#app` > `#stage`, `#hud`, `#dispatch`, `#menu`,
`#about`, `#result` (the three screens are `class="screen"`, hidden except the active one), `#toast`.
Created by modules: `#map` (canvas, first child of `#stage`) by render; `#hud-rank` (the «#37 з 212» text)
and `#hud-extra` (empty slot) inside `#hud`, and the buttons in `#dispatch` (pause, ×3, menu), by hud;
`#shiftList` and one `#shift-<id>` card per shift inside `#menu`, and the contents of `#about` / `#result`,
by screens; the order card by orders (`#order-card`, inside `#stage`); the mute button by audio (inside
`#hud-extra`). `#streets-png` and the data scripts come from the build (§6).

**Node tests** load files: set `globalThis.PG = {DATA: <game_data json>, ROADS: <roads json or undefined>}`,
then run (`vm.runInThisContext`) `00_core, 10_data, 12_roads, 20_engine, 22_rules, 25_ai` in name order,
skipping the missing ones. `10_data` uses `PG.DATA` if set, `12_roads` uses `PG.ROADS`.

## §9 Constants (`PG.C`, and the same numbers in Python where noted)

| Name | Value |
|---|---|
| `BASE_SCALE` | 40 (game s per real s) |
| `FAST` | 3 (extra multiplier in fast mode) |
| `SHIFT` | 7200 game s (= 180 real s) |
| `SLOTS` | `{am:{h:8,label:"08–10"}, lunch:{h:12,label:"12–14"}, pm:{h:17,label:"17–19"}, night:{h:22,label:"22–24"}}`; `sat-night` starts at hour 0 |
| `DAYS` | `mon tue wed thu fri sat sun` = понеділок, вівторок, середа, четвер, п'ятниця, субота, неділя |
| `CALL` | `0 = A` dispatch call, `1 = B` taxi stand, `2 = C` street hail (`CALL_NAMES = ["Виклик","Стоянка","З вулиці"]`) |
| `LEAD` (game s) | `[1200, 1200, 900]` for A, B, C — pin visible from `t − LEAD[c]·DIFF_K·leadK`. Chosen for playability, not for the 200-s measuring bot: on normal a pin lives 30 / 30 / 22 real s (LEAD / `BASE_SCALE`), never under 13 (rush calls, `leadK` 0.6, are shorter). A greedy scripted player over the 28 shifts sees on average 4.8 bright (takeable) pins on a 2.8 km phone view on normal (median 2, p90 15: demand comes in bursts), easy 4.9, hard 3.0. `RADIUS` hardly moves this (9000/6500/4500 gives 4.9). Wave-3 values were `[310, 310, 310]`; `[1000, 720, 600]` gave median 0 and was dropped |
| `RADIUS` (m) | `[6000, 4500, 3000]` — pin visible only within `RADIUS[c]·DIFF_K` of the car (was `[5000, 3500, 2500]`) |
| `DIFF_K` | `{easy:1.3, normal:1, hard:0.8}` — easy shows more pins for longer, hard fewer (was `1.0 / 1 / 0.9`) |
| `BOARD_S` | 30 (boarding seconds added to eta) |
| `HOME` | `{x: 9110, y: 12443}` metres |
| `MAP` | `{w: 15000, h: 19000}` metres |
| `FARE` | base 3.25, per km 0.50, night factor 1.2, night hours 22–05 local |

Night (fare, rivals' «Сова», music = 21–05 for audio only) is by the local hour of day.

**Named places** (lon, lat; used by K1 for hotspot names within 900 m, rivals' targets, hints):

| Name | lon | lat | Name | lon | lat |
|---|---|---|---|---|---|
| Aliados | −8.6112 | 41.1481 | Ribeira | −8.6129 | 41.1406 |
| Bolhão | −8.6062 | 41.1494 | Trindade | −8.6094 | 41.1511 |
| São Bento | −8.6104 | 41.1456 | Clérigos | −8.6146 | 41.1459 |
| Campanhã | −8.5856 | 41.1487 | Bonfim | −8.5930 | 41.1480 |
| Casa da Música | −8.6307 | 41.1588 | Boavista | −8.6340 | 41.1620 |
| Cedofeita | −8.6200 | 41.1520 | Marquês | −8.6054 | 41.1576 |
| Hospital São João | −8.6014 | 41.1827 | Asprela / університет | −8.5963 | 41.1783 |
| Estádio do Dragão | −8.5835 | 41.1618 | Foz | −8.6760 | 41.1500 |
| Castelo do Queijo | −8.6890 | 41.1690 | Matosinhos | −8.6910 | 41.1823 |
| Aeroporto | −8.6814 | 41.2481 | Gaia (Cais) | −8.6160 | 41.1370 |
| Santo Ovídio | −8.6040 | 41.1170 | Campo 24 de Agosto | −8.5990 | 41.1495 |

Stand hint: call type B pins near these are where «Фатіма» camps; «Руй» uses Aeroporto.

## §10 JS `PG.data`

Built from `PG.DATA` (or `#game-data`) at load; JSON snake_case → JS camelCase.
`PG.data = {version, unitM, bounds (metres), shifts, ghostAt(sh, t, out)}`. Each `sh` (array index = campaign
index): `id, name, day, slot, startLocal, startHour, difficulty, nDrivers, taxis, ranking, median, top10,
speedByHour[24], detour, hotM, surgesM, orders, ghostOrders, thr`.

- `sh.orders[i]`: `{i, t, x0, y0, x1, y1, pts:{xs, ys, tRel, n}, d, km, fare, c, stand, taxi}`; x, y in **metres**
  (units × `unitM`); `pts.xs/ys` Float32Array of n points (deltas accumulated), `pts.tRel` Float32Array
  `15·i`; `d`, `km`, `fare` as stored.
- `sh.ghostOrders` = ghost's order objects in time order (`ghost.orders` resolved); `sh.ghost = {taxi, total}`.
- `sh.hotM` = `[{x, y, w, name}]` metres; `sh.surgesM` = `[{x, y, r, t0, t1, n, name}]` metres, `t0/t1` game s.
- `sh.thr = {median, top10, ghost, legend}`, `ghost = ranking[0]`, `legend = 1.25 × ghost`.
- `PG.data.ghostAt(sh, t, out)` → `out {x, y, hx, hy}` (metres, unit heading), no allocation per call: before
  the first ghost pickup it waits at its pickup; during a ghost ride it follows `pts` at `15·i`; between
  rides it travels from the last drop-off to the next pickup, arriving exactly at that order's `t` (along
  `PG.roads.route` if enabled, cached per gap, else straight); after the last ride it stays at the drop-off.
- `PG.data.ghostMoney(sh, t)` → € earned by the ghost with pickup time ≤ t (monotone pointer cache).

## §11 Engine `PG.engine`

```
PG.engine = { config:{difficulty:'normal'}, G, DIFF_K, newGame(idx), step(dt), reachable(o), preview(o),
  startPickup(o), bookNext(o), cruiseTo(x, y), say(text, ms), leadOf(o), calcResult() }
```
Units: metres, seconds (game), € . `DIFF_K` as §9. `config.difficulty` ∈ easy | normal | hard (set before
`newGame`). `newGame(idx)` builds `G`, calls `PG.ai.init(G)` if `PG.ai`, emits `shift:start {idx, sh}`.
`step(dt)` advances `dt` game s, clamped to the end; no-op when `G.over`. Processing is by event time
inside the step (pickup at `leg.t1`, drop-off, booked-next start, real drivers' money, `PG.ai.tick(G, t0,
t1)` per interval) so one big `dt` equals many small ones. At `G.t = 7200` emit `shift:end {result}` once,
set `G.over = true`.

**G fields**: `t` game s; `sh` shift; `idx`; `mode` ∈ `idle` (parked) / `cruise` (free drive to a point) /
`pickup` (to the passenger) / `ride`; `x, y` metres; `hx, hy` unit heading; `leg {t0, t1, x0, y0, x1, y1, path}`
(`path` null or a roads path `{xs, ys, n, len}`); `cur` order being served; `next` booked order (or null);
`tot` money € (rounded to cents at each addition, includes tips) — the single money value; `rides`;
`idleT` s in idle+cruise; `tips`, `combo`, `bestCombo`, `lastDropT` (rules); `trail` (player pos every 10
game s, max 120, `[x,y,…]` ring); `floats` (`{x, y, text, color, born}`, max 40; `+€8,40` at pickup);
`rivals` `[]` (§13); `claim` `Map<o.i, {by, t1}>` (`by` = `'player'` or a rival id); `taken` Set of order
indices the player took; `real` Float64Array money per real driver; `rank` (live, 1-based); `ghostMoney`;
`over`; `paused`; `fast`; `msg {text, until}` (say).

**Rules**
- Hour for speed: `h = (sh.startHour + floor(t/3600)) % 24`; `speed = sh.speedByHour[h]` km/h.
- `eta(fromX, fromY, t, o) = hypot(o.x0 − fromX, o.y0 − fromY) / 1000 × sh.detour / speed × 3600 + 30` s.
- Visible: `o.t − leadOf(o) ≤ t < o.t` **and** distance(car, pickup) ≤ `RADIUS[c] × DIFF_K`.
  `leadOf(o) = LEAD[o.c] × DIFF_K[difficulty] × (PG.rules ? PG.rules.leadK(o) : 1)`.
- One shared feasibility function backs `reachable`, `startPickup` and `bookNext`: an order is takeable iff
  visible, not in `G.taken`, not claimed by a rival whose `t1` ≤ ours (K6 owns the claim rules), and
  `fromT + eta ≤ o.t` (equal = reachable). `from` = car now (modes idle/cruise/pickup) or, while riding,
  the drop-off of `cur` at ride end (`fromT = leg.t1`).
- `reachable(o)` → bool. `preview(o)` → one reused object `{fromX, fromY, eta, wait, ok, km, fare}`:
  `wait = o.t − (fromT + eta)` s (≥ 0 when ok), `ok = reachable(o)`; read-only, no allocation per call.
- `startPickup(o)` (not while riding; from `pickup` it replaces the target): returns bool; on success
  `cur = o`, mode `pickup`, `leg = from→(o.x0,o.y0)`, `t0 = G.t`, `t1 = G.t + eta`, `G.claim.set(o.i,
  {by:'player', t1})`, `PG.ai.onPlayerCommit(G, o)`, emits `order:book {o, kind:'pickup'}`; on failure
  `say('Не встигнеш')` and false.
- At `leg.t1` (pickup): `tot += o.fare`, `rides++`, float `+€x`, emit `pickup {o, fare}`, mode `ride`,
  leg = pickup→drop-off over `o.d` s following `o.pts` (`tRel`).
- At ride end: payload `{o, fare: o.fare, tip: 0}` is emitted as `dropoff` (rules set `tip`); then
  `tot += tip`. If `G.next` is set, re-validate it (same function; at drop-off `from`): ok → start it
  (mode `pickup`); else emit `order:lost {o, by:'real'}`, `say`, mode `idle`. Without `next`: mode `idle`.
- `bookNext(o)` (only in mode `ride`): takeable with `from` = drop-off, i.e. `rideEnd + eta ≤ o.t`; sets
  `G.next = o`, claim, `onPlayerCommit`, emits `order:book {o, kind:'next'}`.
- `cruiseTo(x, y)`: not while riding; cancels a pickup; mode `cruise`, straight leg at current speed,
  clamped inside the map; arrival → `idle`.
- Movement: pickup/cruise legs take `t1 − t0` s (straight × detour / speed); position along `leg.path` via
  `PG.roads.pointAt(path, f, out)` when `PG.roads && PG.roads.enabled` (road hook: `leg.path =
  PG.roads.route(x0,y0,x1,y1)` at leg creation; timing never changes), else straight line; ride follows `o.pts`.
  Idle: parked.
- `say(text, ms)`: sets `G.msg`, emits `note {text, ms}`.
- Real drivers: at `o.t` their money gets `o.fare` (`G.real[o.taxi]`); live `rank = 1 + count(real > tot)`;
  `ghostMoney = PG.data.ghostMoney(sh, t)`; with `PG.ai`, rivals' totals are counted **only for the race place**.
  Emit `rank:change {rank, prev}` only on change; `ghost:overtake {ahead}` on a flip of `tot > ghostMoney`;
  `order:spawn {o}` when `t` crosses `o.t − leadOf(o)`.
- `calcResult()` → `{earned, rank, nDrivers, medal, rides, idlePct, vsGhost, racePlace, raceSize, tips,
  bestCombo, shiftId, idx}`: `earned = tot`; `rank = 1 + count(ranking > earned)` (cents); `idlePct =
  round(100·idleT/7200)`; `vsGhost = earned − ghost.total`; `medal`: 4 if `earned ≥ 1.25·ghost`, else 3 if
  `> ghost`, else 2 if `≥ top10`, else 1 if `≥ median`, else 0; `racePlace/raceSize` = place among the player
  + rivals (`raceSize` = 1 and `racePlace` = 1 without rivals).
- Road hook and **PG.ai hooks** (all no-ops when absent): `PG.ai.init(G)` in `newGame`;
  `PG.ai.tick(G, t0, t1)` per processed interval; `PG.ai.onPlayerCommit(G, o)` after the engine accepted a commit.

## §12 Events (`PG.bus`)

| Event | Payload | Tier | Emitted by |
|---|---|---|---|
| `frame` | `{now, dt}` real s | 0 | boot |
| `ui:click` | `{el}` (any `<button>`) | 0 | input |
| `ui:screen` | `{name}` menu/about/play/result | 0 | screens |
| `shift:start` | `{idx, sh}` | 0 | engine |
| `shift:end` | `{result}` (calcResult) | 0 | engine |
| `order:spawn` | `{o}` | 0 | engine |
| `order:book` | `{o, kind:'pickup'\|'next'}` | 0 | engine |
| `pickup` | `{o, fare}` | 0 | engine |
| `dropoff` | `{o, fare, tip}` (`tip` mutable by rules) | 0 | engine |
| `order:lost` | `{o, by}` `by` = `'real'` or a rival id | 0/1 | engine, ai |
| `rank:change` | `{rank, prev}` | 0 | engine |
| `ghost:overtake` | `{ahead}` bool | 0 | engine |
| `medal` | `{level}` 0..4 | 0 | screens (700 ms after result) |
| `pause` | `{paused}` | 0 | hud |
| `note` | `{text, ms}` toast | 0 | engine, any |
| `rival:lost` | `{rival, o}` a rival lost its target | 1 | ai |
| `rival:pickup` | `{rival, o, fare}` | 1 | ai |
| `combo` | `{n, k}` | 1 | rules |
| `combo:break` | `{n}` | 1 | rules |
| `radio:surge` | `{s, inSec}` (`s` ∈ `sh.surgesM`) | 1 | radio |
| `radio:surge:end` | `{s}` | 1 | radio |

Subscribers must not rely on order except: `rules` subscribes to `dropoff` at load (before everything else).

## §13 Tier-1 game model

**Passenger kinds** (`PG.rules.kindOf(o)` → `'regular'|'vip'|'tourist'|'rush'`): `h = fnv1a32(shiftId + '#' + o.i)`
(UTF-8 bytes, offset 2166136261, prime 16777619), `u = h / 2^32`: `u < 0.70` regular; `< 0.80` tourist;
`< 0.88` vip; else rush. Tip rate (× `o.fare`): regular 0.05, tourist 0.15, vip 0.30, rush 0.10.
`PG.rules.leadK(o)` = 0.6 for rush, else 1. Tip = round to cents of `fare × rate` plus combo bonus.

**Combo**: a pickup within **300 game s** after the previous drop-off (or while booked during a ride, i.e.
pickup time ≤ `lastDropT + 300`; the pickup time is the start of the ride, `G.leg.t0` in the `pickup` handler)
raises `n` by 1, else `n = 1` (and if `n` was ≥ 2, emit `combo:break`). The window was picked with the
measuring bot (`pipeline/sim.py`, 28 shifts, normal): with 90 s only 10 % of its rides reached ×1.1; with 300 s
42 % reach ×1.1 or more and 9 % reach ×1.3; with 600 s 71 % and 37 %.
Multiplier `k`: n=1 → 1.0, n=2 → 1.1, n=3 → 1.2, n ≥ 4 → **1.3** (shown as badge «×1.3»). Bonus paid at
drop-off inside `tip`: `fare × (k − 1)`. Emit `combo {n, k}` on every increase. `G.bestCombo = max n`.

**Progress** (`PG.progress`; localStorage key `porto-lanosiv-progress-v1`, try/catch, works with blocked
storage in memory): `{v:1, difficulty:'normal', best:{<shiftId>:{medal, earned, rank}}, hints:{h1:bool,h2:bool,h3:bool}}`.
Unlock: shift 0 always open; shift *k* is open iff `best[id(k−1)].medal ≥ 1` (bronze on the previous
shift); without `PG.progress` (tier 0) all open. API: `init()`, `isOpen(idx)`, `best(idx)`, `record(result)`
(→ true if a new record), `difficulty()`, `setDifficulty(d)`, `nextIdx()`, `hint(n)`/`markHint(n)`.
Medals: 0 none, 1 бронза, 2 срібло, 3 золото, 4 легенда.

**Difficulty choice**: Легко / Нормально / Важко → `PG.engine.config.difficulty`; changes pin radar/lead
(`DIFF_K`) and rival sharpness (K6 `PG.ai.DIFF`); all 7 rivals drive on every difficulty.

**The 7 Lanos** (`PG.ai.RIVALS`; `G.rivals[] = {id, name, nick, color, f, x, y, hx, hy, mode, target, total, rides}`):

| id | Name | Nick | Colour | Gender | Tactic |
|---|---|---|---|---|---|
| ze | Зé | «Акула» | `#ff8a3d` | m | best € per minute |
| fatima | Дона Фатіма | «Королева стоянки» | `#f4d03f` | f | stands, hotspots |
| rui | Руй | «Сова» | `#4db8ff` | m | long trips, airport, night |
| ines | Інеш | «Блискавка» | `#ff4d6a` | f | fastest reaction, short rides |
| tiago | Тіаго | «Снайпер» | `#ff6ec7` | m | hunts orders near the player |
| lurdes | Лурдеш | «Хвиля» | `#a0e85b` | f | demand waves (surges) |
| nuno | Нуну | «Новачок» | `#ffffff` | m | slow, nearest first |

**Tactics in numbers** (`PG.ai.PERS`; `python -m pipeline.sim --tactics` prints them, `tools/engine_test.mjs`
checks them on every difficulty). A score ≤ 0 means «never take this pin».

| id | Reaction `react` (s) | What it does |
|---|---|---|
| ze | 16, every drive takes 0.85× the time | notices the most pins (×2.5), takes the best € per minute; the top earner per working hour |
| fatima | 40 | stand calls ×1.6 and only within 420 s, a street pin only within 120 s; notices stand pins ×3; waits at stands |
| rui | 34 (night ×0.7) | nothing under 3.5 km unless it touches the airport (2.5 km round it); score ×(1 + km/4), airport ×2.5; drives to the airport 25 % of idle drives (night 60 %) |
| ines | 8 | nothing over 5 km; score `fare / (eta + ½·d + 60)`; notices ×1.4 |
| tiago | 20 | not on easy: only pins within 1500 m of the player (×2); repositions every 45 s next to the player |
| lurdes | 30 | while a demand wave runs (or starts within 240 s) she takes wave pins (×4, noticed ×3) and nothing else beyond 120 s; else the busiest hotspots |
| nuno | 90, every drive takes 1.7× the time, notices ×0.5 | nothing over 4 km, `1 / (eta + 60)`: the nearest pin first; the weakest of the 7 |

Difficulty changes sharpness (`PG.ai.DIFF`): easy `react ×2.4, radius ×0.7, attn 0.14, duty 0.5, speed ×1.0, no
near rule`; normal `×1.0, ×1.0, 0.35, 0.88, ×1.15, near 2500 m at ×0.5`; hard `×0.55, ×1.25, 0.5, 0.9, ×1.6,
near 5000 m at ×0.35`. `duty` is the share of a 1500 s cycle a rival works, the rest is a break (normal 9 %,
hard 8 %, easy 40 % of the shift on break; it was 34–60 %). Rivals hardly take orders away from the measuring bot (0 to 0.1
per shift; the bot's income barely moves even if the rivals drive twice as fast, see the report of the balance
sweep), so the medal shares are set by `LEAD` and `DIFF_K`; the rivals make the race table and the place.
Medal shares of the 200-s bot on the 28 shifts (`node tools/engine_test.mjs`, equal to `pipeline.sim`) with the
wave-4 `LEAD` / `RADIUS` / `DIFF_K` (§9): easy gold+ 96 %, legend 96 %; normal gold+ 100 %, legend 100 %; hard gold+ 100 %,
legend 93 % (bot € 55 / 52 / 51). The wave-3 shares (normal legend 18 %, hard legend 7 %) are gone on purpose: any
`LEAD` of 540 s or more lets the perfect scripted bot see nearly everything, so its medals say little; the targets are
now about the player (enough pins, enough time to reach one) and the bot is mostly the equality check between
`pipeline.sim` and the engine. `RADIUS` hardly moves the bot. Rivals: on hard the weakest of the 7 can be Руй
instead of Нуну (his long trips pay less when pins are plentiful), `engine_test` accepts both.

Arrival-first claims, toasts: brief K6. Race table «Перегони 7 ланосів» on the
result: Ріїн + 7, by €, colour dot, nickname, rides.

**«Про дані» lists**: source UCI 339, CC BY 4.0; **data**: trips, drivers, routes, the ghost, the
ranking, hotspots, demand waves, the road graph (all computed from the raw archive by our Python);
**game model**: fare 3.25 + 0.50 €/km (×1.2 at night), time ×40, pin lead/radius, tips, combo,
passenger kinds, the 7 AI rivals, medals.

## §14 Look

| Token | Value |
|---|---|
| background | `#070b14` (dark night); panels `#0e1424` at 85 % |
| street glow | cool blue `#5aa9ff` at ≤ 18 % alpha, additive thin lines |
| text | `#e8eefc`; muted `#8a96b3` |
| hero car | mint `#3df5b0` |
| ghost | lilac `#b48cff` at 50 % alpha |
| rivals | `#ff8a3d #f4d03f #4db8ff #ff4d6a #ff6ec7 #a0e85b #ffffff` (§13 order) |
| pins by call type | A `#ffc857` amber, B `#5ee6ff` cyan, C `#ff7a90` coral |
| out-of-reach dot | `#6b7488`, radius 3 px, no label |
| ahead / behind | `#3df5b0` / `#ff6b6b` |
| medals | bronze `#cd7f32`, silver `#c0c8d8`, gold `#ffd700`, legend `#b48cff` |

**Pins**: reachable (`PG.engine.reachable(o)`) = bright dot r ≈ 9–12 px, label «€N» (`Math.round(fare)`),
countdown ring = remaining visible time `(o.t − G.t) / leadOf(o)`; colour by call type; labels never overlap
(skip a later one) and stay off the player's car. Out of reach: small grey dot. **Tier 1 two-step tap**
(`PG.orders`): mouse hover → preview, click → take; touch first tap → select + preview (route to the
passenger, the trip along `o.pts`, flag at drop-off, card with price, km, «доїзд N хв», «чекає ще N хв» /
«не встигнеш», call type, button «Беру»), second tap on the same pin or «Беру» → take, tap elsewhere →
clear. Tier 0: one tap/click takes at once. Input hit radius `r + 10` px.

**Fonts**: system only (`system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`), no embedded fonts.
**Portrait phone**: layout min width 360 px; HUD on top (clock, money, rank, ghost, medal bar), map fills
the rest, `#dispatch` buttons ≥ 44 px at the bottom with `env(safe-area-inset-*)`; one toast at a time; card
docks at the bottom, never over the car. **Hero**: Ріїн Гіслінг is our own drawn flat icon (a driver with a
cap); shown on the menu («Ріїн Гіслінг проти 7 ланосів») and on the result («Ріїн Гіслінг заробив €N»);
never a photo or likeness of a real person, no film stills, quotes, music or logos.

## §15 Гра разом (party mode)

Everyone at the presentation plays one shift on one map, from their phones. Single player is unchanged:
without `?party=1` (and in the offline single file) `80_party.js` returns at once and `PG.engine.party` stays `null`.

**Run**: `python tools/party.py [--port 8090] [--build] [--dir game] [--host IP] [--open-host]` (stdlib only; reuses
`tools/serve.py` and `tools/qr.py`). It prints the QR of `http://<LAN-IP>:<port>/?party=1` and the host URL
`http://127.0.0.1:<port>/?party=1&host=1`. `/api/start` and `/api/reset` are accepted only from the server's own machine
(`127.0.0.1`, `::1`, the LAN IP) unless `--open-host`.

**State** (`tools/party.py`, class `Party`, pure, injected clock, one lock): phase `lobby` → `running` → `done`
(`done` at `start_at + duration + 2 s`; `running` includes the countdown before `start_at`); players
`{id, key (secret), name ≤ 20, colour, x, y (null until the first sync), hx, hy, money, trips, seen}`; `claims`
(order index → player id); `shift`, `difficulty`, `duration` (real s, the client sends `SHIFT / BASE_SCALE` = 180),
`start_at` (server time). At most 60 players. A name is cleaned to one printable line; an empty name becomes
«Таксист N», a taken one gets a number. Server time is `time.time()`.

**API** (JSON; replies carry the public state, never the keys):

| Call | Body | Reply |
|---|---|---|
| `GET /api/party` | | `{phase, now, start_at, duration, shift, difficulty, players[{id, name, color, x, y, hx, hy, money, trips, online}], claims{order: id}}` |
| `GET /api/qr` | | `{url, rows[]}`: the QR of the players' URL as strings of `1`/`0` (host draws it on a canvas) |
| `POST /api/join` | `{name, key?}` | `{id, key, state}`; a known `key` rejoins (409 `phase` when `done`, 409 `full`) |
| `POST /api/sync` | `{key, x, y, hx, hy, money, trips}` | state; polled every 500 ms (403 `unknown_player`) |
| `POST /api/claim` | `{key, order}` | `{ok: true}` or `{ok: false, by: name}`; the first claim wins, the owner may repeat; 409 unless `running` |
| `POST /api/release` | `{key, order}` | `{ok}`; only the owner can give an order back |
| `POST /api/start` | `{shift, difficulty, duration?, countdown?}` | state; host only; `start_at = now + countdown` (5 s) |
| `POST /api/reset` | | state; host only; back to `lobby`, claims and money cleared, offline phones dropped |

**Clock**: each reply has `now`; the client keeps the offset of the lowest-latency sample, so the phones agree to
a few tens of ms. Game time `t = (server now − start_at) × BASE_SCALE`; every phone builds the same shift
(`snap.shift`, `snap.difficulty`) at `start_at`.

**Engine hooks** (`20_engine.js`, all inert when `PG.engine.party` is `null`): `party = {clock()}` makes `step()` go to
`clock()` instead of adding `dt`; `G.paused` and `G.fast` become read-only `false` (pause and ×3 off); `PG.ai.init`
is skipped, so `G.rivals` is empty and the 7 rivals are off (the ghost stays). Orders claimed by others are put into
`G.taken` (the pin disappears, feasibility says taken); a claim someone gave back is removed again.

**Claims** (`80_party.js`): `startPickup`, `bookNext` and `cruiseTo` are wrapped. A pickup or booking that passes the
engine's own check sends `/api/claim` first and calls the engine only on `ok` (the tap card closes at once); a refusal
shows «Вже забрав <ім'я>» and removes the pin. Giving up a pickup or a booked order sends `/api/release`.

**Screens** (`?party=1`): name entry (default «Таксист N») → lobby with the names and «Чекаємо на старт» → countdown →
the game (HUD without pause, ×3 and menu; a chip «#N з M» with the leader) → the result with the extra block
«Перегони гравців». Other players are cars with name labels drawn through `PG.render.onDraw` (positions smoothed
between polls). The host (`&host=1`) sees the QR, the players, a shift and difficulty choice and «Старт»; then the
whole map with every car and name, a live leaderboard with the time left, and at the end «Фінал» and «Нова гра».
A phone that reloads keeps its player (key in `sessionStorage`) but restarts its shift at the server time with its
money at 0.
