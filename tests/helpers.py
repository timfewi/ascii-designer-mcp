"""Shared test helpers: environment gates and synthetic frames."""

from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

import numpy as np

from ascii_designer.raster.glyphs import FONT_ENV
from ascii_designer.raster.mapper import FrameInput


def font_path() -> Path:
    value = os.environ.get(FONT_ENV)
    if not value or not Path(value).is_file():
        raise unittest.SkipTest(f"{FONT_ENV} is not set to a font file (enter nix develop)")
    return Path(value)


def require_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise unittest.SkipTest(f"{name} not on PATH (environment blocker, not a failure)")
    return found


def require_blender_tests() -> None:
    if os.environ.get("ASCII_DESIGNER_BLENDER_TESTS") != "1":
        raise unittest.SkipTest("Blender tests are opt-in: set ASCII_DESIGNER_BLENDER_TESTS=1")
    require_tool("blender")


def frame(rgb: np.ndarray, edges: np.ndarray | None = None) -> FrameInput:
    rgb = rgb.astype(np.float32)
    return FrameInput(rgb=rgb, alpha=np.ones(rgb.shape[:2], dtype=np.float32), edges=edges)


def solid(height: int, width: int, value: float, color=(1.0, 1.0, 1.0)) -> np.ndarray:
    return (
        np.ones((height, width, 3), dtype=np.float32)
        * np.float32(value)
        * np.array(color, dtype=np.float32)
    )
