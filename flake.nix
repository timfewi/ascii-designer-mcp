{
  description = "Render Blender 3D scenes as truecolor ASCII animations (wallpapers) via MCP and CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/eaad089433ca2bb662274377d33df3d0e51ef28b";
    project-check = {
      url = "github:timfewi/project-check-nix/f70de45d69b9ca9a31f5b9f94e316ac6e43e514e";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, project-check, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      packageFor =
        system: nixpkgs.legacyPackages.${system}.callPackage ./packages/ascii-designer-mcp.nix { };
    in
    {
      packages = forAllSystems (system: {
        default = packageFor system;
        ascii-designer-mcp = packageFor system;
      });

      checks = forAllSystems (system: {
        package = packageFor system;
        # Renders real Blender passes under software GL (llvmpipe) and runs the
        # Blender integration tests against them.
        blender-smoke = nixpkgs.legacyPackages.${system}.callPackage ./packages/blender-smoke.nix {
          asciiDesigner = packageFor system;
        };
      });

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3.withPackages (ps: [
            ps.fonttools
            ps.mcp
            ps.numpy
            ps.openexr
            ps.pillow
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              project-check.packages.${system}.project-check
              python
              pkgs.bashInteractive
              pkgs.basedpyright
              pkgs.blender
              pkgs.coreutils
              pkgs.deadnix
              pkgs.ffmpeg
              pkgs.git
              pkgs.jq
              pkgs.just
              pkgs.nix
              pkgs.nixfmt
              pkgs.ripgrep
              pkgs.ruff
              pkgs.statix
            ];
            ASCII_DESIGNER_FONT = (packageFor system).font;
          };
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);
    };
}
