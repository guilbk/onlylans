"""Direct tests of the replay's small geometry and drawing helpers."""

import pytest
from PIL import Image, ImageDraw

from pipeline import replay

SIDE = 120
BLACK = (0, 0, 0)


def leg(kind="ride", t0=0.0, t1=30.0, pts=((0.0, 0.0), (10.0, 0.0), (10.0, 20.0))):
    """A leg with two segments of 10 m and 20 m."""
    return replay.Leg(kind, t0, t1, tuple(pts))


def test_lerp_midpoint_and_ends():
    a, b = (0.0, 10.0), (10.0, 30.0)
    assert replay._lerp(a, b, 0.0) == a
    assert replay._lerp(a, b, 1.0) == b
    assert replay._lerp(a, b, 0.5) == (5.0, 20.0)


@pytest.mark.parametrize(
    ("t", "want"),
    [(0.0, (0, 0.0)), (7.5, (0, 0.5)), (15.0, (1, 0.0)), (22.5, (1, 0.5)), (99.0, (1, 1.0))],
)
def test_leg_index_finds_segment_and_fraction(t, want):
    assert replay._leg_index(leg(), t) == want


def test_leg_index_is_clamped_and_handles_degenerate_legs():
    assert replay._leg_index(leg(), -5.0) == (0, 0.0)
    assert replay._leg_index(leg(pts=((1.0, 1.0),)), 10.0) == (0, 0.0)
    assert replay._leg_index(leg(t0=5.0, t1=5.0), 5.0) == (0, 0.0)


def test_glyph_width_is_five_cells_except_the_dots():
    assert replay.glyph_width("0") == 5
    assert replay.glyph_width("€") == 5
    assert replay.glyph_width(":") == replay.glyph_width(".") == 1


def test_alpha_mask_maps_zero_to_zero_and_the_reference_to_the_peak():
    mask = replay.alpha_mask(Image.new("L", (1, 3)))
    assert mask.getpixel((0, 0)) == 0
    ramp = Image.new("L", (3, 1))
    ramp.putdata([0, replay.GLOW_ALPHA_REF, 255])
    got = [replay.alpha_mask(ramp).getpixel((x, 0)) for x in range(3)]
    assert got[0] == 0
    assert got[1] == round(replay.GLOW_PEAK * 255)
    assert got[2] == 255  # clipped
    assert got == sorted(got)


def test_pin_and_flag_draw_above_their_anchor_only():
    for draw_fn in (replay._pin, replay._flag):
        img = Image.new("RGB", (SIDE, SIDE), BLACK)
        draw_fn(ImageDraw.Draw(img), (60.0, 100.0), 1.0, (255, 0, 0))
        box = img.getbbox()
        assert box is not None
        assert box[3] <= 101  # nothing below the anchor


def test_scene_px_uses_the_view():
    view = replay.View(100.0, 200.0, 50.0)
    sc = replay.Scene([leg()], [], 5.0, "2014-05-12 08:00", 30.0, view)
    assert replay.scene_px(sc, 100, (100.0, 200.0)) == (0.0, 0.0)
    assert replay.scene_px(sc, 100, (125.0, 225.0)) == (50.0, 50.0)
    assert replay.scene_px(sc, 100, (150.0, 250.0)) == (100.0, 100.0)


def small_scene():
    """A scene with one ride of 30 s over a 100 m window."""
    order = [60, 0, 0, 4, 0, [2, 0, 2, 0], 30, 1.0, 5.0, 1, 0, 0]
    legs = [leg("ride", 60.0, 90.0, ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)))]
    return replay.Scene(
        legs, [order], 5.0, "2014-05-12 08:00", 120.0, replay.View(-20.0, -50.0, 100.0)
    )


def test_draw_trails_draws_only_after_the_ride_starts():
    sc = small_scene()
    img = Image.new("RGB", (SIDE, SIDE), BLACK)
    replay.draw_trails(ImageDraw.Draw(img), sc, SIDE, 30.0)
    assert img.getbbox() is None
    replay.draw_trails(ImageDraw.Draw(img), sc, SIDE, 90.0)
    assert img.getbbox() is not None


