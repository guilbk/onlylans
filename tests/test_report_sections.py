"""Tests of the report's Markdown sections and chart pieces, one function at a time."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from pipeline import report

TOTALS = {"trips": 4, "taxis": 2, "km": 20.0, "cents": 1000}
ROWS = [
    {"id": "mon-am", "name": "Ранок", "orders": 3, "drivers": 9, "ghost": 30.0, "median": 10.0,
     "top10": 25.0, "difficulty": 3},
    {"id": "mon-pm", "name": "Вечір", "orders": 2, "drivers": 7, "ghost": 12.0, "median": 6.0,
     "top10": 11.0, "difficulty": 2},
]  # fmt: skip


def blank(width: int = 200, height: int = 100) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """A background-coloured image and its drawing context."""
    img = Image.new("RGB", (width, height), report.BG)
    return img, ImageDraw.Draw(img)


def drawn_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of everything that differs from the background colour."""
    return ImageChops.difference(img, Image.new("RGB", img.size, report.BG)).getbbox()


def test_md_week_lists_the_numbers_with_game_formatting() -> None:
    text = "\n".join(report.md_week(TOTALS, 40, 5))
    assert text.startswith("## Тиждень у цифрах")
    assert "| Різних таксистів | 2 |" in text
    assert "| Пройдено, км | 20 |" in text
    assert "| Виторг за тарифом гри | €10,00 |" in text
    assert "| Середній чек | €2,50 |" in text
    assert "| Рядків у тижневих даних | 40 |" in text


def test_md_week_has_no_division_by_zero_for_an_empty_week() -> None:
    empty = {"trips": 0, "taxis": 0, "km": 0.0, "cents": 0}
    text = "\n".join(report.md_week(empty, 0, 0))
    assert "| Середній чек | €0,00 |" in text


def test_md_ghost_lead_has_numbers_or_a_note() -> None:
    lead = report.ghost_lead(ROWS)
    text = "\n".join(report.md_ghost_lead(lead))
    assert (
        "**2,50**" in text
        and "×2,00" in text
        and "×3,00" in text
        and "`mon-pm`" in text
        and "`mon-am`" in text
    )
    assert report.md_ghost_lead(report.ghost_lead([])) == [
        "Привид проти медіани: немає даних.",
        "",
    ]


def test_md_shifts_has_one_row_per_shift_and_the_chart_link() -> None:
    lines = report.md_shifts(ROWS, report.ghost_lead(ROWS))
    rows = [x for x in lines if x.startswith("| `")]
    assert len(rows) == 2 and "€30,00" in rows[0]
    assert any(x.startswith("![") and "img/shifts.png" in x for x in lines)


def test_md_demand_lists_the_five_busiest_hours() -> None:
    counts = [0] * 24
    for hour, n in ((8, 50), (9, 40), (17, 30), (18, 30), (22, 5), (3, 1)):
        counts[hour] = n
    lines = report.md_demand(counts)
    rows = [x for x in lines if x.startswith("| ") and x[2].isdigit()]
    assert [r.split(" | ")[0] for r in rows] == [
        "| 08:00",
        "| 09:00",
        "| 17:00",
        "| 18:00",
        "| 22:00",
    ]
    assert "img/hours.png" in "\n".join(lines)
    assert report.md_demand([0] * 24)  # no division by zero


def test_md_calls_names_each_type() -> None:
    mix = [
        {"trips": 2, "share": 50.0, "km": 4.5, "eur": 6.0},
        {"trips": 1, "share": 25.0, "km": 3.0, "eur": 5.0},
        {"trips": 1, "share": 25.0, "km": 2.0, "eur": 4.0},
    ]
    text = "\n".join(report.md_calls(mix))
    for title in report.CALL_TITLES:
        assert title in text
    assert "| A: виклик диспетчера | 2 | 50,0 | 4,50 | €6,00 |" in text


def test_md_stands_and_md_hotspots() -> None:
    stands = [report.StandRow(7, 1234, 12.5, "Aliados")]
    text = "\n".join(report.md_stands(stands))
    assert "| 7 | 1 234 | 12,5 | Aliados |" in text
    hot = "\n".join(report.md_hotspots([report.HotRow("Foz", 4, 99)]))
    assert "| Foz | 4 | 99 |" in hot and "img/heatmap.png" in hot


def test_md_filter_shares_and_the_dropped_total() -> None:
    table = report.filter_table(200, {report.RULE_STEP: 20})
    text = "\n".join(report.md_filter(200, table, 150))
    assert "відсіяно **50**" in text and "(25,0 %)" in text
    assert report.RULE_TEXT[report.RULE_STEP] in text
    assert "(0,0 %)" in "\n".join(report.md_filter(0, report.filter_table(0, {}), 0))


