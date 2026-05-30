"""Unit tests for build_image_reply."""

from __future__ import annotations

import unittest

from app.services.prompt_builder import build_image_reply


class TestBuildImageReply(unittest.TestCase):
    def test_includes_scene(self) -> None:
        reply = build_image_reply("Jesus holding a white lily in gentle light")
        self.assertIn("Jesus holding a white lily", reply)
        self.assertIn("Please wait", reply)
        self.assertNotIn("I can't", reply)

    def test_truncates_long_scene(self) -> None:
        long_scene = "a " + "very " * 80 + "long scene"
        reply = build_image_reply(long_scene)
        self.assertLess(len(reply), len(long_scene) + 120)


if __name__ == "__main__":
    unittest.main()
