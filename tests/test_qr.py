import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import qr  # noqa: E402

URL = "http://192.168.1.23:8000/"

# 1-M "HELLO WORLD" from the QR tutorials: 16 data codewords and their 10 EC codewords.
HELLO_DATA = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
HELLO_EC = [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]

FORMAT_L = [0x77C4, 0x72F3, 0x7DAA, 0x789D, 0x662F, 0x6318, 0x6C41, 0x6976]
FORMAT_M = [0x5412, 0x5125, 0x5E7C, 0x5B4B, 0x45F9, 0x40CE, 0x4F97, 0x4AA0]


# --- a tiny independent decoder: format -> unmask -> codewords -> RS check -> text ---------------


def read_format(m: qr.Matrix) -> int:
    n = len(m)
    first = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]]
    first += [m[8][14 - i] for i in range(9, 15)]
    second = [m[8][n - 1 - i] for i in range(8)] + [m[n - 15 + i][8] for i in range(8, 15)]
    a = sum(int(b) << i for i, b in enumerate(first))
    b = sum(int(b) << i for i, b in enumerate(second))
    assert a == b, "the two format copies differ"
    return a


def decode(m: qr.Matrix) -> tuple[str, str, int]:
    """Return (text, ec, mask); asserts that every RS block has zero syndromes."""
    n = len(m)
    version = (n - 17) // 4
    fmt = read_format(m)
    ec, mask = next((e, k) for e in qr.EC_LEVELS for k in range(8) if qr.format_bits(e, k) == fmt)
    _, fixed = qr.function_modules(version)
    bits = [m[r][c] ^ qr.mask_bit(mask, r, c) for r, c in qr.data_positions(fixed)]
    data_cw, ec_len, blocks = qr.BLOCK_TABLE[(version, ec)]
    total = data_cw + ec_len * blocks
    words = [int("".join(str(int(b)) for b in bits[i * 8 : i * 8 + 8]), 2) for i in range(total)]
    per = data_cw // blocks
    data = [words[i * blocks + b] for b in range(blocks) for i in range(per)]
    ecs = words[per * blocks :]
    exp, _ = qr.gf_tables()
    for b in range(blocks):
        block = data[b * per : (b + 1) * per] + [ecs[i * blocks + b] for i in range(ec_len)]
        for k in range(ec_len):  # a valid codeword has value 0 at every generator root
            acc = 0
            for coef in block:
                acc = qr.gf_mul(acc, exp[k]) ^ coef
            assert acc == 0, f"block {b} syndrome {k} is not zero"
    stream = "".join(f"{w:08b}" for w in data)
    assert stream[:4] == "0100"
    count = int(stream[4:12], 2)
    raw = bytes(int(stream[12 + 8 * i : 20 + 8 * i], 2) for i in range(count))
    return raw.decode("utf-8"), ec, mask


# --- GF(256) and Reed-Solomon -------------------------------------------------------------------


def test_gf_tables_basics() -> None:
    exp, log = qr.gf_tables()
    assert exp[0] == 1 and exp[1] == 2 and exp[8] == 0x1D
    assert sorted(exp[:255]) == list(range(1, 256))  # 2 generates the whole group
    assert all(exp[log[x]] == x for x in range(1, 256))


def test_gf_mul_properties() -> None:
    exp, log = qr.gf_tables()
    assert qr.gf_mul(0, 77) == 0 and qr.gf_mul(77, 0) == 0
    assert qr.gf_mul(1, 200) == 200
    assert qr.gf_mul(0x80, 2) == 0x1D
    for a in range(1, 256):
        assert qr.gf_mul(a, exp[255 - log[a]]) == 1  # inverse
    assert qr.gf_mul(13, 201) == qr.gf_mul(201, 13)
    a, b, c = 9, 111, 250
    assert qr.gf_mul(a, b ^ c) == qr.gf_mul(a, b) ^ qr.gf_mul(a, c)


def test_rs_generator_degree_7_known() -> None:
    # exponents of the degree-7 generator from the standard: 0, 87, 229, 146, 149, 238, 102, 21
    exp, _ = qr.gf_tables()
    assert qr.rs_generator(7) == [exp[e] for e in (87, 229, 146, 149, 238, 102, 21)]


def test_rs_remainder_known_vector() -> None:
    assert qr.rs_remainder(HELLO_DATA, 10) == HELLO_EC


def test_rs_remainder_of_zeros_is_zero() -> None:
    assert qr.rs_remainder([0] * 9, 7) == [0] * 7


# --- data codewords -----------------------------------------------------------------------------


def test_block_table_adds_up() -> None:
    totals = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134, 6: 172}
    for (version, _), (data, ec_len, blocks) in qr.BLOCK_TABLE.items():
        assert data + ec_len * blocks == totals[version]
        assert data % blocks == 0


