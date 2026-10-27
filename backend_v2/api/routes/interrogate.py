"""Image interrogation and reverse prompt extraction endpoint.

Extracts prompt metadata, Danbooru tags, and descriptions from images.
Prioritizes embedded PNG chunk metadata (ComfyUI / A1111 / Civitai), falling
back to heuristics or vision model interrogation when available.
"""

import base64
import io
import json
import os
import re
from typing import Any, Literal

from fastapi import APIRouter, File, Form, UploadFile
from PIL import Image
from pydantic import BaseModel

from core.exceptions import ValidationError
from infrastructure.logging import api_logger

logger = api_logger()

router = APIRouter(prefix="/api/generate", tags=["generation"])


class InterrogateRequest(BaseModel):
    image_path: str | None = None
    image_data: str | None = None
    mode: Literal["danbooru", "natural", "both"] = "both"


class InterrogateResponse(BaseModel):
    prompt: str
    negative_prompt: str = ""
    tags: list[str] = []
    source: str = "metadata"
    metadata: dict[str, Any] = {}


def _extract_embedded_png_info(img: Image.Image) -> dict[str, Any]:
    """Extract embedded prompt, workflow, and generation parameters from PNG info chunks."""
    result = {
        "prompt": "",
        "negative_prompt": "",
        "tags": [],
        "metadata": {},
    }

    info = getattr(img, "info", {}) or {}

    # 1. Automatic1111 / WebUI 'parameters' chunk
    if "parameters" in info and isinstance(info["parameters"], str):
        raw = info["parameters"]
        parts = raw.split("Negative prompt:")
        prompt = parts[0].strip()
        negative_prompt = ""

        if len(parts) > 1:
            rest = parts[1]
            steps_split = re.split(r"\n\s*(?:Steps:|CFG scale:)", rest, maxsplit=1)
            negative_prompt = steps_split[0].strip()

        result["prompt"] = prompt
        result["negative_prompt"] = negative_prompt
        result["metadata"]["format"] = "automatic1111"

    # 2. ComfyUI 'prompt' or 'workflow' chunk
    elif "prompt" in info:
        try:
            prompt_data = json.loads(info["prompt"]) if isinstance(info["prompt"], str) else info["prompt"]
            if isinstance(prompt_data, dict):
                # Look for CLIPTextEncode nodes
                pos_texts = []
                neg_texts = []
                for _, node in prompt_data.items():
                    class_type = node.get("class_type", "")
                    inputs = node.get("inputs", {})
                    text = inputs.get("text", "")
                    if class_type in ("CLIPTextEncode", "CLIPTextEncodeSDXL", "BNK_CLIPTextEncodeAdvanced") and text:
                        text_str = str(text).strip()
                        # Simple heuristic for negative prompt
                        if any(k in text_str.lower() for k in ("worst quality", "low quality", "bad anatomy", "blurry")):
                            neg_texts.append(text_str)
                        else:
                            pos_texts.append(text_str)

                result["prompt"] = ", ".join(pos_texts)
                result["negative_prompt"] = ", ".join(neg_texts)
                result["metadata"]["format"] = "comfyui"
        except (json.JSONDecodeError, TypeError):
            pass

    # Extract tags from positive prompt
    if result["prompt"]:
        tag_candidates = [
            t.strip()
            for t in result["prompt"].split(",")
            if t.strip() and not t.strip().startswith("(") and not t.strip().startswith("embedding:")
        ]
        result["tags"] = tag_candidates

    return result


@router.post("/interrogate", response_model=InterrogateResponse)
async def interrogate_image(
    request: InterrogateRequest | None = None,
    file: UploadFile | None = File(None),
    image_path: str | None = Form(None),
):
    """Interrogate an image to extract its prompt, negative prompt, and tags."""
    img_bytes = None

    if file is not None:
        img_bytes = await file.read()
    elif request and request.image_data:
        data_str = request.image_data
        if "," in data_str:
            data_str = data_str.split(",", 1)[1]
        try:
            img_bytes = base64.b64decode(data_str)
        except Exception as exc:
            raise ValidationError(f"Invalid base64 image data: {exc}")
    elif (request and request.image_path) or image_path:
        path = (request.image_path if request else None) or image_path
        if not os.path.exists(path):
            raise ValidationError(f"Image file not found: {path}")
        with open(path, "rb") as f:
            img_bytes = f.read()

    if not img_bytes:
        raise ValidationError("No image provided. Provide a file upload, image_path, or image_data.")

    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
    except Exception as exc:
        raise ValidationError(f"Could not parse image: {exc}")

    # Extract embedded metadata
    info_extracted = _extract_embedded_png_info(pil_img)

    if info_extracted["prompt"]:
        return InterrogateResponse(
            prompt=info_extracted["prompt"],
            negative_prompt=info_extracted["negative_prompt"],
            tags=info_extracted["tags"],
            source="embedded_metadata",
            metadata=info_extracted["metadata"],
        )

    # Fallback heuristic when no embedded metadata is present
    width, height = pil_img.size
    aspect = "landscape" if width > height else ("portrait" if height > width else "square")
    fallback_prompt = f"high quality illustration, {aspect} composition, {pil_img.format.lower() if pil_img.format else 'image'}"

    return InterrogateResponse(
        prompt=fallback_prompt,
        negative_prompt="low quality, blurry",
        tags=["high quality", "illustration", aspect],
        source="heuristics",
        metadata={"width": width, "height": height, "format": pil_img.format},
    )
