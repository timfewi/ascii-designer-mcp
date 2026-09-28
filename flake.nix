{
  description = "Render Blender 3D scenes as truecolor ASCII animations (wallpapers) via MCP and CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/eaad089433ca2bb662274377d33df3d0e51ef28b";
    project-check = {
      url = "github:timfewi/project-check-nix/b4f90cdb9a84bb34d5f51a11d037ce60c56e27bb";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, project-check, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      asciiDesigner = pkgs.callPackage ./packages/ascii-designer-mcp.nix { };
      python = pkgs.python3.withPackages (ps: [
        ps.fonttools
        ps.mcp
        ps.numpy
        ps.openexr
        ps.pillow
      ]);
    in
    {
      packages.${system} = {
        default = asciiDesigner;
        ascii-designer-mcp = asciiDesigner;
      };

      checks.${system} = {
        package = asciiDesigner;
        # Renders real Blender passes under software GL (llvmpipe) and runs the
        # Blender integration tests against them.
        blender-smoke = pkgs.callPackage ./packages/blender-smoke.nix { inherit asciiDesigner; };
      };

      devShells.${system}.default = pkgs.mkShell {
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
        ASCII_DESIGNER_FONT = asciiDesigner.font;
      };

      formatter.${system} = pkgs.nixfmt-tree;
    };
}
