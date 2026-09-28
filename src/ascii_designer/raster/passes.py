"""Frame sources: rendered Blender passes, videos and still images -> FrameInput."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import OpenEXR
from PIL import Image

from ascii_designer.errors import EnvironmentBlockedError, RenderError
from ascii_designer.raster.colors import decode_srgb8, luminance
from ascii_designer.raster.edges import geometry_edges, luminance_edges
from ascii_designer.raster.mapper import FrameInput


def load_beauty(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """RGBA PNG -> (premultiplied linear RGB, alpha)."""
    with Image.open(path) as image:
        rgba = np.asarray(image.convert("RGBA"))
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    rgb = decode_srgb8(rgba[..., :3]) * alpha[..., None]
    return rgb, alpha


def load_data(path: Path, shape: tuple[int, int]) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Multilayer EXR with `depth.V` and `normal.X/Y/Z` -> (depth, normal)."""
    depth = normal = None
    with OpenEXR.File(str(path), separate_channels=True) as exr:
        channels: dict[str, np.ndarray] = {}
        for part in exr.parts:
            for name, channel in part.channels.items():
                channels[name] = np.asarray(channel.pixels, dtype=np.float32)
    if "depth.V" in channels:
        depth = channels["depth.V"]
    if all(f"normal.{a}" in channels for a in "XYZ"):
        normal = np.stack([channels[f"normal.{a}"] for a in "XYZ"], axis=-1)
    for array in (depth, normal):
        if array is not None and array.shape[:2] != shape:
            raise RenderError(f"pass {path.name} has size {array.shape[:2]}, expected {shape}")
    return depth, normal


@dataclass(frozen=True)
class PassSequence:
    """Blender pass directory produced by render_passes.py."""

    directory: Path
    frames: tuple[int, ...]
    with_edges: bool = True

    @classmethod
    def open(cls, directory: Path, frames: range, with_edges: bool = True) -> PassSequence:
        missing = [f for f in frames if not (directory / "beauty" / f"{f:04d}.png").is_file()]
        if missing:
            raise RenderError(f"missing rendered frames in {directory}: {missing[:5]}")
        return cls(directory, tuple(frames), with_edges)

    def __len__(self) -> int:
        return len(self.frames)

    def load(self, frame: int) -> FrameInput:
        rgb, alpha = load_beauty(self.directory / "beauty" / f"{frame:04d}.png")
        edges = None
        if self.with_edges:
            data = self.directory / "data" / f"{frame:04d}.exr"
            depth, normal = load_data(data, alpha.shape) if data.is_file() else (None, None)
            if depth is not None:
                if normal is None:
                    normal = np.zeros((*alpha.shape, 3), dtype=np.float32)
                edges = geometry_edges(depth, normal, alpha)
            else:
                edges = luminance_edges(luminance(rgb))
        return FrameInput(rgb=rgb, alpha=alpha, edges=edges)

    def __iter__(self) -> Iterator[FrameInput]:
        for frame in self.frames:
            yield self.load(frame)


def ffmpeg_binary() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise EnvironmentBlockedError("ffmpeg not found on PATH")
    return found


def probe_video(path: Path) -> dict[str, float]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise EnvironmentBlockedError("ffprobe not found on PATH")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames,duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RenderError(f"cannot probe video {path}: {result.stderr.strip()[-400:]}")
    info = json.loads(result.stdout)
    stream = (info.get("streams") or [{}])[0]
    num, _, den = str(stream.get("r_frame_rate", "30/1")).partition("/")
    fps = float(num) / float(den or 1)
    duration = float(stream.get("duration") or info.get("format", {}).get("duration") or 0.0)
    return {
        "width": stream.get("width", 0),
        "height": stream.get("height", 0),
        "fps": fps,
        "duration": duration,
    }


@dataclass(frozen=True)
class VideoSequence:
    """Decodes a video (or still image) with ffmpeg, cover-fitted to the output size."""

    path: Path
    width: int
    height: int
    fps: float
    count: int
    with_edges: bool = False
    still: bool = False

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[FrameInput]:
        fit = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={self.width}:{self.height}"
        )
        args = [ffmpeg_binary(), "-v", "error", "-nostdin"]
        if self.still:
            args += ["-loop", "1", "-i", str(self.path), "-vf", fit, "-frames:v", str(self.count)]
        else:
            args += ["-i", str(self.path), "-vf", f"fps={self.fps},{fit}"]
            args += ["-frames:v", str(self.count)]
        args += ["-pix_fmt", "rgba", "-f", "rawvideo", "-"]
        size = self.width * self.height * 4
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdout is not None
        produced = 0
        try:
            while produced < self.count:
                buffer = process.stdout.read(size)
                if len(buffer) < size:
                    break
                produced += 1
                rgba = np.frombuffer(buffer, dtype=np.uint8).reshape(self.height, self.width, 4)
                alpha = rgba[..., 3].astype(np.float32) / 255.0
                rgb = decode_srgb8(rgba[..., :3]) * alpha[..., None]
                edges = luminance_edges(luminance(rgb)) if self.with_edges else None
                yield FrameInput(rgb=rgb, alpha=alpha, edges=edges)
        finally:
            process.stdout.close()
            stderr = ""
            if process.stderr is not None:
                stderr = process.stderr.read().decode(errors="replace")
                process.stderr.close()
            code = process.wait()
        if produced == 0:
            raise RenderError(f"ffmpeg could not decode {self.path}: {stderr.strip()[-400:]}")
        if code not in (0, -13) and produced < self.count:  # -13: SIGPIPE after early stop
            raise RenderError(f"ffmpeg failed decoding {self.path}: {stderr.strip()[-400:]}")
