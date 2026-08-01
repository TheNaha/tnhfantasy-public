from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from infrastructure.http_client import get_http_client
from infrastructure.logging import model_logger

logger = model_logger()


@dataclass
class ExternalModelServiceError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


class ExternalModelService:
    """Service for external model parsing and search APIs."""

    async def parse_model_url(self, raw_url: str) -> dict[str, Any]:
        url = (raw_url or "").strip()
        if not url:
            raise ExternalModelServiceError(status_code=400, detail="URL is required")

        if "civitai.com" in url:
            return await self._parse_civitai_url(url)

        if "huggingface.co" in url:
            return await self._parse_huggingface_url(url)

        raise ExternalModelServiceError(
            status_code=400,
            detail="URL must be from CivitAI (civitai.com) or HuggingFace (huggingface.co)",
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
            response = await get_http_client().get(url, timeout=10)
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
            response = await get_http_client().get(url, timeout=10)
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
            response = await get_http_client().get(url, timeout=5)
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
            response = await get_http_client().get(url, timeout=10)
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
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.error(f"Error fetching CivitAI tags: {exc}")
            raise ExternalModelServiceError(status_code=502, detail="Failed to fetch tags from CivitAI")

    async def _parse_civitai_url(self, url: str) -> dict[str, Any]:
        match = re.search(r"models/(\d+)", url)
        if not match:
            raise ExternalModelServiceError(
                status_code=400,
                detail="Could not parse CivitAI model ID from URL",
            )

        model_id = match.group(1)

        try:
            return await self.get_civitai_model(int(model_id))
        except ExternalModelServiceError:
            raise
        except Exception as exc:
            raise ExternalModelServiceError(
                status_code=500,
                detail=f"Failed to fetch from CivitAI: {exc!s}",
            ) from exc

    async def get_civitai_model(self, model_id: int) -> dict[str, Any]:
        try:
            response = await get_http_client().get(
                f"https://civitai.com/api/v1/models/{model_id}",
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ExternalModelServiceError(
                status_code=exc.response.status_code,
                detail=f"Failed to fetch from CivitAI: {exc!s}",
            ) from exc
        except Exception as exc:
            raise ExternalModelServiceError(
                status_code=500,
                detail=f"Failed to fetch from CivitAI: {exc!s}",
            ) from exc
    async def get_civitai_model_version(self, version_id: int) -> dict[str, Any]:
        try:
            response = await get_http_client().get(
                f"https://civitai.com/api/v1/model-versions/{version_id}",
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ExternalModelServiceError(
                status_code=exc.response.status_code,
                detail=f"Failed to fetch version from CivitAI: {exc!s}",
            ) from exc
        except Exception as exc:
            raise ExternalModelServiceError(
                status_code=500,
                detail=f"Failed to fetch version from CivitAI: {exc!s}",
            ) from exc
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

        return {
            "id": hf_data.get("id", model_path),
            "name": model_name,
            "type": "Checkpoint",
            "nsfw": False,
            "description": hf_data.get("description", ""),
            "creator": {"username": hf_data.get("author", owner)},
            "stats": {
                "downloadCount": hf_data.get("downloads", 0),
                "thumbsUpCount": hf_data.get("likes", 0),
            },
            "modelVersions": [
                {
                    "id": hf_data.get("sha", "main"),
                    "name": "main",
                    "baseModel": "Unknown",
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
        return {
            "id": model_id,
            "name": model_id.split("/")[-1],
            "type": "Checkpoint",
            "nsfw": False,
            "creator": {"username": model.get("author", "")},
            "modelVersions": [
                {
                    "id": model.get("sha", ""),
                    "name": "main",
                    "downloadUrl": f"https://huggingface.co/{model_id}/resolve/main/model.safetensors",
                    "images": [],
                }
            ],
            "source": "huggingface",
        }
