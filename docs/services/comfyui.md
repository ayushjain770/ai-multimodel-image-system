# ComfyUI + Juggernaut (image generation)

**Port:** 8188  
**Path:** `services/comfyui/`  
**Profile:** `gpu` (prod only)  
**Role:** Renders Christian-themed SDXL images from composed prompts.

## Why this service exists

Image generation requires a dedicated GPU workflow engine. ComfyUI provides
node-based SDXL rendering; Juggernaut XL is the checkpoint chosen for high-quality,
photorealistic Christian art. The backend sends a JSON workflow with the composed
prompt and receives a PNG.

In dev, `IMAGE_BACKEND=mock` returns a placeholder PNG so the image pipeline
(safety guard, prompt compose, URL persistence) is testable without a GPU.

## Architecture

```
Backend (compose_image_prompt)
    │
    ▼
image_prompt.py  →  safety check  →  style template  →  ImageParams
    │
    ▼
comfy_client.py  →  POST workflow JSON  →  ComfyUI :8188
    │
    ▼
PNG bytes  →  chat_store.save_image()  →  /media/{id}.png
```

## Workflow

The baseline SDXL workflow lives at
`services/backend/workflows/baseline_sdxl.json` (mirrored in `services/comfyui/workflows/`).
It is parameterised entirely via environment variables — no hardcoded prompts.

| Parameter | Env var | Default |
| --------- | ------- | ------- |
| Checkpoint | `IMAGE_CHECKPOINT` | `juggernautXL.safetensors` |
| Steps | `IMAGE_STEPS` | 30 |
| CFG scale | `IMAGE_CFG` | 6.5 |
| Width / Height | `IMAGE_WIDTH` / `IMAGE_HEIGHT` | 1024 |
| Sampler | `IMAGE_SAMPLER` | `dpmpp_2m` |
| Scheduler | `IMAGE_SCHEDULER` | `karras` |
| Style template | `IMAGE_STYLE_TEMPLATE` | reverent Christian fine-art… |
| Negative prompt | `IMAGE_NEGATIVE_PROMPT` | lowres, nsfw, gore, … |

## Safety

Before any render:

1. **Rule-based guard** (`check_safety`) — blocks explicit, violent, hateful, mocking prompts.
2. **LLM compose** — the prompt-composer rewrites the request into a dignified scene.
3. **Shared moderation patterns** — same regex/rules as text moderation.

Refused requests return `{ refused: true, reason: "..." }` without calling ComfyUI.

## Model download

Juggernaut is not committed to git. The orchestrator downloads it during `make prod`:

- Source: HuggingFace `RunDiffusion/Juggernaut-XL-v9` (configurable)
- Destination: `models/checkpoints/juggernautXL.safetensors`
- Mounted into ComfyUI at `/opt/ComfyUI/models`

See `infrastructure/lib/models.sh`.

## Key configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `IMAGE_BACKEND` | `mock` | Set to `comfy` in prod |
| `COMFYUI_BASE_URL` | `http://comfyui:8188` | Internal API URL |
| `COMFYUI_PORT` | `8188` | Host port |
| `IMAGE_SAFETY_ENABLED` | `true` | Refuse unsafe prompts |
| `IMAGE_TIMEOUT` | `300` | Render timeout (seconds) |
| `MODELS_DIR` | `./models` | Host checkpoint directory |

## Dev vs prod

| Mode | IMAGE_BACKEND | ComfyUI container | Output |
| ---- | ------------- | ----------------- | ------ |
| Dev | `mock` | Not started | Placeholder PNG |
| Prod | `comfy` | Started (gpu profile) | Real Juggernaut render |

## Related docs

- [Backend](backend.md) — `comfy_client.py`, `image_prompt.py`
- [Infrastructure](../infrastructure.md) — Juggernaut download
