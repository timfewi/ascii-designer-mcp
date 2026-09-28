import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ascii_designer.errors import SpecError
from ascii_designer.output.ansi import frame_to_ansi
from ascii_designer.output.asciimotion import session
from ascii_designer.output.grid import GridRecorder
from ascii_designer.raster.compose import bloom, compose_linear, to_srgb8
from ascii_designer.raster.glyphs import build_atlas
from ascii_designer.raster.mapper import AsciiFrame, Layout
from tests.helpers import font_path


def sample_grid() -> tuple[GridRecorder, AsciiFrame]:
    chars = (" ", "#", "@")
    glyphs = np.array([[0, 1, 2], [2, 1, 0]], dtype=np.int32)
    fg = np.full((2, 3, 3), 0.5, dtype=np.float32)
    bg = np.zeros((2, 3, 3), dtype=np.float32)
    ascii_frame = AsciiFrame(glyphs, fg, bg)
    grid = GridRecorder(chars, 2, 3, 36.0)
    grid.add(ascii_frame)
    grid.add(ascii_frame)
    return grid, ascii_frame


class GridExportTests(unittest.TestCase):
    def test_text_and_roundtrip(self) -> None:
        grid, _ = sample_grid()
        self.assertEqual(grid.text(0), [" #@", "@# "])
        with tempfile.TemporaryDirectory() as tmp:
            loaded = GridRecorder.load(grid.save(Path(tmp) / "g.npz"))
        self.assertEqual(loaded.text(1), grid.text(1))
        self.assertEqual(loaded.fps, 36.0)

    def test_ansi_has_truecolor_codes(self) -> None:
        grid, _ = sample_grid()
        text = frame_to_ansi(grid, 0)
        self.assertIn("\x1b[38;2;188;188;188m", text)
        self.assertEqual(text.count("\n"), 2)

    def test_asciimotion_session_matches_importer_shape(self) -> None:
        grid, _ = sample_grid()
        data = session(grid, "demo", "#000000")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["canvas"]["width"], 3)
        frames = data["animation"]["frames"]
        self.assertEqual(len(frames), 2)
        self.assertAlmostEqual(frames[0]["duration"], 1000 / 36)
        cells = frames[0]["data"]
        self.assertEqual(set(cells), {"1,0", "2,0", "0,1", "1,1"})
        self.assertEqual(cells["2,0"], {"char": "@", "color": "#bcbcbc", "bgColor": "#000000"})
        json.dumps(data)
        with self.assertRaisesRegex(SpecError, "limit"):
            session(grid, "demo", "#000000", budget=3)


class ComposeTests(unittest.TestCase):
    def test_compose_places_grid_and_margin(self) -> None:
        atlas = build_atlas("ascii", 10, 20, font_path())
        layout = Layout.for_size(34, 44, 10, 20)
        glyphs = np.full((layout.rows, layout.cols), atlas.index["#"], dtype=np.int32)
        ascii_frame = AsciiFrame(
            glyphs,
            np.ones((layout.rows, layout.cols, 3), dtype=np.float32),
            np.zeros((layout.rows, layout.cols, 3), dtype=np.float32),
        )
        margin = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        image = compose_linear(ascii_frame, atlas, layout, margin)
        self.assertEqual(image.shape, (44, 34, 3))
        np.testing.assert_allclose(image[0, 0], margin)
        self.assertGreater(
            float(image[layout.off_y : layout.off_y + 20, layout.off_x :].max()), 0.9
        )
        rgba = to_srgb8(compose_linear(ascii_frame, atlas, layout, margin, transparent=True))
        self.assertEqual(rgba.shape, (44, 34, 4))
        self.assertEqual(int(rgba[0, 0, 3]), 0)

    def test_bloom_spreads_light(self) -> None:
        image = np.zeros((64, 64, 3), dtype=np.float32)
        image[30:34, 30:34] = 1.0
        glow = bloom(image)
        self.assertGreater(float(glow[20, 32, 0]), 0.0)
        self.assertEqual(glow.shape, image.shape)


if __name__ == "__main__":
    unittest.main()
