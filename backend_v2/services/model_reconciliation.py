from typing import Dict, Any, List, Optional
import re

from sqlmodel import Session

from core.entities import ModelV2, ModelVersion, ModelFile
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

_DIRECTORY_TO_MODEL_TYPE = {
    "checkpoints": "Checkpoint",
    "loras": "LORA",
    "vae": "VAE",
    "controlnet": "Controlnet",
    "unet": "Checkpoint",
    "clip": "CLIP",
    "upscale_models": "Upscaler",
    "embeddings": "TextualInversion",
    "hypernetworks": "Hypernetwork",
    "aesthetics": "Other",
    "poses": "Poses",
    "wildcards": "Wildcards",
    "ultralytics/bbox": "Other",
    "motion_modules": "MotionModule",
}


def _clean_filename_for_display(filename: str) -> str:
    """
    Convert a storage filename to a cleaner, more readable display name.
    E.g., "akali_league_of_legends_nsfwsf_v10_413394" -> "Akali League Of Legends (NSFW) v10"
    """
    # Remove extension
    name = filename.rsplit(".", 1)[0] if "." in filename else filename

    # Replace common separators with spaces
    name = name.replace("_", " ").replace("-", " ")

    # Handle version patterns like "v10", "v1.0", "version_10"
    name = re.sub(r'\bv(\d+(?:\.\d+)?)\b', r'v\1', name, flags=re.IGNORECASE)

    # Remove common hash/id suffixes (long hex patterns, typically 8+ chars)
    name = re.sub(r'[\s_]?[a-f0-9]{8,}$', '', name, flags=re.IGNORECASE)
    # Remove trailing version IDs that look like civitai-style suffixes: _413394
    name = re.sub(r'[\s_]?\d{6,}$', '', name)

    # Clean up duplicate whitespace
    name = re.sub(r'\s+', ' ', name).strip()

    # Capitalize each word
    name = name.title()

    # Handle common abbreviations and markers
    name = re.sub(r'\bNsfw\b', '(NSFW)', name)
    name = re.sub(r'\bSfw\b', '(SFW)', name)
    name = re.sub(r'\bLora\b', 'LoRA', name)
    name = re.sub(r'\bSdxl\b', 'SDXL', name)
    name = re.sub(r'\bSd\b', 'SD', name)
    name = re.sub(r'\bFp8\b', 'FP8', name)
    name = re.sub(r'\bFp16\b', 'FP16', name)
    name = re.sub(r'\bBf16\b', 'BF16', name)

    # Clean up any double spaces or weird spacing
    name = re.sub(r'\s+', ' ', name).strip()

    return name


class ModelReconciliationService:
    """
    Handles provider model directory reconciliation, auto-discovery,
    and reconciliation caching for the model service.
    """

    def __init__(self, session: Session, repo: Optional[ModelRepositoryV2] = None):
        self.session = session
        self.repo = repo or ModelRepositoryV2(session)

    async def register_discovered_files(
        self,
        provider_id: str,
        files: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        imported = 0
        skipped = 0
        errors = 0
        results = []

        for file_info in files:
            storage_path = file_info.get("path", "")
            size_bytes = file_info.get("size_bytes")

            if not storage_path:
                errors += 1
                results.append({"path": "", "file_id": None, "status": "error", "reason": "empty path"})
                continue

            if self.repo.is_tombstoned(storage_path):
                skipped += 1
                results.append({"path": storage_path, "file_id": None, "status": "deleted", "reason": "Tombstoned"})
                continue

            rel_path = storage_path.replace("models/", "", 1) if storage_path.startswith("models/") else storage_path
            parts = rel_path.split("/")
            if len(parts) < 2:
                errors += 1
                results.append({"path": storage_path, "file_id": None, "status": "error", "reason": "invalid path format"})
                continue

            directory = "/".join(parts[:-1])
            filename = parts[-1]

            try:
                existing_file = self.repo.get_file_by_storage_path(directory, filename)
                if existing_file:
                    self.repo.update_provider_status(
                        file_id=existing_file.id,
                        provider_id=provider_id,
                        status="ready",
                        storage_path=storage_path,
                        size_bytes=size_bytes,
                    )
                    skipped += 1
                    results.append({"path": storage_path, "file_id": existing_file.id, "status": "skipped"})
                else:
                    # Generate a clean display name from filename
                    raw_name = filename.rsplit(".", 1)[0] if "." in filename else filename
                    display_name = _clean_filename_for_display(raw_name)
                    resolved_type = _DIRECTORY_TO_MODEL_TYPE.get(directory, "Other")

                    model = ModelV2(
                        name=display_name,
                        type=resolved_type,
                        directory=directory,
                        description="Auto-discovered from provider storage",
                        source="custom",
                        nsfw=False,
                        nsfw_level=1,
                    )
                    self.session.add(model)
                    self.session.flush()

                    version = ModelVersion(
                        model_id=model.id,
                        name="v1.0",
                        base_model="Custom",
                        base_model_type="Standard",
                        description=f"Auto-discovered from {provider_id} storage",
                        is_enabled=True,
                        is_default=True,
                    )
                    self.session.add(version)
                    self.session.flush()

                    file = ModelFile(
                        version_id=version.id,
                        original_filename=filename,
                        storage_filename=filename,
                        size_kb=(size_bytes or 0) / 1024.0,
                        format=filename.split(".")[-1] if "." in filename else "Unknown",
                        is_primary=True,
                        file_type="Model",
                        hash_sha256=file_info.get("sha256")
                    )
                    self.session.add(file)
                    self.session.flush()

                    self.repo.update_provider_status(
                        file_id=file.id,
                        provider_id=provider_id,
                        status="ready",
                        storage_path=storage_path,
                        size_bytes=size_bytes,
                    )

                    imported += 1
                    results.append({"path": storage_path, "file_id": file.id, "status": "imported"})
            except Exception as exc:
                errors += 1
                results.append({"path": storage_path, "file_id": None, "status": "error", "reason": str(exc)})

        self.session.commit()
        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "total": len(files),
            "files": results,
        }

    def get_pending_downloads(self, provider_id: str) -> List[Dict[str, Any]]:
        """Get files pending download for a provider (sync method for worker)."""
        return self.repo.get_pending_downloads(provider_id)

    def get_full_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all model metadata for reconciliation (sync method for worker)."""
        return self.repo.get_grouped_by_directory()
