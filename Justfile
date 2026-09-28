set shell := ["bash", ".just-shell"]
set positional-arguments

# Show available recipes.
default:
    @just --list

# Run the CLI from this checkout, e.g. `just run render tunnel --seconds 6`.
run *args:
    @PYTHONPATH=src python3 -m ascii_designer "$@"

# Check Blender, ffmpeg encoders, the glyph font and the cache.
status:
    @just run status

# List built-in scenes, their parameters and palettes.
presets:
    @just run presets

# Render one frame of a preset or spec file to PNG, e.g. `just preview planet --frame 40`.
preview spec *args:
    @just run preview "$@"

# Render the full animation, e.g. `just render terrain --param style='"solid"'`.
render spec *args:
    @just run render "$@"

# Render a 12 s looping wallpaper video (HEVC) plus a PNG still into ~/Videos/ascii-designer.
wallpaper preset="torus-knot" *args:
    @just run render "$@" --outputs wallpaper,png

# Save a preset scene as .blend for live editing (Blender Lab MCP), e.g. `just blend galaxy /tmp/g.blend`.
blend preset out *args:
    @just run preset-blend "$1" --out "$2" "${@:3}"

# Start the MCP server on stdio from this checkout (for local MCP client configs).
mcp:
    @just run mcp

# Show the size of the pass cache.
cache-info:
    @just run cache info

# Remove cached Blender passes, optionally only those unused for N days.
cache-prune days="0":
    @just run cache prune --older-than "$1"

# Unit and integration tests (Blender tests are skipped).
test:
    python3 -m unittest discover -s tests -t . -p 'test_*.py'

# Tests including real Blender renders (takes minutes).
test-blender:
    ASCII_DESIGNER_BLENDER_TESTS=1 python3 -m unittest discover -s tests -t . -p 'test_*.py'

# Build the Nix package (result/bin/ascii-designer-mcp).
build:
    nix build path:.#default

# Run declared fast checks; accepts project-check options such as --json.
lint *args:
    @project-check fast "$@"

# Run the declared full gate; accepts project-check options such as --json.
verify *args:
    @project-check full "$@"
