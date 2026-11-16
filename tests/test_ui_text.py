import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import ui_text as ut  # noqa: E402
from ui_text import UiString  # noqa: E402


def ui(text: str, glued: bool = False) -> UiString:
    return UiString("f.js", 7, text, glued)


def texts(source: str) -> list[str]:
    return [s.text for s in ut.extract_js(source, "f.js")]


def rules_of(findings: list[ut.Finding]) -> list[str]:
    return [f.rule for f in findings]


# --- lexer -----------------------------------------------------------------------------------


def test_unescape_js_handles_all_escape_kinds() -> None:
    assert ut.unescape_js(r"a\'b\nA\x41\u{1F600}\\") == "a'b\nAA\U0001f600\\"
    assert ut.unescape_js("a\\\nb") == "ab"


def test_tokenize_skips_comments_and_tracks_lines() -> None:
    toks = ut.tokenize_js("// 'no'\n/* 'no'\n */ x = 'yes';")
    strings = [t for t in toks if t.kind == "str"]
    assert [(t.text, t.line) for t in strings] == [("yes", 3)]


def test_tokenize_template_with_nested_interpolation() -> None:
    toks = ut.tokenize_js("a = `x ${f('in')} y ${z} w`;")
    chunks = [(t.kind, t.text, t.joined) for t in toks if t.kind in {"str", "tpl"}]
    assert chunks == [
        ("tpl", "x ", False),
        ("str", "in", False),
        ("tpl", " y ", True),
        ("tpl", " w", True),
    ]


def test_tokenize_regex_vs_division() -> None:
    toks = ut.tokenize_js("a = s.replace(/^район\\s+'/g, ''); b = c / d / 'e';")
    kinds = [t.kind for t in toks]
    assert kinds.count("regex") == 1
    assert [t.text for t in toks if t.kind == "str"] == ["", "e"]


def test_tokenize_regex_with_slash_in_class() -> None:
    toks = ut.tokenize_js("x = /[/'\"]+/.test(y); z = 'k';")
    assert [t.text for t in toks if t.kind == "str"] == ["k"]


def test_tokenize_survives_a_malformed_string() -> None:
    assert ut.tokenize_js("x = 'oops\ny = 'ok';")  # no exception, no hang


def test_call_contexts_tracks_callee_and_argument() -> None:
    toks = ut.tokenize_js("say(a, f(1), 'x'); el('d', 'c', 'T');")
    ctx = ut.call_contexts(toks)
    by_text = {t.text: ctx[i] for i, t in enumerate(toks) if t.kind == "str"}
    assert by_text["x"] == ("say", 2, "")
    assert by_text["d"] == ("el", 0, "")
    assert by_text["T"] == ("el", 2, "d")


# --- extractor -------------------------------------------------------------------------------


def test_extract_takes_ukrainian_text() -> None:
    assert texts("const a = 'Привіт'; const b = `Гра ${x} кінець`;") == [
        "Привіт",
        "Гра ",
        " кінець",
    ]


def test_extract_skips_keys_comparisons_and_calls() -> None:
    src = """
    const o = { 'ключ': 1, label: 'Мітка' };
    if (k === 'а' || 'я' !== k) {}
    switch (m) { case 'ліс': break; }
    console.log('Лог'); bus.emit('подія'); el.addEventListener('клік', f);
    throw new Error('Помилка');
    """
    assert texts(src) == ["Мітка"]


def test_extract_skips_identifiers_and_classes() -> None:
    src = "el('div', 'btn-big alt', 'Грати'); x.className = 'menu title'; use('use strict');"
    assert texts(src) == ["Грати"]


def test_extract_latin_sentences_and_sink_words() -> None:
    assert texts("say('Game over'); x.textContent = 'Pause'; y = 'ride'; z = 'Pause';") == [
        "Game over",
        "Pause",
    ]


def test_extract_set_attribute_only_text_attributes() -> None:
    src = "b.setAttribute('aria-label', 'Звук'); b.setAttribute('data-x', 'Ключ');"
    assert texts(src) == ["Звук"]


def test_extract_marks_concatenation() -> None:
    found = ut.extract_js("t = n + ' поїздок'; u = 'Усього ' + n;", "f.js")
    assert [(s.text, s.glued) for s in found] == [(" поїздок", True), ("Усього ", False)]


def test_extract_strips_html_tags_from_strings() -> None:
    found = ut.extract_js("h = '<button class=\"oc-btn\">Беру</button>';", "f.js")
    assert [s.text for s in found] == ["Беру"]


