"""Service pipeline with 2D sources and real ffmpeg encoders (no Blender needed)."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from ascii_designer.errors import SpecError
from ascii_designer.output.ffmpeg import VideoEncoder
from ascii_designer.service import Designer
from ascii_designer.spec import parse_spec
from tests.helpers import font_path, require_tool


def probe(path: Path) -> dict:
    ffprobe = require_tool("ffprobe")
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,nb_read_frames,profile",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)["streams"][0]


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        font_path()
        require_tool("ffmpeg")
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._env = dict(os.environ)
        os.environ["ASCII_DESIGNER_CACHE"] = str(self.dir / "cache")

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _gradient_image(self) -> Path:
        y, x = np.mgrid[0:240, 0:400]
        rgb = np.stack([x / 400, y / 240, 1 - x / 400], axis=-1)
        rgb[(x - 200) ** 2 + (y - 120) ** 2 < 60**2] = (1, 0.9, 0.2)
        path = self.dir / "gradient.png"
        Image.fromarray((rgb * 255).astype(np.uint8)).save(path)
        return path

    def test_wallpaper_encoder_is_hevc_main10(self) -> None:
        path = self.dir / "clip.mp4"
        encoder = VideoEncoder(path, "wallpaper", 64, 40, 36.0, 6)
        for i in range(6):
            encoder.write(np.full((40, 64, 3), i * 40, dtype=np.uint8))
        encoder.close()
        info = probe(path)
        self.assertEqual(info["codec_name"], "hevc")
        self.assertEqual(info["pix_fmt"], "yuv420p10le")
        self.assertEqual((info["width"], info["height"], int(info["nb_read_frames"])), (64, 40, 6))

    def test_image_source_preview_and_render(self) -> None:
        image = self._gradient_image()
        spec = parse_spec(
            {
                "source": {"image": str(image)},
                "size": "400x240",
                "outputs": ["png", "ansi", "asciimotion"],
                "output_dir": str(self.dir / "out"),
                "name": "grad",
            }
        )
        designer = Designer()
        preview = designer.preview(spec, out_dir=self.dir / "prev")
        self.assertEqual(preview["grid"], {"columns": 40, "rows": 12})
        self.assertTrue(Path(preview["crop"]).is_file())
        self.assertGreater(preview["filled_cells"], 0.3)
        result = designer.render(spec)
        self.assertEqual(set(result["outputs"]), {"png", "ansi", "asciimotion"})
        with Image.open(result["outputs"]["png"]) as png:
            self.assertEqual(png.size, (400, 240))
        session = json.loads(Path(result["outputs"]["asciimotion"]).read_text(encoding="utf-8"))
        self.assertEqual(session["canvas"]["width"], 40)
        self.assertIsNone(result["seam"])

    def test_image_source_rejects_video_outputs(self) -> None:
        spec = parse_spec({"source": {"image": str(self._gradient_image())}, "size": "400x240"})
        with self.assertRaisesRegex(SpecError, "stills"):
            Designer().render(spec)

    def test_video_source_roundtrip(self) -> None:
        clip = self.dir / "in.mp4"
        encoder = VideoEncoder(clip, "h264", 320, 200, 12.0, 12)
        for i in range(12):
            frame = np.zeros((200, 320, 3), dtype=np.uint8)
            frame[:, i * 20 : i * 20 + 60] = (255, 120, 20)
            encoder.write(frame)
        encoder.close()
        spec = parse_spec(
            {
                "source": {"video": str(clip)},
                "size": "320x200",
                "seconds": 1.0,
                "outputs": ["wallpaper"],
                "output_dir": str(self.dir / "out"),
            }
        )
        result = Designer().render(spec)
        self.assertEqual(result["frames"], 12)
        info = probe(Path(result["outputs"]["wallpaper"]))
        self.assertEqual(int(info["nb_read_frames"]), 12)


if __name__ == "__main__":
    unittest.main()
