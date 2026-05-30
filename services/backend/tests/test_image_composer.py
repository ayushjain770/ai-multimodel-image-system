"""Unit tests for image prompt composer temperature."""

from __future__ import annotations

import unittest

from app.clients.llm_client import MockLLMClient
from app.core.config import settings
from app.services.image_prompt import compose_image_prompt


class TempRecordingLLM(MockLLMClient):
    captured_temperature: float | None = None

    async def chat(
        self,
        message: str,
        history,
        citations=None,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        TempRecordingLLM.captured_temperature = temperature
        return await super().chat(message, history, citations, system_prompt, temperature)


class TestImageComposerTemperature(unittest.IsolatedAsyncioTestCase):
    async def test_compose_passes_image_composer_temperature(self) -> None:
        llm = TempRecordingLLM()
        await compose_image_prompt(llm, "Draw a peaceful nativity scene")
        self.assertEqual(
            TempRecordingLLM.captured_temperature,
            settings.image_composer_temperature,
        )
        self.assertAlmostEqual(TempRecordingLLM.captured_temperature, 0.3)

    async def test_compose_uses_composer_marker(self) -> None:
        llm = TempRecordingLLM()
        params = await compose_image_prompt(llm, "Draw Jesus at the tomb")
        self.assertIn("reverent", params.positive.lower())
        self.assertIn("christian", params.positive.lower())


if __name__ == "__main__":
    unittest.main()
