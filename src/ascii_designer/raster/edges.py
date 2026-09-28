"""Edge fields in [0, 1] per pixel.

3D sources use geometry: relative (log) depth discontinuities and normal-angle
discontinuities. 2D sources fall back to luminance gradients.
"""

from __future__ import annotations

import numpy as np

from ascii_designer.raster.colors import perceptual


def smoothstep(low: float, high: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def geometry_edges(depth: np.ndarray, normal: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Silhouettes, occlusion boundaries and creases from Blender passes."""
    solid = alpha > 0.5
    valid = solid & np.isfinite(depth) & (depth > 0) & (depth < 1e9)
    if valid.any():
        far = float(depth[valid].max()) * 8.0
    else:
        return np.zeros(depth.shape, dtype=np.float32)
    log_depth = np.log(np.where(valid, depth, far)).astype(np.float32)
    # Second differences ignore smooth slopes (floors near the horizon) but
    # catch steps; the step shows up on both neighbours, giving 2 px lines.
    d2 = np.zeros_like(log_depth)
    d2[:, 1:-1] = np.abs(log_depth[:, 2:] - 2 * log_depth[:, 1:-1] + log_depth[:, :-2])
    d2[1:-1, :] = np.maximum(
        d2[1:-1, :], np.abs(log_depth[2:, :] - 2 * log_depth[1:-1, :] + log_depth[:-2, :])
    )
    depth_edges = smoothstep(0.02, 0.06, d2)

    n = np.where(solid[..., None], normal, 0.0).astype(np.float32)
    dn = np.zeros(depth.shape, dtype=np.float32)
    dx = np.linalg.norm(n[:, 1:] - n[:, :-1], axis=-1)
    dy = np.linalg.norm(n[1:, :] - n[:-1, :], axis=-1)
    dn[:, 1:] = np.maximum(dn[:, 1:], dx)
    dn[:, :-1] = np.maximum(dn[:, :-1], dx)
    dn[1:, :] = np.maximum(dn[1:, :], dy)
    dn[:-1, :] = np.maximum(dn[:-1, :], dy)
    normal_edges = smoothstep(0.45, 0.75, dn)
    return np.maximum(depth_edges, normal_edges).astype(np.float32)


def luminance_edges(lum: np.ndarray) -> np.ndarray:
    """Sobel magnitude on display lightness for video and image sources."""
    p = perceptual(lum).astype(np.float32)
    pad = np.pad(p, 1, mode="edge")
    gx = (
        pad[:-2, 2:]
        + 2 * pad[1:-1, 2:]
        + pad[2:, 2:]
        - pad[:-2, :-2]
        - 2 * pad[1:-1, :-2]
        - pad[2:, :-2]
    )
    gy = (
        pad[2:, :-2]
        + 2 * pad[2:, 1:-1]
        + pad[2:, 2:]
        - pad[:-2, :-2]
        - 2 * pad[:-2, 1:-1]
        - pad[:-2, 2:]
    )
    return smoothstep(0.35, 0.9, np.hypot(gx, gy)).astype(np.float32)
