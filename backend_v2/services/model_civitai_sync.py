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

    async def autopopulate_model(self, model_id: str) -> Dict[str, Any]:
        from services.external_model_service import ExternalModelService
        model = self.repo.get_model(model_id)
        if not model:
            raise ValueError("Model not found")

        external = ExternalModelService()
        search_result = await external.search_civitai(model.name, limit=1)
        items = search_result.get("items", [])
        if not items:
            raise ValueError(f"No match found on CivitAI for '{model.name}'")

        civitai_data = items[0]
        model.civitai_model_id = civitai_data.get("id")
        if not model.description or "Auto-discovered" in model.description:
            model.description = civitai_data.get("description", model.description)
        model.nsfw = civitai_data.get("nsfw", False)

        if civitai_data.get("modelVersions"):
            versions = self.repo.get_versions_for_model(model.id)
            if versions:
                civitai_version = civitai_data["modelVersions"][0]
                version = versions[0]
                version.civitai_version_id = civitai_version.get("id")
                if "Auto-discovered" in version.description:
                    version.description = civitai_version.get("description", version.description)
                version.base_model = civitai_version.get("baseModel", version.base_model)
                
                # Save first image if missing
                images = civitai_version.get("images", [])
                
                # Check if version already has images
                from core.entities_v2 import ModelImage
                from sqlmodel import select
                existing_images = self.session.exec(
                    select(ModelImage).where(ModelImage.version_id == version.id)
                ).all()
                
                if images and not existing_images:
                    image_data = images[0]
                    img = ModelImage(
                        version_id=version.id,
                        url=image_data.get("url", ""),
                        nsfw=image_data.get("nsfw", "None") != "None",
                        sort_order=0
                    )
                    self.session.add(img)

        self.session.commit()
        return self.repo.model_to_dict(model)
