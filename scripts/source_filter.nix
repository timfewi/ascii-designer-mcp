let
  flake = builtins.getFlake (builtins.getEnv "SOURCE_CHECK_FLAKE_URI");
  source = import ../nix/source.nix {
    lib = flake.inputs.nixpkgs.lib;
    root = /. + builtins.getEnv "SOURCE_CHECK_FIXTURE_ROOT";
  };
  walk =
    prefix: directory:
    let
      entries = builtins.readDir directory;
    in
    builtins.concatMap (
      name:
      if entries.${name} == "directory" then
        walk "${prefix}${name}/" "${directory}/${name}"
      else
        [ "${prefix}${name}" ]
    ) (builtins.attrNames entries);
  native = flake.inputs.nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-linux" ] (
    system:
    let
      package = flake.packages.${system}.default;
      shell = flake.devShells.${system}.default;
      runner = flake.inputs.project-check.packages.${system}.project-check;
    in
    assert package.system == system;
    assert shell.system == system;
    assert runner.system == system;
    assert builtins.elem runner shell.nativeBuildInputs;
    assert flake.formatter.${system}.system == system;
    assert flake.checks.${system}.package == package;
    assert flake.checks.${system}.blender-smoke.system == system;
    assert package.doInstallCheck;
    assert package ? installCheckPhase;
    {
      inherit (package) system;
      packageFiles = walk "" package.src;
    }
  );
in
{
  path = toString source;
  files = walk "" source;
  inherit native;
}
