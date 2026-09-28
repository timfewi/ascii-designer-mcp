"""ASCII grid -> pixels: vectorized atlas blit and linear-light mixing."""

from __future__ import annotations

import numpy as np

from ascii_designer.raster.colors import encode_srgb8
from ascii_designer.raster.glyphs import GlyphAtlas
from ascii_designer.raster.mapper import AsciiFrame, Layout


def compose_linear(
    frame: AsciiFrame,
    atlas: GlyphAtlas,
    layout: Layout,
    margin: np.ndarray,
    glow: float = 0.0,
    transparent: bool = False,
) -> np.ndarray:
    """Return (H, W, 3) linear RGB, or (H, W, 4) with coverage alpha when transparent."""
    rows, cols, ch, cw = layout.rows, layout.cols, layout.cell_h, layout.cell_w
    masks = atlas.masks[frame.glyphs]  # (rows, cols, ch, cw)
    fg = frame.fg[:, :, None, None, :]
    bg = frame.bg[:, :, None, None, :]
    alpha = masks[..., None]
    cells = bg + (fg - bg) * alpha  # (rows, cols, ch, cw, 3)
    block = cells.transpose(0, 2, 1, 3, 4).reshape(rows * ch, cols * cw, 3)

    out = np.empty((layout.height, layout.width, 3), dtype=np.float32)
    out[...] = margin
    y, x = layout.off_y, layout.off_x
    out[y : y + rows * ch, x : x + cols * cw] = block
    if glow > 0:
        out = out + np.float32(glow) * bloom(out)
    if not transparent:
        return out
    coverage = np.zeros((layout.height, layout.width, 1), dtype=np.float32)
    coverage[y : y + rows * ch, x : x + cols * cw, 0] = masks.transpose(0, 2, 1, 3).reshape(
        rows * ch, cols * cw
    )
    return np.concatenate([out, coverage], axis=2)


def to_srgb8(linear: np.ndarray) -> np.ndarray:
    if linear.shape[-1] == 4:
        rgb = encode_srgb8(linear[..., :3])
        a = np.clip(np.round(linear[..., 3:] * 255.0), 0, 255).astype(np.uint8)
        return np.concatenate([rgb, a], axis=-1)
    return encode_srgb8(linear)


def bloom(image: np.ndarray, factor: int = 4, radius: int = 3) -> np.ndarray:
    """Soft phosphor glow: quarter-resolution blur of the bright parts, upsampled."""
    h, w = image.shape[:2]
    hh, ww = h // factor * factor, w // factor * factor
    small = image[:hh, :ww].reshape(hh // factor, factor, ww // factor, factor, 3).mean(axis=(1, 3))
    for _ in range(3):  # three box passes approximate a gaussian
        small = _box(_box(small, radius, axis=0), radius, axis=1)
    up = np.repeat(np.repeat(small, factor, axis=0), factor, axis=1)
    up = _box(_box(up, factor // 2, axis=0), factor // 2, axis=1)
    out = np.zeros_like(image)
    out[:hh, :ww] = up
    return out


def _box(image: np.ndarray, radius: int, axis: int) -> np.ndarray:
    if radius <= 0:
        return image
    pad = [(0, 0)] * image.ndim
    pad[axis] = (radius + 1, radius)
    padded = np.pad(image, pad, mode="edge")
    csum = np.cumsum(padded, axis=axis, dtype=np.float64)
    n = image.shape[axis]
    upper = np.take(csum, np.arange(2 * radius + 1, 2 * radius + 1 + n), axis=axis)
    lower = np.take(csum, np.arange(0, n), axis=axis)
    return ((upper - lower) / (2 * radius + 1)).astype(np.float32)
