"""MCP server (stdio): a thin transport over `service.Designer` and `jobs`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import anyio
import anyio.from_thread
import anyio.to_thread
from mcp.server.fastmcp import Context, FastMCP, Image
from mcp.types import ToolAnnotations

from ascii_designer import __version__, jobs
from ascii_designer.presets import PALETTES, PRESETS
from ascii_designer.service import Designer, ProgressFn, default_output_dir
from ascii_designer.spec import CHARSETS, OUTPUTS, absolutize, parse_spec

INSTRUCTIONS = f"""\
ascii-designer {__version__} renders 3D scenes as truecolor ASCII animations, mainly
seamlessly looping wallpaper videos (default 1920x1200, 36 fps, HEVC).

Workflow:
1. ascii_list_presets shows built-in procedural scenes, palettes, charsets and outputs.
2. ascii_preview renders ONE frame and returns an overview plus a 1:1 crop. Iterate on
   the spec (preset params, style.charset, style.color_lightness, style.contrast,
   style.background, ...) with previews; they are fast once Blender has rendered.
3. ascii_render starts the full render as a background job; poll ascii_job until done.

Custom scenes via the Blender Lab MCP server (live Blender GUI): build and animate the
scene with its execute_blender_code tool (drivers or keyframes; Python drivers are
disabled when rendering), save it with bpy.ops.wm.save_as_mainfile(filepath=...),
then use {{"source": {{"blend": "/abs/path.blend"}}}} here. ascii_preset_to_blend exports
a built-in preset as a .blend to use as a starting point. For seamless loops the last
frame must lead into the first (frame_end + 1 == frame_start); set "loop": true.

Spec fields: source {{preset, params}} | {{blend}} | {{video}} | {{image}}, seconds, fps,
size "WxH", cell "WxH" (even), frame_range [start,end] (blend), loop, engine eevee|cycles|workbench,
samples, style{{charset {"|".join(CHARSETS)}|custom:<chars>, edges auto|on|off,
edge_threshold, contrast, directional_contrast, hysteresis, color_lightness, saturation,
brightness, background "#rrggbb"|"tint:0.15"|"transparent", glow, font}}, outputs
[{", ".join(OUTPUTS)}], output_dir, name. Paths should be absolute.
"""

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def build_server() -> FastMCP:
    server = FastMCP("ascii-designer", instructions=INSTRUCTIONS, log_level="WARNING")
    # FastMCP has no version argument; report ours instead of the SDK version.
    server._mcp_server.version = __version__  # pyright: ignore[reportPrivateUsage]

    @server.tool(name="ascii_status", title="Toolchain status", annotations=_READ_ONLY)
    def ascii_status() -> dict[str, Any]:
        """Check Blender, ffmpeg encoders, the glyph font, cache size and recent jobs."""
        report = Designer().status()
        report["jobs"] = jobs.list_jobs(limit=3)
        return report

    @server.tool(name="ascii_list_presets", title="List presets", annotations=_READ_ONLY)
    def ascii_list_presets() -> dict[str, Any]:
        """Built-in procedural scenes with parameter schemas, palettes, charsets and outputs."""
        return {
            "presets": [p.schema() for p in PRESETS.values()],
            "palettes": {name: list(colors) for name, colors in PALETTES.items()},
            "charsets": [*CHARSETS, "custom:<chars>"],
            "outputs": list(OUTPUTS),
            "default_output_dir": str(default_output_dir()),
        }

    @server.tool(
        name="ascii_preview",
        title="Preview one frame",
        annotations=_WRITES,
        structured_output=False,
    )
    async def ascii_preview(
        spec: dict[str, Any],
        ctx: Context,
        frame: int | None = None,
        crop: list[int] | None = None,
    ) -> list[Any]:
        """Render one frame of `spec` as ASCII; returns an overview image, a 1:1 crop
        (default: centred 640x400, or crop=[x, y, w, h]) and JSON with the PNG paths.
        Renders the Blender frame if it is not cached yet (cold EEVEE start: 5-30 s)."""
        parsed = parse_spec(spec, Path.cwd())
        box = _crop(crop)
        designer = Designer(_progress_bridge(ctx))
        result = await anyio.to_thread.run_sync(lambda: designer.preview(parsed, frame, box))
        return [
            Image(path=result["overview"]),
            Image(path=result["crop"]),
            json.dumps(result, indent=2),
        ]

    @server.tool(name="ascii_render", title="Start a render job", annotations=_WRITES)
    def ascii_render(spec: dict[str, Any]) -> dict[str, Any]:
        """Validate `spec` and start the full render in the background. Returns the job;
        poll ascii_job(job_id) for progress and the output paths when done."""
        base = Path.cwd()
        data = absolutize(spec, base)
        data.setdefault("output_dir", str(default_output_dir()))
        parse_spec(data, base)  # fail fast on invalid specs
        return jobs.start(data)

    @server.tool(name="ascii_job", title="Job status or cancel", annotations=_WRITES)
    def ascii_job(
        job_id: str | None = None, action: Literal["status", "cancel"] = "status"
    ) -> dict[str, Any]:
        """Status (progress, result with output paths, or error) of a render job; without
        job_id lists recent jobs. action="cancel" stops a running job."""
        if job_id is None:
            return {"jobs": jobs.list_jobs()}
        return jobs.cancel(job_id) if action == "cancel" else jobs.status(job_id)

    @server.tool(name="ascii_preset_to_blend", title="Export preset as .blend", annotations=_WRITES)
    async def ascii_preset_to_blend(spec: dict[str, Any], out: str) -> dict[str, Any]:
        """Save the preset scene of `spec` (source.preset + params, seconds, fps, size) as a
        .blend file at absolute path `out`, e.g. to open and extend it via the Blender Lab
        MCP server (bpy.ops.wm.open_mainfile)."""
        parsed = parse_spec(spec, Path.cwd())
        target = Path(out).expanduser()
        if not target.is_absolute() or target.suffix != ".blend":
            raise ValueError("out must be an absolute path ending in .blend")
        path = await anyio.to_thread.run_sync(lambda: Designer().preset_blend(parsed, target))
        return {"blend": str(path)}

    return server


def _crop(crop: list[int] | None) -> tuple[int, int, int, int] | None:
    if crop is None:
        return None
    if len(crop) != 4 or any(v < 0 for v in crop) or crop[2] == 0 or crop[3] == 0:
        raise ValueError("crop must be [x, y, width, height] with positive size")
    return crop[0], crop[1], crop[2], crop[3]


def _progress_bridge(ctx: Context) -> ProgressFn:
    def report(stage: str, done: int, total: int, message: str) -> None:
        try:
            anyio.from_thread.run(
                ctx.report_progress, float(done), float(total), f"{stage}: {message}"
            )
        except Exception:  # progress is best effort; never fail the render over it
            return

    return report


def run() -> None:
    build_server().run("stdio")
