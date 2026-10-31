from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from infrastructure.http_client import get_http_client
from infrastructure.logging import model_logger
from infrastructure.parsers.hf_parser import infer_base_model, infer_model_type

logger = model_logger()

# HuggingFace tags that describe the repo format rather than what the model is.
# Kept out of the user-visible tag list for the same reason the parser drops
# them, but the raw list is still what infers the type: an HF LoRA is tagged
# ["diffusers","safetensors","lora",...], and stripping "lora" before inferring
# would file every LoRA as a checkpoint.
HF_TECHNICAL_TAGS = frozenset({"diffusers", "safetensors", "pytorch"})


def _hf_tags(hf_data: dict[str, Any]) -> list[str]:
    """Normalised, de-duplicated HuggingFace tag list from a payload."""
    raw = hf_data.get("tags") or []
    if not isinstance(raw, (list, tuple)):
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for tag in raw:
        if not isinstance(tag, str):
            continue
        cleaned = tag.strip()
        if not cleaned or cleaned.lower() in HF_TECHNICAL_TAGS or cleaned in seen:
            continue
        seen.add(cleaned)
        tags.append(cleaned)
    return tags


def _hf_pipeline_tag(hf_data: dict[str, Any]) -> str | None:
    pipeline_tag = hf_data.get("pipeline_tag")
    return pipeline_tag if isinstance(pipeline_tag, str) else None


