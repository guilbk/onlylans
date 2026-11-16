"""Lint of the user-visible Ukrainian text in the game sources.

Extracts string literals from ``game/src/js/*.js`` and ``game/src/index.html`` that a player can
read (identifiers, CSS classes, event names, ids and object keys are skipped), then checks them:
English leftovers, mixed scripts, Russian letters and russisms, the apostrophe style, the euro
format (``€12,40``), gendered forms aimed at the player and plural agreement of «поїздка».

Run ``python tools/ui_text.py [--src game/src] [--strict]``. Findings are printed as
``file:line: rule: text``; the exit code is 1 if there is any error (warnings do not count unless
``--strict`` is given). Lengths and money in the checked strings are not interpreted, only text.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

ERROR = "error"
WARNING = "warning"

APOSTROPHE = "\u2019"  # the project's apostrophe: ’ (as in «п’ятниця»)
BAD_APOSTROPHES = "'\u02bc`\u2032\u2018"  # ASCII, modifier letter, grave, prime, left quote
CYRILLIC_RANGE = ("\u0400", "\u04ff")
RUSSIAN_LETTERS = "ыэъё"

# Porto place names from CONTRACT §9 (Latin spelling is correct for them).
PLACE_NAMES: tuple[str, ...] = (
    "Aliados", "Bolhão", "São Bento", "Campanhã", "Casa da Música", "Cedofeita",
    "Hospital São João", "Estádio do Dragão", "Castelo do Queijo", "Aeroporto", "Gaia (Cais)",
    "Gaia", "Santo Ovídio", "Ribeira", "Trindade", "Clérigos", "Bonfim", "Boavista", "Marquês",
    "Asprela", "Foz", "Matosinhos", "Campo 24 de Agosto",
)  # fmt: skip
# Latin words allowed besides the places: dataset licence/source acronyms and the unit «km».
LATIN_WHITELIST = frozenset({"uci", "cc", "by", "km", "ecml", "pkdd"})
# Words that mix scripts on purpose (the rival «Зé», CONTRACT §13).
MIXED_SCRIPT_OK = frozenset({"Зé"})
HERO_NAMES = ("Ріїн Гіслінг",)

# Russian words that do not exist in Ukrainian -> suggested replacement.
RUSSIAN_WORDS: dict[str, str] = {
    "что": "що", "очень": "дуже", "только": "тільки", "сейчас": "зараз", "конечно": "звісно",
    "спасибо": "дякую", "пожалуйста": "будь ласка", "если": "якщо", "тоже": "теж",
    "нету": "немає", "кстати": "до речі", "водитель": "водій", "поездка": "поїздка",
    "заказ": "замовлення", "такси": "таксі", "деньги": "гроші", "время": "час",
    "игра": "гра", "получить": "отримати", "заработал": "заробив", "пассажир": "пасажир",
}  # fmt: skip
# Calques (russisms made of Ukrainian words) -> suggested replacement.
RUSSIAN_CALQUES: dict[str, str] = {
    "приймати участь": "брати участь", "на протязі": "протягом",
    "в залежності від": "залежно від", "слідуючий": "наступний", "слідуюча": "наступна",
    "дякую вам за": "дякуємо за", "вірно": "правильно",
}  # fmt: skip

# Forms (singular, 2-4, 5+) of nouns whose plural is easy to glue wrongly to a number.
PLURAL_FORMS: dict[str, tuple[str, str, str]] = {
    "поїздка": ("поїздка", "поїздки", "поїздок"),
    "хвилина": ("хвилина", "хвилини", "хвилин"),
    "секунда": ("секунда", "секунди", "секунд"),
    "година": ("година", "години", "годин"),
    "водій": ("водій", "водії", "водіїв"),
}
PLURAL_LOOKUP: dict[str, tuple[str, ...]] = {
    form: forms for forms in PLURAL_FORMS.values() for form in forms
}

GENDER_ADJECTIVES = re.compile(
    r"(?<!\w)(?:готов(?:ий|а)|впевнен(?:ий|а)|упевнен(?:ий|а)|радий|"
    r"задоволен(?:ий|а)|втомлен(?:ий|а)|змушен(?:ий|а))(?!\w)",
    re.IGNORECASE,
)
ADDRESS_ADVERBS = "вже|уже|ще|щойно|майже|не|тепер|знову|також|теж"
ADDRESS_VERB = re.compile(rf"(?<!\w)ти\s+(?:(?:{ADDRESS_ADVERBS})\s+)*([^\W\d_]+)", re.IGNORECASE)
IRREGULAR_PAST = frozenset({"встиг", "зміг", "привіз", "довіз", "виграв", "програв"})

BAD_APOSTROPHE_RE = re.compile(
    rf"(?<=[\u0400-\u04ff])[{re.escape(BAD_APOSTROPHES)}](?=[\u0400-\u04ff])"
)
WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019\u02bc][^\W\d_]+)*")
QUOTED_RE = re.compile(r"«[^»]*»")
SENTENCE_RE = re.compile(r"^[A-Za-zÀ-ÿ]{2,}(?: [A-Za-zÀ-ÿ]{2,})+[.!?]?$")
NUMBER_NOUN_RE = re.compile(r"(?<![\d,.])(\d+)\s+([^\W\d_]+)")
EURO_PREFIX_RE = re.compile(r"€(\s*)(\d+)([.,]\d*)?")
EURO_SUFFIX_RE = re.compile(r"(\d+)([.,]\d+)?\s*€(?!/)")
EURO_RATE_RE = re.compile(r"\d+\.\d+\s*€")
EURO_GLUED_SUFFIX_RE = re.compile(r"\s+€(?!/)")
EURO_FRACTION_LEN = 3  # "," plus two digits
MIN_PAST_VERB_LEN = 3  # shortest gendered past form, «був»
PLURAL_SCAN_WORDS = 3  # how many leading words of a glued string may hold the counted noun

# Calls whose string arguments are never player-visible text.
SKIP_CALLS = frozenset(
    {
        "log", "warn", "error", "info", "debug", "on", "off", "once", "emit",
        "addEventListener", "removeEventListener", "querySelector", "querySelectorAll",
        "getElementById", "createElement", "createElementNS", "add", "remove", "toggle",
        "contains", "require", "getContext", "matchMedia", "getItem", "setItem", "removeItem",
        "fetch", "getAttribute", "hasAttribute", "removeAttribute", "Error", "TypeError",
        "RangeError",
    }
)  # fmt: skip
# Calls whose string arguments are player-visible text (used for single Latin words).
UI_CALLS = frozenset(
    {"say", "showBanner", "floatText", "toast", "el", "btn", "button", "stat", "listBlock",
     "alert", "fillText"}
)  # fmt: skip
UI_PROPS = frozenset(
    {"textContent", "innerText", "innerHTML", "title", "placeholder", "alt", "label"}
)
NON_UI_PROPS = frozenset(
    {"className", "id", "type", "href", "src", "fillStyle", "strokeStyle", "font", "textAlign",
     "textBaseline", "cursor", "display", "position", "value", "name"}
)  # fmt: skip
UI_ATTRIBUTES = frozenset({"title", "aria-label", "alt", "placeholder"})
COMPARE_OPS = frozenset({"===", "!==", "==", "!=", "case", "in", "typeof"})
REGEX_PRECEDERS = frozenset(
    {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do"}
)
TAG_RE = re.compile(r"<[^>]*>")
IGNORED_TEXTS = frozenset({"use strict"})
OPEN_BRACKETS = frozenset("([{")
CLOSE_BRACKETS = frozenset(")]}")

TOKEN_OP_RE = re.compile(
    r"===|!==|\.\.\.|=>|==|!=|<=|>=|&&|\|\||\?\?|\+\+|--|\+=|-=|[-+*/%=<>!&|^~?:.,;(){}\[\]]"
)
WORD_TOKEN_RE = re.compile(r"(?:[^\W\d]|\$)[\w$]*")
NUMBER_TOKEN_RE = re.compile(r"\d[\w.]*")
STRING_RES = {
    "'": re.compile(r"'((?:[^'\\\n]|\\.)*)'", re.DOTALL),
    '"': re.compile(r'"((?:[^"\\\n]|\\.)*)"', re.DOTALL),
}
TEMPLATE_RE = re.compile(r"((?:[^`\\$]|\\.|\$(?!\{))*)(`|\$\{)", re.DOTALL)
ESCAPE_RE = re.compile(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.DOTALL)
SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
                  "\n": ""}  # fmt: skip
HTML_TEXT_ATTRIBUTES = frozenset({"title", "alt", "aria-label", "placeholder", "label"})
HTML_RAW_TAGS = frozenset({"script", "style"})


@dataclass(frozen=True)
class Token:
    """One lexical token of a JavaScript source.

    Attributes:
        kind: ``str``, ``tpl`` (template text chunk), ``word``, ``num``, ``regex`` or ``op``.
        text: Unescaped string value for strings, the raw text otherwise.
        line: 1-based line of the token start.
        joined: For ``tpl`` chunks, True if the chunk follows a ``${...}`` interpolation.
    """

    kind: str
    text: str
    line: int
    joined: bool = False


@dataclass(frozen=True)
class UiString:
    """A user-visible string with the facts the rules need.

    Attributes:
        file: Source file label used in the output.
        line: 1-based line.
        text: String value (unescaped).
        glued: True if the string is concatenated to something before it (``x + 'text'``).
    """

    file: str
    line: int
    text: str
    glued: bool = False


@dataclass(frozen=True)
class Finding:
    """One lint finding.

    Attributes:
        file: Source file label.
        line: 1-based line.
        rule: Rule name.
        severity: ``error`` or ``warning``.
        text: The offending string.
        detail: Short explanation, with the suggested fix where known.
    """

    file: str
    line: int
    rule: str
    severity: str
    text: str
    detail: str


Rule = Callable[[UiString], list[Finding]]


def _unescape_match(m: re.Match[str]) -> str:
    """Resolve one backslash escape matched by ``ESCAPE_RE``.

    Args:
        m: Match whose group 1 is the text after the backslash.

    Returns:
        The character the escape stands for.
    """
    esc = m.group(1)
    if esc.startswith("u{"):
        return chr(int(esc[2:-1], 16))
    if esc[0] in "ux" and len(esc) > 1:
        return chr(int(esc[1:], 16))
    return SIMPLE_ESCAPES.get(esc, esc)


def unescape_js(raw: str) -> str:
    """Resolve the backslash escapes of a JavaScript string literal.

    Args:
        raw: Literal body without the quotes.

    Returns:
        The string value.
    """
    return ESCAPE_RE.sub(_unescape_match, raw)


class _Lexer:
    """Minimal JavaScript lexer: strings, templates, regex literals, comments, words, operators."""

    def __init__(self, source: str) -> None:
        """Prepare a lexer.

        Args:
            source: JavaScript source text.
        """
        self.src = source
        self.pos = 0
        self.line = 1
        self.tokens: list[Token] = []
        self.braces: list[str] = []  # "{" or "${" (open template interpolation)

    def run(self) -> list[Token]:
        """Tokenize the whole source.

        Returns:
            Tokens in source order (comments and whitespace dropped).
        """
        while self.pos < len(self.src):
            if not self._skip_blank():
                self._next_token()
        return self.tokens

    def _move(self, end: int) -> None:
        """Advance to ``end`` keeping the line counter."""
        self.line += self.src.count("\n", self.pos, end)
        self.pos = end

    def _emit(self, kind: str, text: str, line: int, joined: bool = False) -> None:
        """Append a token."""
        self.tokens.append(Token(kind, text, line, joined))

    def _skip_blank(self) -> bool:
        """Skip one whitespace run or comment; return True if something was skipped."""
        src, pos = self.src, self.pos
        if src[pos].isspace():
            end = pos
            while end < len(src) and src[end].isspace():
                end += 1
            self._move(end)
            return True
        if src.startswith("//", pos):
            end = src.find("\n", pos)
            self._move(len(src) if end < 0 else end)
            return True
        if src.startswith("/*", pos):
            end = src.find("*/", pos + 2)
            self._move(len(src) if end < 0 else end + 2)
            return True
        return False

    def _next_token(self) -> None:
        """Lex one token at the current position."""
        ch = self.src[self.pos]
        if ch in STRING_RES:
            self._string(ch)
        elif ch == "`":
            self._move(self.pos + 1)
            self._template(joined=False)
        elif ch == "/" and self._regex_allowed():
            self._regex()
        elif ch == "}" and self.braces and self.braces[-1] == "${":
            self.braces.pop()
            self._move(self.pos + 1)
            self._template(joined=True)
        else:
            self._word_number_op()

    def _string(self, quote: str) -> None:
        """Lex a quoted string (a malformed one is skipped as a bare quote)."""
        m = STRING_RES[quote].match(self.src, self.pos)
        if m is None:
            self._move(self.pos + 1)
            return
        self._emit("str", unescape_js(m.group(1)), self.line)
        self._move(m.end())

    def _template(self, joined: bool) -> None:
        """Lex one text chunk of a template literal, up to the closing quote or ``${``."""
        m = TEMPLATE_RE.match(self.src, self.pos)
        if m is None:
            self._move(len(self.src))
            return
        self._emit("tpl", unescape_js(m.group(1)), self.line, joined)
        if m.group(2) == "${":
            self.braces.append("${")
        self._move(m.end())

    def _regex_allowed(self) -> bool:
        """Tell whether a ``/`` here starts a regex literal (not a division)."""
        if not self.tokens:
            return True
        prev = self.tokens[-1]
        if prev.kind == "word":
            return prev.text in REGEX_PRECEDERS
        if prev.kind == "op":
            return prev.text not in {")", "]", "}", "++", "--"}
        return False

    def _regex(self) -> None:
        """Lex a regex literal with its flags."""
        src, i, in_class = self.src, self.pos + 1, False
        while i < len(src) and src[i] != "\n":
            c = src[i]
            if c == "\\":
                i += 1
            elif c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
            i += 1
        end = i + 1
        while end < len(src) and src[end].isalpha():
            end += 1
        self._emit("regex", src[self.pos : end], self.line)
        self._move(min(end, len(src)))

    def _word_number_op(self) -> None:
        """Lex a word, a number or an operator; unknown characters are skipped."""
        for kind, pattern in (
            ("word", WORD_TOKEN_RE),
            ("num", NUMBER_TOKEN_RE),
            ("op", TOKEN_OP_RE),
        ):
            m = pattern.match(self.src, self.pos)
            if m:
                self._emit(kind, m.group(0), self.line)
                if kind == "op" and m.group(0) == "{":
                    self.braces.append("{")
                elif kind == "op" and m.group(0) == "}" and self.braces:
                    self.braces.pop()
                self._move(m.end())
                return
        self._move(self.pos + 1)


def tokenize_js(source: str) -> list[Token]:
    """Split JavaScript source into tokens.

    Args:
        source: JavaScript source text.

    Returns:
        Tokens in order; template literals become ``tpl`` chunks around the expression tokens.
    """
    return _Lexer(source).run()


@dataclass
class _Frame:
    """An open bracket during the context pass: the callee and the argument position."""

    bracket: str
    callee: str = ""
    arg: int = 0
    first: str = ""


def call_contexts(tokens: list[Token]) -> list[tuple[str, int, str]]:
    """Find, for every token, the innermost enclosing call.

    Args:
        tokens: Tokens from :func:`tokenize_js`.

    Returns:
        Per token ``(callee name, argument index, first string argument)``; the callee is ``""``
        outside any call.
    """
    stack: list[_Frame] = []
    out: list[tuple[str, int, str]] = []
    for i, tok in enumerate(tokens):
        calls = [f for f in stack if f.bracket == "("]
        top = calls[-1] if calls else None
        out.append((top.callee, top.arg, top.first) if top else ("", 0, ""))
        if tok.kind == "op" and tok.text in OPEN_BRACKETS:
            prev = tokens[i - 1] if i else None
            callee = prev.text if tok.text == "(" and prev and prev.kind == "word" else ""
            stack.append(_Frame(tok.text, callee))
        elif tok.kind == "op" and tok.text in CLOSE_BRACKETS and stack:
            stack.pop()
        elif tok.kind == "op" and tok.text == "," and stack and stack[-1].bracket == "(":
            stack[-1].arg += 1
        elif tok.kind == "str" and top is not None and top.arg == 0 and not top.first:
            top.first = tok.text
    return out


def _has_cyrillic(text: str) -> bool:
    """Tell whether ``text`` has a Cyrillic letter."""
    return any(CYRILLIC_RANGE[0] <= c <= CYRILLIC_RANGE[1] for c in text)


def _is_key(tokens: list[Token], i: int) -> bool:
    """Tell whether the string at ``i`` is an object key (``{ 'k': v }``)."""
    prev = tokens[i - 1].text if i else ""
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None
    return prev in {"{", ","} and nxt is not None and nxt.kind == "op" and nxt.text == ":"


def _is_comparison(tokens: list[Token], i: int) -> bool:
    """Tell whether the string at ``i`` is compared, switched on or used as an index."""
    prev = tokens[i - 1] if i else None
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None
    if prev is not None and prev.kind in {"op", "word"} and prev.text in COMPARE_OPS:
        return True
    if nxt is not None and nxt.kind == "op" and nxt.text in COMPARE_OPS:
        return True
    return bool(prev and nxt and prev.text == "[" and nxt.text == "]")


def _assigned_property(tokens: list[Token], i: int) -> str:
    """Return the property name in ``x.prop = 'text'`` for the string at ``i`` (else ``""``)."""
    if i >= 2 and tokens[i - 1].text == "=" and tokens[i - 2].kind == "word":
        return tokens[i - 2].text
    return ""


def _in_ui_sink(callee: str, first: str, arg: int, prop: str) -> bool:
    """Tell whether a string at this position is shown to the player."""
    if prop in UI_PROPS or callee in UI_CALLS:
        return True
    return callee == "setAttribute" and arg == 1 and first in UI_ATTRIBUTES


def is_ui_string(tokens: list[Token], i: int, ctx: tuple[str, int, str]) -> bool:
    """Decide whether the string token at ``i`` is player-visible text.

    Args:
        tokens: All tokens of the file.
        i: Index of a ``str`` or ``tpl`` token.
        ctx: The token's entry from :func:`call_contexts`.

    Returns:
        True for text the player can read.
    """
    tok = tokens[i]
    if not any(c.isalpha() or c == "€" for c in tok.text) or tok.text in IGNORED_TEXTS:
        return False
    callee, arg, first = ctx
    prop = _assigned_property(tokens, i)
    if tok.kind == "str" and (_is_key(tokens, i) or _is_comparison(tokens, i)):
        return False
    if callee in SKIP_CALLS or prop in NON_UI_PROPS:
        return False
    if callee == "setAttribute" and (arg == 0 or first not in UI_ATTRIBUTES):
        return False
    if _has_cyrillic(tok.text) or "€" in tok.text or SENTENCE_RE.match(tok.text.strip()):
        return True
    capitalised = tok.text.strip()[:1].isupper()
    return capitalised and _in_ui_sink(callee, first, arg, prop)


def extract_js(source: str, label: str) -> list[UiString]:
    """Extract the user-visible strings of one JavaScript file.

    Args:
        source: JavaScript source text.
        label: File label used in findings.

    Returns:
        Strings in source order.
    """
    tokens = tokenize_js(source)
    contexts = call_contexts(tokens)
    found: list[UiString] = []
    for i, tok in enumerate(tokens):
        if tok.kind not in {"str", "tpl"} or not is_ui_string(tokens, i, contexts[i]):
            continue
        prev = tokens[i - 1] if i else None
        glued = tok.joined or (prev is not None and prev.kind == "op" and prev.text in {"+", "+="})
        text = " ".join(TAG_RE.sub(" ", tok.text).split()) if "<" in tok.text else tok.text
        if text:
            found.append(UiString(label, tok.line, text, glued))
    return found


class _HtmlText(HTMLParser):
    """Collect text nodes and text-bearing attributes of an HTML document."""

    def __init__(self, label: str) -> None:
        """Prepare a collector.

        Args:
            label: File label used in findings.
        """
        super().__init__(convert_charrefs=True)
        self.label = label
        self.found: list[UiString] = []
        self._raw_depth = 0

    def _add(self, text: str) -> None:
        """Record a non-empty string at the parser's current line."""
        text = " ".join(text.split())
        if text:
            self.found.append(UiString(self.label, self.getpos()[0], text))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record text attributes; track script/style blocks."""
        if tag in HTML_RAW_TAGS:
            self._raw_depth += 1
        for name, value in attrs:
            if name in HTML_TEXT_ATTRIBUTES and value:
                self._add(value)

    def handle_endtag(self, tag: str) -> None:
        """Leave a script/style block."""
        if tag in HTML_RAW_TAGS and self._raw_depth:
            self._raw_depth -= 1

    def handle_data(self, data: str) -> None:
        """Record a text node (not inside script/style)."""
        if not self._raw_depth:
            self._add(data)


def extract_html(source: str, label: str) -> list[UiString]:
    """Extract the visible text and text attributes of an HTML file.

    Args:
        source: HTML source text.
        label: File label used in findings.

    Returns:
        Strings in document order.
    """
    parser = _HtmlText(label)
    parser.feed(source)
    parser.close()
    return parser.found


def _finding(s: UiString, rule: str, detail: str, severity: str = ERROR) -> Finding:
    """Build a finding for a string."""
    return Finding(s.file, s.line, rule, severity, s.text, detail)


def _script_of(ch: str) -> str:
    """Return ``cyr``, ``lat`` or ``other`` for a letter."""
    if CYRILLIC_RANGE[0] <= ch <= CYRILLIC_RANGE[1]:
        return "cyr"
    if unicodedata.name(ch, "").startswith("LATIN"):
        return "lat"
    return "other"


def strip_allowed_latin(text: str) -> str:
    """Remove the Latin text that is allowed: «quoted» titles and Porto place names.

    Args:
        text: UI string.

    Returns:
        The string with the allowed spans replaced by spaces.
    """
    text = QUOTED_RE.sub(" ", text)
    for name in sorted(PLACE_NAMES, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", text)
    return text


def rule_latin(s: UiString) -> list[Finding]:
    """Flag Latin-only words (English leftovers) outside the whitelist."""
    out: list[Finding] = []
    for word in WORD_RE.findall(strip_allowed_latin(s.text)):
        scripts = {_script_of(c) for c in word if c.isalpha()}
        if scripts == {"lat"} and word.casefold() not in LATIN_WHITELIST:
            out.append(_finding(s, "latin", f"Latin word «{word}» in Ukrainian UI text"))
    return out


def rule_mixed_script(s: UiString) -> list[Finding]:
    """Flag words that mix Cyrillic and Latin letters (look-alike typos)."""
    out: list[Finding] = []
    for word in WORD_RE.findall(strip_allowed_latin(s.text)):
        scripts = {_script_of(c) for c in word if c.isalpha()}
        if {"cyr", "lat"} <= scripts and word not in MIXED_SCRIPT_OK:
            out.append(_finding(s, "mixed-script", f"word «{word}» mixes Cyrillic and Latin"))
    return out


def rule_russian(s: UiString) -> list[Finding]:
    """Flag Russian letters, Russian words (errors) and calques (warnings)."""
    out: list[Finding] = []
    lowered = s.text.casefold()
    letters = sorted({c for c in lowered if c in RUSSIAN_LETTERS})
    if letters:
        out.append(_finding(s, "russian", f"Russian letter(s) {' '.join(letters)}"))
    for word in WORD_RE.findall(lowered):
        if word in RUSSIAN_WORDS:
            out.append(_finding(s, "russian", f"«{word}» is Russian; use «{RUSSIAN_WORDS[word]}»"))
    for phrase, fix in RUSSIAN_CALQUES.items():
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered):
            out.append(_finding(s, "russism", f"calque «{phrase}»; use «{fix}»", WARNING))
    return out


def rule_apostrophe(s: UiString) -> list[Finding]:
    """Flag a non-canonical apostrophe between Cyrillic letters (the style is ’)."""
    if BAD_APOSTROPHE_RE.search(s.text):
        return [_finding(s, "apostrophe", f"use the apostrophe {APOSTROPHE} between letters")]
    return []


def rule_euro(s: UiString) -> list[Finding]:
    """Check the euro format: ``€12,40`` (sign first, comma, two digits; ``€12`` is allowed)."""
    out: list[Finding] = []
    for m in EURO_PREFIX_RE.finditer(s.text):
        space, _, frac = m.groups()
        if space:
            out.append(_finding(s, "euro", "no space between € and the number (€12,40)"))
        elif frac and (frac[0] == "." or len(frac) != EURO_FRACTION_LEN):
            out.append(_finding(s, "euro", "decimal comma and two digits: €12,40"))
    if EURO_SUFFIX_RE.search(s.text):
        out.append(_finding(s, "euro", "put € before the number: €12,40"))
    if EURO_RATE_RE.search(s.text):
        out.append(_finding(s, "euro", "decimal comma, not a point, in a rate"))
    if s.glued and EURO_GLUED_SUFFIX_RE.match(s.text):
        out.append(_finding(s, "euro", "number + ' €' built by concatenation; use U.eur(x)"))
    return out


def rule_gender(s: UiString) -> list[Finding]:
    """Warn about gendered forms aimed at the player; the hero's own lines are allowed."""
    if any(name in s.text for name in HERO_NAMES):
        return []
    out: list[Finding] = []
    for m in GENDER_ADJECTIVES.finditer(s.text):
        detail = f"gendered «{m.group(0)}»; use a neutral wording"
        out.append(_finding(s, "gender", detail, WARNING))
    for m in ADDRESS_VERB.finditer(s.text):
        word = m.group(1).casefold()
        gendered = word in IRREGULAR_PAST or (
            len(word) >= MIN_PAST_VERB_LEN and word.endswith(("в", "ла"))
        )
        if gendered:
            detail = f"«ти {word}» is gendered; use a neutral wording"
            out.append(_finding(s, "gender", detail, WARNING))
    return out


def plural_index(n: int) -> int:
    """Index of the Ukrainian plural form for ``n``: 0 = 1, 1 = 2-4, 2 = 5-20 and the rest.

    Args:
        n: Non-negative count.

    Returns:
        0, 1 or 2.
    """
    if n % 10 == 1 and n % 100 != 11:
        return 0
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 1
    return 2


def _plural_literals(s: UiString) -> list[Finding]:
    """Check literal «number noun» pairs such as «5 поїздка»."""
    out: list[Finding] = []
    for m in NUMBER_NOUN_RE.finditer(s.text):
        noun = m.group(2).casefold()
        forms = PLURAL_LOOKUP.get(noun)
        if forms is None:
            continue
        n = int(m.group(1))
        want = plural_index(n)
        allowed = {want, 1} if want == 0 else {want}  # «з 21 поїздки» (genitive) is fine
        if not allowed & {i for i, f in enumerate(forms) if f == noun}:
            out.append(_finding(s, "plural", f"{n} needs «{forms[want]}», not «{m.group(2)}»"))
    return out


def _plural_glued(s: UiString) -> list[Finding]:
    """Warn if a counted noun opens a string that is glued to a number with ``+``."""
    if not s.glued:
        return []
    words = WORD_RE.findall(s.text)[:PLURAL_SCAN_WORDS]
    for word in words:
        if word.casefold() in PLURAL_LOOKUP:
            detail = f"«{word}» glued to a number; use U.plural(n, one, few, many)"
            return [_finding(s, "plural", detail, WARNING)]
    return []


def rule_plural(s: UiString) -> list[Finding]:
    """Check the plural of counted nouns: literal «5 поїздка» and numbers glued by ``+``."""
    return [*_plural_literals(s), *_plural_glued(s)]


RULES: tuple[Rule, ...] = (
    rule_latin,
    rule_mixed_script,
    rule_russian,
    rule_apostrophe,
    rule_euro,
    rule_gender,
    rule_plural,
)


def check_strings(strings: list[UiString]) -> list[Finding]:
    """Run every rule over the strings.

    Args:
        strings: Extracted UI strings.

    Returns:
        Findings sorted by file, line and rule.
    """
    found = [f for s in strings for rule in RULES for f in rule(s)]
    return sorted(found, key=lambda f: (f.file, f.line, f.rule, f.text, f.detail))


def collect_files(src: Path) -> list[Path]:
    """List the files to lint under a ``game/src`` directory.

    Args:
        src: The ``game/src`` directory.

    Returns:
        Sorted ``js/*.js`` files, then ``index.html`` if present.
    """
    files = sorted((src / "js").glob("*.js"))
    html = src / "index.html"
    return [*files, html] if html.is_file() else files


def extract_file(path: Path, label: str) -> list[UiString]:
    """Extract the UI strings of one file by its extension.

    Args:
        path: File to read (UTF-8).
        label: File label used in findings.

    Returns:
        Strings in source order.
    """
    source = path.read_text(encoding="utf-8")
    return extract_html(source, label) if path.suffix == ".html" else extract_js(source, label)


def format_finding(f: Finding) -> str:
    """Format a finding as ``file:line: rule: text`` (warnings carry the word in the rule)."""
    rule = f.rule if f.severity == ERROR else f"{f.rule} (warning)"
    return f"{f.file}:{f.line}: {rule}: {f.text!r} - {f.detail}"


def _label(path: Path, root: Path) -> str:
    """Path relative to ``root`` (POSIX style) if possible."""
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> int:
    """Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if there are no errors, 1 if there is an error (or a warning with ``--strict``),
        2 if the source directory is missing.
    """
    default_src = Path(__file__).resolve().parent.parent / "game" / "src"
    ap = argparse.ArgumentParser(description="Lint the Ukrainian UI text of the game")
    ap.add_argument("--src", type=Path, default=default_src, help="game/src directory")
    ap.add_argument("--strict", action="store_true", help="count warnings as errors")
    args = ap.parse_args(argv)
    if not args.src.is_dir():
        print(f"ui_text: no such directory: {args.src}")
        return 2
    root = args.src.resolve().parent.parent
    strings = [s for p in collect_files(args.src) for s in extract_file(p, _label(p, root))]
    findings = check_strings(strings)
    for f in findings:
        print(format_finding(f))
    errors = sum(f.severity == ERROR for f in findings)
    warnings = len(findings) - errors
    print(f"ui_text: {len(strings)} strings, {errors} errors, {warnings} warnings")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
