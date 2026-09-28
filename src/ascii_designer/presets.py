"""Catalog of the built-in procedural Blender scenes.

The scene builders live in `blender/scripts/presets/<module>.py` and run inside
Blender; this catalog is the pure-Python contract (names, parameters, ranges)
used for validation, `presets` listings and the MCP schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ascii_designer.errors import SpecError

PALETTES: dict[str, tuple[str, str, str, str]] = {
    # primary, secondary, accent, deep background tone
    "synthwave": ("#ff2bd6", "#20e3ff", "#ffb000", "#1a0b2e"),
    "matrix": ("#00ff66", "#00b35a", "#b6ffcf", "#001a0a"),
    "amber": ("#ffb000", "#ff6a00", "#ffe2a8", "#1a0f00"),
    "ice": ("#7fdcff", "#3a7bff", "#ffffff", "#04101f"),
    "sunset": ("#ff5e3a", "#ffcc4d", "#ff2d75", "#1b0a14"),
    "nord": ("#88c0d0", "#b48ead", "#ebcb8b", "#2e3440"),
    "toxic": ("#c6ff00", "#00ffa3", "#ff00c8", "#0a0f00"),
    "mono": ("#ffffff", "#9a9a9a", "#ffffff", "#000000"),
}


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # int | float | bool | choice
    default: Any
    description: str
    low: float | None = None
    high: float | None = None
    choices: tuple[str, ...] = ()

    def schema(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": {"int": "integer", "float": "number", "bool": "boolean"}.get(
                self.kind, "string"
            ),
            "default": self.default,
            "description": self.description,
        }
        if self.low is not None:
            data["minimum"] = self.low
        if self.high is not None:
            data["maximum"] = self.high
        if self.choices:
            data["enum"] = list(self.choices)
        return data


@dataclass(frozen=True)
class Preset:
    name: str
    module: str
    description: str
    params: tuple[Param, ...]
    style: tuple[tuple[str, Any], ...] = ()  # recommended style; user values win

    def defaults(self) -> dict[str, Any]:
        return {p.name: p.default for p in self.params}

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "params": {p.name: p.schema() for p in self.params},
            "style": dict(self.style),
        }


def _palette(default: str) -> Param:
    return Param("palette", "choice", default, "Named colour palette", choices=tuple(PALETTES))


def _seed() -> Param:
    return Param("seed", "int", 7, "Random seed for procedural detail", 0, 99999)


_PRESET_LIST = (
    Preset(
        "torus-knot",
        "torus_knot",
        "Rotating (p,q) torus knot tube with metallic rim lighting.",
        (
            _palette("synthwave"),
            Param("p", "int", 2, "Windings around the rotational axis", 1, 9),
            Param("q", "int", 3, "Windings around the tube interior", 1, 11),
            Param("tube", "float", 0.36, "Tube radius", 0.05, 0.7),
            Param("turns", "int", 1, "Full rotations per loop", 1, 4),
            Param(
                "material", "choice", "metal", "Surface look", choices=("metal", "neon", "matte")
            ),
        ),
    ),
    Preset(
        "tunnel",
        "tunnel",
        "Endless flight through glowing tunnel segments.",
        (
            _palette("synthwave"),
            Param("shape", "choice", "ring", "Segment shape", choices=("ring", "hex", "square")),
            Param("segments", "int", 20, "Visible segments", 8, 64),
            Param("travel", "int", 4, "Segments travelled per loop", 1, 16),
            Param("twist", "float", 0.25, "Segment twist turns per loop", 0.0, 2.0),
        ),
    ),
    Preset(
        "planet",
        "planet",
        "Rotating planet with noise continents, rings, atmosphere and stars.",
        (
            _palette("ice"),
            Param("rings", "bool", True, "Add a ring system"),
            Param("moons", "int", 1, "Orbiting moons", 0, 3),
            Param("turns", "int", 1, "Planet rotations per loop", 1, 3),
            _seed(),
        ),
    ),
    Preset(
        "terrain",
        "terrain",
        "Synthwave flight over an endless looping mountain range.",
        (
            _palette("synthwave"),
            Param("style", "choice", "wire", "Surface style", choices=("wire", "solid")),
            Param("height", "float", 1.0, "Mountain height", 0.2, 3.0),
            Param("sun", "bool", True, "Striped sun on the horizon"),
            _seed(),
        ),
    ),
    Preset(
        "cube-wave",
        "cube_wave",
        "Grid of pillars rising in a travelling wave, isometric view.",
        (
            _palette("toxic"),
            Param("grid", "int", 12, "Pillars per side", 6, 30),
            Param("waves", "int", 2, "Wave crests across the grid", 1, 4),
            Param("shape", "choice", "cube", "Pillar shape", choices=("cube", "cylinder")),
        ),
    ),
    Preset(
        "gyroscope",
        "gyroscope",
        "Nested rings spinning on alternating axes around a glowing core.",
        (
            _palette("amber"),
            Param("rings", "int", 4, "Number of rings", 2, 6),
        ),
    ),
    Preset(
        "dna-helix",
        "dna_helix",
        "Rotating double helix with base-pair rungs.",
        (
            _palette("ice"),
            Param("pairs", "int", 22, "Base pairs", 8, 40),
            Param("turns", "int", 1, "Rotations per loop", 1, 3),
        ),
    ),
    Preset(
        "galaxy",
        "galaxy",
        "Spiral galaxy of emissive stars rotating by one arm per loop.",
        (
            _palette("sunset"),
            Param("arms", "int", 3, "Spiral arms", 2, 6),
            Param("stars", "int", 3000, "Star count", 300, 12000),
            _seed(),
        ),
        style=(("edges", "off"),),
    ),
    Preset(
        "metaballs",
        "metaballs",
        "Liquid metaballs orbiting and merging on periodic paths.",
        (
            _palette("toxic"),
            Param("balls", "int", 6, "Number of metaballs", 3, 10),
            _seed(),
        ),
    ),
    Preset(
        "city-flyover",
        "city_flyover",
        "Endless flight over a procedural skyline grid.",
        (
            _palette("nord"),
            Param("density", "float", 0.5, "Building density", 0.2, 1.0),
            _seed(),
        ),
    ),
    Preset(
        "attractor",
        "attractor",
        "Strange attractor traced as a tube, slowly orbiting.",
        (
            _palette("sunset"),
            Param("kind", "choice", "lorenz", "Attractor", choices=("lorenz", "aizawa", "thomas")),
            Param("tube", "float", 0.05, "Tube radius", 0.01, 0.2),
        ),
    ),
)

PRESETS: dict[str, Preset] = {p.name: p for p in _PRESET_LIST}


def validate_params(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return the full parameter set for a preset, rejecting unknown or out-of-range values."""
    preset = PRESETS[name]
    by_name = {p.name: p for p in preset.params}
    unknown = sorted(set(params) - set(by_name))
    if unknown:
        raise SpecError(
            f"unknown parameter(s) for preset {name}: {', '.join(unknown)}; "
            f"available: {', '.join(by_name)}"
        )
    result = preset.defaults()
    for key, value in params.items():
        result[key] = _check(name, by_name[key], value)
    return result


def _check(preset: str, param: Param, value: Any) -> Any:
    where = f"preset {preset} parameter {param.name}"
    if param.kind == "bool":
        if not isinstance(value, bool):
            raise SpecError(f"{where} must be true or false")
        return value
    if param.kind == "choice":
        if value not in param.choices:
            raise SpecError(f"{where} must be one of: {', '.join(param.choices)}")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SpecError(f"{where} must be a number")
    if param.kind == "int" and not float(value).is_integer():
        raise SpecError(f"{where} must be an integer")
    low = param.low if param.low is not None else float("-inf")
    high = param.high if param.high is not None else float("inf")
    if not low <= value <= high:
        raise SpecError(f"{where} must be between {param.low} and {param.high}")
    return int(value) if param.kind == "int" else float(value)