def test_draw_trails_draws_a_glide_as_a_thin_line():
    sc = small_scene()
    glide = replay.Leg("glide", 0.0, 60.0, ((-10.0, 0.0), (0.0, 0.0)))
    sc = replay.Scene([glide], sc.orders, 5.0, sc.start_local, sc.end_s, sc.view)
    img = Image.new("RGB", (SIDE, SIDE), BLACK)
    replay.draw_trails(ImageDraw.Draw(img), sc, SIDE, 60.0)
    assert img.getbbox() is not None


def test_draw_orders_dims_a_taken_pin_and_lights_a_waiting_one():
    sc = small_scene()
    before = Image.new("RGB", (SIDE, SIDE), BLACK)
    after = Image.new("RGB", (SIDE, SIDE), BLACK)
    replay.draw_orders(ImageDraw.Draw(before), sc, SIDE, 0.0)
    replay.draw_orders(ImageDraw.Draw(after), sc, SIDE, 100.0)
    assert before.getbbox() is not None and after.getbbox() is not None
    assert before.tobytes() != after.tobytes()


def test_draw_ghost_is_centred_on_the_position():
    sc = small_scene()
    img = Image.new("RGB", (SIDE, SIDE), BLACK)
    replay.draw_ghost(ImageDraw.Draw(img), sc, SIDE, 0.0)
    left, top, right, bottom = img.getbbox()
    cx, cy = replay.scene_px(sc, SIDE, (0.0, 0.0))
    assert abs((left + right) / 2 - cx) <= 1 and abs((top + bottom) / 2 - cy) <= 1


def test_draw_scene_does_not_change_its_base():
    sc = small_scene()
    base = Image.new("RGB", (SIDE, SIDE), replay.BACKGROUND)
    keep = base.tobytes()
    out = replay.draw_scene(sc, base, SIDE, 90.0)
    assert base.tobytes() == keep
    assert out.tobytes() != keep and out.size == (SIDE, SIDE)


def test_draw_hud_draws_clock_money_and_progress_bar():
    sc = small_scene()
    img = Image.new("RGB", (SIDE, SIDE), BLACK)
    replay.draw_hud(img, sc, 60.0)
    assert img.getpixel((SIDE // 4, SIDE - 1)) == replay.GHOST  # bar: half of the picture
    assert img.getpixel((SIDE - 1, SIDE - 1)) == BLACK
    top_rows = img.crop((0, 0, SIDE, SIDE // 2)).getbbox()
    assert top_rows is not None  # the clock and the money panels
    start = Image.new("RGB", (SIDE, SIDE), BLACK)
    replay.draw_hud(start, sc, 0.0)
    assert start.getpixel((0, SIDE - 1)) == BLACK  # no progress yet


def test_finish_frame_resizes_and_adds_the_hud():
    sc = small_scene()
    big = Image.new("RGB", (2 * SIDE, 2 * SIDE), replay.BACKGROUND)
    out = replay.finish_frame(sc, big, SIDE, 120.0)
    assert out.size == (SIDE, SIDE)
    assert out.getpixel((SIDE - 1, SIDE - 1)) == replay.GHOST  # full progress bar


def test_shared_palette_is_deterministic_and_covers_the_frames():
    frames = [Image.new("RGB", (8, 8), (i * 20, 0, 255 - i * 20)) for i in range(12)]
    a, b = replay.shared_palette(frames), replay.shared_palette(frames)
    assert a.mode == "P" and a.tobytes() == b.tobytes()
    assert a.getpalette() == b.getpalette()


def test_geometry_constants_keep_their_values():
    assert (replay.MINUTES_PER_HOUR, replay.HOURS_PER_DAY) == (60, 24)
    assert (replay.ALPHA_MAX, replay.ALPHA_LEVELS) == (255, 256)
    assert len(replay.GLYPHS["0"]) == replay.GLYPH_ROWS
