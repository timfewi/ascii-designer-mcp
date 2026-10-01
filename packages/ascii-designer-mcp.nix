# The packaged `ascii-designer-mcp` CLI and MCP server.
#
# Blender and ffmpeg are placed on PATH by the wrapper so the MCP server works
# in sandboxes that clear PATH; ASCII_DESIGNER_FONT defaults to the terminal
# font but stays overridable (`--set-default`).
{
  lib,
  python3Packages,
  blender,
  ffmpeg,
  nerd-fonts,
}:
let
  font = "${nerd-fonts.caskaydia-cove}/share/fonts/truetype/NerdFonts/CaskaydiaCove/CaskaydiaCoveNerdFontMono-SemiBold.ttf";
in
python3Packages.buildPythonApplication {
  pname = "ascii-designer-mcp";
  version = "0.1.0";
  pyproject = true;

  src = import ../nix/source.nix {
    inherit lib;
    root = ../.;
  };

  build-system = [ python3Packages.hatchling ];

  dependencies = [
    python3Packages.fonttools
    python3Packages.mcp
    python3Packages.numpy
    python3Packages.openexr
    python3Packages.pillow
  ];

  nativeCheckInputs = [ ffmpeg ];

  # Unit and integration tests; Blender tests are opt-in (ASCII_DESIGNER_BLENDER_TESTS).
  checkPhase = ''
    runHook preCheck
    export ASCII_DESIGNER_FONT=${font}
    python -m unittest discover -s tests -t . -p 'test_*.py'
    runHook postCheck
  '';

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [
      blender
      ffmpeg
    ])
    "--set-default"
    "ASCII_DESIGNER_FONT"
    font
  ];

  passthru = { inherit font; };

  meta = {
    description = "Render Blender 3D scenes as truecolor ASCII animations via MCP and CLI";
    license = lib.licenses.mit;
    mainProgram = "ascii-designer-mcp";
    platforms = lib.platforms.linux;
  };
}
