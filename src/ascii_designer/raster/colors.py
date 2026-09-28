"""Colour-space helpers: sRGB <-> linear light and luminance.

All mixing happens in linear light; sRGB encoding happens once per output frame.
"""

from __future__ import annotations

import numpy as np

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_ENCODE_SIZE = 16384


def _srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


_DECODE_LUT = _srgb_to_linear(np.arange(256, dtype=np.float64) / 255.0).astype(np.float32)
_ENCODE_LUT = np.clip(
    np.round(_linear_to_srgb(np.linspace(0.0, 1.0, _ENCODE_SIZE)) * 255.0), 0, 255
).astype(np.uint8)


def decode_srgb8(image: np.ndarray) -> np.ndarray:
    """uint8 sRGB -> float32 linear light."""
    return _DECODE_LUT[image]


def encode_srgb8(linear: np.ndarray) -> np.ndarray:
    """float linear light -> uint8 sRGB (clipped)."""
    index = np.clip(linear, 0.0, 1.0) * (_ENCODE_SIZE - 1) + 0.5
    return _ENCODE_LUT[index.astype(np.int32)]


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb @ LUMA


def hex_to_linear(value: str) -> np.ndarray:
    raw = value.removeprefix("#")
    srgb = np.array([int(raw[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.uint8)
    return decode_srgb8(srgb)


def linear_to_hex(rgb: np.ndarray) -> str:
    r, g, b = (int(v) for v in encode_srgb8(np.asarray(rgb, dtype=np.float32)))
    return f"#{r:02x}{g:02x}{b:02x}"


def perceptual(x: np.ndarray) -> np.ndarray:
    """Approximate display lightness used for glyph matching distances."""
    return np.power(np.clip(x, 0.0, 1.0), 1 / 2.2)


def brightness(rgb: np.ndarray) -> np.ndarray:
    """Chroma-aware brightness driving glyph density.

    Pure luminance makes saturated blues and magentas nearly empty; mixing in the
    brightest channel keeps vivid colours dense (Helmholtz-Kohlrausch-like).
    """
    return 0.35 * (rgb @ LUMA) + 0.65 * rgb.max(axis=-1)
