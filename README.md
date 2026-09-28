# ascii-designer-mcp

Official source: <https://github.com/timfewi/ascii-designer-mcp>

Render Blender 3D scenes as high quality **truecolor ASCII animations**, mainly
seamlessly looping desktop wallpaper videos. Usable as a CLI and as an MCP server
for coding agents; pairs with the [Blender Lab MCP server](https://www.blender.org/lab/mcp-server/)
for building custom scenes live in Blender.

```
source ─► passes (cached) ─► ASCII grid ─► outputs
preset / .blend: Blender 5.2 headless → beauty PNG + depth/normal EXR
video / image:   ffmpeg decode
                 shape-aware glyphs, 3D edge lines, ink colour, loop-safe hysteresis
                 → HEVC wallpaper, 4:4:4, H.264, lossless master, PNG, ANSI, ASCII Motion
```

## Quick start

```sh
nix develop path:.          # or direnv; provides Blender 5.2, ffmpeg, font and checks
just status                 # Blender, ffmpeg encoders, font, cache
just presets                # built-in scenes, parameters and palettes
just preview tunnel --frame 40            # one frame → PNG overview + 1:1 crop
just wallpaper planet                     # 12 s loop → ~/Videos/ascii-designer/planet.mp4
just render terrain --param style='"solid"' --style charset='"blocks"'
nix build path:.#default    # packaged CLI: result/bin/ascii-designer-mcp
```

Play a rendered loop as a Wayland wallpaper, for example with mpvpaper; the
closed GOP makes `loop-file=inf` seamless and `hwdec=auto-safe` lets the GPU
decode the HEVC stream:

```sh
mpvpaper -o "no-audio loop-file=inf hwdec=auto-safe" '*' ~/Videos/ascii-designer/planet.mp4
```

## How it looks good

- **One brightness model.** Glyph density carries part of the brightness and the
  truecolor foreground carries the rest (`style.color_lightness`, 0…1). Density is
  chroma-aware, so saturated blue or magenta surfaces stay dense.
- **Calm fills, sharp structure.** Flat cells use a short density ramp
  (` .:-=+*#%@`); cells with real structure use the whole charset, matched by
  sub-cell shape against the font's average ink profile, with directional and
  gated contrast enhancement.
- **3D edges.** Relative log-depth steps and normal-angle creases from Blender's
  passes become oriented line glyphs (`| / \ - _`) when they continue across
  cells. Isolated specks such as stars stay `.` or `*`.
- **Ink colour.** Each cell's colour is averaged under the chosen glyph's ink, not
  over the whole cell, so boundaries do not mix colours.
- **Stable and loopable.** Hysteresis keeps glyphs from shimmering, and a warm-up
  runs until the state is a fixed point, so the loop seam cannot pop. Presets
  animate with drivers of `frame` over exactly one period. Every render reports
  the seam: `glyph_state_mismatch` and `scene_mean_abs_diff`.
- **Pixel-exact output.** The default is 1920x1200 with 10x20 px cells (192x60
  glyphs), all even-aligned for 4:2:0 chroma, at 36 fps (4 refreshes per frame on
  144 Hz). Output is HEVC Main10 with a closed GOP of exactly one loop. Glyphs use
  hinted FreeType at the target size (CaskaydiaCove SemiBold by default), and
  block, sextant and Braille glyphs are drawn procedurally.

## Spec

The CLI takes a spec file (TOML or JSON), inline JSON or a preset name plus flags;
MCP tools take the same object.

```toml
seconds = 12
fps = 36
size = "1920x1200"
cell = "10x20"
engine = "eevee"          # eevee | cycles | workbench
samples = 32
outputs = ["wallpaper", "png"]   # wallpaper wallpaper444 h264 master png ansi asciimotion
output_dir = "~/Videos/ascii-designer"

[source]                  # exactly one of: preset | blend | video | image
preset = "planet"
params = { palette = "ice", moons = 2 }

[style]
charset = "symbols"       # symbols | ascii | blocks | braille | custom:<chars>
edges = "auto"            # auto (on for 3D sources) | on | off
color_lightness = 0.5     # 0: density carries brightness … 1: colour carries it
contrast = 1.8
hysteresis = 0.15
saturation = 1.15
background = "#000000"    # "#rrggbb" | "tint:0.15" | "transparent" (PNG)
glow = 0.0                # phosphor bloom strength
```

`frame_range = [start, end]` and `loop = true` apply to `.blend` sources.
Relative paths resolve against the spec file.

### Presets

| Preset | Scene |
| --- | --- |
| `torus-knot` | Rotating (p,q) torus knot with rim lighting |
| `tunnel` | Endless flight through glowing ring, hex or square segments |
| `planet` | Ringed planet with continents, atmosphere, moons and stars |
| `terrain` | Synthwave flight over a looping mountain range (wire or solid) |
| `cube-wave` | Isometric grid of pillars in a travelling wave |
| `gyroscope` | Nested rings spinning around a glowing core |
| `dna-helix` | Rotating double helix |
| `galaxy` | Spiral galaxy turning by one arm per loop |
| `metaballs` | Liquid metaballs on periodic paths |
| `city-flyover` | Endless flight over a procedural skyline |
| `attractor` | Lorenz, Aizawa or Thomas attractor as a tube |
| `logo` | Your logo image (PNG/JPG) as an embossed, double-sided 3D emblem that sways, floats or spins |

Palettes: synthwave, matrix, amber, ice, sunset, nord, toxic, mono.

The `logo` preset turns any image into a 3D emblem. The foreground comes from the
alpha channel or, for opaque images, from the distance to the border colour.
Brighter colour regions stand higher (`relief`), and the original colours are
used as texture:

```sh
just render logo --param 'image="/path/to/logo.png"' --param 'motion="spin"' --param 'palette="ice"'
```

## MCP surface

`ascii-designer-mcp mcp` serves stdio.

| Tool | Purpose |
| --- | --- |
| `ascii_status` | Toolchain, encoders, font, cache size, recent jobs |
| `ascii_list_presets` | Presets with parameter schemas, palettes, charsets, outputs |
| `ascii_preview` | One frame as overview image + 1:1 crop image + PNG paths |
| `ascii_render` | Start the full render as a background job |
| `ascii_job` | Job progress, result (output paths, seam report) or cancel |
| `ascii_preset_to_blend` | Save a preset as `.blend` to extend it live in Blender |

### With the Blender Lab MCP server

1. **Build the scene.** Use the Blender Lab MCP (`execute_blender_code`) to build
   and animate a scene in the running Blender GUI. Animate with keyframes or
   simple-expression drivers; Python drivers are disabled when rendering (`-Y`).
2. **Save it** with `bpy.ops.wm.save_as_mainfile(filepath="/abs/scene.blend")`.
3. **Iterate** with `ascii_preview` on `{"source": {"blend": "/abs/scene.blend"}}`.
4. **Render** with `ascii_render`. For seamless loops set `"loop": true` and make
   `frame_end + 1` equal to `frame_start`.

`ascii_preset_to_blend` gives you a starting point. Rendering always uses
`--factory-startup`, so user add-ons (including the MCP bridge on port 9876) do not
load in the render process.

## ASCII Motion

The `asciimotion` output writes a session file that
[ASCII Motion](https://ascii-motion.app) imports: the v1 session shape, which its
importer migrates to v2. Use it to hand-edit a clip or add ASCII Motion's
effects. Browser memory limits the size, so exports above 600k cells are refused;
use fewer columns or seconds. The wallpaper videos themselves do not need it.

## Configuration

| Variable | Default |
| --- | --- |
| `ASCII_DESIGNER_FONT` | CaskaydiaCove Nerd Font Mono SemiBold (set by the package) |
| `ASCII_DESIGNER_BLENDER` | `blender` on `PATH` (Blender 5.2) |
| `ASCII_DESIGNER_OUTPUT_DIR` | `$XDG_VIDEOS_DIR/ascii-designer` or `~/Videos/ascii-designer` |
| `ASCII_DESIGNER_CACHE` | `$XDG_CACHE_HOME/ascii-designer` (passes, grids, jobs) |

A 12 s loop at 1920x1200 takes about 1 s per frame in EEVEE, plus about 0.35 s
per frame for mapping and encoding. It caches about 2 GB of passes;
`just cache-prune` clears them. Restyling (charset, colours, contrast) reuses the
cached passes.

## Development

```sh
nix develop path:.
just test            # unit + integration (Blender tests skipped)
just test-blender    # includes real renders
just lint            # project-check fast: nixfmt, statix, deadnix, ruff, basedpyright, unittest
just verify          # project-check full: nix flake check incl. Blender smoke render
```

Layout: `src/ascii_designer/{spec,presets,service,cache,jobs,cli,mcp_server}.py`,
`raster/` (glyphs, mapper, edges, colours, compose, passes), `output/` (ffmpeg,
grid, ansi, asciimotion), `blender/` (runner and the scripts that run inside Blender,
Python 3.13).

## License

MIT
