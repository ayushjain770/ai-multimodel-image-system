"""Image generation endpoint.

Theme in -> safety guard -> style-wrapped SDXL prompt -> ComfyUI/Juggernaut (or
the mock backend in dev) -> base64 PNG out. Used by the UI, the MCP
`generate_image` tool, and for debugging.
"""

from fastapi import APIRouter, Request

from app.core.config import settings
from app.schemas import ImageRequest, ImageResponse
from app.services.image_prompt import build_prompt, check_safety

router = APIRouter(prefix="/api/v1", tags=["image"])


@router.post("/image", response_model=ImageResponse)
async def generate_image(request: Request, payload: ImageRequest) -> ImageResponse:
    backend = settings.image_backend.value

    safety = check_safety(payload.prompt)
    if not safety.ok:
        return ImageResponse(refused=True, reason=safety.reason, backend=backend)

    params = build_prompt(payload.prompt, negative_override=payload.negative)
    image_b64 = await request.app.state.image_client.generate(params)
    return ImageResponse(
        image_base64=image_b64,
        prompt_used=params.positive,
        negative_used=params.negative,
        backend=backend,
    )