def _hf_base_model(hf_data: dict[str, Any]) -> str | None:
    """The base model HuggingFace declares structurally.

    This is the only authoritative signal, and it was being thrown away:
    inference ran on free-form tags plus the model card's prose, so a repo with
    no family tag was filed as SD 1.5. Measured on this library's payloads, the
    tag array is empty on most entries that declare a base model at all.

    HuggingFace returns it in either place depending on the repo — `config` for
    diffusers layouts, `cardData` for metadata in the card — so both are read.
    """
    for container in (hf_data.get("config"), hf_data.get("cardData"), hf_data):
        if isinstance(container, dict):
            for key in ("base_model", "baseModel"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


@dataclass
class ExternalModelServiceError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


class ExternalModelService:
    """Service for external model parsing and search APIs."""

    @staticmethod
    def _civitai_headers() -> dict[str, str]:
        headers = {"User-Agent": "TNHFantasy/1.0"}
        token = os.getenv("CIVITAI_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _hf_headers() -> dict[str, str]:
        token = os.getenv("HF_TOKEN", "").strip()
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    async def parse_model_url(self, raw_url: str) -> dict[str, Any]:
        url = (raw_url or "").strip()
        if not url:
            raise ExternalModelServiceError(status_code=400, detail="URL is required")

        if "civitai.com" in url or "civitai.red" in url:
            prefer_red = "civitai.red" in url
            return await self._parse_civitai_url(url, prefer_red=prefer_red)

        if "huggingface.co" in url:
            return await self._parse_huggingface_url(url)

        raise ExternalModelServiceError(
            status_code=400,
            detail="URL must be from CivitAI (civitai.com / civitai.red) or HuggingFace (huggingface.co)",
        )

    async def search_civitai(
        self,
        query: str = "",
        limit: int = 20,
        types: str = None,
        sort: str = None,
        baseModels: str = None,
        nsfw: bool = None,
        period: str = None,
        page: int = None,
        cursor: str = None,
        username: str = None,
        tag: str = None,
    ) -> dict[str, Any]:
        params = {"limit": limit}
        if query:
            params["query"] = query
        
        # CivitAI returns 400 if 'page' is used with 'query'
        if cursor:
            params["cursor"] = str(cursor)
        elif page:
            if not query:
                params["page"] = page
        if username:
            params["username"] = username
        if tag:
            params["tag"] = tag
        if types:
            # Map standard model types to CivitAI expected casing/values
            type_mapping = {
                "lora": "LORA",
                "lycoris": "LORA",  # CivitAI often groups these
                "checkpoint": "Checkpoint",
                "textual inversion": "TextualInversion",
                "textualinversion": "TextualInversion",
                "embedding": "TextualInversion",
                "controlnet": "Controlnet",
                "aesthetic gradient": "AestheticGradient",
                "poses": "Poses",
                "hypernetwork": "Hypernetwork",
            }
            # Allow multiple comma-separated types
            mapped_types = []
            for t in types.split(","):
                clean_t = t.strip()
                if clean_t:
                    mapped_types.append(type_mapping.get(clean_t.lower(), clean_t))
            params["types"] = mapped_types

        if sort:
            params["sort"] = sort
            
        if baseModels:
            bm_mapping = {
                "sdxl": "SDXL 1.0",
                "sdxl 1.0": "SDXL 1.0",
                "sd 1.5": "SD 1.5",
                "sd1.5": "SD 1.5",
                "pony": "Pony",
                "illustrious": "Illustrious",
                "sd 3.5": "SD 3.5",
                "flux.1 d": "Flux.1 D",
                "flux.1 s": "Flux.1 S",
            }
            mapped_bms = []
            for bm in baseModels.split(","):
                clean_bm = bm.strip()
                if clean_bm:
                    mapped_bms.append(bm_mapping.get(clean_bm.lower(), clean_bm))
            params["baseModels"] = mapped_bms
        if nsfw is not None:
            params["nsfw"] = str(nsfw).lower()
        if period:
            params["period"] = period

        qs = urllib.parse.urlencode(params, doseq=True)
        url = f"https://civitai.com/api/v1/models?{qs}"

        try:
            response = await get_http_client().get(url, headers=self._civitai_headers(), timeout=10)
            if response.status_code == 200:
                return response.json()

            raise ExternalModelServiceError(
                status_code=response.status_code,
                detail="CivitAI search failed",
            )
        except ExternalModelServiceError:
            raise
        except Exception as exc:
            raise ExternalModelServiceError(status_code=500, detail=str(exc)) from exc

    async def get_civitai_model_version_by_hash(self, file_hash: str) -> Optional[dict[str, Any]]:
        """Fetch a specific model version from CivitAI by its SHA256 file hash."""
        url = f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}"
        try:
            response = await get_http_client().get(url, headers=self._civitai_headers(), timeout=10)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return None  # Hash not found
            raise ExternalModelServiceError(
                status_code=response.status_code,
                detail=f"CivitAI hash lookup failed: {response.text}",
            )
        except ExternalModelServiceError:
            raise
        except Exception as exc:
            raise ExternalModelServiceError(status_code=500, detail=str(exc)) from exc

    async def get_civitai_enums(self) -> dict[str, Any]:
        """Fetch current valid enum values (ModelType, BaseModel, etc.) from CivitAI API."""
        url = "https://civitai.com/api/v1/enums"
        try:
            response = await get_http_client().get(url, headers=self._civitai_headers(), timeout=5)
            if response.status_code == 200:
                return response.json()
            raise ExternalModelServiceError(
                status_code=response.status_code,
                detail="Failed to fetch CivitAI enums",
            )
        except Exception as e:
            if isinstance(e, ExternalModelServiceError):
                raise
            raise ExternalModelServiceError(500, str(e))

    async def search_huggingface(self, query: str, limit: int = 20) -> dict[str, Any]:
        encoded_query = urllib.parse.quote(query, safe="")
        url = f"https://huggingface.co/api/models?search={encoded_query}&limit={limit}&filter=diffusers"

        try:
            response = await get_http_client().get(url, headers=self._hf_headers(), timeout=10)
            if response.status_code != 200:
                raise ExternalModelServiceError(
                    status_code=response.status_code,
                    detail="HuggingFace search failed",
                )

            hf_models = response.json() or []
            items = [self._normalize_huggingface_model(model) for model in hf_models[:limit]]
            return {"items": items}
        except ExternalModelServiceError:
            raise
        except Exception as exc:
            raise ExternalModelServiceError(status_code=500, detail=str(exc)) from exc

    async def get_civitai_tags(self, limit: int = 20) -> dict[str, Any]:
        """Fetch popular tags from CivitAI."""
        url = f"https://civitai.com/api/v1/tags?limit={limit}"
        client = get_http_client()
        try:
            response = await client.get(url, headers=self._civitai_headers(), timeout=10.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.error(f"Error fetching CivitAI tags: {exc}")
            raise ExternalModelServiceError(status_code=502, detail="Failed to fetch tags from CivitAI")

    async def _parse_civitai_url(self, url: str, prefer_red: bool = False) -> dict[str, Any]:
        match = re.search(r"models/(\d+)", url)
        if not match:
            raise ExternalModelServiceError(
                status_code=400,
                detail="Could not parse CivitAI model ID from URL",
            )

        model_id = match.group(1)

        try:
            return await self.get_civitai_model(int(model_id), prefer_red=prefer_red)
        except ExternalModelServiceError:
            raise
        except Exception as exc:
            raise ExternalModelServiceError(
                status_code=500,
                detail=f"Failed to fetch from CivitAI: {exc!s}",
            ) from exc

    async def get_civitai_model(self, model_id: int, prefer_red: bool = False) -> dict[str, Any]:
        domains = ["civitai.red", "civitai.com"] if prefer_red else ["civitai.com", "civitai.red"]
        last_error = None
        for domain in domains:
            try:
                response = await get_http_client().get(
                    f"https://{domain}/api/v1/models/{model_id}",
                    headers=self._civitai_headers(),
                    timeout=15,
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 404:
                    last_error = httpx.HTTPStatusError("Not Found", request=getattr(response, "request", None), response=response)
                    continue
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404:
                    continue
                raise ExternalModelServiceError(
                    status_code=exc.response.status_code,
                    detail=f"Failed to fetch from CivitAI: {exc!s}",
                ) from exc
            except Exception as exc:
                last_error = exc
                continue

        if isinstance(last_error, httpx.HTTPStatusError):
            raise ExternalModelServiceError(
                status_code=last_error.response.status_code,
                detail=f"Failed to fetch from CivitAI: {last_error!s}",
            ) from last_error
        raise ExternalModelServiceError(
            status_code=500,
            detail=f"Failed to fetch from CivitAI: {last_error!s}",
        )

    async def get_civitai_model_version(self, version_id: int, prefer_red: bool = False) -> dict[str, Any]:
        domains = ["civitai.red", "civitai.com"] if prefer_red else ["civitai.com", "civitai.red"]
        last_error = None
        for domain in domains:
            try:
                response = await get_http_client().get(
                    f"https://{domain}/api/v1/model-versions/{version_id}",
                    headers=self._civitai_headers(),
                    timeout=15,
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 404:
                    last_error = httpx.HTTPStatusError("Not Found", request=getattr(response, "request", None), response=response)
                    continue
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404:
                    continue
                raise ExternalModelServiceError(
                    status_code=exc.response.status_code,
                    detail=f"Failed to fetch version from CivitAI: {exc!s}",
                ) from exc
            except Exception as exc:
                last_error = exc
                continue

        if isinstance(last_error, httpx.HTTPStatusError):
            raise ExternalModelServiceError(
                status_code=last_error.response.status_code,
                detail=f"Failed to fetch version from CivitAI: {last_error!s}",
            ) from last_error
        raise ExternalModelServiceError(
            status_code=500,
            detail=f"Failed to fetch version from CivitAI: {last_error!s}",
        )
    async def _parse_huggingface_url(self, url: str) -> dict[str, Any]:
        match = re.search(r"huggingface\.co/([^/]+/[^/]+)", url)
        if not match:
            raise ExternalModelServiceError(
                status_code=400,
                detail="Could not parse HuggingFace model path from URL",
            )

        model_path = match.group(1)

        try:
            response = await get_http_client().get(
                f"https://huggingface.co/api/models/{model_path}",
                headers=self._hf_headers(),
                timeout=15,
            )
            response.raise_for_status()
            hf_data = response.json()
            return self._normalize_huggingface_model_detail(model_path, hf_data)
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalModelServiceError(
                status_code=500,
                detail=f"Failed to fetch from HuggingFace: {exc!s}",
            ) from exc

    def _normalize_huggingface_model_detail(
        self,
        model_path: str,
        hf_data: dict[str, Any],
    ) -> dict[str, Any]:
        owner = model_path.split("/")[0]
        model_name = model_path.split("/")[-1]

        # HF tags are the only description of what a repo actually is: an HF
        # LoRA, ControlNet or pose bundle carries no other field that says so.
        # They were being dropped here, and `type` was hardcoded to
        # "Checkpoint", so every HF LoRA was filed as a checkpoint and could
        # not be found by type or by tag at all.
        tags = _hf_tags(hf_data)
        model_type = infer_model_type(tags, _hf_pipeline_tag(hf_data))
        base_model = infer_base_model(
            tags, hf_data.get("cardData", {}).get("content") or "", _hf_base_model(hf_data)
        )

        return {
            "id": hf_data.get("id", model_path),
            "name": model_name,
            "type": model_type,
            "nsfw": False,
            "description": hf_data.get("description", ""),
            "tags": tags,
            "creator": {"username": hf_data.get("author", owner)},
            "stats": {
                "downloadCount": hf_data.get("downloads", 0),
                "thumbsUpCount": hf_data.get("likes", 0),
            },
            "modelVersions": [
                {
                    "id": hf_data.get("sha", "main"),
                    "name": "main",
                    "baseModel": base_model,
                    "downloadUrl": f"https://huggingface.co/{model_path}/resolve/main/model.safetensors",
                    "files": [
                        {
                            "name": "model.safetensors",
                            "sizeKB": 0,
                            "downloadUrl": f"https://huggingface.co/{model_path}/resolve/main/model.safetensors",
                            "primary": True,
                        }
                    ],
                    "images": [],
                }
            ],
            "source": "huggingface",
        }

    def _normalize_huggingface_model(self, model: dict[str, Any]) -> dict[str, Any]:
        model_id = model.get("id", "")
        tags = _hf_tags(model)
        return {
            "id": model_id,
            "name": model_id.split("/")[-1],
            "type": infer_model_type(tags, _hf_pipeline_tag(model)),
            "nsfw": False,
            "description": model.get("description", ""),
            "tags": tags,
            "creator": {"username": model.get("author", "")},
            "modelVersions": [
                {
                    "id": model.get("sha", ""),
                    "name": "main",
                    "baseModel": infer_base_model(tags, None, _hf_base_model(model)),
                    "downloadUrl": f"https://huggingface.co/{model_id}/resolve/main/model.safetensors",
                    "images": [],
                }
            ],
            "source": "huggingface",
        }
