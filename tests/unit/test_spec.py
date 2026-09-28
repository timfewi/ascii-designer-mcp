import json
import tempfile
import unittest
from pathlib import Path

from ascii_designer.errors import SpecError
from ascii_designer.spec import absolutize, load_spec_file, parse_spec


class SpecTests(unittest.TestCase):
    def test_defaults_for_preset(self) -> None:
        spec = parse_spec({"source": "torus-knot"})
        self.assertEqual((spec.width, spec.height), (1920, 1200))
        self.assertEqual((spec.columns, spec.rows), (192, 60))
        self.assertTrue(spec.is_loop)
        self.assertEqual(spec.effective_fps(), 36)
        self.assertEqual(spec.frame_count(), 432)
        self.assertEqual(spec.style.charset, "symbols")
        self.assertTrue(spec.edges_enabled())
        self.assertEqual(spec.source.params["p"], 2)
        self.assertEqual(spec.outputs, ("wallpaper",))

    def test_preset_params_are_validated(self) -> None:
        spec = parse_spec({"source": {"preset": "tunnel", "params": {"shape": "hex"}}})
        self.assertEqual(spec.source.params["shape"], "hex")
        with self.assertRaisesRegex(SpecError, "must be one of"):
            parse_spec({"source": {"preset": "tunnel", "params": {"shape": "star"}}})
        with self.assertRaisesRegex(SpecError, "unknown parameter"):
            parse_spec({"source": {"preset": "tunnel", "params": {"speed": 3}}})
        with self.assertRaisesRegex(SpecError, "between"):
            parse_spec({"source": {"preset": "tunnel", "params": {"segments": 500}}})

    def test_preset_style_defaults_yield_to_user_style(self) -> None:
        self.assertEqual(parse_spec({"source": "galaxy"}).style.edges, "off")
        spec = parse_spec({"source": "galaxy", "style": {"edges": "on"}})
        self.assertEqual(spec.style.edges, "on")

    def test_logo_image_parameter(self) -> None:
        with self.assertRaisesRegex(SpecError, "needs params.image"):
            parse_spec({"source": "logo"})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "mark.png").write_bytes(b"")
            spec = parse_spec({"source": {"preset": "logo", "params": {"image": "mark.png"}}}, base)
            self.assertEqual(spec.source.params["image"], str((base / "mark.png").resolve()))
            self.assertEqual(spec.source.params["motion"], "sway")
            with self.assertRaisesRegex(SpecError, "file not found"):
                parse_spec({"source": {"preset": "logo", "params": {"image": "nope.png"}}}, base)
            raw = absolutize({"source": {"preset": "logo", "params": {"image": "mark.png"}}}, base)
            self.assertTrue(Path(raw["source"]["params"]["image"]).is_absolute())

    def test_rejects_invalid_values(self) -> None:
        cases = [
            ({"source": "nope"}, "unknown preset"),
            ({"source": "tunnel", "size": "big"}, "size must look like"),
            ({"source": "tunnel", "cell": "9x20"}, "even"),
            ({"source": "tunnel", "outputs": ["gif"]}, "unknown output"),
            ({"source": "tunnel", "colour": 1}, "unknown spec field"),
            ({"source": "tunnel", "style": {"background": "red"}}, "background"),
            ({"source": "tunnel", "style": {"charset": "emoji"}}, "charset"),
            ({"source": "tunnel", "frame_range": [1, 10]}, "blend sources only"),
            ({"source": {"video": "/does/not/exist.mp4"}}, "not found"),
            ({"source": {"preset": "tunnel", "blend": "x.blend"}}, "exactly one"),
        ]
        for data, message in cases:
            with self.subTest(data=data), self.assertRaisesRegex(SpecError, message):
                parse_spec(data)

    def test_custom_charset_and_backgrounds(self) -> None:
        spec = parse_spec(
            {"source": "tunnel", "style": {"charset": "custom:.oO@", "background": "tint:0.2"}}
        )
        self.assertEqual(spec.style.charset_name(), "custom")
        parse_spec({"source": "tunnel", "style": {"background": "transparent"}})
        parse_spec({"source": "tunnel", "style": {"background": "#102030"}})

    def test_files_and_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "clip.mp4").write_bytes(b"")
            spec_file = base / "job.toml"
            spec_file.write_text('seconds = 3\n[source]\nvideo = "clip.mp4"\n', encoding="utf-8")
            spec = parse_spec(load_spec_file(spec_file), base)
            self.assertEqual(spec.source.path, (base / "clip.mp4").resolve())
            self.assertFalse(spec.is_loop)
            self.assertFalse(spec.edges_enabled())
            raw = absolutize({"source": {"video": "clip.mp4"}, "output_dir": "out"}, base)
            self.assertTrue(Path(raw["source"]["video"]).is_absolute())
            self.assertEqual(raw["output_dir"], str((base / "out").resolve()))
            bad = base / "bad.json"
            bad.write_text(json.dumps([1, 2]), encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "must contain an object"):
                load_spec_file(bad)


if __name__ == "__main__":
    unittest.main()
