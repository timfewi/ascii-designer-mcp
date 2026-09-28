"""Truecolor ANSI text export of one frame (view with `cat file.ans`)."""

from __future__ import annotations

from pathlib import Path

from ascii_designer.output.grid import GridRecorder

RESET = "\x1b[0m"


def frame_to_ansi(grid: GridRecorder, index: int, background: bool = True) -> str:
    glyphs, fg, bg = grid.glyphs[index], grid.fg[index], grid.bg[index]
    lines = []
    for y in range(grid.rows):
        parts: list[str] = []
        last_fg: tuple[int, ...] | None = None
        last_bg: tuple[int, ...] | None = None
        for x in range(grid.cols):
            char = grid.chars[int(glyphs[y, x])]
            color = tuple(int(v) for v in fg[y, x])
            back = tuple(int(v) for v in bg[y, x])
            if background and back != last_bg:
                parts.append("\x1b[48;2;{};{};{}m".format(*back))
                last_bg = back
            if char != " " and color != last_fg:
                parts.append("\x1b[38;2;{};{};{}m".format(*color))
                last_fg = color
            parts.append(char)
        lines.append("".join(parts) + RESET)
    return "\n".join(lines) + "\n"


def write_ansi(grid: GridRecorder, path: Path, index: int = 0) -> Path:
    path.write_text(frame_to_ansi(grid, index), encoding="utf-8")
    return path
