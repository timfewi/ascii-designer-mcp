# Project policy

- Keep credentials, personal data and runtime state outside Git.
- Preserve existing user changes. Write documentation and CLI text in English.
- Run `project-check fast` after meaningful changes and `project-check full`
  before handoff. Checks are declared in `.project-checks.json` and never run on
  their own.
- Missing tools or offline dependencies are environment blockers, not failures.
  Enter the pinned toolchain with `nix develop path:.` (or reload direnv).
  `just lint --json` and `just verify --json` forward options to project-check.
- Do not stage, commit, push, publish or deploy without explicit authorization.

## Toolchain and layout

- Python 3.14 package in `src/ascii_designer`; `service.py` owns orchestration,
  `cli.py` and `mcp_server.py` stay thin. Blender, ffmpeg and the default font
  come from Nix (`packages/ascii-designer-mcp.nix` wraps them in).
- `src/ascii_designer/blender/scripts/` runs inside Blender 5.2 (bundled Python
  3.13, `bpy`): keep it 3.13 compatible and free of repository imports.
  basedpyright excludes it; `tests/unit/test_presets.py` parses it.
- Preset parameters live in `presets.py`; each entry needs a builder in
  `blender/scripts/presets/<module>.py`. Animate only with drivers of `frame`
  (see `_common.phase`/`loop_value`) so loops are exact and `-Y` renders work.
- Blender tests are opt-in (`ASCII_DESIGNER_BLENDER_TESTS=1`, `just test-blender`);
  `nix flake check` runs a Blender smoke render under llvmpipe.
- Runtime state lives in `$ASCII_DESIGNER_CACHE` (default
  `~/.cache/ascii-designer`); scratch files belong in the ignored `.scratch/`.
- Progress checkpoint for multi-session work: `HANDOFF.md`.
