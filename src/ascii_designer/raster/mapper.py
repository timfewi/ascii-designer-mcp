"""Image -> ASCII grid mapping.

Per cell the luminance is sampled on a sub-cell grid (a shape vector), sharpened
(directional and gated global contrast), divided into a glyph target and a
foreground lightness (one brightness model), and matched to the glyph atlas by
nearest neighbour. 3D edges override cells with oriented line glyphs. Temporal
hysteresis keeps glyphs stable between frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ascii_designer.raster.colors import brightness, hex_to_linear, luminance, perceptual
from ascii_designer.raster.edges import smoothstep
from ascii_designer.raster.glyphs import EDGE_CHARS, FILL_RAMPS, GlyphAtlas, charset_chars

SHAPE_GRIDS = {"ascii": (2, 3), "symbols": (2, 3), "blocks": (2, 6), "braille": (2, 4)}
_EPS = 1e-6


@dataclass(frozen=True)
class Layout:
    """Cell grid placed inside the output frame; offsets are even for 4:2:0 chroma."""

    width: int
    height: int
    cell_w: int
    cell_h: int
    cols: int
    rows: int
    off_x: int
    off_y: int

    @classmethod
    def for_size(cls, width: int, height: int, cell_w: int, cell_h: int) -> Layout:
        cols, rows = width // cell_w, height // cell_h
        off_x = ((width - cols * cell_w) // 2) & ~1
        off_y = ((height - rows * cell_h) // 2) & ~1
        return cls(width, height, cell_w, cell_h, cols, rows, off_x, off_y)

    @property
    def cells(self) -> int:
        return self.cols * self.rows

    def split(self, image: np.ndarray) -> np.ndarray:
        """(H, W, ...) -> (cells, cell_h * cell_w, ...) in row-major cell order."""
        h, w = self.rows * self.cell_h, self.cols * self.cell_w
        region = image[self.off_y : self.off_y + h, self.off_x : self.off_x + w]
        tail = region.shape[2:]
        blocks = region.reshape(self.rows, self.cell_h, self.cols, self.cell_w, *tail)
        blocks = np.moveaxis(blocks, 2, 1)
        return blocks.reshape(self.cells, self.cell_h * self.cell_w, *tail)


@dataclass(frozen=True)
class FrameInput:
    rgb: np.ndarray  # (H, W, 3) float32 linear light, premultiplied over black
    alpha: np.ndarray  # (H, W) float32
    edges: np.ndarray | None = None  # (H, W) float32 edge field in [0, 1]


@dataclass(frozen=True)
class EdgeFeatures:
    strength: np.ndarray  # line length through the cell relative to a full crossing
    angle: np.ndarray  # line orientation, radians in [0, pi)
    coherence: np.ndarray  # 1 = one clean direction, 0 = corner or noise
    cx: np.ndarray  # edge centroid in cell fractions
    cy: np.ndarray


@dataclass(frozen=True)
class CellFeatures:
    target: np.ndarray  # (cells, regions) glyph target in [0, 1]
    reference: np.ndarray  # (cells,) foreground lightness before ink gain
    edge: EdgeFeatures | None = None

    @property
    def nbytes(self) -> int:
        total = self.target.nbytes + self.reference.nbytes
        if self.edge is not None:
            total += sum(a.nbytes for a in vars(self.edge).values())
        return total


@dataclass
class AsciiFrame:
    glyphs: np.ndarray  # (rows, cols) int32 atlas indices
    fg: np.ndarray  # (rows, cols, 3) float32 linear
    bg: np.ndarray  # (rows, cols, 3) float32 linear


@dataclass
class MapperState:
    glyphs: np.ndarray | None = None
    edge_on: np.ndarray | None = None
    edge_choice: np.ndarray | None = None

    def copy(self) -> MapperState:
        return MapperState(
            None if self.glyphs is None else self.glyphs.copy(),
            None if self.edge_on is None else self.edge_on.copy(),
            None if self.edge_choice is None else self.edge_choice.copy(),
        )

    def same_as(self, other: MapperState) -> int:
        """Number of cells whose glyph differs (0 means converged)."""
        if self.glyphs is None or other.glyphs is None:
            return -1
        return int(np.count_nonzero(self.glyphs != other.glyphs))


@dataclass(frozen=True)
class MapperConfig:
    charset: str = "symbols"
    contrast: float = 1.8
    contrast_floor: float = 0.25
    directional_contrast: float = 1.0
    hysteresis: float = 0.15
    hysteresis_floor: float = 0.01
    color_lightness: float = 0.5
    shape_weight: float = 0.35
    flat_shape: float = 0.003
    saturation: float = 1.15
    brightness: float = 1.0
    edges: bool = True
    edge_threshold: float = 0.45
    edge_min_lightness: float = 0.5
    background: str = "#000000"
    grid: tuple[int, int] | None = None
    ramp: str | None = None  # overrides the charset's flat-cell ramp ("" disables)

    @property
    def edge_glyph_mode(self) -> bool:
        """Font charsets draw edges as line glyphs; mosaics draw them into the target."""
        return self.charset not in ("blocks", "braille")

    def shape_grid(self) -> tuple[int, int]:
        return self.grid or SHAPE_GRIDS.get(self.charset, (2, 3))


def atlas_chars(config: MapperConfig) -> str:
    chars = charset_chars(config.charset)
    if config.edges and config.edge_glyph_mode:
        chars += "".join(c for c in EDGE_CHARS if c not in chars)
    return chars


def region_matrix(cell_w: int, cell_h: int, gx: int, gy: int) -> np.ndarray:
    """(gy * gx, cell_h * cell_w) area weights; each row averages one sub-cell."""

    def spans(n: int, parts: int) -> np.ndarray:
        edges = np.arange(n + 1, dtype=np.float64)
        rows = []
        for i in range(parts):
            a, b = i * n / parts, (i + 1) * n / parts
            rows.append(np.clip(np.minimum(edges[1:], b) - np.maximum(edges[:-1], a), 0, 1))
        return np.stack(rows)

    weights = np.einsum("yh,xw->yxhw", spans(cell_h, gy), spans(cell_w, gx))
    weights = weights.reshape(gy * gx, cell_h * cell_w)
    return (weights / weights.sum(axis=1, keepdims=True)).astype(np.float32)


def _orientation(
    field_: np.ndarray, cell_w: int, cell_h: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Line angle (radians, [0, pi)), coherence and centroid per (n, cell_h, cell_w) field."""
    gy, gx = np.gradient(field_, axis=(1, 2))
    jxx = (gx * gx).sum(axis=(1, 2))
    jyy = (gy * gy).sum(axis=(1, 2))
    jxy = (gx * gy).sum(axis=(1, 2))
    phi = 0.5 * np.arctan2(2 * jxy, jxx - jyy)
    angle = np.mod(phi + np.pi / 2, np.pi)
    coherence = np.sqrt((jxx - jyy) ** 2 + 4 * jxy**2) / (jxx + jyy + _EPS)
    total = field_.sum(axis=(1, 2)) + _EPS
    ys = (np.arange(cell_h, dtype=np.float32) + 0.5)[None, :, None]
    xs = (np.arange(cell_w, dtype=np.float32) + 0.5)[None, None, :]
    cy = (field_ * ys).sum(axis=(1, 2)) / total / cell_h
    cx = (field_ * xs).sum(axis=(1, 2)) / total / cell_w
    return angle, coherence, cx, cy


