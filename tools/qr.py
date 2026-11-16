"""Small pure-Python QR Code encoder (model 2, byte mode, versions 1-6, EC levels L and M).

The encoder returns a square matrix of booleans (``True`` = dark module, row-major, one module per
cell, no quiet zone). ``render_text`` turns a matrix into Unicode half-block text for a terminal
(two matrix rows per text line). Sizes are in modules: version ``v`` is ``4 * v + 17`` modules wide.

Run ``python tools/qr.py TEXT`` to print the code for TEXT.
"""

from __future__ import annotations

import argparse
import sys
from functools import cache

Matrix = list[list[bool]]

# --- tables (ISO/IEC 18004, versions 1-6) -------------------------------------------------------

GF_POLY = 0x11D  # x^8 + x^4 + x^3 + x^2 + 1, the GF(256) reduction polynomial
GF_SIZE = 256
MIN_VERSION = 1
MAX_VERSION = 6
EC_LEVELS = ("L", "M")
FORMAT_EC_BITS = {"L": 1, "M": 0}  # two-bit EC indicator inside the format word
FORMAT_GEN = 0x537  # BCH(15,5) generator of the format word
FORMAT_XOR = 0x5412  # mask XORed into the format word
MASK_COUNT = 8
MODE_BYTE = 0b0100
COUNT_BITS = 8  # character-count field width for versions 1-9 in byte mode
PAD_BYTES = (0xEC, 0x11)
TIMING_INDEX = 6  # row and column of the timing patterns
QUIET_ZONE = 4  # modules of light border the standard asks for

# (data codewords, EC codewords per block, number of blocks) per version and EC level.
BLOCK_TABLE: dict[tuple[int, str], tuple[int, int, int]] = {
    (1, "L"): (19, 7, 1),
    (1, "M"): (16, 10, 1),
    (2, "L"): (34, 10, 1),
    (2, "M"): (28, 16, 1),
    (3, "L"): (55, 15, 1),
    (3, "M"): (44, 26, 1),
    (4, "L"): (80, 20, 1),
    (4, "M"): (64, 18, 2),
    (5, "L"): (108, 26, 1),
    (5, "M"): (86, 24, 2),
    (6, "L"): (136, 18, 2),
    (6, "M"): (108, 16, 4),
}

# Penalty weights of the four mask rules (ISO/IEC 18004, 8.8.2).
PEN_RUN = 3
PEN_BLOCK = 3
PEN_FINDER = 40
PEN_BALANCE = 10
RUN_MIN = 5
FINDER_LIKE = (True, False, True, True, True, False, True, False, False, False, False)


class QRError(ValueError):
    """Raised when the text cannot be encoded (too long, bad EC level)."""


# --- GF(256) and Reed-Solomon -------------------------------------------------------------------


