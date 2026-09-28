"""Background render jobs for the MCP server.

A job is `ascii-designer-mcp render` in its own process group, with its state in
files (spec, progress lines, result, log) so it survives server restarts and can
be inspected or cancelled later. One job runs at a time: renders use the GPU
and several GB of RAM.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ascii_designer.cache import cache_root
from ascii_designer.errors import DesignerError

_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}


def jobs_dir() -> Path:
    return cache_root() / "jobs"


def start(spec_data: dict[str, Any]) -> dict[str, Any]:
    running = [j for j in list_jobs() if j["state"] == "running"]
    if running:
        raise DesignerError(
            f"job {running[0]['id']} is still running; wait for it or cancel it first"
        )
    job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    directory = jobs_dir() / job_id
    directory.mkdir(parents=True)
    spec_file = directory / "spec.json"
    spec_file.write_text(json.dumps(spec_data, indent=2), encoding="utf-8")
    argv = [
        sys.executable,
        "-m",
        "ascii_designer",
        "render",
        str(spec_file),
        "--progress",
        str(directory / "progress.jsonl"),
        "--result",
        str(directory / "result.json"),
    ]
    env = dict(os.environ)
    # The child must import exactly what this process imports (Nix wrappers
    # inject site paths into sys.path rather than the environment).
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    with (directory / "render.log").open("wb") as log:
        process = subprocess.Popen(
            argv,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(Path.cwd()),
            env=env,
            start_new_session=True,
        )
    _PROCESSES[job_id] = process
    meta = {"id": job_id, "pid": process.pid, "started": time.time(), "dir": str(directory)}
    (directory / "job.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return status(job_id)


def status(job_id: str) -> dict[str, Any]:
    directory = _job_path(job_id)
    meta = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    result_file = directory / "result.json"
    cancelled = (directory / "cancelled").exists()
    code = _exit_code(job_id, int(meta["pid"]))
    if result_file.is_file():
        state = "done"
    elif cancelled:
        state = "cancelled"
    elif code is None:
        state = "running"
    else:
        state = "failed"
    report: dict[str, Any] = {
        "id": job_id,
        "state": state,
        "elapsed_seconds": round(time.time() - float(meta["started"]), 1),
        "dir": str(directory),
    }
    progress = _last_progress(directory / "progress.jsonl")
    if progress:
        report["progress"] = progress
    if state == "done":
        report["result"] = json.loads(result_file.read_text(encoding="utf-8"))
    elif state == "failed":
        report["error"] = _log_tail(directory / "render.log")
    return report


def cancel(job_id: str) -> dict[str, Any]:
    current = status(job_id)
    if current["state"] != "running":
        return current
    directory = _job_path(job_id)
    meta = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    (directory / "cancelled").touch()
    with contextlib.suppress(ProcessLookupError):
        os.killpg(int(meta["pid"]), signal.SIGTERM)
    process = _PROCESSES.get(job_id)
    if process is not None:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(int(meta["pid"]), signal.SIGKILL)
    return status(job_id)


def list_jobs(limit: int = 10) -> list[dict[str, Any]]:
    root = jobs_dir()
    if not root.is_dir():
        return []
    ids = sorted((p.name for p in root.iterdir() if (p / "job.json").is_file()), reverse=True)
    return [status(job_id) for job_id in ids[:limit]]


def _job_path(job_id: str) -> Path:
    if not job_id or "/" in job_id or job_id.startswith("."):
        raise DesignerError(f"invalid job id {job_id!r}")
    directory = jobs_dir() / job_id
    if not (directory / "job.json").is_file():
        raise DesignerError(f"unknown job {job_id!r}")
    return directory


def _exit_code(job_id: str, pid: int) -> int | None:
    """None while the process runs; an exit code (or -1 if unknown) afterwards."""
    process = _PROCESSES.get(job_id)
    if process is not None:
        return process.poll()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return -1
    except PermissionError:
        return None
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file() and ") Z " in stat.read_text():
        return -1
    return None


def _last_progress(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1]) if lines else None


def _log_tail(path: Path, limit: int = 1500) -> str:
    if not path.is_file():
        return "render process exited without output"
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r", "\n")
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("[")]
    return "\n".join(lines)[-limit:] or "render process exited without a result"
