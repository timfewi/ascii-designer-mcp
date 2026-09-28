"""Command line interface: `ascii-designer-mcp <command>`.

Diagnostics go to stderr; machine-readable results go to stdout as JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ascii_designer import __version__, cache
from ascii_designer.errors import DesignerError, EnvironmentBlockedError
from ascii_designer.presets import PALETTES, PRESETS
from ascii_designer.service import OUTPUT_ENV, Designer
from ascii_designer.spec import OUTPUTS, Spec, load_spec_file, parse_spec

EXIT_FAILED = 1
EXIT_BLOCKED = 3


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.handler(args) or 0)
    except EnvironmentBlockedError as error:
        print(f"blocked: {error}", file=sys.stderr)
        return EXIT_BLOCKED
    except DesignerError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ascii-designer-mcp",
        description="Render Blender 3D scenes as truecolor ASCII animations (wallpapers).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    status = sub.add_parser("status", help="check Blender, ffmpeg, font and cache")
    status.set_defaults(handler=_status)

    presets = sub.add_parser("presets", help="list built-in scenes and their parameters")
    presets.set_defaults(handler=_presets)

    preview = sub.add_parser("preview", help="render one frame to PNG (overview + 1:1 crop)")
    _spec_arguments(preview)
    preview.add_argument("--frame", type=int, help="source frame (default: first)")
    preview.add_argument("--crop", help="1:1 crop box x,y,w,h (default: centred 640x400)")
    preview.set_defaults(handler=_preview)

    render = sub.add_parser("render", help="render the full animation and outputs")
    _spec_arguments(render)
    render.add_argument("--progress", type=Path, help="append JSON progress lines to this file")
    render.add_argument("--result", type=Path, help="write the JSON result to this file")
    render.set_defaults(handler=_render)

    blend = sub.add_parser("preset-blend", help="save a preset scene as .blend for live editing")
    _spec_arguments(blend)
    blend.add_argument("--out", type=Path, required=True, help="target .blend path")
    blend.set_defaults(handler=_preset_blend)

    cache_cmd = sub.add_parser("cache", help="show or prune the pass cache")
    cache_cmd.add_argument("action", choices=("info", "prune"))
    cache_cmd.add_argument("--older-than", type=float, default=0.0, help="days (prune only)")
    cache_cmd.set_defaults(handler=_cache)

    mcp = sub.add_parser("mcp", help="run the MCP server on stdio")
    mcp.add_argument("--output-dir", type=Path, help="default directory for rendered files")
    mcp.add_argument("--cache-dir", type=Path, help="pass cache, grids and job state")
    mcp.set_defaults(handler=_mcp)
    return parser


def _spec_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "spec",
        nargs="?",
        help="spec file (.toml/.json), inline JSON, or a preset name",
    )
    parser.add_argument("--preset", help="use a built-in preset as source")
    parser.add_argument("--blend", help="use a .blend file as source")
    parser.add_argument("--video", help="use a video file as source")
    parser.add_argument("--image", help="use an image file as source")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="preset parameter (JSON value), repeatable",
    )
    parser.add_argument(
        "--style",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="style setting (JSON value), repeatable",
    )
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--size", help="output size, e.g. 1920x1200")
    parser.add_argument("--cell", help="cell size in pixels, e.g. 10x20")
    parser.add_argument("--engine", choices=("eevee", "cycles", "workbench"))
    parser.add_argument("--samples", type=int)
    parser.add_argument("--charset", help="symbols | ascii | blocks | braille | custom:<chars>")
    parser.add_argument("--outputs", help=f"comma separated: {','.join(OUTPUTS)}")
    parser.add_argument("-o", "--output-dir", help="directory for rendered files")
    parser.add_argument("--name", help="base name of output files")


def build_spec(args: argparse.Namespace) -> Spec:
    data: dict[str, Any] = {}
    base = Path.cwd()
    if args.spec:
        candidate = Path(args.spec)
        if candidate.suffix in (".toml", ".json") and candidate.is_file():
            data = load_spec_file(candidate)
            base = candidate.resolve().parent
        elif args.spec.lstrip().startswith("{"):
            data = json.loads(args.spec)
        elif args.spec in PRESETS:
            data = {"source": {"preset": args.spec}}
        else:
            raise DesignerError(f"spec {args.spec!r} is neither a file, JSON nor a preset name")
    for kind in ("preset", "blend", "video", "image"):
        value = getattr(args, kind)
        if value:
            data["source"] = {kind: value}
    if args.param:
        raw = data.get("source")
        source: dict[str, Any] = {"preset": raw} if isinstance(raw, str) else dict(raw or {})
        params = dict(source.get("params") or {})
        params.update(_pairs(args.param, "--param"))
        source["params"] = params
        data["source"] = source
    if args.style:
        style = dict(data.get("style") or {})
        style.update(_pairs(args.style, "--style"))
        data["style"] = style
    if args.charset:
        data.setdefault("style", {})["charset"] = args.charset
    for key in ("seconds", "fps", "size", "cell", "engine", "samples", "name"):
        value = getattr(args, key)
        if value is not None:
            data[key] = value
    if args.outputs:
        data["outputs"] = [o.strip() for o in args.outputs.split(",") if o.strip()]
    if args.output_dir:
        data["output_dir"] = args.output_dir
    return parse_spec(data, base)


def _pairs(items: list[str], flag: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise DesignerError(f"{flag} expects KEY=VALUE, got {item!r}")
        try:
            result[key] = json.loads(raw)
        except json.JSONDecodeError:
            result[key] = raw
    return result


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _stderr_progress(stage: str, done: int, total: int, message: str) -> None:
    print(f"\r[{stage}] {done}/{total} {message}\x1b[K", end="", file=sys.stderr, flush=True)
    if done >= total:
        print(file=sys.stderr)


def _status(_args: argparse.Namespace) -> int:
    report = Designer().status()
    _print(report)
    ok = all(report[k].get("ok") for k in ("blender", "ffmpeg", "font"))
    return 0 if ok else EXIT_BLOCKED


def _presets(_args: argparse.Namespace) -> int:
    _print(
        {
            "presets": [p.schema() for p in PRESETS.values()],
            "palettes": {name: list(colors) for name, colors in PALETTES.items()},
        }
    )
    return 0


def _preview(args: argparse.Namespace) -> int:
    spec = build_spec(args)
    crop = None
    if args.crop:
        try:
            x, y, w, h = (int(v) for v in args.crop.split(","))
        except ValueError as error:
            raise DesignerError("--crop expects x,y,w,h") from error
        crop = (x, y, w, h)
    out = Path(args.output_dir) if args.output_dir else None
    _print(Designer(_stderr_progress).preview(spec, args.frame, crop, out))
    return 0


def _render(args: argparse.Namespace) -> int:
    spec = build_spec(args)
    progress_file = args.progress.open("a", encoding="utf-8") if args.progress else None

    def progress(stage: str, done: int, total: int, message: str) -> None:
        _stderr_progress(stage, done, total, message)
        if progress_file:
            record = {"stage": stage, "done": done, "total": total, "message": message}
            progress_file.write(json.dumps(record) + "\n")
            progress_file.flush()

    try:
        result = Designer(progress).render(spec)
    finally:
        if progress_file:
            progress_file.close()
    if args.result:
        args.result.write_text(json.dumps(result, indent=2), encoding="utf-8")
    _print(result)
    return 0


def _preset_blend(args: argparse.Namespace) -> int:
    spec = build_spec(args)
    path = Designer(_stderr_progress).preset_blend(spec, args.out)
    _print({"blend": str(path.resolve())})
    return 0


def _cache(args: argparse.Namespace) -> int:
    _print(cache.usage() if args.action == "info" else cache.prune(args.older_than))
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from ascii_designer.mcp_server import run  # noqa: PLC0415 - keeps other commands fast

    # Environment variables are what the service, cache and job children read.
    if args.output_dir:
        os.environ[OUTPUT_ENV] = str(args.output_dir.expanduser().resolve())
    if args.cache_dir:
        os.environ[cache.CACHE_ENV] = str(args.cache_dir.expanduser().resolve())

    run()
    return 0
