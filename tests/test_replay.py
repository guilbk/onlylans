import io
import json

import pytest
from PIL import Image, ImageDraw

from pipeline import geo, replay

UNIT = 5.0
I_T = replay.I_T


def order(t, x0, y0, steps, fare=10.0, call=0):
    """A section 4 order array; ``steps`` are (dx, dy) deltas in map units."""
    flat = [v for s in steps for v in s]
    x1 = x0 + sum(s[0] for s in steps)
    y1 = y0 + sum(s[1] for s in steps)
    return [t, x0, y0, x1, y1, flat, 15 * len(steps), 3.0, fare, call, 0, 0]


A = order(600, 100, 100, [(10, 0), (10, 0), (0, 10), (0, 10)], fare=7.5, call=0)  # 60 s ride
B = order(2000, 150, 200, [(20, 0)] * 8, fare=12.25, call=1)  # 120 s ride
SHIFT = {
    "id": "t-am",
    "start_local": "2014-05-12 08:00",
    "orders": [A, B],
    "ghost": {"taxi": 0, "total": 19.75, "orders": [0, 1]},
}
NO_STREETS = replay.Backdrop(None, [])


def scene():
    """The scene of the synthetic shift."""
    sc = replay.make_scene(SHIFT, UNIT)
    assert sc is not None
    return sc


# clock and money


@pytest.mark.parametrize(
    ("start", "t", "want"),
    [
        ("2014-05-12 08:00", 0, "08:00"),
        ("2014-05-12 08:00", 42 * 60, "08:42"),
        ("2014-05-12 08:00", 42 * 60 + 59, "08:42"),
        ("2014-05-16 22:00", 7200, "00:00"),
        ("2014-05-16 22:00", 3600 + 90, "23:01"),
        ("2014-05-18 00:00", 7199, "01:59"),
    ],
)
def test_clock_text(start, t, want):
    assert replay.clock_text(start, t) == want


def test_money_is_a_step_function_at_pickup():
    orders = [A, B]
    assert replay.money_at(orders, 0) == 0
    assert replay.money_at(orders, 599.9) == 0
    assert replay.money_at(orders, 600) == 7.5
    assert replay.money_at(orders, 1999) == 7.5
    assert replay.money_at(orders, 2000) == 19.75
    assert replay.money_at(orders, 99999) == 19.75


def test_money_timeline_and_text():
    assert replay.money_timeline([B, A]) == [(600.0, 7.5), (2000.0, 19.75)]
    assert replay.money_text(7.5) == "€7.50"
    assert replay.money_text(0) == "€0.00"


def test_money_timeline_has_no_float_noise():
    orders = [order(t, 0, 0, [(1, 0)], fare=0.1) for t in (0, 10, 20)]
    assert [m for _, m in replay.money_timeline(orders)] == [0.1, 0.2, 0.3]


def test_replay_end_covers_last_drop_off():
    assert replay.replay_end_s([A, B]) == replay.SHIFT_S
    late = order(7195, 0, 0, [(1, 0)] * 48)  # 720 s ride, like mon-am
    assert replay.replay_end_s([A, late]) == 7195 + 720
    assert replay.replay_end_s([]) == replay.SHIFT_S


def test_frame_times():
    ts = replay.frame_times(5, 100.0)
    assert ts == [0.0, 25.0, 50.0, 75.0, 100.0]
    assert len(replay.frame_times(120, 7200.0)) == 120


# decoding and interpolation


def test_ride_points_decode_to_metres_and_end_at_drop_off():
    pts = geo.decode_path(A, UNIT)
    assert pts[0] == (500.0, 500.0)
    assert len(pts) == 5
    assert pts[-1] == (A[3] * UNIT, A[4] * UNIT)
    assert pts[2] == (600.0, 500.0)


def test_timeline_legs_in_order_without_overlap():
    legs = replay.build_timeline([B, A], UNIT, 7200.0)
    kinds = [leg.kind for leg in legs]
    assert kinds == ["wait", "ride", "wait", "glide", "ride", "wait"]
    for a, b in zip(legs, legs[1:], strict=False):
        assert a.t1 == b.t0
    assert legs[0].t0 == 0
    assert legs[-1].t1 == 7200


def test_glide_is_the_last_deadhead_seconds_before_pickup():
    legs = replay.build_timeline([A, B], UNIT, 7200.0)
    glide = next(leg for leg in legs if leg.kind == "glide")
    assert (glide.t0, glide.t1) == (B[I_T] - replay.DEADHEAD_S, B[I_T])
    assert glide.pts == ((A[3] * UNIT, A[4] * UNIT), (B[1] * UNIT, B[2] * UNIT))


def test_short_gap_has_no_wait_leg():
    near = order(A[0] + 60 + 100, 100, 100, [(5, 0)])  # 100 s after the drop-off
    kinds = [leg.kind for leg in replay.build_timeline([A, near], UNIT, 1000.0)]
    assert kinds == ["wait", "ride", "glide", "ride", "wait"]


