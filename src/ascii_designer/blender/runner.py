"""Run Blender headless with render_passes.py and stream its progress events."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from ascii_designer.errors import EnvironmentBlockedError, RenderError

SCRIPTS = Path(__file__).resolve().parent / "scripts"
PASS_SCRIPT = SCRIPTS / "render_passes.py"
BLENDER_ENV = "ASCII_DESIGNER_BLENDER"
EVENT_PREFIX = "ASCII_DESIGNER "
SUPPORTED_FILE_VERSION = (5, 2)

Progress = Callable[[dict[str, Any]], None]


def blender_binary() -> str:
    explicit = os.environ.get(BLENDER_ENV)
    if explicit:
        if not Path(explicit).is_file():
            raise EnvironmentBlockedError(f"{BLENDER_ENV} points to a missing file: {explicit}")
        return explicit
    found = shutil.which("blender")
    if not found:
        raise EnvironmentBlockedError(
            f"blender not found on PATH; install Blender 5.2 or set {BLENDER_ENV}"
        )
    return found


@cache
def blender_version(binary: str) -> str:
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=_child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EnvironmentBlockedError(f"cannot run {binary}: {error}") from error
    match = re.search(r"Blender (\d+\.\d+(?:\.\d+)?)", result.stdout)
    if not match:
        raise EnvironmentBlockedError(f"cannot read the Blender version from {binary}")
    return match.group(1)


def script_digest() -> str:
    """Hash of every Blender-side script; part of the pass cache key."""
    digest = hashlib.sha256()
    for path in sorted(SCRIPTS.rglob("*.py")):
        digest.update(path.relative_to(SCRIPTS).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def blend_file_version(path: Path) -> tuple[int, int] | None:
    """Best-effort read of the Blender version that saved a .blend file."""
    with path.open("rb") as handle:
        head = handle.read(32)
    if head[:2] == b"\x1f\x8b" or head[:4] == b"\x28\xb5\x2f\xfd":
        return None  # compressed; Blender itself will report problems
    match = re.match(rb"BLENDER(?:\d\d-\d\d[vV](\d)(\d\d)|[_-][vV](\d)(\d\d))", head)
    if not match:
        return None
    major, minor = (match.group(1), match.group(2)) if match.group(1) else match.group(3, 4)
    return int(major), int(minor)


def run_job(
    job: dict[str, Any],
    *,
    blend: Path | None = None,
    log_path: Path | None = None,
    progress: Progress | None = None,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Run one render_passes.py job; returns all emitted events."""
    binary = blender_binary()
    with tempfile.TemporaryDirectory(prefix="ascii-designer-") as tmp:
        job_file = Path(tmp) / "job.json"
        job_file.write_text(json.dumps(job), encoding="utf-8")
        argv = [binary, "-b", "--factory-startup", "-noaudio"]
        if blend is not None:
            argv += ["-Y", str(blend)]
        argv += ["--python-exit-code", "1", "-P", str(PASS_SCRIPT), "--", str(job_file)]
        env = _child_env()
        env["HOME"] = env.get("HOME") or tmp
        events: list[dict[str, Any]] = []
        tail: list[str] = []
        log = log_path.open("w", encoding="utf-8") if log_path else None
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            assert process.stdout is not None
            for line in process.stdout:
                if log:
                    log.write(line)
                tail = [*tail[-39:], line.rstrip()]
                if line.startswith(EVENT_PREFIX):
                    event = json.loads(line[len(EVENT_PREFIX) :])
                    events.append(event)
                    if progress:
                        progress(event)
            code = process.wait(timeout=timeout)
        finally:
            if log:
                log.close()
    if code != 0 or not any(e.get("event") in ("done", "saved", "info") for e in events):
        detail = "\n".join(line for line in tail if line.strip())[-1500:]
        raise RenderError(f"Blender failed (exit {code}):\n{detail}")
    return events


def _child_env() -> dict[str, str]:
    # Blender bundles Python 3.13; never let the caller's Python environment leak in.
    return {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
