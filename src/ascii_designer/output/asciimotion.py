"""ASCII Motion session export (open via "Import session" in ascii-motion.app).

Writes the v1.0.0 session shape that ASCII Motion's importer detects and
migrates to its current v2 format (checked against src/utils/sessionImporter.ts
and sessionMigration.ts in github.com/CameronFoxly/Ascii-Motion): frames carry a
duration in milliseconds and cells keyed "x,y" with char, color and bgColor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ascii_designer.errors import SpecError
from ascii_designer.output.grid import GridRecorder

# Larger sessions make the browser editor sluggish or run out of memory.
CELL_BUDGET = 600_000


def _hex(rgb: np.ndarray) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(v) for v in rgb))


def session(
    grid: GridRecorder, name: str, background: str, budget: int = CELL_BUDGET
) -> dict[str, Any]:
    space = grid.chars.index(" ") if " " in grid.chars else -1
    total = sum(int(np.count_nonzero(g != space)) for g in grid.glyphs)
    if total > budget:
        raise SpecError(
            f"ASCII Motion export would contain {total} cells (limit {budget}); "
            "use fewer columns (larger style cell) or fewer seconds for this output"
        )
    duration = 1000.0 / grid.fps
    frames = []
    for index in range(len(grid)):
        glyphs, fg, bg = grid.glyphs[index], grid.fg[index], grid.bg[index]
        ys, xs = np.nonzero(glyphs != space)
        data = {
            f"{x},{y}": {
                "char": grid.chars[int(glyphs[y, x])],
                "color": _hex(fg[y, x]),
                "bgColor": _hex(bg[y, x]),
            }
            for y, x in zip(ys.tolist(), xs.tolist(), strict=True)
        }
        frames.append(
            {
                "id": f"frame-{index + 1}",
                "name": f"Frame {index + 1}",
                "duration": duration,
                "data": data,
            }
        )
    return {
        "version": "1.0.0",
        "name": name,
        "canvas": {
            "width": grid.cols,
            "height": grid.rows,
            "canvasBackgroundColor": background,
            "showGrid": False,
        },
        "animation": {
            "frames": frames,
            "currentFrameIndex": 0,
            "frameRate": grid.fps,
            "looping": True,
        },
        "tools": {
            "activeTool": "pencil",
            "selectedColor": "#ffffff",
            "selectedBgColor": background,
        },
    }


def write_session(grid: GridRecorder, path: Path, name: str, background: str) -> Path:
    path.write_text(
        json.dumps(session(grid, name, background), separators=(",", ":")), encoding="utf-8"
    )
    return path
