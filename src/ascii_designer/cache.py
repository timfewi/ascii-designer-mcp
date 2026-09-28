"""Pass cache: rendered Blender frames keyed by everything that affects pixels."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

CACHE_ENV = "ASCII_DESIGNER_CACHE"


def cache_root() -> Path:
    explicit = os.environ.get(CACHE_ENV)
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "ascii-designer"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key_for(parts: dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:24]


def pass_dir(key: str) -> Path:
    return cache_root() / "passes" / key


def is_complete(directory: Path, frames: range) -> bool:
    marker = directory / "complete.json"
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        data.get("frame_start", 1) <= frames.start and data.get("frame_end", 0) >= frames.stop - 1
    )


def mark_complete(directory: Path, frames: range, info: dict[str, Any]) -> None:
    payload = {"frame_start": frames.start, "frame_end": frames.stop - 1, **info}
    (directory / "complete.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def usage() -> dict[str, Any]:
    root = cache_root()
    total = 0
    entries = 0
    for directory in (root / "passes").glob("*") if (root / "passes").is_dir() else []:
        entries += 1
        total += sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
    return {"path": str(root), "pass_sets": entries, "bytes": total}


def prune(older_than_days: float = 0.0) -> dict[str, Any]:
    """Remove cached pass sets (all, or those unused for the given number of days)."""
    root = cache_root() / "passes"
    removed = 0
    freed = 0
    cutoff = time.time() - older_than_days * 86400
    for directory in root.glob("*") if root.is_dir() else []:
        if older_than_days and directory.stat().st_mtime > cutoff:
            continue
        freed += sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
        shutil.rmtree(directory, ignore_errors=True)
        removed += 1
    return {"removed": removed, "freed_bytes": freed}