def test_extract_html_text_and_attributes() -> None:
    html = (
        "<html><head><title>7 ланосів</title><style>a{}</style></head>"
        '<body><div title="Підказка">  Текст\n  тут </div><!-- коментар -->'
        "<script>var a = 'Не показувати';</script></body></html>"
    )
    found = ut.extract_html(html, "i.html")
    assert [s.text for s in found] == ["7 ланосів", "Підказка", "Текст тут"]
    assert found[0].line == 1


# --- rules -----------------------------------------------------------------------------------


def test_latin_flags_english_words() -> None:
    found = ut.rule_latin(ui("Натисни Start"))
    assert rules_of(found) == ["latin"] and "Start" in found[0].detail


@pytest.mark.parametrize(
    "text",
    [
        "Біля Boavista",
        "Рейс на Hospital São João",
        "Estádio do Dragão — матч",
        "ліцензія CC BY 4.0",
        "джерело UCI, 12 km",
        "набір «Taxi Service Trajectory»",
        "Campo 24 de Agosto",
        "тільки кирилиця",
    ],
)
def test_latin_allows_whitelist(text: str) -> None:
    assert ut.rule_latin(ui(text)) == []


def test_latin_place_name_does_not_hide_neighbours() -> None:
    assert rules_of(ut.rule_latin(ui("Boavista trips"))) == ["latin"]


def test_mixed_script_catches_lookalikes() -> None:
    assert rules_of(ut.rule_mixed_script(ui("Рiїн"))) == ["mixed-script"]  # Latin i
    assert ut.rule_mixed_script(ui("Зé Нуну")) == []
    assert ut.rule_mixed_script(ui("Ріїн")) == []


def test_russian_letters_and_words() -> None:
    found = ut.rule_russian(ui("Это всё"))
    assert rules_of(found) == ["russian"] and "э ё" in found[0].detail
    assert rules_of(ut.rule_russian(ui("Что там"))) == ["russian"]
    assert ut.rule_russian(ui("Це все")) == []
    found = ut.rule_russian(ui("Очень быстро"))
    assert any("дуже" in f.detail for f in found)


def test_russian_calque_is_a_warning() -> None:
    found = ut.rule_russian(ui("Приймати участь у перегонах"))
    assert [(f.rule, f.severity) for f in found] == [("russism", ut.WARNING)]
    assert ut.rule_russian(ui("Брати участь")) == []


@pytest.mark.parametrize("bad", ["п'ятниця", "пʼятниця", "п`ятниця", "п‘ятниця"])
def test_apostrophe_flags_wrong_marks(bad: str) -> None:
    assert rules_of(ut.rule_apostrophe(ui(bad))) == ["apostrophe"]


def test_apostrophe_accepts_the_project_mark_and_quotes() -> None:
    assert ut.rule_apostrophe(ui("п’ятниця")) == []
    assert ut.rule_apostrophe(ui("він сказав 'так'")) == []


@pytest.mark.parametrize(
    "text", ["+€8,40", "Найкраще: €12,40", "€12", "0,50 €/км", "3,25 + 0,50 €/км (×1,2 вночі)"]
)
def test_euro_accepts_contract_format(text: str) -> None:
    assert ut.rule_euro(ui(text)) == []


@pytest.mark.parametrize(
    "text", ["€12.40", "€12,4", "€ 12,40", "12,40 €", "12€", "0.50 €/км", "€12,400"]
)
def test_euro_rejects_other_formats(text: str) -> None:
    assert rules_of(ut.rule_euro(ui(text))) == ["euro"]


def test_euro_glued_suffix_and_letterless_strings() -> None:
    assert rules_of(ut.rule_euro(ui(" €", glued=True))) == ["euro"]
    assert ut.rule_euro(ui("€", glued=True)) == []  # '€' + number is the right order
    assert ut.rule_euro(ui(" €", glued=False)) == []
    assert ut.rule_euro(ui(" €/км", glued=True)) == []
    assert texts("el('div', 'hud-money', '€0,00'); n + ' €'; m = '+€';") == ["€0,00", " €", "+€"]


def test_gender_flags_player_forms() -> None:
    assert rules_of(ut.rule_gender(ui("ти заробив €5"))) == ["gender"]
    assert rules_of(ut.rule_gender(ui("Ти вже встиг"))) == ["gender"]
    assert rules_of(ut.rule_gender(ui("ти зробила це"))) == ["gender"]
    assert rules_of(ut.rule_gender(ui("Будь готовий"))) == ["gender"]
    assert all(f.severity == ut.WARNING for f in ut.rule_gender(ui("Ти готова")))


