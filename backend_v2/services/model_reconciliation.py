import re
from typing import Any
import unicodedata

from sqlmodel import Session

from core.entities import ModelFile, ModelV2, ModelVersion
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from services.engines.base import MODEL_DIRECTORIES
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
    # The segmentation tree is a separate directory from the bbox tree, and
    # it was missing here - so a model discovered under it was typed "Other",
    # which is the type the model list filters on and the type the UI shows.
    "ultralytics/seg": "Other",
    "motion_modules": "MotionModule",
    # The CLIP vision encoder is the text encoder's sibling and has its own
    # directory. It was missing here for the same reason.
    "clip_vision": "CLIP",
    # The IPAdapter weights. Also missing - which is why the IPAdapter
    # picker was always empty even on a provider that had the weights
    # installed: the directory was not in the reconciled list at all.
    "ipadapter": "IPAdapter",
}

_CANONICAL_MODEL_DIRS = tuple(
    sorted(
        [d.replace("models/", "", 1) if d.startswith("models/") else d for d in MODEL_DIRECTORIES],
        key=len,
        reverse=True,
    )
)


def split_canonical_storage_path(storage_path: str) -> tuple[str, str, str] | None:
    """Split a storage path into (canonical_directory, relative_filename, basename).

    Handles shallow paths ('models/checkpoints/model.safetensors'),
    deep subfolder paths ('models/checkpoints/sdxl/v1/model.safetensors'),
    and 2-segment canonical directories like 'models/ultralytics/bbox/face.pt'.

    Returns:
        (canonical_directory, relative_filename, basename) or None if path is invalid.
    """
    clean_path = storage_path.replace("\\", "/").strip()
    if not clean_path:
        return None
    rel_path = clean_path.replace("models/", "", 1) if clean_path.startswith("models/") else clean_path
    rel_path = rel_path.lstrip("/")

    for canon_dir in _CANONICAL_MODEL_DIRS:
        prefix = f"{canon_dir}/"
        if rel_path.startswith(prefix):
            rel_filename = rel_path[len(prefix):]
            if not rel_filename:
                return None
            basename = rel_filename.split("/")[-1]
            return (canon_dir, rel_filename, basename)

    parts = rel_path.split("/")
    if len(parts) >= 2:
        return ("/".join(parts[:-1]), parts[-1], parts[-1])
    return None


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

    def _write_provider_status(self, **kwargs) -> None:
        """Write a provider file status AND invalidate the availability caches.

        `ModelDownloader.update_provider_file_status` is the writer that
        invalidates. Writing through the repository directly bypassed it, so
        a model this pass had just marked `ready` stayed ineligible for the
        availability check for up to the 30 s TTL.
        """
        self.repo.update_provider_status(**kwargs)
        from services.load_balancer import LoadBalancer

        LoadBalancer.invalidate_model_availability_cache()


    def __init__(self, session: Session, repo: ModelRepositoryV2 | None = None):
        self.session = session
        self.repo = repo or ModelRepositoryV2(session)

    async def register_discovered_files(
        self,
        provider_id: str,
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        imported = 0
        skipped = 0
        errors = 0
        results = []

        for file_info in files:
            storage_path = unicodedata.normalize("NFC", file_info.get("path") or "")
            size_bytes = file_info.get("size_bytes")

            if not storage_path:
                errors += 1
                results.append({"path": "", "file_id": None, "status": "error", "reason": "empty path"})
                continue

            if self.repo.is_tombstoned(storage_path) or self.repo.is_tombstoned(unicodedata.normalize("NFD", storage_path)):
                skipped += 1
                results.append({"path": storage_path, "file_id": None, "status": "deleted", "reason": "Tombstoned"})
                continue

            split_res = split_canonical_storage_path(storage_path)
            if not split_res:
                errors += 1
                results.append({"path": storage_path, "file_id": None, "status": "error", "reason": "invalid path format"})
                continue

            directory, rel_filename, basename = split_res
            rel_filename = unicodedata.normalize("NFC", rel_filename)
            basename = unicodedata.normalize("NFC", basename)

            try:
                existing_file = (
                    self.repo.get_file_by_storage_path(directory, rel_filename)
                    or self.repo.get_file_by_storage_path(directory, basename)
                )
                if existing_file:
                    self._write_provider_status(
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
                    raw_name = basename.rsplit(".", 1)[0] if "." in basename else basename
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
                        original_filename=rel_filename,
                        storage_filename=basename,
                        size_bytes=size_bytes,
                        type=resolved_type,
                        is_primary=True,
                        file_type="Model",
                        hash_sha256=file_info.get("sha256"),
                    )
                    self.session.add(file)
                    self.session.flush()

                    self._write_provider_status(
                        file_id=file.id,
                        provider_id=provider_id,
                        status="ready",
                        storage_path=storage_path,
                        size_bytes=size_bytes,
                    )

                    imported += 1
                    results.append({"path": storage_path, "file_id": file.id, "status": "imported"})
            except Exception as exc:
                self.session.rollback()
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

    def get_pending_downloads(self, provider_id: str) -> list[dict[str, Any]]:
        """Get files pending download for a provider (sync method for worker)."""
        return self.repo.get_pending_downloads(provider_id)
