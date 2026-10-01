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

- Implemented: spec, 12 presets, Blender runner and pass cache, mapper,
  compose, encoders, ANSI, ASCII Motion session export, CLI, MCP server with
  background jobs, Justfile, Nix package and Blender smoke check.
- Verified: `project-check fast` and `full` (flake check including the Blender
  smoke render under llvmpipe); packaged binary: status and a stdio MCP session
  (preview images, background job, concurrent job refusal); 4 s tunnel render:
  144 frames, seam mismatch 0, 2:57 total, 1.36 GB peak RSS; HEVC wallpaper vs
  lossless master PSNR 38.7 dB (4:4:4: 43.7 dB).
- Not verified: wallpaper playback on a desktop and importing the ASCII Motion
  session in the browser.

- Galaxy loop fix (commit `327f312`): the preset spun the tilted disc about world Z
  (Euler `XYZ`), so it tumbled and the loop jumped (seam diff 60). Now `ZXY`, star
  copies turn with their arm and the core glow has 60 segments; the seam test for
  `galaxy` (`tests/blender/test_blender.py`) passes, `project-check fast` passed.
- Not done: a full-quality render after the fix and desktop wallpaper playback.
  Render output and local desktop configuration remain outside this repository.

## Next

- Run a full-quality galaxy render, check `seam.seamless`, then play it with
  `mpvpaper -o "no-audio loop-file=inf hwdec=auto-safe" '*' <video>`.

- Host integration: pin this flake and enable the coding-agent registration
  (server name `ascii_designer`, `ascii-designer-mcp mcp`).

## Native Linux outputs and clean package sources — 2026-10-01

The previous flake exported only x86-64 Linux and hardcoded its formatter in the
fast gate. Packages, shells, formatters and both package/render checks now use
their selected native platform for x86-64 and ARM64 Linux. The shared project-check
input moved to `f70de45d`; Nixpkgs and Python dependencies retain their pins.

Reproduced a synthetic bytecode cache entering the previous package source and
changing its store path. `nix/source.nix` now selects the manifest, README,
license and regular Python source/test files, including all Blender scripts.
Git-backed Flake/Direnv commands and matching recipes avoid copying untracked
workspace state. Authorized new source needs staging before Nix evaluation.
`scripts/source_filter.nix` and `scripts/check_source_filter.py` verify the real
package inventories, native check runner composition, and synthetic cache,
symlink and FIFO exclusions. Source edits must change the source store path;
cache edits must not.

The declared fast gate passed using cached tools, including pinned Python,
font, ffmpeg and project-check, without realizing the development shell or
building a package. It ran 43 tests, with the three opt-in Blender tests skipped,
and passed types, format/lint, both Linux evaluations and source regressions.
The installed toolbox and meter executed the presets CLI from the actual
filtered Nix source: all 12 presets remained available, stdout/stderr and byte
counts were exact, and the mode-0600 event log contained no command or output
contents. The tracked-source privacy scan completed with zero findings.

The old local desktop/output notes were replaced with portable pending work;
the already committed galaxy fix is identified accurately. No full builds,
Blender renders, ARM64 execution, Git-history audit, Direnv approval or host
activation were performed. Next: review the remaining canonical tool flakes for
native platform assumptions and reproducible source inputs.
