"""MCP server exercised through the SDK's in-memory client session."""

import json
import os
import tempfile
import unittest
from pathlib import Path

import anyio
import numpy as np
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ImageContent, TextContent
from PIL import Image

from ascii_designer.mcp_server import build_server
from tests.helpers import font_path, require_tool


class McpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._env = dict(os.environ)
        os.environ["ASCII_DESIGNER_CACHE"] = str(self.dir / "cache")
        os.environ["ASCII_DESIGNER_OUTPUT_DIR"] = str(self.dir / "out")

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def _run(self, body):
        async def main():
            async with create_connected_server_and_client_session(build_server()) as client:
                return await body(client)

        return anyio.run(main)

    def test_tools_are_listed(self) -> None:
        async def body(client):
            return {t.name for t in (await client.list_tools()).tools}

        self.assertEqual(
            self._run(body),
            {
                "ascii_status",
                "ascii_list_presets",
                "ascii_preview",
                "ascii_render",
                "ascii_job",
                "ascii_preset_to_blend",
            },
        )

    def test_list_presets(self) -> None:
        async def body(client):
            return await client.call_tool("ascii_list_presets", {})

        result = self._run(body)
        self.assertFalse(result.isError)
        data = result.structuredContent
        assert data is not None
        names = {p["name"] for p in data["presets"]}
        self.assertTrue({"torus-knot", "tunnel", "planet", "terrain"} <= names)

    def test_invalid_spec_is_a_tool_error(self) -> None:
        async def body(client):
            return await client.call_tool("ascii_render", {"spec": {"source": "no-such"}})

        result = self._run(body)
        self.assertTrue(result.isError)
        text = result.content[0]
        assert isinstance(text, TextContent)
        self.assertIn("unknown preset", text.text)

    def test_preview_returns_images(self) -> None:
        font_path()
        require_tool("ffmpeg")
        image = self.dir / "dot.png"
        rgb = np.zeros((200, 320, 3), dtype=np.uint8)
        rgb[60:140, 100:220] = (40, 200, 255)
        Image.fromarray(rgb).save(image)

        async def body(client):
            spec = {"source": {"image": str(image)}, "size": "320x200"}
            return await client.call_tool("ascii_preview", {"spec": spec})

        result = self._run(body)
        self.assertFalse(result.isError, result.content)
        kinds = [type(c) for c in result.content]
        self.assertEqual(kinds[:2], [ImageContent, ImageContent])
        text = result.content[2]
        assert isinstance(text, TextContent)
        self.assertEqual(json.loads(text.text)["grid"], {"columns": 32, "rows": 10})


if __name__ == "__main__":
    unittest.main()
