# P5 gate (balance simulator and sweep): partial, blocked on applying the numbers

Base: main at 7112c65 (K6 merged), branch feat/p5-balance. Nothing was applied to the JS or the contract.

## Gate
- `ruff check pipeline tests tools`: All checks passed
- `python tools/check_py.py`: clean
- `pytest -q`: 126 passed
- `node tools/engine_test.mjs --data game/game_data.json`: ALL OK (1630 checks), unchanged (no JS touched)
- Not run: the rebuild and `tools/smoke.py` (nothing to rebuild, no JS or data changed)

## Fidelity of pipeline/sim.py against the real JS (python -m pipeline.sim --compare)
- 84 games (28 shifts x easy/normal/hard, 200 s bot): bot EUR, every rival EUR, medal and lost-order count
  are identical to the JS engine.
- Also identical off the defaults (checked with a scratch JS oracle): LEAD 540/210/180, and a set with
  aggressive hard and normal rivals plus DIFF_K 0.7 / 1.5 (steals and breaks happen there).
- `--compare` prints mean |diff| 0.0 % (section 3, per shift) and 0.1 % (section 6, bot and 7 rivals;
  the remainder is the one-decimal rounding of the JS table).

## Sweep result (python -m pipeline.tune)
- Baseline (measured here): normal gold+ 27/28, legend 22/28; easy 28/28 (legend 25); hard gold+ 27/28 (legend 21).
- Best point anywhere: LEAD 600/210/210, normal bronze+ 93 %, gold+ 39 %, legend 14 %; easy K 1.0 gold+ 57 %;
  hard K 0.85 gold+ 18 %. All bands hit, but LEAD B and C are below the bot's reaction delay plus boarding
  (200 + 30 s): the bot plays only call type A there (110 of 110 pickups), and the result flips with the delay
  (gold+ 89 % at a 120 s delay against 36 % at 200 s). Not a usable setting.
- Best point with the reachability floor: LEAD 360/330/330, normal gold+ 79 %, legend 64 %; easy gold+ 93 %;
  hard (K 0.85) gold+ 71 %. No band is met.
- RADIUS does not move the bot at all (the bot cruises to the nearest pin whatever the radar shows; with a
  radar-respecting scratch bot it still does not move). Rival DIFF changes lost orders by under 1 per shift.

## Files
pipeline/sim.py, pipeline/tune.py, tests/test_sim.py, tests/test_tune.py, GATE.md. No lockfile, CI, hook or secrets baseline touched.
