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
        import json
        import re
        from services.external_model_service import ExternalModelService
        from core.entities import ModelImage, ModelTag
        from sqlmodel import select

        model = self.repo.get_model(model_id)
        if not model:
            raise ValueError("Model not found")

        external = ExternalModelService()

        # Try direct lookup by CivitAI model ID first (most accurate)
        civitai_data = None
        if model.civitai_model_id:
            try:
                civitai_data = await external.get_civitai_model(model.civitai_model_id)
            except Exception:
                pass

        # Fall back to search by cleaned name
        if not civitai_data:
            search_query = self._clean_search_query(model.name)
            search_result = await external.search_civitai(search_query, limit=3)
            items = search_result.get("items", [])
            if not items:
                raise ValueError(f"No match found on CivitAI for '{model.name}'")

            # Prefer exact name match over first result
            civitai_data = items[0]
            for item in items:
                if item.get("name", "").lower() == model.name.lower():
                    civitai_data = item
                    break

        # Update model-level fields
        model.civitai_model_id = civitai_data.get("id")
        model.nsfw = civitai_data.get("nsfw", False)
        
        if civitai_data.get("name"):
            model.name = civitai_data.get("name")

        # Update description (always replace "Auto-discovered" stubs)
        new_desc = civitai_data.get("description", "")
        if new_desc and (not model.description or "Auto-discovered" in model.description):
            model.description = new_desc

        # Update creator
        creator = civitai_data.get("creator", {})
        if creator:
            model.creator_username = creator.get("username", model.creator_username)
            model.creator_image = creator.get("image", model.creator_image)

        # Update stats
        stats = civitai_data.get("stats", {})
        if stats:
            model.stats_downloads = stats.get("downloadCount", model.stats_downloads)
            model.stats_thumbs_up = stats.get("thumbsUpCount", model.stats_thumbs_up)
            model.stats_thumbs_down = stats.get("thumbsDownCount", model.stats_thumbs_down)
            model.stats_comments = stats.get("commentCount", model.stats_comments)

        # Update tags
        civitai_tags = civitai_data.get("tags", [])
        if civitai_tags:
            existing_tags = self.session.exec(
                select(ModelTag).where(ModelTag.model_id == model.id)
            ).all()
            existing_tag_set = {t.tag for t in existing_tags}
            for tag_name in civitai_tags:
                if tag_name not in existing_tag_set:
                    self.session.add(ModelTag(model_id=model.id, tag=tag_name))

        # Update versions — try to match by name or use first
        if civitai_data.get("modelVersions"):
            local_versions = self.repo.get_versions_for_model(model.id)
            civitai_versions = civitai_data["modelVersions"]

            for civitai_version in civitai_versions:
                # Find matching local version by name or civitai_version_id
                matched_version = None
                for lv in local_versions:
                    if lv.civitai_version_id == civitai_version.get("id"):
                        matched_version = lv
                        break
                if not matched_version:
                    for lv in local_versions:
                        if lv.name.lower() == civitai_version.get("name", "").lower():
                            matched_version = lv
                            break
                if not matched_version and local_versions:
                    matched_version = local_versions[0]

                if not matched_version:
                    continue

                matched_version.civitai_version_id = civitai_version.get("id")

                if "Auto-discovered" in (matched_version.description or ""):
                    matched_version.description = civitai_version.get("description", matched_version.description)

                matched_version.base_model = civitai_version.get("baseModel", matched_version.base_model)

                # Update trained_words (trigger words)
                trained = civitai_version.get("trainedWords", [])
                if trained:
                    matched_version.trained_words = json.dumps(trained)

                # Save first image if missing
                images = civitai_version.get("images", [])
                existing_images = self.session.exec(
                    select(ModelImage).where(ModelImage.version_id == matched_version.id)
                ).all()

                if images and not existing_images:
                    image_data = images[0]
                    img = ModelImage(
                        version_id=matched_version.id,
                        url=image_data.get("url", ""),
                        nsfw_level=1 if image_data.get("nsfw", "None") == "None" else 3,
                        sort_order=0,
                    )
                    self.session.add(img)

        self.session.commit()
        return self.repo.model_to_dict(model)

    @staticmethod
    def _clean_search_query(name: str) -> str:
        """Clean a display name for CivitAI search by removing noise tokens."""
        import re
        q = name
        # Remove parenthetical annotations like (NSFW), (SFW), (fp16)
        q = re.sub(r'\([^)]*\)', '', q)
        # Remove trailing version tokens like v10, v2.0, _pruned
        q = re.sub(r'[_\s]*v\d+(\.\d+)*[\w]*$', '', q, flags=re.IGNORECASE)
        q = re.sub(r'[_\s]*pruned[\w]*$', '', q, flags=re.IGNORECASE)
        q = re.sub(r'[_\s]*fp16[\w]*$', '', q, flags=re.IGNORECASE)
        q = re.sub(r'[_\s]*fp32[\w]*$', '', q, flags=re.IGNORECASE)
        # Replace underscores with spaces and collapse whitespace
        q = q.replace('_', ' ')
        q = re.sub(r'\s+', ' ', q).strip()
        return q
