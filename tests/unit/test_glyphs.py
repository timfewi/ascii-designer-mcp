import unittest

import numpy as np

from ascii_designer.raster.glyphs import (
    build_atlas,
    build_char_atlas,
    charset_chars,
    procedural_mask,
)
from tests.helpers import font_path


class ProceduralGlyphTests(unittest.TestCase):
    def test_blocks_have_exact_coverage(self) -> None:
        full = procedural_mask("█", 10, 20)
        upper = procedural_mask("▀", 10, 20)
        quadrant = procedural_mask("▗", 10, 20)
        assert full is not None and upper is not None and quadrant is not None
        self.assertTrue(np.all(full == 1.0))
        self.assertAlmostEqual(float(upper.mean()), 0.5)
        self.assertTrue(np.all(upper[:10] == 1.0) and np.all(upper[10:] == 0.0))
        self.assertAlmostEqual(float(quadrant.mean()), 0.25)
        self.assertEqual(float(quadrant[15, 7]), 1.0)

    def test_sextants_are_distinct_and_skip_half_blocks(self) -> None:
        masks = [procedural_mask(chr(0x1FB00 + i), 10, 18) for i in range(60)]
        signatures = {tuple(np.round(m[::6, ::5].ravel(), 2)) for m in masks if m is not None}
        self.assertEqual(len(signatures), 60)
        left_half = np.zeros((18, 10), dtype=np.float32)
        left_half[:, :5] = 1
        self.assertFalse(any(np.array_equal(m, left_half) for m in masks if m is not None))

    def test_braille_density_follows_dot_count(self) -> None:
        one = procedural_mask(chr(0x2801), 10, 20)
        eight = procedural_mask(chr(0x28FF), 10, 20)
        blank = procedural_mask(chr(0x2800), 10, 20)
        assert one is not None and eight is not None and blank is not None
        self.assertEqual(float(blank.sum()), 0.0)
        self.assertAlmostEqual(float(eight.sum()), float(one.sum()) * 8, delta=float(one.sum()))

    def test_custom_charset_always_has_space(self) -> None:
        self.assertTrue(charset_chars("custom:ab").startswith(" "))
        self.assertEqual(charset_chars("custom:aab"), " ab")


class FontAtlasTests(unittest.TestCase):
    def test_ascii_atlas(self) -> None:
        atlas = build_atlas("ascii", 10, 20, font_path())
        self.assertEqual(len(atlas.chars), 95)
        self.assertEqual(atlas.masks.shape, (95, 20, 10))
        coverage = dict(zip(atlas.chars, atlas.coverage(), strict=True))
        self.assertEqual(coverage[" "], 0.0)
        self.assertGreater(coverage["@"], coverage["."])
        self.assertGreater(coverage["#"], coverage["-"])

    def test_missing_glyphs_are_skipped(self) -> None:
        atlas = build_char_atlas(" a\U000e0001", 10, 20, font_path())
        self.assertIn("a", atlas.chars)
        self.assertIn("\U000e0001", atlas.skipped)


if __name__ == "__main__":
    unittest.main()