@dataclass
class GlyphMapper:
    atlas: GlyphAtlas
    layout: Layout
    config: MapperConfig
    _regions: np.ndarray = field(init=False)
    _fill: np.ndarray = field(init=False)
    _glyph_density: np.ndarray = field(init=False)
    _glyph_shape: np.ndarray = field(init=False)
    _glyph_shape_norm: np.ndarray = field(init=False)
    _mean_profile: np.ndarray = field(init=False)
    _off_ramp: np.ndarray = field(init=False)
    _ink_gain: float = field(init=False)
    _edge_idx: np.ndarray = field(init=False)
    _edge_angle: np.ndarray = field(init=False)
    _edge_cx: np.ndarray = field(init=False)
    _edge_cy: np.ndarray = field(init=False)
    _background: np.ndarray | None = field(init=False)
    _tint: float = field(init=False)

    def __post_init__(self) -> None:
        cw, ch = self.layout.cell_w, self.layout.cell_h
        gx, gy = self.config.shape_grid()
        self._regions = region_matrix(cw, ch, gx, gy)
        fill_chars = charset_chars(self.config.charset)
        self._fill = np.array(
            [i for i, c in enumerate(self.atlas.chars) if c in fill_chars or c == " "],
            dtype=np.int64,
        )
        descriptors = self.atlas.flat[self._fill] @ self._regions.T  # (n, regions)
        regions = descriptors.shape[1]
        density = descriptors.mean(axis=1)
        dmax = max(float(density.max()), _EPS)
        self._ink_gain = float(np.clip(1.0 / dmax, 1.0, 2.5))
        self._glyph_density = perceptual(density / dmax).astype(np.float32)
        # Shape = how a glyph distributes its ink relative to the charset's average
        # profile, so the font's empty ascender/descender band is not a "shape".
        profile = descriptors / np.maximum(descriptors.sum(axis=1, keepdims=True), _EPS)
        weights = density / max(float(density.sum()), _EPS)
        self._mean_profile = (profile * weights[:, None]).sum(axis=0).astype(np.float32)
        shape = (profile - self._mean_profile) * regions
        shape[density < 1e-4] = 0.0
        self._glyph_shape = shape.astype(np.float32)
        self._glyph_shape_norm = (self._glyph_shape**2).sum(axis=1)
        ramp = (
            self.config.ramp
            if self.config.ramp is not None
            else FILL_RAMPS.get(self.config.charset, "")
        )
        fill_chars = [self.atlas.chars[i] for i in self._fill]
        self._off_ramp = np.array(
            [0.0 if (not ramp or c in ramp) else 1.0 for c in fill_chars], dtype=np.float32
        )

        edge = [self.atlas.index[c] for c in EDGE_CHARS if c in self.atlas.index]
        self._edge_idx = np.array(edge, dtype=np.int64)
        if edge:
            angle, _, cx, cy = _orientation(self.atlas.masks[self._edge_idx], cw, ch)
            self._edge_angle, self._edge_cx, self._edge_cy = angle, cx, cy
        else:
            self._edge_angle = self._edge_cx = self._edge_cy = np.zeros(0, dtype=np.float32)

        bg = self.config.background
        self._tint = float(bg.removeprefix("tint:")) if bg.startswith("tint:") else 0.0
        self._background = hex_to_linear(bg) if bg.startswith("#") else None

    @property
    def ink_gain(self) -> float:
        return self._ink_gain

    def map(self, frame: FrameInput, state: MapperState) -> AsciiFrame:
        features = self.features(frame)
        glyphs, edge_on = self.decide(features, state)
        return self.colorize(frame.rgb, glyphs, features.reference, edge_on)

    def features(self, frame: FrameInput) -> CellFeatures:
        """Everything the glyph decision needs, reduced to per-cell arrays."""
        cfg, layout = self.config, self.layout
        rgb = frame.rgb * np.float32(cfg.brightness)
        lum = brightness(rgb)
        edges = frame.edges if cfg.edges else None
        if edges is not None and not cfg.edge_glyph_mode:
            # Mosaics are fine enough to draw outlines directly.
            lum = np.maximum(lum, edges * np.float32(0.85))
        values = layout.split(lum) @ self._regions.T  # (n, R)
        peak = np.clip(values.max(axis=1), 0.0, 1.0)
        values = self._global_contrast(self._directional(values))
        reference = np.maximum(peak ** np.float32(cfg.color_lightness), _EPS).astype(np.float32)
        target = np.clip(values / reference[:, None], 0.0, 1.0).astype(np.float32)
        edge = None
        if edges is not None and cfg.edge_glyph_mode and len(self._edge_idx):
            edge = self._edge_features(edges)
        return CellFeatures(target, reference, edge)

    def decide(self, features: CellFeatures, state: MapperState) -> tuple[np.ndarray, np.ndarray]:
        """Pick glyph indices (with hysteresis) and update the temporal state."""
        cfg, layout = self.config, self.layout
        dist = self._distances(features.target)
        choice = dist.argmin(axis=1)
        glyphs = self._fill[choice]
        if state.glyphs is not None and cfg.hysteresis > 0:
            glyphs = self._hysteresis(glyphs, choice, dist, state.glyphs.ravel())
        edge_on = np.zeros(layout.cells, dtype=bool)
        if features.edge is not None:
            glyphs, edge_on = self._apply_edges(features.edge, glyphs, state)
        state.glyphs = glyphs.reshape(layout.rows, layout.cols).copy()
        return glyphs, edge_on

    def colorize(
        self, rgb: np.ndarray, glyphs: np.ndarray, reference: np.ndarray, edge_on: np.ndarray
    ) -> AsciiFrame:
        layout = self.layout
        cell_rgb = layout.split(rgb * np.float32(self.config.brightness))  # (n, P, 3)
        fg, bg = self._colors(glyphs, cell_rgb, reference, edge_on)
        return AsciiFrame(
            glyphs=glyphs.reshape(layout.rows, layout.cols).astype(np.int32),
            fg=fg.reshape(layout.rows, layout.cols, 3),
            bg=bg.reshape(layout.rows, layout.cols, 3),
        )

    def _distances(self, target: np.ndarray) -> np.ndarray:
        """Density difference (perceptual) plus gated shape-deviation difference."""
        cfg = self.config
        regions = target.shape[1]
        density = perceptual(target.mean(axis=1)).astype(np.float32)
        dist = (density[:, None] - self._glyph_density[None, :]) ** 2
        spread = _relative_spread(target)
        structure = smoothstep(cfg.contrast_floor, 2 * cfg.contrast_floor, spread)
        # Flat cells use the density ramp only; structured cells may use every
        # glyph and follow their shape.
        dist += (1.0 - structure)[:, None].astype(np.float32) * self._off_ramp[None, :]
        gate = cfg.shape_weight * (cfg.flat_shape + (1 - cfg.flat_shape) * structure)
        # A uniform target corresponds to the charset's average glyph profile.
        profile = target / np.maximum(target.sum(axis=1, keepdims=True), _EPS)
        shape = ((profile - 1.0 / regions) * regions).astype(np.float32)
        shape[target.sum(axis=1) < 1e-4] = 0.0
        shape_dist = (
            (shape**2).sum(axis=1)[:, None]
            - 2.0 * shape @ self._glyph_shape.T
            + self._glyph_shape_norm[None, :]
        ) / regions
        dist += gate[:, None].astype(np.float32) * np.maximum(shape_dist, 0.0)
        return dist

    # --- shape vector sharpening ---------------------------------------------

    def _directional(self, values: np.ndarray) -> np.ndarray:
        k = self.config.directional_contrast
        if k <= 0:
            return values
        gx, gy = self.config.shape_grid()
        rows, cols = self.layout.rows, self.layout.cols
        img = values.reshape(rows, cols, gy, gx).transpose(0, 2, 1, 3).reshape(rows * gy, cols * gx)
        context = img.copy()
        jj = np.arange(cols * gx)
        ii = np.arange(rows * gy)
        left = (jj % gx == 0) & (jj > 0)
        right = (jj % gx == gx - 1) & (jj < cols * gx - 1)
        top = (ii % gy == 0) & (ii > 0)
        bottom = (ii % gy == gy - 1) & (ii < rows * gy - 1)
        context[:, left] = np.maximum(context[:, left], img[:, np.flatnonzero(left) - 1])
        context[:, right] = np.maximum(context[:, right], img[:, np.flatnonzero(right) + 1])
        context[top, :] = np.maximum(context[top, :], img[np.flatnonzero(top) - 1, :])
        context[bottom, :] = np.maximum(context[bottom, :], img[np.flatnonzero(bottom) + 1, :])
        sharpened = img * np.power(img / np.maximum(context, _EPS), k)
        return sharpened.reshape(rows, gy, cols, gx).transpose(0, 2, 1, 3).reshape(rows * cols, -1)

    def _global_contrast(self, values: np.ndarray) -> np.ndarray:
        cfg = self.config
        if cfg.contrast <= 1.0:
            return values
        high = values.max(axis=1, keepdims=True)
        # Only cells with real structure are sharpened; smooth shading stays smooth.
        gate = smoothstep(cfg.contrast_floor, 2 * cfg.contrast_floor, _relative_spread(values))[
            :, None
        ]
        enhanced = high * np.power(values / np.maximum(high, _EPS), cfg.contrast)
        return values + (enhanced - values) * gate

    def _hysteresis(
        self, glyphs: np.ndarray, choice: np.ndarray, dist: np.ndarray, previous: np.ndarray
    ) -> np.ndarray:
        cfg = self.config
        lookup = np.full(len(self.atlas.chars), -1, dtype=np.int64)
        lookup[self._fill] = np.arange(len(self._fill))
        prev_choice = lookup[previous]
        valid = prev_choice >= 0
        cells = np.arange(len(glyphs))
        d_best = dist[cells, choice]
        d_prev = np.where(valid, dist[cells, np.maximum(prev_choice, 0)], np.inf)
        keep = valid & (
            (d_best >= d_prev * (1 - cfg.hysteresis)) | (d_prev - d_best < cfg.hysteresis_floor)
        )
        return np.where(keep, previous, glyphs)

    # --- edges ----------------------------------------------------------------

    def _edge_features(self, edges: np.ndarray) -> EdgeFeatures:
        layout = self.layout
        cw, ch = layout.cell_w, layout.cell_h
        cells = layout.split(edges).reshape(layout.cells, ch, cw)
        angle, coherence, cx, cy = _orientation(cells, cw, ch)
        cos_a = np.maximum(np.abs(np.cos(angle)), _EPS)
        sin_a = np.maximum(np.abs(np.sin(angle)), _EPS)
        length = np.minimum(cw / cos_a, ch / sin_a)
        strength = cells.sum(axis=(1, 2)) / (2.0 * length)
        return EdgeFeatures(*(a.astype(np.float32) for a in (strength, angle, coherence, cx, cy)))

    def _apply_edges(
        self, edge: EdgeFeatures, glyphs: np.ndarray, state: MapperState
    ) -> tuple[np.ndarray, np.ndarray]:
        diff = np.abs(
            np.mod(edge.angle[:, None] - self._edge_angle[None, :] + np.pi / 2, np.pi) - np.pi / 2
        )
        score = (
            diff / (np.pi / 4)
            + 0.8 * np.abs(edge.cy[:, None] - self._edge_cy[None, :])
            + 0.8 * np.abs(edge.cx[:, None] - self._edge_cx[None, :])
        )
        pick = score.argmin(axis=1)
        was_on = state.edge_on if state.edge_on is not None else np.zeros(len(pick), dtype=bool)
        if state.edge_choice is not None:
            cells_idx = np.arange(len(pick))
            prev = state.edge_choice
            keep = was_on & (score[cells_idx, prev] <= score[cells_idx, pick] + 0.25)
            pick = np.where(keep, prev, pick)
        threshold = self.config.edge_threshold
        candidate = (edge.coherence > 0.45) & (edge.strength > threshold)
        # Lines continue into neighbouring cells; isolated specks (stars, tiny
        # parts) stay fill glyphs such as '.' or '*'.
        linked = self._neighbours(candidate) >= 2
        on = (candidate & linked) | (
            was_on & (edge.coherence > 0.45) & (edge.strength > 0.6 * threshold)
        )
        state.edge_on = on
        state.edge_choice = pick
        return np.where(on, self._edge_idx[pick], glyphs), on

    def _neighbours(self, flags: np.ndarray) -> np.ndarray:
        grid = flags.reshape(self.layout.rows, self.layout.cols).astype(np.int8)
        padded = np.pad(grid, 1)
        total = sum(
            padded[1 + dy : 1 + dy + grid.shape[0], 1 + dx : 1 + dx + grid.shape[1]]
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if dy or dx
        )
        return np.asarray(total).ravel()

    # --- colour -----------------------------------------------------------------

    def _colors(
        self,
        glyphs: np.ndarray,
        cell_rgb: np.ndarray,
        reference: np.ndarray,
        edge_on: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        cfg = self.config
        masks = self.atlas.flat[glyphs]  # (n, P)
        ink_weight = masks.sum(axis=1)
        mean = cell_rgb.mean(axis=1)
        ink = np.einsum("np,npc->nc", masks, cell_rgb) / np.maximum(ink_weight, _EPS)[:, None]
        ink_y = brightness(ink)
        use_mean = ink_y < 1e-4
        ink = np.where(use_mean[:, None], mean, ink)
        ink_y = np.where(use_mean, brightness(mean), ink_y)
        # Hue and chroma from the pixels under the ink; lightness from the model.
        lightness = reference * self._ink_gain
        lightness = np.where(
            edge_on, np.maximum(reference, cfg.edge_min_lightness) * self._ink_gain, lightness
        )
        dark = ink_y < 1e-4
        fg = np.where(
            dark[:, None],
            lightness[:, None],
            ink * (lightness / np.maximum(ink_y, 1e-4))[:, None],
        )
        fg = _saturate(fg, cfg.saturation)
        fg = _gamut(fg).astype(np.float32)

        if self._background is not None:
            bg = np.broadcast_to(self._background, fg.shape).astype(np.float32)
        elif self._tint > 0:
            rest = 1.0 - masks
            bg = (
                np.einsum("np,npc->nc", rest, cell_rgb)
                / np.maximum(rest.sum(axis=1), _EPS)[:, None]
            )
            bg = (bg * self._tint).astype(np.float32)
        else:
            bg = np.zeros_like(fg)
        return fg, bg


def _relative_spread(values: np.ndarray) -> np.ndarray:
    high = values.max(axis=1)
    return (high - values.min(axis=1)) / np.maximum(high, 0.02)


def _saturate(rgb: np.ndarray, amount: float) -> np.ndarray:
    if amount == 1.0:
        return rgb
    y = luminance(rgb)[:, None]
    return np.maximum(y + (rgb - y) * amount, 0.0)


def _gamut(rgb: np.ndarray) -> np.ndarray:
    """Hue-preserving clip: scale colours whose brightest channel exceeds 1."""
    peak = rgb.max(axis=1, keepdims=True)
    return np.clip(rgb / np.maximum(peak, 1.0), 0.0, 1.0)
