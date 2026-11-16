"""Tests of the Python twin of the game (pipeline.sim): pure helpers, rules and a tiny shift."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pipeline import sim


def make_order(
    i: int, t: float, x0: float = 9110.0, y0: float = 12443.0, **kw: object
) -> sim.Order:
    """Build a short order starting at ``(x0, y0)`` and ending 1 km east."""
    fields: dict[str, object] = {
        "i": i, "t": t, "x0": x0, "y0": y0, "x1": x0 + 1000.0, "y1": y0, "d": 60.0, "km": 1.0,
        "fare": 4.0, "c": 0, "stand": 0, "kind": "regular",
        "xs": [x0, x0 + 500.0, x0 + 1000.0], "ys": [y0, y0, y0],
    }  # fmt: skip
    fields.update(kw)
    return sim.Order(**fields)  # type: ignore[arg-type]


def make_shift(orders: list[sim.Order], **kw: object) -> sim.Shift:
    """Build a tiny shift (flat 30 km/h, detour 1.0, two hotspots)."""
    fields: dict[str, object] = {
        "id": "tst-am", "start_hour": 8, "detour": 1.0, "speed_by_hour": [30.0] * 24,
        "hot": [sim.Spot(9000.0, 12000.0, 0.6), sim.Spot(9500.0, 12800.0, 0.4)],
        "surges": [], "orders": orders, "median": 5.0, "top10": 9.0, "ghost": 12.0,
        "times": [o.t for o in orders],
    }  # fmt: skip
    fields.update(kw)
    return sim.Shift(**fields)  # type: ignore[arg-type]


def test_js_round_is_half_up() -> None:
    assert sim.js_round(2.5) == 3
    assert sim.js_round(-2.5) == -2
    assert sim.js_round(0.49) == 0


def test_to_cents() -> None:
    assert sim.to_cents(1.005 + 0.0) in (1.0, 1.01)
    assert sim.to_cents(4.126) == 4.13
    assert sim.to_cents(0.0) == 0.0


def test_f32_matches_node_fround() -> None:
    assert sim.f32(459 * 0.6) == 275.3999938964844
    assert sim.f32(0.5) == 0.5


def test_clamp() -> None:
    assert sim.clamp(5, 0, 3) == 3
    assert sim.clamp(-1, 0, 3) == 0
    assert sim.clamp(2, 0, 3) == 2


def test_mix_and_fnv_match_the_js_values() -> None:
    assert sim.fnv("mon-am") == 1380580688
    assert sim.fnv("ze") == 3962620290
    assert sim.mix(12345, 1) == pytest.approx(0.37686445005238056, abs=1e-15)
    assert sim.mix(sim.fnv("mon-am"), 7) == pytest.approx(0.46578338742256165, abs=1e-15)
    assert sim.mix(4000000000, 123456) == pytest.approx(0.624561624834314, abs=1e-15)


def test_fnv1a32_matches_the_js_values() -> None:
    assert sim.fnv1a32("mon-am#0") == 2838729805
    assert sim.fnv1a32("sun-night#123") == 741543653


def test_kind_for_mix_is_about_70_percent_regular() -> None:
    kinds = [sim.kind_for("mon-am", i) for i in range(4000)]
    assert 0.65 < kinds.count("regular") / 4000 < 0.75
    assert set(kinds) == {"regular", "tourist", "vip", "rush"}


def test_combo_k_and_tip() -> None:
    assert [sim.combo_k(n) for n in (0, 1, 2, 3, 4, 9)] == [1.0, 1.0, 1.1, 1.2, 1.3, 1.3]
    assert sim.tip_for(10.0, "regular", 1) == 0.5
    assert sim.tip_for(10.0, "vip", 2) == 4.0


def test_speed_at_uses_the_local_hour() -> None:
    sh = make_shift([], start_hour=23, speed_by_hour=[float(h) for h in range(24)])
    assert sim.speed_at(sh, 0) == 23.0
    assert sim.speed_at(sh, 3600) == 0.0


def test_medal_of_thresholds() -> None:
    sh = make_shift([])
    assert [sim.medal_of(sh, e) for e in (4.99, 5.0, 9.0, 12.0, 12.01, 15.0)] == [0, 1, 2, 2, 3, 4]


def test_parse_order_decodes_deltas_and_units() -> None:
    raw = [100, 10, 20, 13, 20, [1, 0, 2, 0], 45, 1.2, 4.5, 1, 7, 3]
    o = sim.parse_order(raw, 5, 5.0, "mon-am")
    assert (o.i, o.t, o.x0, o.y0, o.x1) == (5, 100.0, 50.0, 100.0, 65.0)
    assert o.xs == [50.0, 55.0, 65.0]
    assert o.d == 45.0
    assert (o.c, o.stand, o.fare) == (1, 7, 4.5)


def test_parse_shift_and_load(tmp_path: Path) -> None:
    raw = {
        "unit_m": 5, "shifts": [{
            "id": "mon-am", "start_hour": 8, "detour": 1.4, "speed_by_hour": [20.0] * 24,
            "orders": [[1, 10, 10, 20, 20, [1, 1], 30, 1.0, 4.0, 0, 0, 0]],
            "hot": [{"x": 10, "y": 10, "w": 0.5}],
            "surges": [{"x": 10, "y": 10, "r": 100, "t0": 150, "t1": 900}],
            "ranking": [20.0, 10.0], "median": 10.0, "top10": 20.0,
        }],
    }  # fmt: skip
    import json

    path = tmp_path / "d.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    (sh,) = sim.load_shifts(path)
    assert sh.ghost == 20.0 and sh.times == [1.0]
    assert sh.surges[0].w == 500.0 and sh.hot[0].x == 50.0


def test_build_stands_needs_three_orders() -> None:
    orders = [
        make_order(i, 10.0 * i, x0=1000.0 * (i % 2), stand=5 if i < 4 else 6) for i in range(6)
    ]
    stands = sim.build_stands(make_shift(orders))
    assert len(stands) == 1
    assert stands[0].w == pytest.approx(4 / 6)


def test_build_hot_sorted_and_fallback() -> None:
    sh = make_shift([make_order(0, 5.0)])
    assert [h.w for h in sim.build_hot(sh)] == [0.6, 0.4]
    cells = make_shift([make_order(i, 5.0 * i) for i in range(4)], hot=[])
    assert len(sim.build_hot(cells)) == 1


def test_pick_clamps_the_index() -> None:
    arr = [sim.Spot(0, 0, 1), sim.Spot(1, 1, 1)]
    assert sim.pick(arr, 0.0) is arr[0]
    assert sim.pick(arr, 0.999999) is arr[1]


def test_is_night() -> None:
    assert sim.is_night(make_shift([], start_hour=22), 0)
    assert not sim.is_night(make_shift([], start_hour=12), 0)
    assert sim.is_night(make_shift([], start_hour=0), 0)


def test_active_surge_and_in_surge() -> None:
    s = sim.Spot(100.0, 100.0, 50.0, 1000.0, 2000.0)
    sh = make_shift([], surges=[s])
    assert sim.active_surge(sh, 800.0) is s
    assert sim.active_surge(sh, 700.0) is None
    assert sim.active_surge(sh, 2000.0) is None
    assert sim.in_surge(sh, make_order(0, 1500.0, x0=120.0, y0=100.0))
    assert not sim.in_surge(sh, make_order(0, 1500.0, x0=300.0, y0=100.0))


def test_near_airport() -> None:
    assert sim.near_airport(make_order(0, 1.0, x0=3300.0, y0=1300.0))
    assert not sim.near_airport(make_order(0, 1.0, x0=9000.0, y0=9000.0, x1=9100.0, y1=9000.0))


def test_attention_boosts() -> None:
    sh = make_shift([make_order(0, 100.0, c=1), make_order(1, 100.0, c=0, km=7.0)])
    g = sim.new_game(sh, "normal", sim.Settings())
    base = g.D.attn
    by = {rv.id: rv for rv in g.rivals}
    stand, long_trip = sh.orders
    quiet = sim.Ctx()
    assert sim.attention(g, by["ze"], stand, False, quiet) == pytest.approx(base * 2.5)
    assert sim.attention(g, by["fatima"], stand, False, quiet) == pytest.approx(base * 3)
    assert sim.attention(g, by["fatima"], long_trip, False, quiet) == pytest.approx(base * 0.5)
    assert sim.attention(g, by["rui"], stand, True, quiet) == pytest.approx(base * 1.4)
    assert sim.attention(g, by["rui"], long_trip, False, sim.Ctx(air=True)) == pytest.approx(
        base * 2 * 1.5
    )
    assert sim.attention(g, by["ines"], stand, False, quiet) == pytest.approx(base * 1.4)
    assert sim.attention(g, by["lurdes"], stand, False, sim.Ctx(surge=True)) == pytest.approx(
        base * 3
    )
    assert sim.attention(g, by["lurdes"], stand, False, quiet) == pytest.approx(base * 0.7)
    assert sim.attention(g, by["tiago"], stand, False, quiet) == pytest.approx(base)
    assert sim.attention(g, by["nuno"], stand, False, quiet) == pytest.approx(base * 0.5)


def test_scorers_show_each_tactic() -> None:
    o = make_order(0, 100.0, km=2.0, d=300.0, fare=5.0)
    long_o = make_order(1, 100.0, km=9.0, d=900.0, fare=8.0)
    stand = make_order(2, 100.0, c=1)
    quiet = sim.Ctx()
    assert sim.SCORERS["ze"](o, 100.0, quiet) == pytest.approx(5.0 / 430.0)
    # Fatima: stand calls only within STAND_WAIT_S, street pins only when right next to her
    assert sim.SCORERS["fatima"](stand, 100.0, quiet) > sim.SCORERS["fatima"](o, 100.0, quiet) > 0
    assert sim.SCORERS["fatima"](stand, sim.STAND_WAIT_S + 1, quiet) == 0
    assert sim.SCORERS["fatima"](o, sim.STAND_ETA_S + 1, quiet) == 0
    # Rui: nothing short unless it touches the airport, long and airport trips are boosted
    assert sim.SCORERS["rui"](o, 100.0, quiet) == 0
    assert sim.SCORERS["rui"](o, 100.0, sim.Ctx(air=True)) > 0
    assert sim.SCORERS["rui"](long_o, 100.0, quiet) > 0
    assert sim.SCORERS["rui"](long_o, 100.0, sim.Ctx(air=True)) > sim.SCORERS["rui"](
        long_o, 100.0, quiet
    )
    # Ines and Nuno refuse long trips (Nuno from 4 km)
    assert sim.SCORERS["ines"](long_o, 100.0, quiet) == 0 < sim.SCORERS["ines"](o, 100.0, quiet)
    four_five = make_order(3, 100.0, km=4.5)
    assert sim.SCORERS["ines"](four_five, 100.0, quiet) > 0
    assert sim.SCORERS["nuno"](four_five, 100.0, quiet) == 0 < sim.SCORERS["nuno"](o, 100.0, quiet)
    assert sim.SCORERS["nuno"](o, 50.0, quiet) > sim.SCORERS["nuno"](o, 500.0, quiet)
    # Tiago hunts near the player, except on easy
    assert sim.SCORERS["tiago"](o, 100.0, sim.Ctx(pdist=sim.HUNT_M + 1)) == 0
    assert sim.SCORERS["tiago"](o, 100.0, sim.Ctx(pdist=10.0)) == pytest.approx(
        2 * sim.SCORERS["ze"](o, 100.0, quiet)
    )
    assert sim.SCORERS["tiago"](o, 100.0, sim.Ctx(pdist=1e9, easy=True)) > 0
    # Lurdes: a running wave pulls her to wave pins
    wave = sim.Ctx(live=True, surge=True)
    away = sim.Ctx(live=True)
    assert sim.SCORERS["lurdes"](o, 100.0, wave) > 3 * sim.SCORERS["lurdes"](o, 100.0, quiet)
    assert sim.SCORERS["lurdes"](o, sim.STAND_ETA_S + 1, away) == 0
    assert sim.SCORERS["lurdes"](o, 100.0, quiet) == pytest.approx(
        sim.SCORERS["ze"](o, 100.0, quiet)
    )


def test_scan_skips_a_zero_score() -> None:
    far = make_order(0, 900.0, km=9.0, x0=9110.0, y0=12443.0)
    g = sim.new_game(make_shift([far]), "normal", sim.Settings())
    nuno = next(rv for rv in g.rivals if rv.id == "nuno")
    nuno.x, nuno.y, nuno.free_at = far.x0, far.y0, 0.0
    assert (
        sim.scan(g, nuno, 800.0) is None
    )  # Nuno refuses 9 km trips even when nothing else is there


def test_note_pickup_measures_the_tactic() -> None:
    o = make_order(0, 100.0, km=3.0, c=1, x0=3300.0, y0=1300.0)
    g = sim.new_game(make_shift([o]), "normal", sim.Settings())
    rv = g.rivals[1]
    rv.c_pd, rv.c_react, rv.c_dist = 100.0, 12.0, 2500.0
    sim.note_pickup(g, rv, o)
    t = rv.tac
    assert (t["rides"], t["km"], t["air"], t["stand"], t["near"], t["surge"]) == (
        1,
        3.0,
        1,
        1,
        1,
        0,
    )
    assert (t["react"], t["dist"], t["fare"]) == (12.0, 2.5, 4.0)


def test_tactic_table_has_a_line_per_rival() -> None:
    orders = [make_order(i, 400.0 + 200.0 * i, x0=9110.0 + 50 * i) for i in range(20)]
    res = sim.play_shift(make_shift(orders), "normal", sim.Settings())
    assert (
        len(res.tactics) == 7
        and sum(res.tactics[0].get(m, 0) for m in ("idle", "cruise", "pickup", "ride", "break"))
        == sim.BOT_TICKS
    )
    lines = sim.tactic_table([res])
    assert lines[0] == sim.TACTIC_HEAD and [ln.split()[0] for ln in lines[1:]] == list(
        sim.RIVAL_IDS
    )


def test_combo_window_is_measured_from_the_pickup() -> None:
    # a chain of orders 250 s apart at one spot: a window of 300 s keeps the combo, 60 s breaks it
    orders = [make_order(i, 400.0 + 250.0 * i) for i in range(12)]
    sh = make_shift(orders)
    chained = sim.play_shift(sh, "easy", sim.Settings(delay=0.0, combo_window=300.0))
    broken = sim.play_shift(sh, "easy", sim.Settings(delay=0.0, combo_window=1.0))
    assert sum(broken.combo[1:]) == 0 < sum(chained.combo[1:])
    assert sum(chained.combo) == chained.rides and sum(broken.combo) == broken.rides
    assert sim.COMBO_WINDOW_S == 300.0


def test_idle_bot_drives_to_a_hotspot_and_stays() -> None:
    g = sim.new_game(make_shift([make_order(0, 7000.0)]), "easy", sim.Settings())
    sim.bot_tick(g)  # nothing visible yet
    assert g.mode == "cruise" and (g.lx1, g.ly1) in {(h.x, h.y) for h in g.hot}
    g.x, g.y, g.mode = g.lx1, g.ly1, "idle"
    sim.bot_tick(g)
    assert g.mode == "idle"


def test_grid_up_and_leg_pos_and_place() -> None:
    rv = sim.Rival("ze", 1)
    rv.phase = 2.0
    assert sim.grid_up(rv, 6.0) == 7.0
    assert sim.grid_up(rv, 7.0) == 7.0
    rv.x = 0.0
    sim.start_leg(rv, 10.0, 100.0, 0.0, 20.0)
    assert sim.leg_pos(rv, 20.0) == 0.5 and rv.x == 50.0
    rv.mode = "cruise"
    sim.place(rv, 40.0)
    assert rv.mode == "idle" and rv.idle_since == 30.0 and rv.x == 100.0


def test_claim_kind_and_blocks() -> None:
    sh = make_shift([make_order(0, 500.0)])
    g = sim.new_game(sh, "normal", sim.Settings())
    o = sh.orders[0]
    assert sim.claim_kind(g, o, 100.0, 0.0) == 1
    g.claim[0] = sim.Claim("ze", 200.0)
    assert sim.claim_kind(g, o, 150.0, 0.0) == 2
    assert sim.claim_kind(g, o, 250.0, 0.0) == 0
    assert sim.claim_blocks(g, o, 250.0) and not sim.claim_blocks(g, o, 150.0)
    g.claim[0].boarded = True
    assert sim.claim_kind(g, o, 100.0, 0.0) == 0 and sim.claim_blocks(g, o, 1.0)
    g.claim[0] = sim.Claim("player", 300.0)
    g.cur, g.mode = o, "pickup"
    assert sim.claim_kind(g, o, 250.0, 0.0) == 3 and sim.claim_kind(g, o, 350.0, 0.0) == 0


def test_easy_shields_the_player() -> None:
    sh = make_shift([make_order(0, 500.0)])
    g = sim.new_game(sh, "easy", sim.Settings())
    g.claim[0] = sim.Claim("ze", 100.0)
    assert not sim.claim_blocks(g, sh.orders[0], 400.0)
    g.claim[0] = sim.Claim("player", 300.0)
    g.cur, g.mode = sh.orders[0], "pickup"
    assert sim.claim_kind(g, sh.orders[0], 100.0, 0.0) == 0


def test_ride_pos_interpolates_and_clamps() -> None:
    o = make_order(0, 0.0)
    assert sim.ride_pos(o, 0.0) == (o.x0, o.y0)
    assert sim.ride_pos(o, 7.5)[0] == pytest.approx(o.x0 + 250.0)
    assert sim.ride_pos(o, 999.0)[0] == pytest.approx(o.x1)


def test_eta_visible_and_feasibility() -> None:
    o = make_order(0, 600.0, x0=9110.0 + 1000.0, c=2)
    g = sim.new_game(make_shift([o]), "normal", sim.Settings())
    assert sim.eta_from(g, g.x, g.y, 0.0, o) == pytest.approx(1.0 / 30 * 3600 + 30)
    assert not sim.visible(g, o)  # lead 420: the pin appears at t = 180
    g.t = 200.0
    assert sim.visible(g, o)
    assert sim.feasibility(g, o, False) == sim.OK
    g.t = 590.0
    assert sim.feasibility(g, o, False) == sim.LATE
    g.taken.add(0)
    assert sim.feasibility(g, o, False) == sim.GONE


def test_start_pickup_ride_and_tip() -> None:
    o = make_order(0, 600.0)
    g = sim.new_game(make_shift([o]), "easy", sim.Settings())
    g.t = 100.0
    assert sim.start_pickup(g, o) and g.mode == "pickup" and g.claim[0].by == "player"
    for _ in range(200):
        sim.step(g, 7.2)
    assert g.rides == 1
    assert g.tot == pytest.approx(4.0 + sim.tip_for(4.0, "regular", 1) * 0 + g.tips)
    assert g.tips == 0.2 and g.mode == "idle"


def test_book_next_and_cruise_to() -> None:
    a, b = make_order(0, 300.0), make_order(1, 900.0)
    g = sim.new_game(make_shift([a, b]), "easy", sim.Settings())
    g.t = 100.0
    assert not sim.book_next(g, b)
    assert sim.start_pickup(g, a)
    g.t = g.lt1
    sim.process_due(g)
    assert g.mode == "ride" and sim.book_next(g, b) and g.nxt is b
    g2 = sim.new_game(make_shift([a]), "easy", sim.Settings())
    assert sim.cruise_to(g2, 20000.0, -5.0) and (g2.lx1, g2.ly1) == (sim.MAP_W_M, 0.0)
    assert not sim.cruise_to(g2, g2.x, g2.y) or g2.mode == "idle"


def test_step_ends_the_shift_exactly() -> None:
    g = sim.new_game(make_shift([make_order(0, 300.0)]), "normal", sim.Settings())
    sim.step(g, 100000.0)
    assert g.over and g.t == sim.SHIFT_S
    sim.step(g, 10.0)
    assert g.t == sim.SHIFT_S


def test_rivals_drive_and_are_deterministic() -> None:
    orders = [make_order(i, 200.0 + 150.0 * i, x0=9000.0 + 100 * (i % 5)) for i in range(40)]
    sh = make_shift(orders)
    r1 = sim.play_shift(sh, "hard", sim.Settings())
    r2 = sim.play_shift(sh, "hard", sim.Settings())
    assert r1 == r2
    assert sum(r1.rival_rides) > 0 and len(r1.rival_eur) == 7
    assert 1 <= r1.race_place <= 8


def test_bot_earns_on_a_dense_tiny_shift() -> None:
    orders = [make_order(i, 400.0 + 200.0 * i, x0=9110.0 + 50 * i) for i in range(30)]
    res = sim.play_shift(make_shift(orders), "easy", sim.Settings(delay=0.0))
    assert res.earned > 0 and res.rides >= 1 and res.lost_to_rivals == 0


def test_longer_delay_never_helps_a_single_order() -> None:
    sh = make_shift([make_order(0, 300.0)])
    fast = sim.play_shift(sh, "easy", sim.Settings(delay=0.0))
    slow = sim.play_shift(sh, "easy", sim.Settings(delay=10000.0))
    assert fast.earned > slow.earned == 0.0


def test_summarise_means_and_shares() -> None:
    def res(e: float, m: int) -> sim.ShiftResult:
        return sim.ShiftResult("x", e, m, 1, 2, 0, (1.0,) * 7, (1,) * 7, 3)

    sm = sim.summarise([res(10.0, 0), res(20.0, 3)])
    assert sm.n == 2 and sm.bot_eur == 15.0 and sm.bronze == 0.5 and sm.gold == 0.5
    assert sm.legend == 0.0 and sm.lost == 2.0 and sm.place == 3.0
    assert "gold+  50%" in sim.format_summary("normal", sm)


def test_rel_diff() -> None:
    assert sim.rel_diff(11.0, 10.0) == pytest.approx(0.1)
    assert sim.rel_diff(0.0, 0.0) == 0.0
    assert math.isinf(sim.rel_diff(1.0, 0.0))


def test_parse_engine_test_reads_both_tables() -> None:
    text = "\n".join([
        "shift          bot €  median",
        "mon-am         34.18    9.63   16.78   30.10  4    1/293      6    16",
        "  easy   bot avg €46.2 | medals>=bronze 100% (none 0)",
        "     ze €17.4 r2.9 | fatima €16.9 r3.0",
        "  normal bot avg €41.8 | medals>=bronze 100%",
        "     ze €25.1 r4.2 | nuno €19.5 r3.5",
    ])  # fmt: skip
    ref = sim.parse_engine_test(text)
    assert ref.shift_eur == {"mon-am": 34.18}
    assert ref.bot_eur == {"easy": 46.2, "normal": 41.8}
    assert ref.rival_eur["easy"] == {"ze": 17.4, "fatima": 16.9}
    assert ref.rival_eur["normal"]["nuno"] == 19.5


def test_play_many_in_process_matches_play_shift(tmp_path: Path) -> None:
    import json

    raw = {
        "unit_m": 5, "shifts": [{
            "id": "mon-am", "start_hour": 8, "detour": 1.4, "speed_by_hour": [20.0] * 24,
            "orders": [[60 * k, 1800, 2400, 1900, 2400, [20, 0], 30, 1.0, 4.0, 0, 0, 0]
                       for k in range(1, 40)],
            "hot": [{"x": 1800, "y": 2400, "w": 1.0}], "surges": [],
            "ranking": [20.0, 10.0], "median": 5.0, "top10": 9.0,
        }],
    }  # fmt: skip
    path = tmp_path / "d.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    shifts = sim.load_shifts(path)
    st = sim.Settings()
    got = sim.play_many([(0, "easy", st), (0, "hard", st)], path, 1)
    assert got[0] == sim.play_shift(shifts[0], "easy", st)
    by = sim.run_difficulties(path, st, ("easy", "normal"), 1, 1)
    assert set(by) == {"easy", "normal"} and len(by["easy"]) == 1
