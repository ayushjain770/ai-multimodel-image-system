"""Swappable image-generation client.

`ImageBackend` selects the implementation at startup:
  - MockImageClient: returns a generated placeholder PNG, no GPU (Mac dev).
  - ComfyUIClient: drives the baseline SDXL/Juggernaut workflow on ComfyUI.

Both return a base64-encoded PNG string.
"""

import asyncio
import base64
import json
import struct
import zlib
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from app.core.config import ImageBackend, settings
from app.core.logging import get_logger
from app.services.image_prompt import ImageParams

logger = get_logger(__name__)

_WORKFLOW_PATH = Path(__file__).resolve().parents[2] / "workflows" / "baseline_sdxl.json"
# Node ids inside baseline_sdxl.json (ComfyUI API format).
_SAMPLER_NODE = "3"
_CHECKPOINT_NODE = "4"
_LATENT_NODE = "5"
_POSITIVE_PROMPT_NODE = "6"
_NEGATIVE_PROMPT_NODE = "7"


def _make_placeholder_png(width: int = 512, height: int = 512) -> bytes:
    """Build a small solid-colour PNG with no third-party deps (stdlib only)."""

    r, g, b = 79, 70, 229  # indigo, just so it's visibly "an image"
    row = b"\x00" + bytes([r, g, b]) * width
    raw = row * height
    compressed = zlib.compress(raw, level=6)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


class ImageClient(ABC):
    @abstractmethod
    async def generate(self, params: ImageParams) -> str:
        """Render the given parameters and return a base64-encoded PNG."""

    @abstractmethod
    async def health(self) -> tuple[bool, str]: ...

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None


class MockImageClient(ImageClient):
    async def generate(self, params: ImageParams) -> str:
        logger.info("[mock-image] placeholder for prompt: %s", params.positive[:80])
        return base64.b64encode(_make_placeholder_png()).decode("ascii")

    async def health(self) -> tuple[bool, str]:
        return True, "mock backend always ready"


class ComfyUIClient(ImageClient):
    """Queues the baseline workflow on ComfyUI and returns the rendered image."""

    def __init__(self) -> None:
        self._base_url = settings.comfyui_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=settings.image_timeout)
        self._workflow = json.loads(_WORKFLOW_PATH.read_text())

    async def generate(self, params: ImageParams) -> str:
        workflow = json.loads(json.dumps(self._workflow))  # deep copy
        workflow[_POSITIVE_PROMPT_NODE]["inputs"]["text"] = params.positive
        workflow[_NEGATIVE_PROMPT_NODE]["inputs"]["text"] = params.negative
        workflow[_CHECKPOINT_NODE]["inputs"]["ckpt_name"] = params.checkpoint
        workflow[_LATENT_NODE]["inputs"]["width"] = params.width
        workflow[_LATENT_NODE]["inputs"]["height"] = params.height
        sampler = workflow[_SAMPLER_NODE]["inputs"]
        sampler["seed"] = params.seed
        sampler["steps"] = params.steps
        sampler["cfg"] = params.cfg
        sampler["sampler_name"] = params.sampler
        sampler["scheduler"] = params.scheduler

        queued = await self._client.post(
            f"{self._base_url}/prompt", json={"prompt": workflow}
        )
        queued.raise_for_status()
        prompt_id = queued.json()["prompt_id"]

        image_meta = await self._poll_for_image(prompt_id)
        view = await self._client.get(f"{self._base_url}/view", params=image_meta)
        view.raise_for_status()
        return base64.b64encode(view.content).decode("ascii")

    async def _poll_for_image(self, prompt_id: str) -> dict:
        deadline = settings.image_timeout
        waited = 0.0
        while waited < deadline:
            hist = await self._client.get(f"{self._base_url}/history/{prompt_id}")
            hist.raise_for_status()
            data = hist.json()
            if prompt_id in data:
                for node_output in data[prompt_id].get("outputs", {}).values():
                    images = node_output.get("images")
                    if images:
                        img = images[0]
                        return {
                            "filename": img["filename"],
                            "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output"),
                        }
            await asyncio.sleep(1.0)
            waited += 1.0
        raise TimeoutError(f"ComfyUI did not return an image for {prompt_id}")

    async def health(self) -> tuple[bool, str]:
        try:
            resp = await self._client.get(
                f"{self._base_url}/system_stats", timeout=5.0
            )
            ok = resp.status_code == 200
            return ok, f"comfyui /system_stats -> {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, f"comfyui unreachable: {exc}"

    async def aclose(self) -> None:
        await self._client.aclose()


def build_image_client() -> ImageClient:
    if settings.image_backend is ImageBackend.COMFY:
        logger.info("Using ComfyUIClient (%s)", settings.comfyui_base_url)
        return ComfyUIClient()
    logger.info("Using MockImageClient")
    return MockImageClient()