def test_gender_allows_neutral_and_hero_lines() -> None:
    assert ut.rule_gender(ui("Ти попереду привида!")) == []
    assert ut.rule_gender(ui("Не встигнеш")) == []
    assert ut.rule_gender(ui("Ріїн Гіслінг заробив €5")) == []
    assert ut.rule_gender(ui("Ріїн Гіслінг готовий")) == []
    assert ut.rule_gender(ui("Інеш випередила")) == []


@pytest.mark.parametrize(
    ("n", "idx"),
    [(0, 2), (1, 0), (2, 1), (4, 1), (5, 2), (11, 2), (12, 2), (14, 2), (21, 0), (22, 1), (111, 2)],
)
def test_plural_index(n: int, idx: int) -> None:
    assert ut.plural_index(n) == idx


def test_plural_literal_agreement() -> None:
    assert ut.rule_plural(ui("1 поїздка, 2 поїздки, 5 поїздок, 21 поїздка")) == []
    assert ut.rule_plural(ui("з 21 поїздки")) == []
    assert rules_of(ut.rule_plural(ui("5 поїздка"))) == ["plural"]
    assert rules_of(ut.rule_plural(ui("2 поїздок"))) == ["plural"]
    assert rules_of(ut.rule_plural(ui("11 поїздки"))) == ["plural"]
    assert ut.rule_plural(ui("3 хвилини і 10 хвилин")) == []


def test_plural_concatenation_is_a_warning() -> None:
    found = ut.rule_plural(ui(" поїздок", glued=True))
    assert [(f.rule, f.severity) for f in found] == [("plural", ut.WARNING)]
    assert ut.rule_plural(ui(" поїздок", glued=False)) == []
    assert ut.rule_plural(ui(" з гравців", glued=True)) == []
    assert rules_of(ut.rule_plural(ui(" хвилин тому", glued=True))) == ["plural"]
    assert rules_of(ut.rule_plural(ui(" справжніх водіїв", glued=True))) == ["plural"]
    assert ut.rule_plural(ui(" справжніх таксі на мапі", glued=True)) == []
    assert ut.rule_plural(ui(" а б в г поїздок", glued=True)) == []  # too far from the number
    assert ut.rule_plural(ui(" хвиля замовлень біля ", glued=True)) == []  # fixed phrase


# --- driver ----------------------------------------------------------------------------------


def test_check_strings_sorts_findings() -> None:
    strings = [UiString("b.js", 1, "Start"), UiString("a.js", 9, "ти заробив"), ui("п'ятниця")]
    found = ut.check_strings(strings)
    assert [(f.file, f.line, f.rule) for f in found] == [
        ("a.js", 9, "gender"),
        ("b.js", 1, "latin"),
        ("f.js", 7, "apostrophe"),
    ]


def test_format_finding() -> None:
    err = ut.Finding("g/a.js", 3, "latin", ut.ERROR, "Start", "Latin word")
    warn = ut.Finding("g/a.js", 4, "gender", ut.WARNING, "ти встиг", "gendered")
    assert ut.format_finding(err).startswith("g/a.js:3: latin: 'Start'")
    assert ut.format_finding(warn).startswith("g/a.js:4: gender (warning): ")


def make_src(tmp_path: Path, js: str, html: str = "<p>Привіт</p>") -> Path:
    src = tmp_path / "game" / "src"
    (src / "js").mkdir(parents=True)
    (src / "js" / "10_a.js").write_text(js, encoding="utf-8")
    (src / "index.html").write_text(html, encoding="utf-8")
    return src


def test_collect_files_orders_js_then_html(tmp_path: Path) -> None:
    src = make_src(tmp_path, "")
    (src / "js" / "05_b.js").write_text("", encoding="utf-8")
    assert [p.name for p in ut.collect_files(src)] == ["05_b.js", "10_a.js", "index.html"]


def test_main_clean_source_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = make_src(tmp_path, "const a = 'Грати';")
    assert ut.main(["--src", str(src)]) == 0
    assert "0 errors, 0 warnings" in capsys.readouterr().out


def test_main_error_exits_one_and_prints_location(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = make_src(tmp_path, "\n\nconst a = 'Привіт Start';")
    assert ut.main(["--src", str(src)]) == 1
    assert "game/src/js/10_a.js:3: latin: " in capsys.readouterr().out


def test_main_warning_only_passes_unless_strict(tmp_path: Path) -> None:
    src = make_src(tmp_path, "const a = 'Будь готовий';")
    assert ut.main(["--src", str(src)]) == 0
    assert ut.main(["--src", str(src), "--strict"]) == 1


def test_main_missing_directory(tmp_path: Path) -> None:
    assert ut.main(["--src", str(tmp_path / "nope")]) == 2
