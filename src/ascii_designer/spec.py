"""Job specification shared by the CLI (TOML/JSON files) and the MCP server (JSON objects).

A spec is parsed once into frozen dataclasses; every later stage trusts it.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, cast

from ascii_designer.errors import SpecError
from ascii_designer.presets import PRESETS, validate_params

SourceKind = Literal["preset", "blend", "video", "image"]
Engine = Literal["eevee", "cycles", "workbench"]

ENGINES: tuple[Engine, ...] = ("eevee", "cycles", "workbench")
CHARSETS = ("symbols", "ascii", "blocks", "braille")
OUTPUTS = ("wallpaper", "wallpaper444", "h264", "master", "png", "ansi", "asciimotion")
EDGE_MODES = ("auto", "on", "off")
DEFAULT_PRESET_FPS = 36  # four refreshes per frame on a 144 Hz panel

_SIZE = re.compile(r"^(\d{1,5})x(\d{1,5})$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Source:
    kind: SourceKind
    preset: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def label(self) -> str:
        if self.kind == "preset":
            return str(self.preset)
        return self.path.stem if self.path else self.kind


@dataclass(frozen=True)
class Style:
    charset: str = "symbols"
    edges: str = "auto"
    edge_threshold: float = 0.1
    contrast: float = 1.8
    directional_contrast: float = 1.0
    hysteresis: float = 0.15
    color_lightness: float = 0.5
    saturation: float = 1.15
    brightness: float = 1.0
    background: str = "#000000"
    glow: float = 0.0
    font: Path | None = None

    def charset_name(self) -> str:
        return "custom" if self.charset.startswith("custom:") else self.charset


@dataclass(frozen=True)
class Spec:
    source: Source
    seconds: float = 12.0
    fps: int | None = None
    width: int = 1920
    height: int = 1200
    cell_w: int = 10
    cell_h: int = 20
    frame_range: tuple[int, int] | None = None
    loop: bool | None = None
    engine: Engine = "eevee"
    samples: int = 32
    motion_blur: bool = True
    style: Style = field(default_factory=Style)
    outputs: tuple[str, ...] = ("wallpaper",)
    output_dir: Path | None = None
    name: str | None = None

    @property
    def columns(self) -> int:
        return self.width // self.cell_w

    @property
    def rows(self) -> int:
        return self.height // self.cell_h

    @property
    def is_loop(self) -> bool:
        return self.loop if self.loop is not None else self.source.kind == "preset"

    def effective_fps(self) -> int | None:
        if self.fps is not None:
            return self.fps
        return DEFAULT_PRESET_FPS if self.source.kind == "preset" else None

    def frame_count(self) -> int:
        """Frames of one loop period for presets (frame N+1 equals frame 1)."""
        return max(1, round(self.seconds * (self.effective_fps() or DEFAULT_PRESET_FPS)))

    def output_name(self) -> str:
        return self.name or self.source.label()

    def edges_enabled(self) -> bool:
        if self.style.edges == "auto":
            return self.source.kind in ("preset", "blend")
        return self.style.edges == "on"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return json.loads(json.dumps(data, default=str))


def load_spec_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SpecError(f"cannot read spec file {path}: {error.strerror}") from error
    try:
        data = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        raise SpecError(f"invalid spec file {path}: {error}") from error
    if not isinstance(data, dict):
        raise SpecError(f"spec file {path} must contain an object")
    return data


def parse_spec(data: dict[str, Any], base_dir: Path | None = None) -> Spec:
    """Validate a raw mapping into a Spec; relative paths resolve against base_dir."""
    base = base_dir or Path.cwd()
    known = {
        "source",
        "seconds",
        "fps",
        "size",
        "cell",
        "frame_range",
        "loop",
        "engine",
        "samples",
        "motion_blur",
        "style",
        "outputs",
        "output_dir",
        "name",
    }
    _reject_unknown(data, known, "spec")
    if "source" not in data:
        raise SpecError("spec.source is required, e.g. {'preset': 'torus-knot'}")
    source = _parse_source(data["source"], base)
    width, height = _parse_size(data.get("size", "1920x1200"), "size")
    cell_w, cell_h = _parse_size(data.get("cell", "10x20"), "cell")
    if not 4 <= cell_w <= 64 or not 4 <= cell_h <= 128:
        raise SpecError("cell must be between 4x4 and 64x128 pixels")
    if cell_w % 2 or cell_h % 2:
        raise SpecError("cell sizes must be even so 4:2:0 chroma never straddles two cells")
    if width < cell_w * 4 or height < cell_h * 2:
        raise SpecError("size is too small for the cell size")
    if width % 2 or height % 2:
        raise SpecError("size must be even for video encoding")
    spec = Spec(
        source=source,
        seconds=_number(data, "seconds", 12.0, 0.1, 600.0),
        fps=_optional_int(data, "fps", 1, 240),
        width=width,
        height=height,
        cell_w=cell_w,
        cell_h=cell_h,
        frame_range=_parse_frame_range(data.get("frame_range")),
        loop=_optional_bool(data, "loop"),
        engine=_choice(data, "engine", "eevee", ENGINES),
        samples=int(_number(data, "samples", 32, 1, 4096)),
        motion_blur=bool(_optional_bool(data, "motion_blur") is not False),
        style=_parse_style(_preset_style(source, data.get("style", {})), base),
        outputs=_parse_outputs(data.get("outputs", ["wallpaper"])),
        output_dir=_path(data["output_dir"], base) if data.get("output_dir") else None,
        name=_parse_name(data.get("name")),
    )
    if spec.frame_range and source.kind != "blend":
        raise SpecError("frame_range applies to blend sources only; use seconds otherwise")
    return spec


def _preset_style(source: Source, raw: Any) -> Any:
    if source.kind != "preset" or not isinstance(raw, dict) or source.preset is None:
        return raw
    return {**dict(PRESETS[source.preset].style), **raw}


def with_overrides(spec: Spec, **changes: Any) -> Spec:
    return replace(spec, **changes)


def _reject_unknown(data: dict[str, Any], known: set[str], where: str) -> None:
    unknown = sorted(set(data) - known)
    if unknown:
        raise SpecError(f"unknown {where} field(s): {', '.join(unknown)}")


def _parse_source(raw: Any, base: Path) -> Source:
    if isinstance(raw, str):
        raw = {"preset": raw}
    if not isinstance(raw, dict):
        raise SpecError("source must be an object with one of: preset, blend, video, image")
    kinds = [k for k in ("preset", "blend", "video", "image") if k in raw]
    if len(kinds) != 1:
        raise SpecError("source needs exactly one of: preset, blend, video, image")
    kind = cast(SourceKind, kinds[0])
    _reject_unknown(raw, {kind, "params"}, "source")
    if kind == "preset":
        name = raw["preset"]
        if name not in PRESETS:
            raise SpecError(f"unknown preset {name!r}; available: {', '.join(sorted(PRESETS))}")
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            raise SpecError("source.params must be an object")
        validated = validate_params(name, params)
        for key in PRESETS[name].path_params():
            path = _path(validated[key], base)
            if not path.is_file():
                raise SpecError(f"preset {name} parameter {key}: file not found: {path}")
            validated[key] = str(path)
        return Source(kind="preset", preset=name, params=validated)
    if "params" in raw:
        raise SpecError("source.params applies to presets only")
    path = _path(raw[kind], base)
    if not path.is_file():
        raise SpecError(f"source {kind} file not found: {path}")
    if kind == "blend" and path.suffix != ".blend":
        raise SpecError(f"blend source must be a .blend file: {path}")
    return Source(kind=kind, path=path)


def _parse_style(raw: Any, base: Path) -> Style:
    if not isinstance(raw, dict):
        raise SpecError("style must be an object")
    defaults = Style()
    _reject_unknown(raw, set(defaults.__dataclass_fields__), "style")
    charset = raw.get("charset", defaults.charset)
    if not isinstance(charset, str) or not (
        charset in CHARSETS or (charset.startswith("custom:") and len(charset) > len("custom:"))
    ):
        raise SpecError(f"style.charset must be one of {', '.join(CHARSETS)} or 'custom:<chars>'")
    background = raw.get("background", defaults.background)
    _validate_background(background)
    font = raw.get("font")
    font_path = _path(font, base) if font else None
    if font_path and not font_path.is_file():
        raise SpecError(f"style.font not found: {font_path}")
    return Style(
        charset=charset,
        edges=_choice(raw, "edges", defaults.edges, EDGE_MODES, "style."),
        edge_threshold=_number(raw, "edge_threshold", defaults.edge_threshold, 0.0, 1.0, "style."),
        contrast=_number(raw, "contrast", defaults.contrast, 1.0, 6.0, "style."),
        directional_contrast=_number(
            raw, "directional_contrast", defaults.directional_contrast, 0.0, 4.0, "style."
        ),
        hysteresis=_number(raw, "hysteresis", defaults.hysteresis, 0.0, 0.9, "style."),
        color_lightness=_number(
            raw, "color_lightness", defaults.color_lightness, 0.0, 1.0, "style."
        ),
        saturation=_number(raw, "saturation", defaults.saturation, 0.0, 3.0, "style."),
        brightness=_number(raw, "brightness", defaults.brightness, 0.1, 4.0, "style."),
        background=background,
        glow=_number(raw, "glow", defaults.glow, 0.0, 1.0, "style."),
        font=font_path,
    )


def _validate_background(value: Any) -> None:
    if not isinstance(value, str):
        raise SpecError("style.background must be a string")
    if value == "transparent" or _HEX.match(value):
        return
    if value.startswith("tint:"):
        try:
            amount = float(value.removeprefix("tint:"))
        except ValueError:
            amount = -1.0
        if 0.0 <= amount <= 1.0:
            return
    raise SpecError("style.background must be '#rrggbb', 'tint:<0..1>' or 'transparent'")


def _parse_outputs(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise SpecError("outputs must be a non-empty list")
    for item in raw:
        if item not in OUTPUTS:
            raise SpecError(f"unknown output {item!r}; available: {', '.join(OUTPUTS)}")
    return tuple(dict.fromkeys(raw))


def _parse_size(raw: Any, name: str) -> tuple[int, int]:
    match = _SIZE.match(raw) if isinstance(raw, str) else None
    if not match:
        raise SpecError(f"{name} must look like '1920x1200'")
    return int(match.group(1)), int(match.group(2))


def _parse_frame_range(raw: Any) -> tuple[int, int] | None:
    if raw is None:
        return None
    if (
        not isinstance(raw, list | tuple)
        or len(raw) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in raw)
        or raw[0] > raw[1]
        or raw[0] < 0
    ):
        raise SpecError("frame_range must be [start, end] with 0 <= start <= end")
    return int(raw[0]), int(raw[1])


def _parse_name(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", raw):
        raise SpecError("name may contain letters, digits, '.', '_' and '-' only")
    return raw


def _path(raw: Any, base: Path) -> Path:
    if not isinstance(raw, str) or not raw:
        raise SpecError("paths must be non-empty strings")
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _number(
    data: dict[str, Any], key: str, default: float, low: float, high: float, prefix: str = ""
) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SpecError(f"{prefix}{key} must be a number")
    if not low <= value <= high:
        raise SpecError(f"{prefix}{key} must be between {low} and {high}")
    return float(value)


def _optional_int(data: dict[str, Any], key: str, low: int, high: int) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SpecError(f"{key} must be an integer between {low} and {high}")
    return value


def _optional_bool(data: dict[str, Any], key: str) -> bool | None:
    value = data.get(key)
    if value is None or isinstance(value, bool):
        return value
    raise SpecError(f"{key} must be true or false")


def _choice(
    data: dict[str, Any], key: str, default: str, choices: tuple[str, ...], prefix: str = ""
) -> Any:
    value = data.get(key, default)
    if value not in choices:
        raise SpecError(f"{prefix}{key} must be one of: {', '.join(choices)}")
    return value


def absolutize(data: dict[str, Any], base: Path) -> dict[str, Any]:
    """Copy of a raw spec with every path made absolute (for handing to a subprocess)."""
    result = json.loads(json.dumps(data))
    source = result.get("source")
    if isinstance(source, dict):
        for kind in ("blend", "video", "image"):
            if isinstance(source.get(kind), str):
                source[kind] = str(_path(source[kind], base))
        preset = PRESETS.get(source.get("preset", ""))
        params = source.get("params")
        if preset is not None and isinstance(params, dict):
            for key in preset.path_params():
                if isinstance(params.get(key), str) and params[key]:
                    params[key] = str(_path(params[key], base))
    style = result.get("style")
    if isinstance(style, dict) and isinstance(style.get("font"), str):
        style["font"] = str(_path(style["font"], base))
    if isinstance(result.get("output_dir"), str):
        result["output_dir"] = str(_path(result["output_dir"], base))
    return result
