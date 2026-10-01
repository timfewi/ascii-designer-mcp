{ lib, root }:
lib.cleanSourceWith {
  name = "ascii-designer-source";
  src = root;
  filter =
    path: type:
    let
      relative = lib.removePrefix "${toString root}/" (toString path);
      parts = lib.splitString "/" relative;
      inTree = builtins.elem (builtins.head parts) [
        "src"
        "tests"
      ];
      runtimeDirectory = lib.any (
        part:
        builtins.elem part [
          ".ast-index"
          ".direnv"
          ".git"
          ".pytest_cache"
          ".ruff_cache"
          ".scratch"
          ".venv"
          "__pycache__"
        ]
      ) parts;
    in
    !runtimeDirectory
    && (
      (inTree && type == "directory")
      || (
        type == "regular"
        && (
          builtins.elem relative [
            "pyproject.toml"
            "README.md"
            "LICENSE"
          ]
          || (inTree && lib.hasSuffix ".py" relative)
        )
      )
    );
}