def test_capacity_known_values() -> None:
    assert [qr.capacity(v, "L") for v in range(1, 7)] == [17, 32, 53, 78, 106, 134]
    assert [qr.capacity(v, "M") for v in range(1, 7)] == [14, 26, 42, 62, 84, 106]


def test_choose_version_edges() -> None:
    assert qr.choose_version(0, "M") == 1
    assert qr.choose_version(14, "M") == 1
    assert qr.choose_version(15, "M") == 2
    assert qr.choose_version(134, "L") == 6
    with pytest.raises(qr.QRError):
        qr.choose_version(135, "L")
    with pytest.raises(qr.QRError):
        qr.choose_version(1, "H")


def test_data_codewords_header_and_padding() -> None:
    words = qr.data_codewords(b"A", 1, "M")
    assert len(words) == 16
    assert words[:3] == [0x40, 0x14, 0x10]  # 0100 00000001 01000001 0000
    assert words[3:7] == [0xEC, 0x11, 0xEC, 0x11]


def test_data_codewords_full_capacity() -> None:
    words = qr.data_codewords(b"x" * 14, 1, "M")
    assert len(words) == 16
    assert words[-1] & 0x0F == 0  # only the terminator is left in the last byte


def test_interleave_two_blocks() -> None:
    words = list(range(64))
    out = qr.interleave(4, "M", words)
    assert len(out) == 100
    assert out[:4] == [0, 32, 1, 33]
    assert out[64:66] == [qr.rs_remainder(words[:32], 18)[0], qr.rs_remainder(words[32:], 18)[0]]


# --- format bits --------------------------------------------------------------------------------


def test_format_bits_match_the_standard_table() -> None:
    assert [qr.format_bits("L", m) for m in range(8)] == FORMAT_L
    assert [qr.format_bits("M", m) for m in range(8)] == FORMAT_M


def test_format_bits_are_15_bits_and_distinct() -> None:
    words = {qr.format_bits(e, m) for e in qr.EC_LEVELS for m in range(8)}
    assert len(words) == 16 and all(0 <= w < 1 << 15 for w in words)


def test_versions_1_to_6_carry_no_version_info() -> None:
    # Version information blocks start at version 7; the matrix size is the only version signal.
    assert [qr.size_of(v) for v in range(1, 7)] == [21, 25, 29, 33, 37, 41]


# --- matrix -------------------------------------------------------------------------------------


def finder_at(m: qr.Matrix, r0: int, c0: int) -> list[str]:
    return ["".join("#" if m[r0 + r][c0 + c] else "." for c in range(7)) for r in range(7)]


@pytest.mark.parametrize("text", ["a", URL, "x" * 60, "y" * 100])
def test_finders_timing_and_size(text: str) -> None:
    m = qr.encode(text, "L")
    n = len(m)
    assert n == qr.size_of((n - 17) // 4) and len(m[0]) == n
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        assert finder_at(m, r0, c0) == qr.FINDER
    assert all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8))
    assert all(m[i][6] == (i % 2 == 0) for i in range(8, n - 8))
    assert m[n - 8][8] is True  # dark module


def test_separators_are_light() -> None:
    m = qr.encode(URL)
    n = len(m)
    assert not any(m[7][c] for c in range(8))
    assert not any(m[r][7] for r in range(8))
    assert not any(m[7][c] for c in range(n - 8, n))
    assert not any(m[r][n - 8] for r in range(8))
    assert not any(m[n - 8][c] for c in range(8))


def test_alignment_pattern_present_from_version_2() -> None:
    m = qr.encode(URL)  # 25 characters: version 2
    assert len(m) == 25
    assert ["".join("#" if m[16 + r][16 + c] else "." for c in range(5)) for r in range(5)] == (
        qr.ALIGN
    )
    assert qr.alignment_center(1) is None and qr.alignment_center(6) == 34


def test_known_url_size_and_version() -> None:
    assert len(qr.encode(URL, "M")) == 25  # 25 bytes: version 2-M (cap 26)
    assert len(qr.encode(URL, "L")) == 25  # version 2-L is the smallest that fits 25
    assert len(qr.encode("http://a.b/", "L")) == 21  # 11 bytes fit version 1-L


def test_deterministic() -> None:
    assert qr.encode(URL) == qr.encode(URL)
    assert qr.render_text(qr.encode(URL)) == qr.render_text(qr.encode(URL))


def test_data_positions_cover_exactly_the_data_modules() -> None:
    for version in range(1, 7):
        _, fixed = qr.function_modules(version)
        pos = qr.data_positions(fixed)
        assert len(pos) == len(set(pos))
        total = qr.BLOCK_TABLE[(version, "L")]
        codewords = total[0] + total[1] * total[2]
        remainder = 0 if version == 1 else 7
        assert len(pos) == codewords * 8 + remainder


