"""Real Blender renders; opt-in (ASCII_DESIGNER_BLENDER_TESTS=1) because they take minutes."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from ascii_designer.blender import runner
from ascii_designer.presets import PRESETS
from ascii_designer.raster.passes import PassSequence
from ascii_designer.service import Designer
from ascii_designer.spec import parse_spec
from tests.helpers import font_path, require_blender_tests


class BlenderTests(unittest.TestCase):
    def setUp(self) -> None:
        require_blender_tests()
        font_path()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._env = dict(os.environ)
        os.environ["ASCII_DESIGNER_CACHE"] = str(self.dir / "cache")

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _spec(self, preset: str, **extra) -> dict:
        return {
            "source": preset,
            "size": "160x100",
            "cell": "8x16",
            "seconds": 0.25,
            "fps": 12,
            "samples": 4,
            "engine": os.environ.get("ASCII_DESIGNER_TEST_ENGINE", "eevee"),
            "output_dir": str(self.dir / "out"),
            **extra,
        }

    def test_passes_have_expected_layout(self) -> None:
        designer = Designer()
        spec = parse_spec(self._spec("torus-knot"))
        plan = designer.plan(spec)
        directory = designer.ensure_passes(spec, plan)
        frames = PassSequence.open(directory, plan.frames)
        first = frames.load(1)
        self.assertEqual(first.rgb.shape, (100, 160, 3))
        assert first.edges is not None
        self.assertGreater(float(first.alpha.mean()), 0.02)
        self.assertGreater(float(first.edges.max()), 0.5)
        marker = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["blender"]["passes"], ["depth", "normal"])

    def test_loop_render_is_seamless(self) -> None:
        result = Designer().render(parse_spec(self._spec("tunnel", outputs=["wallpaper", "png"])))
        self.assertEqual(result["frames"], 3)
        self.assertTrue(Path(result["outputs"]["wallpaper"]).is_file())
        seam = result["seam"]
        self.assertEqual(seam["glyph_state_mismatch"], 0)
        self.assertLess(seam["scene_mean_abs_diff"], 0.5)

    def test_every_preset_builds(self) -> None:
        for name in PRESETS:
            with self.subTest(preset=name):
                out = self.dir / f"{name}.blend"
                Designer().preset_blend(parse_spec(self._spec(name)), out)
                self.assertTrue(out.is_file())
                self.assertEqual(runner.blend_file_version(out), (5, 2))


if __name__ == "__main__":
    unittest.main()
