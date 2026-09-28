import ast
import unittest
from pathlib import Path

from ascii_designer.blender.runner import SCRIPTS
from ascii_designer.presets import PALETTES, PRESETS


class PresetCatalogTests(unittest.TestCase):
    def test_every_preset_has_a_builder(self) -> None:
        for preset in PRESETS.values():
            with self.subTest(preset=preset.name):
                path = SCRIPTS / "presets" / f"{preset.module}.py"
                self.assertTrue(path.is_file(), path)
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
                self.assertIn("build", names)

    def test_defaults_are_within_ranges(self) -> None:
        for preset in PRESETS.values():
            for param in preset.params:
                with self.subTest(preset=preset.name, param=param.name):
                    if param.kind == "choice":
                        self.assertIn(param.default, param.choices)
                    elif param.kind in ("int", "float"):
                        assert param.low is not None and param.high is not None
                        self.assertTrue(param.low <= param.default <= param.high)
            self.assertIn("palette", {p.name for p in preset.params})

    def test_palettes_are_hex(self) -> None:
        for name, colors in PALETTES.items():
            with self.subTest(palette=name):
                self.assertEqual(len(colors), 4)
                for value in colors:
                    self.assertRegex(value, r"^#[0-9a-f]{6}$")

    def test_scripts_stay_python_313_compatible(self) -> None:
        for path in Path(SCRIPTS).rglob("*.py"):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 13))


if __name__ == "__main__":
    unittest.main()
