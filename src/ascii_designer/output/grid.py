"""The ASCII grid as the explicit intermediate: glyph, fg and bg per cell and frame.

Every text export (ANSI, ASCII Motion) derives from it, and it is saved next to
the pass cache so re-exports never re-run the matcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ascii_designer.raster.colors import encode_srgb8
from ascii_designer.raster.mapper import AsciiFrame


@dataclass
class GridRecorder:
    chars: tuple[str, ...]
    rows: int
    cols: int
    fps: float
    glyphs: list[np.ndarray] = field(default_factory=list)
    fg: list[np.ndarray] = field(default_factory=list)
    bg: list[np.ndarray] = field(default_factory=list)

    def add(self, frame: AsciiFrame) -> None:
        self.glyphs.append(frame.glyphs.astype(np.uint16))
        self.fg.append(encode_srgb8(frame.fg))
        self.bg.append(encode_srgb8(frame.bg))

    def __len__(self) -> int:
        return len(self.glyphs)

    def text(self, index: int) -> list[str]:
        lookup = np.array(self.chars)
        return ["".join(row) for row in lookup[self.glyphs[index]]]

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            chars=np.array(self.chars),
            fps=np.array(self.fps),
            glyphs=np.stack(self.glyphs),
            fg=np.stack(self.fg),
            bg=np.stack(self.bg),
        )
        return path

    @classmethod
    def load(cls, path: Path) -> GridRecorder:
        with np.load(path) as data:
            glyphs = data["glyphs"]
            return cls(
                chars=tuple(str(c) for c in data["chars"]),
                rows=int(glyphs.shape[1]),
                cols=int(glyphs.shape[2]),
                fps=float(data["fps"]),
                glyphs=list(glyphs),
                fg=list(data["fg"]),
                bg=list(data["bg"]),
            )
