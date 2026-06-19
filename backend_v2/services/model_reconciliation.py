from typing import Dict, Any, List, Optional

from sqlmodel import Session

from core.entities_v2 import ModelV2, ModelVersion, ModelFile
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

            parts = storage_path.replace("models/", "", 1).split("/")
            if len(parts) < 2:
                errors += 1
                results.append({"path": storage_path, "file_id": None, "status": "error", "reason": "invalid path format"})
                continue

            directory = parts[0]
            filename = "/".join(parts[1:])

            try:
                existing_file = self.repo.get_file_by_storage_path(directory, filename)
                if existing_file:
                    self.repo.update_provider_status(
                        file_id=existing_file.id,
                        provider_name=provider_id,
                        status="ready",
                        storage_path=storage_path,
                        size_bytes=size_bytes,
                    )
                    skipped += 1
                    results.append({"path": storage_path, "file_id": existing_file.id, "status": "skipped"})
                else:
                    name = filename.rsplit(".", 1)[0] if "." in filename else filename
                    resolved_type = _DIRECTORY_TO_MODEL_TYPE.get(directory, "Other")

                    model = ModelV2(
                        name=name,
                        type=resolved_type,
                        directory=directory,
                        description=f"Auto-discovered from {provider_id} storage",
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
                    )
                    self.session.add(file)
                    self.session.flush()

                    self.repo.update_provider_status(
                        file_id=file.id,
                        provider_name=provider_id,
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

    def get_pending_downloads(self, provider_name: str) -> List[Dict[str, Any]]:
        """Get files pending download for a provider (sync method for worker)."""
        return self.repo.get_pending_downloads(provider_name)

    def get_full_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all model metadata for reconciliation (sync method for worker)."""
        return self.repo.get_grouped_by_directory()
