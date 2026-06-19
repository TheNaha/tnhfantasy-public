from typing import Dict, Any, List, Optional

from sqlmodel import Session

from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from services.model_downloader import ModelDownloader


class ModelCivitaiSyncService:
    """
    Handles CivitAI metadata importing/parsing logic for the model service.
    """

    def __init__(
        self,
        session: Session,
        repo: Optional[ModelRepositoryV2] = None,
        downloader: Optional[ModelDownloader] = None,
    ):
        self.session = session
        self.repo = repo or ModelRepositoryV2(session)
        self.downloader = downloader or ModelDownloader(session, self.repo)

    async def add_model_from_civitai(
        self,
        civitai_data: Dict[str, Any],
        selected_version_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Add a model from CivitAI with selected versions.

        Args:
            civitai_data: Full CivitAI API response
            selected_version_ids: List of CivitAI version IDs to include

        Returns:
            Created model as dict
        """
        # Check if model already exists
        civitai_id = civitai_data.get("id")
        existing = self.repo.get_model_by_civitai_id(civitai_id)
        if existing:
            # Add new versions to existing model
            added_versions = self.repo.add_versions_to_model(
                model=existing,
                civitai_data=civitai_data,
                selected_version_ids=selected_version_ids
            )

            if added_versions:
                # Trigger download for only the new versions (not all versions)
                new_version_ids = [v.id for v in added_versions]
                await self.downloader.trigger_download_to_providers(
                    existing.id, version_ids=new_version_ids
                )

            result = self.repo.model_to_dict(existing)
            result["added_versions"] = len(added_versions)
            return result

        model = self.repo.create_model_with_versions(
            civitai_data=civitai_data,
            selected_version_ids=selected_version_ids
        )

        # Trigger immediate download to all enabled providers
        await self.downloader.trigger_download_to_providers(model.id)

        # Auto-download Flux dependencies if this is a Flux model
        await self.downloader.check_and_trigger_dependencies(civitai_data=civitai_data)

        return self.repo.model_to_dict(model)