def test_font_and_text_width() -> None:
    _, d = blank()
    f = report.font(report.FONT_SMALL_PX)
    assert report.text_w(d, "", f) == 0
    assert report.text_w(d, "abcd", f) > report.text_w(d, "ab", f) > 0


def test_load_game_data_reads_json(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"shifts": [1]}), encoding="utf-8")
    assert report.load_game_data(path) == {"shifts": [1]}


def test_build_parser_defaults_and_overrides() -> None:
    args = report.build_parser().parse_args([])
    assert (args.week, args.data, args.out) == (
        report.DEFAULT_WEEK,
        report.DEFAULT_DATA,
        report.DEFAULT_OUT,
    )
    args = report.build_parser().parse_args(["--out", "x"])
    assert args.out == Path("x")


def test_draw_hours_header_draws_only_in_the_top_strip() -> None:
    img, d = blank(report.IMG_W, report.HOURS_H)
    report.draw_hours_header(d, 42)
    box = drawn_box(img)
    assert box is not None and box[3] < report.HOURS_PLOT_TOP
    assert img.getpixel((report.IMG_W - report.MARGIN - 2, report.HOURS_PEAK_Y + 6)) != report.BG


def test_draw_hours_bars_marks_the_busiest_hour_in_amber() -> None:
    img, d = blank(report.IMG_W, report.HOURS_H)
    counts = [1] * 24
    counts[8] = 10
    report.draw_hours_bars(d, counts, 10)
    slot = (report.IMG_W - 2 * report.MARGIN) / 24
    bottom = report.HOURS_H - report.HOURS_PLOT_BOTTOM
    x = int(report.MARGIN + 8 * slot + slot / 2)
    assert img.getpixel((x, bottom - 5)) == report.AMBER
    other = int(report.MARGIN + 5 * slot + slot / 2)
    assert img.getpixel((other, bottom - 5)) == report.CYAN


def test_draw_shifts_legend_and_row() -> None:
    img, d = blank(report.IMG_W, 120)
    report.draw_shifts_legend(d)
    assert img.getpixel((report.MARGIN + 2, report.SHIFT_LEGEND_BOX_Y[0] + 3)) == report.GHOST
    img, d = blank(report.IMG_W, 120)
    left = report.MARGIN + report.SHIFT_LABEL_W
    report.draw_shift_row(d, ROWS[0], 10, left, 300.0, 30.0)
    assert img.getpixel((left + 100, 10 + 2)) == report.GHOST  # the ghost bar is the top one
    assert img.getpixel((left + 100, 10 + report.SHIFT_BAR_H + 2)) == report.MINT
    assert img.getpixel((left + 100, 10 + 2 * report.SHIFT_BAR_H + 2)) == report.MUTED
    assert img.getpixel((left + 301, 10 + 2)) != report.GHOST  # nothing beyond the span


def test_draw_landmarks_and_scale_bar() -> None:
    img, d = blank(report.IMG_W, 300)
    report.draw_scale_bar(d, 300, 0.04)
    y = 300 - report.MARGIN
    assert img.getpixel((report.MARGIN + 100, y)) == report.TEXT
    assert img.getpixel((report.MARGIN + 100, y - 20)) == report.BG
    img, d = blank(2000, 2000)
    report.draw_landmarks(d, 0.04)
    assert drawn_box(img) is not None


def test_heat_palette_has_256_ordered_endpoints() -> None:
    pal = report.heat_palette()
    assert len(pal) == report.PALETTE_LEVELS == 256
    assert pal[0] == report.HEAT_RAMP[0] and pal[-1] == report.HEAT_RAMP[-1]


def test_heat_levels_of_an_empty_grid_are_zero_and_the_peak_is_255() -> None:
    assert not report.heat_levels(np.zeros((5, 5))).any()
    grid = np.zeros((9, 9))
    grid[4, 4] = 50.0
    levels = report.heat_levels(grid)
    assert levels.dtype == np.uint8 and levels.max() == 255 and levels[4, 4] == 255


def test_chart_constants_keep_their_values() -> None:
    assert (report.HOURS_PER_DAY, report.CENTS_PER_EUR, report.TOP_HOURS) == (24, 100, 5)
    assert (report.M_PER_KM, report.PERCENT) == (1000.0, 100.0)
    assert report.SHIFT_SERIES == 3 and report.SCALE_BAR_M == 5000
    assert (report.LEVEL_MAX, report.RGB_CHANNELS) == (255, 3)