@cache
def gf_tables() -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Build the exp and log tables of GF(256) (generator 2, polynomial 0x11D).

    Returns:
        ``(exp, log)``: ``exp`` has 512 entries (so products need no modulo), ``log`` has 256.
    """
    exp = [0] * (2 * GF_SIZE)
    log = [0] * GF_SIZE
    x = 1
    for i in range(GF_SIZE - 1):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & GF_SIZE:
            x ^= GF_POLY
    for i in range(GF_SIZE - 1, 2 * GF_SIZE):
        exp[i] = exp[i - (GF_SIZE - 1)]
    return tuple(exp), tuple(log)


def gf_mul(a: int, b: int) -> int:
    """Multiply two elements of GF(256).

    Args:
        a: Element, 0..255.
        b: Element, 0..255.

    Returns:
        The product, 0..255.
    """
    if a == 0 or b == 0:
        return 0
    exp, log = gf_tables()
    return exp[log[a] + log[b]]


def rs_generator(degree: int) -> list[int]:
    """Reed-Solomon generator polynomial ``(x - a^0)...(x - a^(degree-1))``.

    Args:
        degree: Number of EC codewords (count).

    Returns:
        Coefficients from the highest power down, without the leading 1 (``degree`` values).
    """
    exp, _ = gf_tables()
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= gf_mul(c, exp[i])
        poly = nxt
    return poly[1:]


def rs_remainder(data: list[int], degree: int) -> list[int]:
    """Compute the EC codewords of one data block.

    Args:
        data: Data codewords (bytes, 0..255).
        degree: Number of EC codewords (count).

    Returns:
        ``degree`` EC codewords.
    """
    gen = rs_generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = [*rem[1:], 0]
        for i, g in enumerate(gen):
            rem[i] ^= gf_mul(g, factor)
    return rem


# --- data codewords -----------------------------------------------------------------------------


def capacity(version: int, ec: str) -> int:
    """Largest byte-mode payload of a version.

    Args:
        version: QR version, 1..6.
        ec: Error correction level, ``"L"`` or ``"M"``.

    Returns:
        Capacity in bytes (data codewords minus the 4-bit mode and 8-bit count fields).
    """
    data_cw = BLOCK_TABLE[(version, ec)][0]
    return data_cw - 2  # 12 header bits + 8 n payload bits <= 8 * data_cw


def choose_version(n_bytes: int, ec: str) -> int:
    """Pick the smallest version that holds the payload.

    Args:
        n_bytes: Payload length in bytes.
        ec: Error correction level.

    Returns:
        Version 1..6.

    Raises:
        QRError: If the payload does not fit in version 6.
    """
    if ec not in EC_LEVELS:
        raise QRError(f"EC level must be one of {EC_LEVELS}, got {ec!r}")
    for version in range(MIN_VERSION, MAX_VERSION + 1):
        if n_bytes <= capacity(version, ec):
            return version
    raise QRError(f"{n_bytes} bytes do not fit in version {MAX_VERSION}-{ec}")


def data_codewords(payload: bytes, version: int, ec: str) -> list[int]:
    """Build the padded data codeword sequence (mode, count, payload, terminator, pads).

    Args:
        payload: Bytes to encode.
        version: QR version, 1..6.
        ec: Error correction level.

    Returns:
        Exactly the number of data codewords of that version and level.
    """
    total = BLOCK_TABLE[(version, ec)][0]
    bits = f"{MODE_BYTE:04b}{len(payload):0{COUNT_BITS}b}" + "".join(f"{b:08b}" for b in payload)
    bits += "0" * min(4, total * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    words = [int(bits[i : i + 8], 2) for i in range(0, len(bits), 8)]
    pad = 0
    while len(words) < total:
        words.append(PAD_BYTES[pad % 2])
        pad += 1
    return words


def split_blocks(words: list[int], n_blocks: int) -> list[list[int]]:
    """Cut data codewords into equal blocks (versions 1-6 never need unequal blocks).

    Args:
        words: Data codewords.
        n_blocks: Number of blocks.

    Returns:
        ``n_blocks`` lists of equal length.
    """
    size = len(words) // n_blocks
    return [words[i * size : (i + 1) * size] for i in range(n_blocks)]


def interleave(version: int, ec: str, words: list[int]) -> list[int]:
    """Add EC codewords per block and interleave data then EC codewords.

    Args:
        version: QR version.
        ec: Error correction level.
        words: Padded data codewords.

    Returns:
        The final codeword sequence to place in the matrix.
    """
    _, ec_len, n_blocks = BLOCK_TABLE[(version, ec)]
    blocks = split_blocks(words, n_blocks)
    ecs = [rs_remainder(b, ec_len) for b in blocks]
    out = [b[i] for i in range(len(blocks[0])) for b in blocks]
    out += [e[i] for i in range(ec_len) for e in ecs]
    return out


# --- matrix -------------------------------------------------------------------------------------


def size_of(version: int) -> int:
    """Side length of a version.

    Args:
        version: QR version.

    Returns:
        Modules per side.
    """
    return 4 * version + 17


def format_bits(ec: str, mask: int) -> int:
    """The 15-bit format word (EC level + mask, BCH protected, XOR-masked).

    Args:
        ec: Error correction level.
        mask: Mask pattern, 0..7.

    Returns:
        The 15-bit word.
    """
    data = FORMAT_EC_BITS[ec] << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * FORMAT_GEN)
    return (data << 10 | rem) ^ FORMAT_XOR


def alignment_center(version: int) -> int | None:
    """Centre (row = column) of the single alignment pattern of versions 2-6.

    Args:
        version: QR version.

    Returns:
        Module index, or ``None`` for version 1.
    """
    return None if version == 1 else size_of(version) - 7


def _set_square(
    grid: Matrix, fixed: list[list[bool]], r0: int, c0: int, rows: list[str], dark: str = "#"
) -> None:
    """Draw a small ASCII picture into the grid and mark its cells as function modules.

    Args:
        grid: Module matrix (modified).
        fixed: Function-module flags (modified).
        r0: Top row of the picture (module index).
        c0: Left column of the picture (module index).
        rows: Picture lines; ``dark`` is a dark module, anything else light.
        dark: Character meaning dark.
    """
    n = len(grid)
    for dr, line in enumerate(rows):
        for dc, ch in enumerate(line):
            r, c = r0 + dr, c0 + dc
            if 0 <= r < n and 0 <= c < n:
                grid[r][c] = ch == dark
                fixed[r][c] = True


FINDER = ["#######", "#.....#", "#.###.#", "#.###.#", "#.###.#", "#.....#", "#######"]
ALIGN = ["#####", "#...#", "#.#.#", "#...#", "#####"]


def function_modules(version: int) -> tuple[Matrix, list[list[bool]]]:
    """Draw finders, separators, timing, alignment, dark module; reserve format areas.

    Args:
        version: QR version.

    Returns:
        ``(grid, fixed)``: module values so far and the flags of function (non-data) modules.
    """
    n = size_of(version)
    grid = [[False] * n for _ in range(n)]
    fixed = [[False] * n for _ in range(n)]
    for i in range(8, n - 8):  # timing patterns
        grid[6][i] = grid[i][6] = i % 2 == 0
        fixed[6][i] = fixed[i][6] = True
    # finders with their one-module separators (the 8x8 area is fixed, light outside the 7x7)
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        _set_square(grid, fixed, r0 - 1, c0 - 1, ["........."] * 9)
        _set_square(grid, fixed, r0, c0, FINDER)
    ac = alignment_center(version)
    if ac is not None:
        _set_square(grid, fixed, ac - 2, ac - 2, ALIGN)
    for i in range(9):  # format areas (filled later)
        fixed[8][i] = fixed[i][8] = True
    for i in range(8):
        fixed[8][n - 1 - i] = fixed[n - 1 - i][8] = True
    grid[n - 8][8] = True  # the always-dark module
    fixed[n - 8][8] = True
    return grid, fixed


def place_format(grid: Matrix, ec: str, mask: int) -> None:
    """Write both copies of the format word into the grid.

    Args:
        grid: Module matrix (modified).
        ec: Error correction level.
        mask: Mask pattern, 0..7.
    """
    n = len(grid)
    bits = format_bits(ec, mask)

    def bit(i: int) -> bool:
        """Bit ``i`` of the format word (0 = least significant)."""
        return (bits >> i) & 1 == 1

    for i in range(6):
        grid[i][8] = bit(i)
    grid[7][8] = bit(6)
    grid[8][8] = bit(7)
    grid[8][7] = bit(8)
    for i in range(9, 15):
        grid[8][14 - i] = bit(i)
    for i in range(8):
        grid[8][n - 1 - i] = bit(i)
    for i in range(8, 15):
        grid[n - 15 + i][8] = bit(i)
    grid[n - 8][8] = True


def data_positions(fixed: list[list[bool]]) -> list[tuple[int, int]]:
    """List the data module coordinates in placement order (zigzag from the bottom right).

    Args:
        fixed: Function-module flags.

    Returns:
        ``(row, col)`` pairs of every non-function module.
    """
    n = len(fixed)
    out: list[tuple[int, int]] = []
    upward = True
    for pair in range(n - 1, 0, -2):
        right = pair - 1 if pair <= TIMING_INDEX else pair  # skip the vertical timing column
        rows = range(n - 1, -1, -1) if upward else range(n)
        for r in rows:
            for c in (right, right - 1):
                if not fixed[r][c]:
                    out.append((r, c))
        upward = not upward
    return out


def mask_bit(mask: int, r: int, c: int) -> bool:
    """Whether mask pattern ``mask`` flips the module at (r, c).

    Args:
        mask: Mask pattern, 0..7.
        r: Row.
        c: Column.

    Returns:
        ``True`` if the module is inverted.
    """
    rules = (
        (r + c) % 2 == 0,
        r % 2 == 0,
        c % 3 == 0,
        (r + c) % 3 == 0,
        (r // 2 + c // 3) % 2 == 0,
        (r * c) % 2 + (r * c) % 3 == 0,
        ((r * c) % 2 + (r * c) % 3) % 2 == 0,
        ((r + c) % 2 + (r * c) % 3) % 2 == 0,
    )
    return rules[mask]


def apply_mask(grid: Matrix, fixed: list[list[bool]], mask: int) -> Matrix:
    """Return a copy of the grid with the mask applied to data modules only.

    Args:
        grid: Module matrix with data placed.
        fixed: Function-module flags.
        mask: Mask pattern, 0..7.

    Returns:
        A new matrix.
    """
    n = len(grid)
    return [
        [grid[r][c] ^ (not fixed[r][c] and mask_bit(mask, r, c)) for c in range(n)]
        for r in range(n)
    ]


# --- mask choice --------------------------------------------------------------------------------


def _run_penalty(line: list[bool]) -> int:
    """Rule 1 for one row or column: runs of five or more equal modules.

    Args:
        line: Modules of one row or column.

    Returns:
        Penalty points.
    """
    total, run = 0, 1
    for prev, cur in zip(line, line[1:], strict=False):
        run = run + 1 if cur == prev else 1
        if run == RUN_MIN:
            total += PEN_RUN
        elif run > RUN_MIN:
            total += 1
    return total


def _finder_penalty(line: list[bool]) -> int:
    """Rule 3 for one row or column: finder-like 1:1:3:1:1 patterns with a light margin.

    Args:
        line: Modules of one row or column.

    Returns:
        Penalty points.
    """
    k = len(FINDER_LIKE)
    rev = FINDER_LIKE[::-1]
    total = 0
    for i in range(len(line) - k + 1):
        window = tuple(line[i : i + k])
        if window in (FINDER_LIKE, rev):
            total += PEN_FINDER
    return total


def penalty(grid: Matrix) -> int:
    """Total mask penalty score (ISO/IEC 18004, 8.8.2); lower is better.

    Args:
        grid: Complete matrix.

    Returns:
        Penalty points (sum of the four rules).
    """
    n = len(grid)
    cols = [[grid[r][c] for r in range(n)] for c in range(n)]
    total = sum(_run_penalty(line) + _finder_penalty(line) for line in (*grid, *cols))
    for r in range(n - 1):
        for c in range(n - 1):
            if grid[r][c] == grid[r][c + 1] == grid[r + 1][c] == grid[r + 1][c + 1]:
                total += PEN_BLOCK
    dark = sum(sum(row) for row in grid)
    steps = -(-abs(dark * 20 - n * n * 10) // (n * n)) - 1
    return total + PEN_BALANCE * max(steps, 0)


# --- public API ---------------------------------------------------------------------------------


def encode_bytes(payload: bytes, ec: str = "M") -> Matrix:
    """Encode bytes as a QR code (smallest version 1-6, best mask by penalty score).

    Args:
        payload: Bytes to encode.
        ec: Error correction level, ``"L"`` or ``"M"``.

    Returns:
        Square matrix of bools, ``True`` = dark; no quiet zone.

    Raises:
        QRError: If the payload is too long or ``ec`` is unknown.
    """
    version = choose_version(len(payload), ec)
    words = interleave(version, ec, data_codewords(payload, version, ec))
    grid, fixed = function_modules(version)
    bits = [(w >> s) & 1 == 1 for w in words for s in range(7, -1, -1)]
    for i, (r, c) in enumerate(data_positions(fixed)):
        grid[r][c] = bits[i] if i < len(bits) else False
    candidates = []
    for mask in range(MASK_COUNT):
        cand = apply_mask(grid, fixed, mask)
        place_format(cand, ec, mask)
        candidates.append(cand)
    return min(candidates, key=penalty)  # first minimum wins: deterministic


def encode(text: str, ec: str = "M") -> Matrix:
    """Encode text (UTF-8, byte mode) as a QR code.

    Args:
        text: Text to encode.
        ec: Error correction level, ``"L"`` or ``"M"``.

    Returns:
        Square matrix of bools, ``True`` = dark; no quiet zone.
    """
    return encode_bytes(text.encode("utf-8"), ec)


def render_text(matrix: Matrix, quiet: int = QUIET_ZONE, ansi: bool = False) -> str:
    """Render a matrix as text, two module rows per line, with Unicode half blocks.

    Args:
        matrix: Square matrix, ``True`` = dark.
        quiet: Light border width in modules, added on every side.
        ansi: Paint black on white with ANSI colours so the code scans on any terminal theme.
            Without it dark modules are drawn as filled blocks and light ones as spaces.

    Returns:
        Text lines joined with newlines (no trailing newline).
    """
    n = len(matrix)
    side = n + 2 * quiet

    def dark(r: int, c: int) -> bool:
        """Whether module (r, c) of the bordered picture is dark."""
        r, c = r - quiet, c - quiet
        return 0 <= r < n and 0 <= c < n and matrix[r][c]

    glyph = {(False, False): " ", (True, False): "▀", (False, True): "▄"}
    lines = []
    for r in range(0, side, 2):
        row = "".join(glyph.get((dark(r, c), dark(r + 1, c)), "█") for c in range(side))
        lines.append(f"\x1b[30;47m{row}\x1b[0m" if ansi else row)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point: print the QR code of a text.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 on success, 1 if the text is too long.
    """
    ap = argparse.ArgumentParser(description="Print a QR code in the terminal")
    ap.add_argument("text", help="text to encode (UTF-8)")
    ap.add_argument("--ec", choices=EC_LEVELS, default="M", help="error correction level")
    ap.add_argument("--ansi", action="store_true", help="black on white with ANSI colours")
    args = ap.parse_args(argv)
    try:
        matrix = encode(args.text, args.ec)
    except QRError as err:
        print(f"qr error: {err}", file=sys.stderr)
        return 1
    print(render_text(matrix, ansi=args.ansi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
