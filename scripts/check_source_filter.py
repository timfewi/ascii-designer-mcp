"""Check cache-independent sources and native Linux outputs without building."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def evaluate(project: Path, fixture: Path) -> dict:
    result = subprocess.run(
        [
            "nix",
            "eval",
            "--offline",
            "--no-write-lock-file",
            "--impure",
            "--option",
            "allow-import-from-derivation",
            "false",
            "--json",
            "--file",
            str(project / "scripts/source_filter.nix"),
        ],
        env={
            **os.environ,
            "SOURCE_CHECK_FLAKE_URI": "git+file://" + quote(str(project), safe="/"),
            "SOURCE_CHECK_FIXTURE_ROOT": str(fixture),
        },
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.stderr)
    return json.loads(result.stdout)


def main() -> None:
    project = Path(__file__).resolve().parent.parent
    expected = ["LICENSE", "README.md", "pyproject.toml", "src/app.py", "tests/test_app.py"]
    with tempfile.TemporaryDirectory(prefix="ascii-source-check-") as temporary:
        base = Path(temporary)
        clean, dirty = base / "clean", base / "dirty"
        for root in (clean, dirty):
            for path, text in (
                ("LICENSE", "Synthetic license\n"),
                ("README.md", "Synthetic package readme\n"),
                ("pyproject.toml", '[project]\nname = "fixture"\nversion = "0.0.0"\n'),
                ("src/app.py", "VALUE = 1\n"),
                ("tests/test_app.py", "assert True\n"),
            ):
                write(root, path, text)
        for path in (
            ".git/config",
            ".ast-index/index.json",
            ".direnv/environment",
            ".ruff_cache/data",
            ".venv/private.py",
            ".scratch/job.json",
            "src/__pycache__/app.pyc",
            "src/__pycache__/cached.py",
            "src/.ast-index/cached.py",
            "tests/.pytest_cache/cached.py",
            "tests/job.json",
            "docs/private.py",
            "private.txt",
        ):
            write(dirty, path, "Synthetic runtime state.\n")
        outside = base / "outside.py"
        outside.write_text("OUTSIDE = True\n")
        (dirty / "src/linked.py").symlink_to(outside)
        os.mkfifo(dirty / "src/pipe.py")
        first, second = evaluate(project, clean), evaluate(project, dirty)
        assert first["files"] == expected == second["files"], "Unexpected package files"
        assert first["path"] == second["path"], "Runtime state changed source store path"
        write(dirty, "src/__pycache__/app.pyc", "Changed runtime state.\n")
        assert evaluate(project, dirty)["path"] == first["path"], "Cache update changed source"
        write(dirty, "src/app.py", "VALUE = 2\n")
        assert evaluate(project, dirty)["path"] != first["path"], "Source edit was omitted"
        assert set(second["native"]) == {"x86_64-linux", "aarch64-linux"}
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "src", "tests"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        required = {"LICENSE", "README.md", "pyproject.toml"} | {
            path for path in tracked.split("\0") if path.endswith(".py")
        }
        for system, package in second["native"].items():
            assert package["system"] == system
            assert set(package["packageFiles"]) == required, "Actual package sources differ"
    print(
        "Source filter passed: all Python and Blender scripts retained; runtime state "
        "excluded; hashes stable; package, shell, formatter, runner and checks "
        "match both Linux systems."
    )


if __name__ == "__main__":
    main()
