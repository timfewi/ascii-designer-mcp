import itertools
import unittest

import numpy as np

from ascii_designer.raster.edges import geometry_edges
from ascii_designer.raster.glyphs import build_char_atlas
from ascii_designer.raster.mapper import (
    GlyphMapper,
    Layout,
    MapperConfig,
    MapperState,
    atlas_chars,
    region_matrix,
)
from tests.helpers import font_path, frame, solid


def make_mapper(width: int, height: int, **config) -> GlyphMapper:
    cfg = MapperConfig(**config)
    atlas = build_char_atlas(atlas_chars(cfg), 10, 20, font_path())
    return GlyphMapper(atlas, Layout.for_size(width, height, 10, 20), cfg)


def chars(mapper: GlyphMapper, glyphs: np.ndarray) -> str:
    return "".join(mapper.atlas.chars[int(i)] for i in glyphs.ravel())


class LayoutTests(unittest.TestCase):
    def test_even_offsets_and_split(self) -> None:
        layout = Layout.for_size(1926, 1206, 10, 20)
        self.assertEqual((layout.cols, layout.rows), (192, 60))
        self.assertEqual((layout.off_x % 2, layout.off_y % 2), (0, 0))
        image = np.arange(40 * 20, dtype=np.float32).reshape(40, 20)
        cells = Layout.for_size(20, 40, 10, 20).split(image)
        self.assertEqual(cells.shape, (4, 200))
        self.assertEqual(cells[1, 0], image[0, 10])

    def test_region_matrix_rows_average(self) -> None:
        regions = region_matrix(10, 20, 2, 3)
        self.assertEqual(regions.shape, (6, 200))
        np.testing.assert_allclose(regions.sum(axis=1), 1.0, rtol=1e-6)


class MappingTests(unittest.TestCase):
    def test_flat_ramp_is_monotonic_and_uses_the_ramp(self) -> None:
        mapper = make_mapper(200, 20, edges=False, color_lightness=0.0)
        values = np.linspace(0.0, 1.0, 20, dtype=np.float32)
        rgb = np.repeat(np.repeat(values[None, :], 20, 0), 10, 1)[..., None].repeat(3, -1)
        result = mapper.map(frame(rgb), MapperState())
        text = chars(mapper, result.glyphs)
        coverage = [float(mapper.atlas.masks[i].mean()) for i in result.glyphs.ravel()]
        self.assertEqual(text[0], " ")
        self.assertTrue(all(b >= a - 1e-6 for a, b in itertools.pairwise(coverage)))
        self.assertTrue(set(text) <= set(" .:-=+*#%@"), text)

    def test_offset_stripe_moves_ink_to_its_side(self) -> None:
        mapper = make_mapper(10, 20, edges=False, charset="ascii")
        rgb = np.zeros((20, 10, 3), dtype=np.float32)
        rgb[:, 1:4] = 1.0
        glyph = int(mapper.map(frame(rgb), MapperState()).glyphs[0, 0])
        mask = mapper.atlas.masks[glyph]
        centroid = float((mask.sum(axis=0) * (np.arange(10) + 0.5)).sum() / mask.sum())
        self.assertLess(centroid, 5.0, mapper.atlas.chars[glyph])

    def test_left_half_prefers_left_heavy_glyph(self) -> None:
        mapper = make_mapper(10, 20, edges=False, charset="blocks")
        rgb = np.zeros((20, 10, 3), dtype=np.float32)
        rgb[:, :5] = 1.0
        self.assertEqual(chars(mapper, mapper.map(frame(rgb), MapperState()).glyphs), "▌")

    def test_hysteresis_holds_glyphs_under_noise(self) -> None:
        rng = np.random.default_rng(3)
        base = (
            np.linspace(0.1, 0.9, 400, dtype=np.float32)[None, :, None].repeat(200, 0).repeat(3, 2)
        )
        stable = make_mapper(400, 200, edges=False, hysteresis=0.3)
        jumpy = make_mapper(400, 200, edges=False, hysteresis=0.0)
        state_a, state_b = MapperState(), MapperState()
        changes_a = changes_b = 0
        prev_a = prev_b = None
        for _ in range(8):
            noisy = np.clip(base + rng.normal(0, 0.03, base.shape).astype(np.float32), 0, 1)
            a = stable.map(frame(noisy), state_a).glyphs
            b = jumpy.map(frame(noisy), state_b).glyphs
            if prev_a is not None and prev_b is not None:
                changes_a += int((a != prev_a).sum())
                changes_b += int((b != prev_b).sum())
            prev_a, prev_b = a, b
        self.assertLess(changes_a, changes_b * 0.5)

    def test_warm_start_reaches_a_fixed_point(self) -> None:
        mapper = make_mapper(200, 100, edges=False, hysteresis=0.2)
        frames = [
            frame(solid(100, 200, 0.2 + 0.6 * (0.5 + 0.5 * np.sin(2 * np.pi * k / 6))))
            for k in range(6)
        ]
        features = [mapper.features(f) for f in frames]
        state = MapperState()
        before = state.copy()
        for _ in range(4):
            before = state.copy()
            for f in features:
                mapper.decide(f, state)
        self.assertEqual(state.same_as(before), 0)

    def test_depth_step_becomes_edge_glyphs(self) -> None:
        height, width = 200, 400
        depth = np.full((height, width), 5.0, dtype=np.float32)
        depth[:, width // 2 :] = 9.0
        normal = np.zeros((height, width, 3), dtype=np.float32)
        normal[..., 2] = 1.0
        alpha = np.ones((height, width), dtype=np.float32)
        edges = geometry_edges(depth, normal, alpha)
        self.assertGreater(float(edges[:, width // 2 - 1 : width // 2 + 1].mean()), 0.9)
        self.assertEqual(float(edges[:, :150].max()), 0.0)
        mapper = make_mapper(width, height)
        result = mapper.map(frame(solid(height, width, 0.5), edges), MapperState())
        middle = width // 10 // 2
        column = chars(mapper, result.glyphs[:, middle - 1 : middle + 1])
        self.assertIn("|", column)

    def test_ink_colour_comes_from_under_the_glyph(self) -> None:
        mapper = make_mapper(10, 20, edges=False, charset="blocks", saturation=1.0)
        rgb = np.zeros((20, 10, 3), dtype=np.float32)
        rgb[:, :5] = (0.9, 0.05, 0.05)  # red left half
        result = mapper.map(frame(rgb), MapperState())
        fg = result.fg[0, 0]
        self.assertGreater(fg[0], 0.8)
        self.assertLess(fg[2], 0.2)

    def test_tint_background(self) -> None:
        mapper = make_mapper(10, 20, edges=False, background="tint:0.5")
        result = mapper.map(frame(solid(20, 10, 0.4, (0.2, 0.4, 1.0))), MapperState())
        self.assertGreater(float(result.bg[0, 0, 2]), 0.0)


if __name__ == "__main__":
    unittest.main()
