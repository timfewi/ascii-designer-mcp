"""Video encoders: raw RGB frames piped into ffmpeg.

`wallpaper` is HEVC Main10 4:2:0 (hardware-decodable by common GPU video engines)
with a closed GOP whose keyframe interval equals the loop length, so every loop
starts on an IDR frame and the wrap is clean.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ascii_designer.errors import RenderError
from ascii_designer.raster.passes import ffmpeg_binary

_COLOR_TAGS = [
    "-colorspace",
    "bt709",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "iec61966-2-1",
    "-color_range",
    "tv",
]
_TO_YUV = "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int"


def _hevc(pix_fmt: str, profile: str) -> Callable[[int], list[str]]:
    def build(gop: int) -> list[str]:
        params = f"keyint={gop}:min-keyint={gop}:no-open-gop=1:aq-mode=3:log-level=error"
        return [
            "-vf",
            f"{_TO_YUV},format={pix_fmt}",
            "-c:v",
            "libx265",
            "-profile:v",
            profile,
            "-preset",
            "slow",
            "-crf",
            "16",
            "-x265-params",
            params,
            *_COLOR_TAGS,
            "-tag:v",
            "hvc1",
            "-movflags",
            "+faststart",
        ]

    return build


def _h264(gop: int) -> list[str]:
    return [
        "-vf",
        f"{_TO_YUV},format=yuv420p",
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-preset",
        "slow",
        "-crf",
        "16",
        "-tune",
        "animation",
        "-g",
        str(gop),
        "-keyint_min",
        str(gop),
        "-sc_threshold",
        "0",
        *_COLOR_TAGS,
        "-movflags",
        "+faststart",
    ]


def _master(gop: int) -> list[str]:
    del gop  # every FFV1 frame is intra
    return ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "rgb24", "-g", "1"]


@dataclass(frozen=True)
class VideoPreset:
    suffix: str
    description: str
    build: Callable[[int], list[str]]


VIDEO_PRESETS: dict[str, VideoPreset] = {
    "wallpaper": VideoPreset(
        ".mp4", "HEVC Main10 4:2:0, hardware decodable", _hevc("yuv420p10le", "main10")
    ),
    "wallpaper444": VideoPreset(
        ".444.mp4",
        "HEVC 4:4:4 10-bit, no chroma bleed (software decode)",
        _hevc("yuv444p10le", "main444-10"),
    ),
    "h264": VideoPreset(".h264.mp4", "H.264 High 4:2:0 for compatibility", _h264),
    "master": VideoPreset(".master.mkv", "Lossless FFV1 RGB master", _master),
}


class VideoEncoder:
    def __init__(self, path: Path, preset: str, width: int, height: int, fps: float, gop: int):
        self.path = path
        self.frames = 0
        spec = VIDEO_PRESETS[preset]
        path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            f"{fps:g}",
            "-i",
            "-",
            *spec.build(max(1, gop)),
            "-an",
            str(path),
        ]
        self._process = subprocess.Popen(argv, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, frame: np.ndarray) -> None:
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(np.ascontiguousarray(frame[..., :3]).tobytes())
        except BrokenPipeError as error:
            raise RenderError(
                f"ffmpeg stopped while writing {self.path}: {self._stderr()}"
            ) from error
        self.frames += 1

    def close(self) -> Path:
        assert self._process.stdin is not None
        self._process.stdin.close()
        code = self._process.wait()
        stderr = self._stderr()
        if code != 0:
            raise RenderError(f"ffmpeg failed writing {self.path}: {stderr}")
        return self.path

    def abort(self) -> None:
        if self._process.poll() is None:
            self._process.kill()
            self._process.wait()
        for pipe in (self._process.stdin, self._process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()
        self.path.unlink(missing_ok=True)

    def _stderr(self) -> str:
        if self._process.stderr is None or self._process.stderr.closed:
            return ""
        text = self._process.stderr.read().decode(errors="replace").strip()[-600:]
        self._process.stderr.close()
        return text