@pytest.mark.parametrize("ec", ["L", "M"])
@pytest.mark.parametrize("n", [1, 14, 15, 26, 27, 42, 62, 84, 106])
def test_roundtrip_decodes_with_zero_syndromes(n: int, ec: str) -> None:
    text = "".join(chr(ord("a") + (i * 7) % 26) for i in range(n))
    if n > qr.capacity(6, ec):
        pytest.skip("does not fit")
    got, got_ec, _ = decode(qr.encode(text, ec))
    assert got == text and got_ec == ec


def test_roundtrip_url_and_utf8() -> None:
    assert decode(qr.encode(URL))[0] == URL
    assert decode(qr.encode("Відкрий на телефоні", "L"))[0] == "Відкрий на телефоні"


def test_too_long_raises() -> None:
    with pytest.raises(qr.QRError):
        qr.encode("z" * 200, "M")


def test_chosen_mask_has_the_lowest_penalty() -> None:
    m = qr.encode(URL)
    _, _, mask = decode(m)
    version = (len(m) - 17) // 4
    grid, fixed = qr.function_modules(version)
    scores = []
    for k in range(8):
        # undo the chosen mask, apply mask k, put its format word back
        plain = qr.apply_mask(m, fixed, mask)
        cand = qr.apply_mask(plain, fixed, k)
        qr.place_format(cand, "M", k)
        scores.append(qr.penalty(cand))
    assert scores[mask] == min(scores)
    assert scores.index(min(scores)) == mask  # ties go to the lowest index


# --- penalty and masks --------------------------------------------------------------------------


def test_run_penalty() -> None:
    assert qr._run_penalty([True] * 4 + [False] * 4) == 0
    assert qr._run_penalty([True] * 5) == 3
    assert qr._run_penalty([True] * 7) == 5


def test_finder_penalty() -> None:
    line = [False] * 4 + list(qr.FINDER_LIKE[:7]) + [False] * 4
    assert qr._finder_penalty(line) == 2 * qr.PEN_FINDER  # margin on both sides counts both ways
    assert qr._finder_penalty([False] * 20) == 0


def test_penalty_of_blank_and_checkerboard() -> None:
    n = 21
    blank = [[False] * n for _ in range(n)]
    board = [[(r + c) % 2 == 0 for c in range(n)] for r in range(n)]
    assert qr.penalty(board) < qr.penalty(blank)
    # blank: every row/col is one run of 21 (3 + 16), 20*20 blocks, balance 0 dark -> 9 steps
    assert qr.penalty(blank) == 42 * 19 + 400 * 3 + 10 * 9


def test_mask_bit_formulas() -> None:
    assert [qr.mask_bit(0, 0, c) for c in range(4)] == [True, False, True, False]
    assert [qr.mask_bit(1, r, 0) for r in range(4)] == [True, False, True, False]
    assert [qr.mask_bit(2, 0, c) for c in range(6)] == [True, False, False, True, False, False]
    assert all(qr.mask_bit(k, 0, 0) for k in range(8))
    assert not qr.mask_bit(5, 1, 1) and qr.mask_bit(7, 1, 0) is False


def test_apply_mask_is_an_involution_and_spares_function_modules() -> None:
    grid, fixed = qr.function_modules(2)
    once = qr.apply_mask(grid, fixed, 3)
    assert qr.apply_mask(once, fixed, 3) == grid
    n = len(grid)
    assert all(once[r][c] == grid[r][c] for r in range(n) for c in range(n) if fixed[r][c])


# --- renderer -----------------------------------------------------------------------------------


def test_render_text_shape_and_glyphs() -> None:
    m = qr.encode("a", "L")  # 21 modules
    text = qr.render_text(m, quiet=2)
    lines = text.split("\n")
    assert len(lines) == (21 + 4 + 1) // 2
    assert all(len(line) == 25 for line in lines)
    assert set(text) <= set(" ▀▄█\n")
    assert lines[0].strip() == ""  # quiet zone


def test_render_text_pixels_roundtrip() -> None:
    m = qr.encode(URL)
    quiet = 3
    lines = qr.render_text(m, quiet=quiet).split("\n")
    back = []
    for r in range(len(m)):
        line = lines[(r + quiet) // 2]
        row = []
        for c in range(len(m)):
            ch = line[c + quiet]
            upper = ch in "▀█"
            lower = ch in "▄█"
            row.append(lower if (r + quiet) % 2 else upper)
        back.append(row)
    assert back == m


def test_render_text_ansi_wraps_lines() -> None:
    lines = qr.render_text(qr.encode("a", "L"), ansi=True).split("\n")
    assert all(line.startswith("\x1b[30;47m") and line.endswith("\x1b[0m") for line in lines)


def test_main_prints_and_reports_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert qr.main([URL]) == 0
    assert "█" in capsys.readouterr().out
    assert qr.main(["z" * 300]) == 1
    assert "qr error" in capsys.readouterr().err
