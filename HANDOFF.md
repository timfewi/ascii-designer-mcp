# Handoff

Progress checkpoint for multi-session work. Update it when requirements,
decisions or verification results change.

## Requirements

- Very high quality 3D truecolor ASCII animations, mainly seamless looping
  wallpaper videos (for example played by mpvpaper).
- Blender both ways: built-in headless presets and arbitrary `.blend` files
  (built live with the Blender Lab MCP server).
- MCP server and CLI; Justfile recipes to start it; native registration in
  coding-agent configurations like visual-qa-mcp.
- ASCII Motion is an optional export, not the renderer.

## Decisions

- Python 3.14 package; Blender 5.2.1, ffmpeg 9 and CaskaydiaCove SemiBold from
  Nix (pinned nixpkgs `eaad0894…`, same as the sibling tool repositories).
- Default 1920x1200, 10x20 px cells, 36 fps, HEVC Main10 4:2:0 with a closed GOP
  of exactly one loop (hardware-decodable); `wallpaper444` for fidelity.
- Passes: beauty PNG via the normal render output; raw Depth/Normal via one
  File Output node (multilayer half EXR, `depth.V`, `normal.X/Y/Z`), using the
  Blender 5.x compositor API. Rendering always uses `--factory-startup` and `-Y`.
- Mapper: chroma-aware brightness, one brightness model (`color_lightness`),
  density ramp for flat cells and shape matching for structured cells, 3D edge
  glyphs when linked across cells, ink-weighted colour, hysteresis with warm-up
  passes on cached cell features until a fixed point (seamless loops).
- Presets animate only with simple-expression drivers of `frame`.
- Default charset `symbols` (ASCII without letters); a mixed ASCII/block charset
  was dropped after visual comparison.
- `mcp --output-dir/--cache-dir` let hosts place outputs and cache via arguments.

## Status

- Implemented: spec, 11 presets, Blender runner and pass cache, mapper,
  compose, encoders, ANSI, ASCII Motion session export, CLI, MCP server with
  background jobs, Justfile, Nix package and Blender smoke check.
- Verified: `project-check fast` and `full` (flake check including the Blender
  smoke render under llvmpipe); packaged binary: status and a stdio MCP session
  (preview images, background job, concurrent job refusal); 4 s tunnel render:
  144 frames, seam mismatch 0, 2:57 total, 1.36 GB peak RSS; HEVC wallpaper vs
  lossless master PSNR 38.7 dB (4:4:4: 43.7 dB).
- Not verified: wallpaper playback on a desktop and importing the ASCII Motion
  session in the browser.

- Galaxy loop fix (uncommitted): the preset spun the tilted disc about world Z
  (Euler `XYZ`), so it tumbled and the loop jumped (seam diff 60). Now `ZXY`, star
  copies turn with their arm and the core glow has 60 segments; the seam test for
  `galaxy` (`tests/blender/test_blender.py`) passes, `project-check fast` passed.
- Not done: the full 24 s render after the fix (6x12 cells, `stars=7000`, 36 fps,
  `--outputs wallpaper,wallpaper444,png`, about 35 min at nice 19) was stopped on
  request; `~/Videos/ascii-designer/galaxy-ascii-hq*` is still the old, tumbling
  render. Wallpaper via `mpvpaper` (nixpkgs 1.9, niri, 1920x1200@144 Hz) not set.

## Next

- Re-run the galaxy render above, check `seam.seamless`, then play it with
  `mpvpaper -o "no-audio loop-file=inf hwdec=auto-safe" '*' <video>`.

- Host integration: pin this flake and enable the coding-agent registration
  (server name `ascii_designer`, `ascii-designer-mcp mcp`).
