"""Glyph atlas: exact per-pixel coverage masks at the output cell size.

Font glyphs are rendered with FreeType hinting at the target size (grayscale
anti-aliasing, no subpixel rendering). Block elements, sextants and Braille are
drawn procedurally with exact coverage so mosaics tile without seams and do not
depend on font support.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from ascii_designer.errors import EnvironmentBlockedError, SpecError

FONT_ENV = "ASCII_DESIGNER_FONT"

_ASCII = "".join(chr(c) for c in range(32, 127))
_SYMBOLS = " .,:;'`\"^~-_=+*!?|/\\()[]{}<>#%&@$"
_BLOCK_EXTRAS = "█▀▄▌▐▖▗▘▝▚▞▙▛▜▟"
_SHADES = "░▒▓"
_SEXTANTS = "".join(chr(0x1FB00 + i) for i in range(60))
_BRAILLE = "".join(chr(0x2800 + i) for i in range(256))

CHARSET_CHARS = {
    "ascii": _ASCII,
    "symbols": _SYMBOLS,
    "blocks": " " + _BLOCK_EXTRAS + _SHADES + _SEXTANTS,
    "braille": _BRAILLE,
}
# Density ramps used for flat (unstructured) cells; the full charset is only
# used where a cell has real structure. A short ramp gives calm, even fills.
FILL_RAMPS = {
    "ascii": " .:-=+*#%@",
    "symbols": " .:-=+*#%@",
    "blocks": " ░▒▓█",
}
# Line glyphs used for 3D edges with font charsets.
EDGE_CHARS = "-|/\\_"


@dataclass(frozen=True)
class GlyphAtlas:
    chars: tuple[str, ...]
    masks: np.ndarray  # (n, cell_h, cell_w) float32 coverage 0..1
    cell_w: int
    cell_h: int
    font: str
    skipped: tuple[str, ...] = field(default=())
    index: dict[str, int] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        self.index.update({c: i for i, c in enumerate(self.chars)})

    @property
    def flat(self) -> np.ndarray:
        return self.masks.reshape(len(self.chars), -1)

    def coverage(self) -> np.ndarray:
        return self.flat.mean(axis=1)


def resolve_font(explicit: Path | None) -> Path:
    candidate = explicit or (Path(os.environ[FONT_ENV]) if os.environ.get(FONT_ENV) else None)
    if candidate is None:
        raise EnvironmentBlockedError(
            f"no font configured: set style.font or {FONT_ENV} to a monospace .ttf/.otf"
        )
    if not candidate.is_file():
        raise EnvironmentBlockedError(f"font not found: {candidate}")
    return candidate


def charset_chars(charset: str) -> str:
    if charset.startswith("custom:"):
        chars = charset.removeprefix("custom:")
        return " " + "".join(dict.fromkeys(c for c in chars if c != " "))
    if charset not in CHARSET_CHARS:
        raise SpecError(f"unknown charset {charset!r}")
    return CHARSET_CHARS[charset]


def build_atlas(charset: str, cell_w: int, cell_h: int, font: Path) -> GlyphAtlas:
    return _build_atlas(charset_chars(charset), cell_w, cell_h, str(font))


def build_char_atlas(chars: str, cell_w: int, cell_h: int, font: Path) -> GlyphAtlas:
    return _build_atlas(chars, cell_w, cell_h, str(font))


@cache
def _build_atlas(chars: str, cell_w: int, cell_h: int, font: str) -> GlyphAtlas:
    renderer = _FontRenderer(Path(font), cell_w, cell_h)
    kept: list[str] = []
    masks: list[np.ndarray] = []
    skipped: list[str] = []
    for char in dict.fromkeys(chars):
        mask = procedural_mask(char, cell_w, cell_h)
        if mask is None:
            if not renderer.supports(char):
                skipped.append(char)
                continue
            mask = renderer.render(char)
        kept.append(char)
        masks.append(mask)
    if " " not in kept:
        kept.insert(0, " ")
        masks.insert(0, np.zeros((cell_h, cell_w), dtype=np.float32))
    return GlyphAtlas(
        chars=tuple(kept),
        masks=np.stack(masks).astype(np.float32),
        cell_w=cell_w,
        cell_h=cell_h,
        font=font,
        skipped=tuple(skipped),
    )


class _FontRenderer:
    def __init__(self, path: Path, cell_w: int, cell_h: int) -> None:
        try:
            with TTFont(str(path), lazy=True, fontNumber=0) as tt:
                self._cmap = set(tt.getBestCmap() or {})
                upm = tt["head"].unitsPerEm  # pyright: ignore[reportAttributeAccessIssue]
                advance = tt["hmtx"]["M"][0]  # pyright: ignore[reportIndexIssue]
                hhea = tt["hhea"]
                height_units = hhea.ascent - hhea.descent  # pyright: ignore[reportAttributeAccessIssue]
        except Exception as error:  # fontTools raises many types for broken fonts
            raise EnvironmentBlockedError(f"cannot read font {path}: {error}") from error
        size = min(cell_w * upm / advance, cell_h * upm / height_units)
        self._font = ImageFont.truetype(str(path), size=size)
        ascent, descent = self._font.getmetrics()
        self._baseline = (cell_h - (ascent + descent)) / 2 + ascent
        self._x = (cell_w - advance * size / upm) / 2
        self._w = cell_w
        self._h = cell_h

    def supports(self, char: str) -> bool:
        return ord(char) in self._cmap

    def render(self, char: str) -> np.ndarray:
        image = Image.new("L", (self._w, self._h), 0)
        ImageDraw.Draw(image).text(
            (self._x, self._baseline), char, font=self._font, fill=255, anchor="ls"
        )
        return np.asarray(image, dtype=np.float32) / 255.0


# --- procedural mosaics -------------------------------------------------------

# Block elements as (x0, y0, x1, y1) rectangles in cell fractions, or a flat shade.
_BLOCKS: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "▀": ((0, 0, 1, 0.5),),
    "▁": ((0, 7 / 8, 1, 1),),
    "▂": ((0, 3 / 4, 1, 1),),
    "▃": ((0, 5 / 8, 1, 1),),
    "▄": ((0, 0.5, 1, 1),),
    "▅": ((0, 3 / 8, 1, 1),),
    "▆": ((0, 1 / 4, 1, 1),),
    "▇": ((0, 1 / 8, 1, 1),),
    "█": ((0, 0, 1, 1),),
    "▉": ((0, 0, 7 / 8, 1),),
    "▊": ((0, 0, 3 / 4, 1),),
    "▋": ((0, 0, 5 / 8, 1),),
    "▌": ((0, 0, 0.5, 1),),
    "▍": ((0, 0, 3 / 8, 1),),
    "▎": ((0, 0, 1 / 4, 1),),
    "▏": ((0, 0, 1 / 8, 1),),
    "▐": ((0.5, 0, 1, 1),),
    "▔": ((0, 0, 1, 1 / 8),),
    "▕": ((7 / 8, 0, 1, 1),),
    "▖": ((0, 0.5, 0.5, 1),),
    "▗": ((0.5, 0.5, 1, 1),),
    "▘": ((0, 0, 0.5, 0.5),),
    "▙": ((0, 0, 0.5, 1), (0.5, 0.5, 1, 1)),
    "▚": ((0, 0, 0.5, 0.5), (0.5, 0.5, 1, 1)),
    "▛": ((0, 0, 1, 0.5), (0, 0.5, 0.5, 1)),
    "▜": ((0, 0, 1, 0.5), (0.5, 0.5, 1, 1)),
    "▝": ((0.5, 0, 1, 0.5),),
    "▞": ((0.5, 0, 1, 0.5), (0, 0.5, 0.5, 1)),
    "▟": ((0.5, 0, 1, 1), (0, 0.5, 0.5, 1)),
}
_SHADE_LEVEL = {"░": 0.25, "▒": 0.5, "▓": 0.75}


def procedural_mask(char: str, cell_w: int, cell_h: int) -> np.ndarray | None:
    code = ord(char)
    if char in _BLOCKS:
        return _rects(_BLOCKS[char], cell_w, cell_h)
    if char in _SHADE_LEVEL:
        return np.full((cell_h, cell_w), _SHADE_LEVEL[char], dtype=np.float32)
    if 0x1FB00 <= code <= 0x1FB3B:
        return _sextant(code - 0x1FB00, cell_w, cell_h)
    if 0x2800 <= code <= 0x28FF:
        return _braille(code - 0x2800, cell_w, cell_h)
    return None


def _overlap(n: int, a: float, b: float) -> np.ndarray:
    edges = np.arange(n + 1, dtype=np.float64)
    return np.clip(np.minimum(edges[1:], b) - np.maximum(edges[:-1], a), 0.0, 1.0)


def _rects(
    rects: tuple[tuple[float, float, float, float], ...], cell_w: int, cell_h: int
) -> np.ndarray:
    mask = np.zeros((cell_h, cell_w), dtype=np.float64)
    for x0, y0, x1, y1 in rects:
        ox = _overlap(cell_w, x0 * cell_w, x1 * cell_w)
        oy = _overlap(cell_h, y0 * cell_h, y1 * cell_h)
        mask = np.maximum(mask, np.outer(oy, ox))
    return mask.astype(np.float32)


def _sextant(offset: int, cell_w: int, cell_h: int) -> np.ndarray:
    # U+1FB00.. enumerate 2x3 patterns 1..62 skipping the left (21) and right (42) columns.
    pattern = offset + 1
    if pattern >= 21:
        pattern += 1
    if pattern >= 42:
        pattern += 1
    rects = []
    for bit in range(6):
        if pattern & (1 << bit):
            col, row = bit % 2, bit // 2
            rects.append((col / 2, row / 3, (col + 1) / 2, (row + 1) / 3))
    return _rects(tuple(rects), cell_w, cell_h)


_BRAILLE_DOTS = ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3))


def _braille(bits: int, cell_w: int, cell_h: int) -> np.ndarray:
    scale = 4
    w, h = cell_w * scale, cell_h * scale
    ys, xs = np.mgrid[0:h, 0:w]
    xs = (xs + 0.5) / scale
    ys = (ys + 0.5) / scale
    radius = min(cell_w / 4, cell_h / 8) * 0.78
    hi = np.zeros((h, w), dtype=bool)
    for bit, (col, row) in enumerate(_BRAILLE_DOTS):
        if bits & (1 << bit):
            cx = (col + 0.5) * cell_w / 2
            cy = (row + 0.5) * cell_h / 4
            hi |= (xs - cx) ** 2 + (ys - cy) ** 2 <= radius**2
    return hi.reshape(cell_h, scale, cell_w, scale).mean(axis=(1, 3)).astype(np.float32)