def test_position_interpolates_along_points_at_15_s_steps():
    legs = replay.build_timeline([A, B], UNIT, 7200.0)
    t0 = A[0]
    assert replay.position_at(legs, t0) == (500.0, 500.0)
    assert replay.position_at(legs, t0 + 15) == (550.0, 500.0)
    assert replay.position_at(legs, t0 + 7.5) == (525.0, 500.0)
    assert replay.position_at(legs, t0 + 30) == (600.0, 500.0)
    assert replay.position_at(legs, t0 + 52.5) == (600.0, 575.0)
    assert replay.position_at(legs, t0 + 60) == (A[3] * UNIT, A[4] * UNIT)


def test_position_waits_before_first_pickup_and_after_last_drop_off():
    legs = replay.build_timeline([A, B], UNIT, 7200.0)
    assert replay.position_at(legs, 0) == (500.0, 500.0)
    assert replay.position_at(legs, 599) == (500.0, 500.0)
    end = (B[3] * UNIT, B[4] * UNIT)
    assert replay.position_at(legs, 7200) == end
    assert replay.position_at(legs, 99999) == end


def test_position_glides_in_a_straight_line():
    legs = replay.build_timeline([A, B], UNIT, 7200.0)
    glide = next(leg for leg in legs if leg.kind == "glide")
    (x0, y0), (x1, y1) = glide.pts
    mid = replay.position_at(legs, (glide.t0 + glide.t1) / 2)
    assert mid == pytest.approx(((x0 + x1) / 2, (y0 + y1) / 2))


def test_leg_points_until_cuts_at_the_current_position():
    ride = replay.build_timeline([A], UNIT, 1000.0)[1]
    assert replay.leg_points_until(ride, ride.t0) == []
    cut = replay.leg_points_until(ride, ride.t0 + 22.5)
    assert cut == [(500.0, 500.0), (550.0, 500.0), (575.0, 500.0)]
    assert replay.leg_points_until(ride, ride.t1 + 5) == list(ride.pts)


# map frame -> pixels


def test_fit_view_is_square_centred_and_has_a_margin():
    view = replay.fit_view([(1000.0, 2000.0), (3000.0, 2500.0)], pad=0.1, min_span=100.0)
    assert view.span == pytest.approx(2000.0 * 1.2)
    assert view.x0 + view.span / 2 == pytest.approx(2000.0)
    assert view.y0 + view.span / 2 == pytest.approx(2250.0)


def test_fit_view_has_a_minimum_span():
    assert replay.fit_view([(10.0, 10.0)]).span == replay.MIN_SPAN_M


def test_to_px_corners_and_centre():
    view = replay.View(1000.0, 2000.0, 4000.0)
    assert replay.to_px(view, 400, 1000.0, 2000.0) == (0.0, 0.0)
    assert replay.to_px(view, 400, 5000.0, 6000.0) == (400.0, 400.0)
    assert replay.to_px(view, 400, 3000.0, 4000.0) == (200.0, 200.0)
    # y grows south: a point further south is lower in the picture
    assert replay.to_px(view, 400, 1000.0, 3000.0)[1] == 100.0


def test_mix():
    assert replay.mix((0, 0, 0), (100, 200, 50), 0.5) == (50, 100, 25)
    assert replay.mix((10, 10, 10), (90, 90, 90), 0.0) == (10, 10, 10)


# size budget


def test_fits_budget():
    assert replay.fits_budget(1_500_000)
    assert not replay.fits_budget(1_500_001)
    assert replay.fits_budget(10, budget=10)


def test_next_size_shrinks_to_even_numbers_until_the_floor():
    assert replay.next_size(480) == 408
    assert replay.next_size(300) == 254
    assert replay.next_size(250) is None
    assert replay.next_size(241, min_size=100) == 204
    assert replay.next_size(4, min_size=1) == 2


def test_build_within_budget_steps_down_until_it_fits():
    calls = []

    def render(size):
        calls.append(size)
        return bytes(size * 10)

    data, used = replay.build_within_budget(render, 480, budget=3000, min_size=240)
    assert calls == [480, 408, 346, 294]
    assert used == 294
    assert len(data) == 2940


def test_build_within_budget_returns_smallest_when_nothing_fits():
    data, used = replay.build_within_budget(lambda s: bytes(10**6), 480, budget=10, min_size=300)
    assert used < 480
    assert replay.next_size(used, 300) is None
    assert len(data) == 10**6


# text glyphs


def test_all_glyph_rows_have_equal_width_and_seven_rows():
    for ch, rows in replay.GLYPHS.items():
        assert len(rows) == 7, ch
        assert len({len(r) for r in rows}) == 1, ch


def test_text_width_counts_gaps():
    assert replay.text_width("08", 2) == (5 + 1 + 5) * 2
    assert replay.text_width("1:2", 1) == 5 + 1 + 1 + 1 + 5


def test_draw_text_lights_pixels_inside_the_box():
    img = Image.new("RGB", (40, 20))
    replay.draw_text(ImageDraw.Draw(img), (2, 2), "1", 2, (255, 0, 0))
    box = img.getbbox()
    assert box is not None
    assert box[0] >= 2 and box[1] >= 2 and box[2] <= 2 + 5 * 2 and box[3] <= 2 + 7 * 2


