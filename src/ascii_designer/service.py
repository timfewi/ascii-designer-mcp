"""Orchestration shared by the CLI and the MCP server (transport-independent).

source -> passes (cached) -> ASCII grid per frame -> outputs
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ascii_designer import __version__, cache
from ascii_designer.blender import runner
from ascii_designer.errors import DesignerError, EnvironmentBlockedError, SpecError
from ascii_designer.output import ansi, asciimotion
from ascii_designer.output.ffmpeg import VIDEO_PRESETS, VideoEncoder
from ascii_designer.output.grid import GridRecorder
from ascii_designer.presets import PALETTES, PRESETS
from ascii_designer.raster.colors import hex_to_linear
from ascii_designer.raster.compose import compose_linear, to_srgb8
from ascii_designer.raster.glyphs import build_char_atlas, resolve_font
from ascii_designer.raster.mapper import (
    CellFeatures,
    FrameInput,
    GlyphMapper,
    Layout,
    MapperConfig,
    MapperState,
    atlas_chars,
)
from ascii_designer.raster.passes import PassSequence, VideoSequence, ffmpeg_binary, probe_video
from ascii_designer.spec import Spec

OUTPUT_ENV = "ASCII_DESIGNER_OUTPUT_DIR"
FEATURE_CACHE_BYTES = 1_500_000_000  # per-frame cell features kept for warm-up passes
MAX_WARM_PASSES = 6
ProgressFn = Callable[[str, int, int, str], None]


def default_output_dir() -> Path:
    explicit = os.environ.get(OUTPUT_ENV)
    if explicit:
        return Path(explicit).expanduser()
    videos = os.environ.get("XDG_VIDEOS_DIR") or str(Path.home() / "Videos")
    return Path(videos).expanduser() / "ascii-designer"


@dataclass(frozen=True)
class FramePlan:
    """Which source frames make up the output, and at which rate."""

    first: int
    count: int
    fps: float
    loop: bool
    seam_frame: int | None  # frame after the last, rendered only for the seam check

    @property
    def frames(self) -> range:
        return range(self.first, self.first + self.count)

    @property
    def render_range(self) -> range:
        end = self.seam_frame if self.seam_frame is not None else self.first + self.count - 1
        return range(self.first, end + 1)


class Designer:
    def __init__(self, progress: ProgressFn | None = None) -> None:
        self._progress = progress or (lambda *_: None)

    # --- status ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        report: dict[str, Any] = {"version": __version__, "warnings": []}
        try:
            binary = runner.blender_binary()
            report["blender"] = {
                "ok": True,
                "path": binary,
                "version": runner.blender_version(binary),
            }
        except EnvironmentBlockedError as error:
            report["blender"] = {"ok": False, "error": str(error)}
        try:
            binary = ffmpeg_binary()
            encoders = subprocess.run(
                [binary, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
            ).stdout
            report["ffmpeg"] = {
                "ok": True,
                "path": binary,
                "encoders": {name: name in encoders for name in ("libx265", "libx264", "ffv1")},
            }
        except EnvironmentBlockedError as error:
            report["ffmpeg"] = {"ok": False, "error": str(error)}
        try:
            report["font"] = {"ok": True, "path": str(resolve_font(None))}
        except EnvironmentBlockedError as error:
            report["font"] = {"ok": False, "error": str(error)}
        report["cache"] = cache.usage()
        report["output_dir"] = str(default_output_dir())
        renderer_file = cache.cache_root() / "renderer.json"
        if renderer_file.is_file():
            renderer = json.loads(renderer_file.read_text(encoding="utf-8"))
            report["last_gpu_renderer"] = renderer
            if "llvmpipe" in str(renderer.get("renderer", "")).lower():
                report["warnings"].append(
                    "EEVEE rendered on llvmpipe (software GL); renders will be very slow"
                )
        return report

    # --- planning ----------------------------------------------------------------

    def plan(self, spec: Spec) -> FramePlan:
        source = spec.source
        if source.kind == "preset":
            count = spec.frame_count()
            fps = float(spec.effective_fps() or 36)
            return FramePlan(1, count, fps, spec.is_loop, count + 1 if spec.is_loop else None)
        if source.kind == "blend":
            if spec.frame_range:
                start, end = spec.frame_range
                fps = float(spec.fps) if spec.fps else self._blend_info(spec)["fps"]
            else:
                info = self._blend_info(spec)
                start, end = int(info["frame_start"]), int(info["frame_end"])
                fps = float(spec.fps or info["fps"])
            count = end - start + 1
            return FramePlan(start, count, fps, spec.is_loop, end + 1 if spec.is_loop else None)
        if source.kind == "video":
            assert source.path is not None
            info = probe_video(source.path)
            fps = float(spec.fps or info["fps"] or 30.0)
            available = int(info["duration"] * fps) if info["duration"] else spec.frame_count()
            count = max(1, min(available, round(spec.seconds * fps)))
            return FramePlan(1, count, fps, spec.is_loop, None)
        return FramePlan(1, 1, float(spec.fps or 1), False, None)

    def _blend_info(self, spec: Spec) -> dict[str, Any]:
        assert spec.source.path is not None
        version = runner.blend_file_version(spec.source.path)
        if version and version > runner.SUPPORTED_FILE_VERSION:
            raise SpecError(
                f"{spec.source.path.name} was saved by Blender {version[0]}.{version[1]}; "
                "this tool renders with Blender 5.2 and cannot open newer files reliably"
            )
        events = runner.run_job({"mode": "info"}, blend=spec.source.path)
        info = next(e for e in events if e["event"] == "info")
        if not info.get("camera"):
            raise SpecError(f"{spec.source.path.name} has no active camera")
        return info

    # --- passes --------------------------------------------------------------------

    def _pass_key(self, spec: Spec, plan: FramePlan) -> str:
        binary = runner.blender_binary()
        source = spec.source
        identity: dict[str, Any]
        if source.kind == "preset":
            assert source.preset is not None
            files = {
                key: cache.file_digest(Path(source.params[key]))
                for key in PRESETS[source.preset].path_params()
            }
            identity = {
                "preset": source.preset,
                "params": source.params,
                "files": files,
                "loop": plan.count,
            }
        else:
            assert source.path is not None
            identity = {"blend": cache.file_digest(source.path)}
        return cache.key_for(
            {
                "source": identity,
                "size": [spec.width, spec.height],
                "fps": plan.fps,
                "engine": spec.engine,
                "samples": spec.samples,
                "motion_blur": spec.motion_blur,
                "scripts": runner.script_digest(),
                "blender": runner.blender_version(binary),
            }
        )

    def _blender_job(self, spec: Spec, plan: FramePlan, **extra: Any) -> dict[str, Any]:
        source = spec.source
        job: dict[str, Any] = {
            "mode": "render",
            "width": spec.width,
            "height": spec.height,
            "fps": round(plan.fps) if source.kind == "preset" or spec.fps else None,
            "engine": spec.engine,
            "samples": spec.samples,
            "motion_blur": spec.motion_blur,
            "loop_frames": plan.count,
            "frame_start": None,
            "frame_end": None,
        }
        if source.kind == "preset":
            assert source.preset is not None
            params = dict(source.params)
            params["palette_colors"] = list(PALETTES[params.get("palette", "synthwave")])
            job["source"] = {
                "kind": "preset",
                "module": PRESETS[source.preset].module,
                "params": params,
            }
            job["frame_start"], job["frame_end"] = 1, plan.count
        else:
            job["source"] = {"kind": "blend"}
            if spec.frame_range:
                job["frame_start"], job["frame_end"] = spec.frame_range
        job.update(extra)
        return job

    def ensure_passes(self, spec: Spec, plan: FramePlan, frames: range | None = None) -> Path:
        """Render (or reuse) Blender passes; returns the pass directory."""
        directory = cache.pass_dir(self._pass_key(spec, plan))
        wanted = frames or plan.render_range
        if cache.is_complete(directory, wanted) or (
            frames is not None
            and all((directory / "beauty" / f"{f:04d}.png").is_file() for f in wanted)
        ):
            os.utime(directory)
            return directory
        directory.mkdir(parents=True, exist_ok=True)
        total = len(wanted)
        done = [0]

        def on_event(event: dict[str, Any]) -> None:
            if event.get("event") == "frame":
                done[0] += 1
                self._progress("blender", done[0], total, f"rendered frame {event['frame']}")
            elif event.get("event") == "renderer":
                (cache.cache_root() / "renderer.json").write_text(
                    json.dumps(event), encoding="utf-8"
                )

        self._progress("blender", 0, total, "starting Blender")
        job = self._blender_job(
            spec, plan, out_dir=str(directory), render_frames=[wanted.start, wanted.stop - 1]
        )
        blend = spec.source.path if spec.source.kind == "blend" else None
        events = runner.run_job(
            job, blend=blend, log_path=directory / "blender.log", progress=on_event
        )
        start = next((e for e in events if e["event"] == "start"), {})
        if frames is None:
            cache.mark_complete(directory, wanted, {"blender": start})
        return directory

    # --- frame sources --------------------------------------------------------------

    def _source(self, spec: Spec, plan: FramePlan, frames: range) -> PassSequence | VideoSequence:
        edges = spec.edges_enabled()
        if spec.source.kind in ("preset", "blend"):
            directory = self.ensure_passes(spec, plan, None if frames == plan.frames else frames)
            return PassSequence.open(directory, frames, with_edges=edges)
        assert spec.source.path is not None
        still = spec.source.kind == "image"
        return VideoSequence(
            spec.source.path, spec.width, spec.height, plan.fps, len(frames), edges, still
        )

    # --- mapping ---------------------------------------------------------------------

    def _mapper(self, spec: Spec) -> tuple[GlyphMapper, Layout]:
        style = spec.style
        config = MapperConfig(
            charset=style.charset,
            contrast=style.contrast,
            directional_contrast=style.directional_contrast,
            hysteresis=style.hysteresis,
            color_lightness=style.color_lightness,
            saturation=style.saturation,
            brightness=style.brightness,
            edges=spec.edges_enabled(),
            edge_threshold=style.edge_threshold,
            background=style.background,
        )
        font = resolve_font(style.font)
        atlas = build_char_atlas(atlas_chars(config), spec.cell_w, spec.cell_h, font)
        layout = Layout.for_size(spec.width, spec.height, spec.cell_w, spec.cell_h)
        return GlyphMapper(atlas, layout, config), layout

    def _margin(self, spec: Spec) -> np.ndarray:
        bg = spec.style.background
        return hex_to_linear(bg) if bg.startswith("#") else np.zeros(3, dtype=np.float32)

    # --- preview ------------------------------------------------------------------------

    def preview(
        self,
        spec: Spec,
        frame: int | None = None,
        crop: tuple[int, int, int, int] | None = None,
        out_dir: Path | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        plan = self.plan(spec)
        index = frame if frame is not None else plan.first
        if not plan.first <= index < plan.first + plan.count:
            raise SpecError(f"frame {index} is outside {plan.first}..{plan.first + plan.count - 1}")
        mapper, layout = self._mapper(spec)
        source = self._source(spec, plan, range(index, index + 1))
        if isinstance(source, VideoSequence) and index > 1:
            source = VideoSequence(
                source.path, source.width, source.height, source.fps, index, source.with_edges
            )
        frames = list(source)
        ascii_frame = mapper.map(frames[-1], MapperState())
        transparent = spec.style.background == "transparent"
        linear = compose_linear(
            ascii_frame, mapper.atlas, layout, self._margin(spec), spec.style.glow, transparent
        )
        image = to_srgb8(linear)
        target = (out_dir or (default_output_dir() / "previews")).resolve()
        target.mkdir(parents=True, exist_ok=True)
        stem = f"{spec.output_name()}-f{index:04d}"
        full = target / f"{stem}.png"
        Image.fromarray(image).save(full)
        x, y, w, h = crop or _default_crop(spec.width, spec.height)
        x, y = max(0, min(x, spec.width - 1)), max(0, min(y, spec.height - 1))
        crop_path = target / f"{stem}-crop.png"
        Image.fromarray(image[y : y + h, x : x + w]).save(crop_path)
        overview = Image.fromarray(image)
        overview.thumbnail((1280, 800), Image.Resampling.LANCZOS)
        overview_path = target / f"{stem}-overview.png"
        overview.save(overview_path)
        space = mapper.atlas.index.get(" ", -1)
        filled = float(np.mean(ascii_frame.glyphs != space))
        return {
            "frame": index,
            "frames": plan.count,
            "fps": plan.fps,
            "grid": {"columns": layout.cols, "rows": layout.rows},
            "filled_cells": round(filled, 3),
            "image": str(full),
            "overview": str(overview_path),
            "crop": str(crop_path),
            "crop_box": [x, y, w, h],
            "seconds": round(time.monotonic() - started, 2),
        }

    # --- render ----------------------------------------------------------------------------

    def render(self, spec: Spec) -> dict[str, Any]:
        started = time.monotonic()
        plan = self.plan(spec)
        videos = [o for o in spec.outputs if o in VIDEO_PRESETS]
        if spec.source.kind == "image" and videos:
            raise SpecError("image sources produce stills; use outputs png, ansi or asciimotion")
        mapper, layout = self._mapper(spec)
        out_dir = spec.output_dir or default_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        name = spec.output_name()

        if spec.source.kind in ("preset", "blend"):
            self.ensure_passes(spec, plan)
        state = MapperState()
        convergence: int | None = None
        cached: list[CellFeatures] | None = None
        warm_passes = 0
        if plan.loop and plan.count > 1:
            # Warm-up: the first output frame must see the state left by the last
            # one, otherwise hysteresis pops at the loop seam.
            cached, size = [], 0
            for i, frame in enumerate(self._frames(spec, plan, plan.frames)):
                features = mapper.features(frame)
                mapper.decide(features, state)
                if cached is not None:
                    cached.append(features)
                    size += features.nbytes
                    if size > FEATURE_CACHE_BYTES:
                        cached = None
                self._progress("warmup", i + 1, plan.count, "analysing frames")
            warm_passes = 1
            while cached is not None and warm_passes < MAX_WARM_PASSES:
                before = state.copy()
                for features in cached:
                    mapper.decide(features, state)
                warm_passes += 1
                if state.same_as(before) == 0:
                    break
        start_state = state.copy()

        recorder = GridRecorder(mapper.atlas.chars, layout.rows, layout.cols, plan.fps)
        encoders = [
            VideoEncoder(
                out_dir / f"{name}{VIDEO_PRESETS[o].suffix}",
                o,
                spec.width,
                spec.height,
                plan.fps,
                plan.count if plan.loop else round(plan.fps * 2),
            )
            for o in videos
        ]
        outputs: dict[str, str] = {}
        transparent = spec.style.background == "transparent"
        margin = self._margin(spec)
        try:
            frames = self._frames(spec, plan, plan.frames, edges=cached is None)
            for i, frame in enumerate(frames):
                features = cached[i] if cached is not None else mapper.features(frame)
                glyphs, edge_on = mapper.decide(features, state)
                ascii_frame = mapper.colorize(frame.rgb, glyphs, features.reference, edge_on)
                recorder.add(ascii_frame)
                if encoders or (i == 0 and "png" in spec.outputs):
                    linear = compose_linear(
                        ascii_frame, mapper.atlas, layout, margin, spec.style.glow, transparent
                    )
                    image = to_srgb8(linear)
                    for encoder in encoders:
                        encoder.write(image)
                    if i == 0 and "png" in spec.outputs:
                        path = out_dir / f"{name}.png"
                        Image.fromarray(image).save(path)
                        outputs["png"] = str(path)
                self._progress("encode", i + 1, plan.count, "mapping and encoding")
            for output, encoder in zip(videos, encoders, strict=True):
                outputs[output] = str(encoder.close())
        except BaseException:
            for encoder in encoders:
                encoder.abort()
            raise

        if "ansi" in spec.outputs:
            outputs["ansi"] = str(ansi.write_ansi(recorder, out_dir / f"{name}.ans"))
        if "asciimotion" in spec.outputs:
            path = out_dir / f"{name}.asciimotion.json"
            bg = spec.style.background if spec.style.background.startswith("#") else "#000000"
            outputs["asciimotion"] = str(asciimotion.write_session(recorder, path, name, bg))

        if plan.loop and plan.count > 1:
            convergence = state.same_as(start_state)

        seam = self._seam(spec, plan, convergence)
        grid_path = recorder.save(cache.cache_root() / "grids" / f"{name}.npz")
        return {
            "name": name,
            "outputs": outputs,
            "frames": plan.count,
            "fps": plan.fps,
            "seconds_of_video": round(plan.count / plan.fps, 3),
            "grid": {"columns": layout.cols, "rows": layout.rows, "path": str(grid_path)},
            "loop": plan.loop,
            "warmup_passes": warm_passes,
            "seam": seam,
            "elapsed_seconds": round(time.monotonic() - started, 1),
        }

    def _frames(
        self, spec: Spec, plan: FramePlan, frames: range, edges: bool = True
    ) -> Iterator[FrameInput]:
        source = self._source(spec, plan, frames)
        if not edges:
            source = dataclasses.replace(source, with_edges=False)
        if not isinstance(source, PassSequence):
            yield from source
            return
        # Decoding PNG/EXR and computing edge fields dominates; prefetch in threads.
        workers = min(4, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = [pool.submit(source.load, f) for f in frames[: workers * 2]]
            nxt = workers * 2
            for _ in range(len(frames)):
                result = pending.pop(0).result()
                if nxt < len(frames):
                    pending.append(pool.submit(source.load, frames[nxt]))
                    nxt += 1
                yield result

    def _seam(self, spec: Spec, plan: FramePlan, convergence: int | None) -> dict[str, Any] | None:
        if not plan.loop or plan.seam_frame is None:
            return None
        directory = cache.pass_dir(self._pass_key(spec, plan)) / "beauty"
        first, after = directory / f"{plan.first:04d}.png", directory / f"{plan.seam_frame:04d}.png"
        result: dict[str, Any] = {"glyph_state_mismatch": convergence}
        if first.is_file() and after.is_file():
            a = np.asarray(Image.open(first).convert("RGBA"), dtype=np.int16)
            b = np.asarray(Image.open(after).convert("RGBA"), dtype=np.int16)
            result["scene_mean_abs_diff"] = round(float(np.abs(a - b).mean()), 4)
            result["seamless"] = bool(result["scene_mean_abs_diff"] < 0.5 and not convergence)
        return result

    # --- preset -> .blend ------------------------------------------------------------------

    def preset_blend(self, spec: Spec, out: Path) -> Path:
        if spec.source.kind != "preset":
            raise SpecError("preset_blend needs a preset source")
        plan = self.plan(spec)
        out.parent.mkdir(parents=True, exist_ok=True)
        job = self._blender_job(spec, plan, mode="save_blend", blend_out=str(out.resolve()))
        runner.run_job(job)
        return out


def _default_crop(width: int, height: int) -> tuple[int, int, int, int]:
    w, h = min(640, width), min(400, height)
    return ((width - w) // 2) & ~1, ((height - h) // 2) & ~1, w, h


__all__ = ["Designer", "DesignerError", "FramePlan", "default_output_dir"]
