# End-to-end smoke check with real Blender under software GL (llvmpipe), as
# nixpkgs' own blender render test does: every preset must build, and a tiny
# looping render must produce a seamless HEVC wallpaper, a PNG and ANSI text.
{
  runCommand,
  jq,
  mesa,
  nixos-icons,
  asciiDesigner,
}:
let
  # A real logo with transparency for the `logo` preset.
  logo = "${nixos-icons}/share/icons/hicolor/256x256/apps/nix-snowflake.png";
in
runCommand "ascii-designer-blender-smoke"
  {
    nativeBuildInputs = [
      asciiDesigner
      jq
      mesa.llvmpipeHook
    ];
  }
  ''
    set -euo pipefail
    export HOME="$TMPDIR" ASCII_DESIGNER_CACHE="$TMPDIR/cache"
    mkdir -p "$out"
    ascii-designer-mcp status > "$out/status.json"
    for preset in $(ascii-designer-mcp presets | jq -r '.presets[].name'); do
      echo "building preset $preset"
      extra=()
      if [ "$preset" = logo ]; then
        extra=(--param 'image="${logo}"' --param resolution=128)
      fi
      ascii-designer-mcp preset-blend "$preset" --size 160x100 --cell 8x16 \
        --seconds 0.25 --fps 12 "''${extra[@]}" --out "$TMPDIR/$preset.blend" > /dev/null
    done
    ascii-designer-mcp render tunnel --size 160x100 --cell 8x16 --seconds 0.25 --fps 12 \
      --samples 4 --outputs wallpaper,png,ansi -o "$out" --result "$out/result.json" > /dev/null
    jq -e '.frames == 3 and .seam.glyph_state_mismatch == 0 and .seam.seamless' "$out/result.json"
    test -s "$out/tunnel.mp4" && test -s "$out/tunnel.png" && test -s "$out/tunnel.ans"
  ''