# data helpers


def test_find_shift_and_ghost_orders():
    data = {"shifts": [SHIFT]}
    assert replay.find_shift(data, "t-am") is SHIFT
    assert replay.find_shift(data, "nope") is None
    assert replay.ghost_orders(SHIFT) == [A, B]


def test_make_scene_without_ghost_orders_is_none():
    empty = {**SHIFT, "ghost": {"taxi": 0, "total": 0, "orders": []}}
    assert replay.make_scene(empty, UNIT) is None


def test_load_roads_decodes_nodes_and_interior_points(tmp_path):
    path = tmp_path / "roads.json"
    path.write_text(
        json.dumps({"v": 1, "unit_m": 2.5, "nodes": [0, 0, 10, 0], "edges": [[0, 1, [4, 2]]]})
    )
    assert replay.load_roads(path) == [[(0.0, 0.0), (10.0, 5.0), (25.0, 0.0)]]


def test_load_backdrop_prefers_streets_then_roads_then_nothing(tmp_path):
    streets = tmp_path / "streets.png"
    roads = tmp_path / "roads.json"
    assert replay.load_backdrop(streets, roads) == NO_STREETS
    roads.write_text(
        json.dumps({"v": 1, "unit_m": 1, "nodes": [0, 0, 1, 1], "edges": [[0, 1, []]]})
    )
    assert replay.load_backdrop(streets, roads).roads == [[(0.0, 0.0), (1.0, 1.0)]]
    Image.new("RGBA", (30, 38), (90, 169, 255, 77)).save(streets)
    layer = replay.load_backdrop(streets, roads)
    assert layer.alpha is not None
    assert layer.alpha.getpixel((3, 3)) == 77
    assert layer.roads == []


# rendering


def test_backdrop_glow_is_brighter_where_alpha_is_higher():
    alpha = Image.new("L", (30, 38), 0)
    alpha.paste(77, (0, 0, 15, 38))  # west half has streets
    view = replay.View(0.0, 0.0, 15000.0)
    img = replay.draw_backdrop(view, 60, replay.Backdrop(alpha, []))
    assert img.getpixel((5, 5)) != replay.BACKGROUND
    assert img.getpixel((55, 5)) == replay.BACKGROUND
    assert sum(img.getpixel((5, 5))) > sum(replay.BACKGROUND)


def test_backdrop_draws_fallback_roads():
    view = replay.View(0.0, 0.0, 100.0)
    roads = replay.Backdrop(None, [[(0.0, 50.0), (100.0, 50.0)]])
    img = replay.draw_backdrop(view, 100, roads)
    assert img.getpixel((50, 50)) != replay.BACKGROUND
    assert img.getpixel((50, 5)) == replay.BACKGROUND


def test_frame_has_the_requested_size_and_changes_over_time():
    sc = scene()
    first = replay.render_frame(sc, NO_STREETS, 96, 0)
    later = replay.render_frame(sc, NO_STREETS, 96, 2100)
    assert first.size == later.size == (96, 96)
    assert first.tobytes() != later.tobytes()


def test_frames_count_and_all_differ():
    frames = replay.render_frames(scene(), NO_STREETS, 96, 7)
    assert len(frames) == 7
    assert len({f.tobytes() for f in frames}) == 7


def test_gif_has_every_frame_loops_and_is_deterministic():
    sc = scene()
    first = replay.encode_gif(replay.render_frames(sc, NO_STREETS, 96, 6))
    second = replay.encode_gif(replay.render_frames(sc, NO_STREETS, 96, 6))
    assert first == second
    gif = Image.open(io.BytesIO(first))
    assert gif.format == "GIF"
    assert gif.n_frames == 6
    assert gif.size == (96, 96)
    assert gif.info["loop"] == 0


def test_render_shift_is_deterministic_and_within_budget():
    sc = scene()
    gif, png, used = replay.render_shift(sc, NO_STREETS, 96, 5)
    again = replay.render_shift(sc, NO_STREETS, 96, 5)
    assert (gif, png, used) == again
    assert used == 96
    assert replay.fits_budget(len(gif))
    still = Image.open(io.BytesIO(png))
    assert still.format == "PNG"
    assert still.size == (96 * replay.STILL_SCALE,) * 2


def test_main_writes_both_files_and_reports_errors(tmp_path, capsys):
    data = tmp_path / "game_data.json"
    data.write_text(json.dumps({"unit_m": UNIT, "shifts": [SHIFT]}))
    out = tmp_path / "img"
    args = ["--data", str(data), "--streets", str(tmp_path / "none.png"), "--out", str(out)]
    assert replay.main([*args, "--shift", "t-am", "--frames", "4", "--size", "240"]) == 0
    assert (out / "replay-t-am.gif").stat().st_size > 0
    assert (out / "replay-t-am.png").stat().st_size > 0
    assert "t-am" in capsys.readouterr().out
    assert replay.main([*args, "--shift", "zzz"]) == 1
    assert replay.main([*args, "--frames", "1"]) == 1
    assert replay.main(["--data", str(tmp_path / "missing.json")]) == 1
