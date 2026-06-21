from typing import Dict, Any, List, Optional

from sqlmodel import Session

from core.entities import ModelFile, ModelVersion
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

    async def autopopulate_model(self, model_id: str, target_civitai_id: Optional[int] = None) -> Dict[str, Any]:
        import json
        import re
        from services.external_model_service import ExternalModelService
        from core.entities import ModelImage, ModelTag
        from sqlmodel import select

        model = self.repo.get_model(model_id)
        if not model:
            raise ValueError("Model not found")

        civitai_data = None

        if target_civitai_id:
            external = ExternalModelService()
            try:
                civitai_data = await external.get_civitai_model(target_civitai_id)
            except Exception:
                pass

        if not civitai_data and model.civitai_model_id:
            external = ExternalModelService()
            try:
                civitai_data = await external.get_civitai_model(model.civitai_model_id)
            except Exception:
                pass

        if not civitai_data:
            scored = await self._search_civitai_scored(model)
            if not scored:
                raise ValueError(f"No match found on CivitAI for '{model.name}'")
            civitai_data = scored[0][1]

        # Update model-level fields
        model.civitai_model_id = civitai_data.get("id")
        model.nsfw = civitai_data.get("nsfw", False)
        model.nsfw_level = civitai_data.get("nsfwLevel", 3 if model.nsfw else 1)
        model.source = civitai_data.get("source", "civitai")
        model.type = civitai_data.get("type", model.type)
        
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

        # Update versions — match by civitai_id or name, create new versions for unmatched
        if civitai_data.get("modelVersions"):
            local_versions = self.repo.get_versions_for_model(model.id)
            civitai_versions = civitai_data["modelVersions"]
            matched_ids = set()

            for civitai_version in civitai_versions:
                matched_version = None

                # Try matching by CivitAI version ID first
                for lv in local_versions:
                    if lv.civitai_version_id == civitai_version.get("id"):
                        matched_version = lv
                        break

                # Fall back to name matching
                if not matched_version:
                    for lv in local_versions:
                        if lv.name.lower() == civitai_version.get("name", "").lower():
                            matched_version = lv
                            break

                # Fall back to reusing the auto-discovered "v1.0" version if it's unlinked
                if not matched_version:
                    for lv in local_versions:
                        if lv.name == "v1.0" and not lv.civitai_version_id:
                            matched_version = lv
                            matched_version.name = civitai_version.get("name", "v1.0")
                            break

                if not matched_version:
                    # Create a new ModelVersion for unmatched CivitAI versions
                    new_version = ModelVersion(
                        model_id=model.id,
                        name=civitai_version.get("name", "v1.0"),
                        civitai_version_id=civitai_version.get("id"),
                        base_model=civitai_version.get("baseModel", "Unknown"),
                        base_model_type="Standard",
                        description=civitai_version.get("description", ""),
                        trained_words=json.dumps(civitai_version.get("trainedWords", [])),
                        is_enabled=True,
                        is_default=len(local_versions) == 0,
                    )
                    self.session.add(new_version)
                    self.session.flush()
                    matched_version = new_version
                    local_versions.append(new_version)

                matched_ids.add(matched_version.id)
                matched_version.civitai_version_id = civitai_version.get("id")

                # Update file size from CivitAI data if currently 0
                civitai_files = civitai_version.get("files", [])
                if civitai_files:
                    primary_civitai = next((f for f in civitai_files if f.get("primary")), civitai_files[0])
                    civitai_size_kb = primary_civitai.get("sizeKB")
                    if civitai_size_kb is not None:
                        existing_files = self.session.exec(
                            select(ModelFile).where(ModelFile.version_id == matched_version.id)
                        ).all()
                        for ef in existing_files:
                            if ef.size_kb is None or ef.size_kb == 0:
                                ef.size_kb = float(civitai_size_kb)

                if "Auto-discovered" in (matched_version.description or ""):
                    matched_version.description = civitai_version.get("description", matched_version.description)

                matched_version.base_model = civitai_version.get("baseModel", matched_version.base_model)

                trained = civitai_version.get("trainedWords", [])
                if trained:
                    matched_version.trained_words = json.dumps(trained)

                images = civitai_version.get("images", [])
                existing_images = self.session.exec(
                    select(ModelImage).where(ModelImage.version_id == matched_version.id)
                ).all()

                if images and not existing_images:
                    image_data = images[0]
                    img_nsfw = image_data.get("nsfw", "None")
                    img_nsfw_level = image_data.get("nsfwLevel")
                    if img_nsfw_level is not None:
                        resolved_nsfw_level = img_nsfw_level
                    else:
                        resolved_nsfw_level = 3 if img_nsfw else 1
                    img = ModelImage(
                        version_id=matched_version.id,
                        url=image_data.get("url", ""),
                        nsfw_level=resolved_nsfw_level,
                        sort_order=0,
                    )
                    self.session.add(img)

        self.session.commit()
        return self.repo.model_to_dict(model)

    def _extract_civitai_id_from_files(self, model) -> int | None:
        """Extract a CivitAI model ID from model version file names.
        
        Many auto-discovered models have filenames ending with _<civitai_id>
        (e.g. my_model_v1_413394.safetensors). This extracts that ID.
        """
        import re
        from sqlmodel import select

        files = self.session.exec(
            select(ModelFile).where(
                ModelFile.version_id.in_(
                    select(ModelVersion.id).where(ModelVersion.model_id == model.id)
                )
            )
        ).all()

        for f in files:
            name = f.original_filename or f.storage_filename or ""
            base = name.rsplit(".", 1)[0]
            m = re.search(r'_(\d{6,})$', base)
            if m:
                return int(m.group(1))
        return None

    def _compute_token_overlap_score(self, a: str, b: str) -> int:
        """Compute a 0-100 score based on token overlap ratio, 
        giving higher weight to matching tokens.
        """
        if not a or not b:
            return 0
        a_tokens = set(a.lower().split())
        b_tokens = set(b.lower().split())
        if not a_tokens or not b_tokens:
            return 0
        intersection = a_tokens & b_tokens
        union = a_tokens | b_tokens
        jaccard = len(intersection) / len(union)
        return int(jaccard * 100)

    async def _search_civitai_scored(self, model) -> list:
        """Search CivitAI for a model and return scored candidates.
        
        Returns a list of (score, item_dict) tuples sorted by score descending.
        Uses 4-stage search with token-overlap scoring.
        Stage 1: Direct CivitAI ID lookup from filename embedded IDs
        Stage 2: Filtered search (by type + query)
        Stage 3: Unfiltered search
        Stage 4: Raw filename-based search
        """
        from services.external_model_service import ExternalModelService
        from sqlmodel import select
        import re as _re
        external = ExternalModelService()

        # Stage 1: Direct ID lookup from filenames (fastest path)
        extracted_id = self._extract_civitai_id_from_files(model)
        if extracted_id:
            try:
                model_data = await external.get_civitai_model(extracted_id)
                if model_data:
                    return [(100, model_data)]
            except Exception:
                pass

        search_query = self._clean_search_query(model.name)
        all_items = []
        seen_ids = set()

        # Stage 2: Filtered search (by type + cleaned query)
        search_kwargs = {"query": search_query, "limit": 10}
        if model.type and model.type.lower() not in ("other", "unknown"):
            search_kwargs["types"] = model.type
        elif model.directory and model.directory not in ("other", "unknown"):
            from services.model_reconciliation import _DIRECTORY_TO_MODEL_TYPE
            mapped_type = _DIRECTORY_TO_MODEL_TYPE.get(model.directory, "Checkpoint")
            if mapped_type != "Other":
                search_kwargs["types"] = mapped_type

        result = await external.search_civitai(**search_kwargs)
        for item in result.get("items", []):
            if item.get("id") not in seen_ids:
                all_items.append(item)
                seen_ids.add(item.get("id"))

        # Stage 3: Unfiltered search (broader)
        result = await external.search_civitai(query=search_query, limit=10)
        for item in result.get("items", []):
            if item.get("id") not in seen_ids:
                all_items.append(item)
                seen_ids.add(item.get("id"))

        # Stage 4: Fuzzy search (remove parentheticals)
        fuzzy_query = _re.sub(r'\s*\(.*?\)\s*', '', search_query).strip()
        if fuzzy_query and fuzzy_query != search_query:
            result = await external.search_civitai(query=fuzzy_query, limit=10)
            for item in result.get("items", []):
                if item.get("id") not in seen_ids:
                    all_items.append(item)
                    seen_ids.add(item.get("id"))

        # Stage 5: Raw filename-based search
        raw_queries = set()
        files = self.session.exec(
            select(ModelFile).where(
                ModelFile.version_id.in_(
                    select(ModelVersion.id).where(ModelVersion.model_id == model.id)
                )
            )
        ).all()
        for f in files:
            raw = (f.original_filename or f.storage_filename or "")
            base = raw.rsplit(".", 1)[0]
            raw_clean = _re.sub(r'[_-]', ' ', base)
            raw_clean = _re.sub(r'\s+', ' ', raw_clean).strip()
            if raw_clean and raw_clean != search_query:
                raw_queries.add(raw_clean)
        for rq in list(raw_queries)[:2]:
            result = await external.search_civitai(query=rq, limit=10)
            for item in result.get("items", []):
                if item.get("id") not in seen_ids:
                    all_items.append(item)
                    seen_ids.add(item.get("id"))

        if not all_items:
            return []

        # Score all candidates using token overlap
        lower_name = model.name.lower()
        scored = []
        for item in all_items:
            item_name = (item.get("name") or "").lower()
            score = self._compute_token_overlap_score(lower_name, item_name)
            if score == 0:
                continue
            scored.append((score, item))

        scored.sort(key=lambda x: -x[0])
        return scored

    async def search_civitai_candidates(self, model_id: str) -> dict:
        """Search CivitAI for candidates matching an auto-discovered model.
        
        Returns model info and scored candidates without enriching the model.
        This is used by the frontend AutopopulateSelector to let users pick.
        """
        model = self.repo.get_model(model_id)
        if not model:
            raise ValueError("Model not found")

        # Gather raw filenames for the UI
        from sqlmodel import select
        raw_filenames = []
        files = self.session.exec(
            select(ModelFile).where(
                ModelFile.version_id.in_(
                    select(ModelVersion.id).where(ModelVersion.model_id == model.id)
                )
            )
        ).all()
        for f in files:
            raw_filenames.append(f.original_filename or f.storage_filename or "")

        scored = await self._search_civitai_scored(model)

        def match_label(score: int) -> str:
            if score >= 100:
                return "Exact match"
            elif score >= 60:
                return "Close match"
            elif score >= 30:
                return "Partial match"
            elif score > 0:
                return "Weak match"
            return "No match"

        candidates = []
        for score, item in scored:
            civitai_id = item.get("id")
            civitai_source = item.get("source", "civitai")

            candidates.append({
                "score": score,
                "score_percent": score,
                "match_label": match_label(score),
                "civitai_model": item,
            })

        return {
            "model_id": str(model.id),
            "model_name": model.name,
            "model_type": model.type,
            "model_directory": model.directory,
            "model_description": model.description,
            "raw_filenames": raw_filenames,
            "search_query": self._clean_search_query(model.name),
            "candidates": candidates,
            "total_candidates": len(candidates),
            "source": "civitai",
        }

    @staticmethod
    def _clean_search_query(name: str) -> str:
        """Clean a display name for CivitAI search by removing noise tokens."""
        import re
        q = name
        q = re.sub(r'\([^)]*\)', '', q)
        q = re.sub(r'[_\s]*v\d+(\.\d+)*[\w]*$', '', q, flags=re.IGNORECASE)
        q = re.sub(r'[_\s]*pruned[\w]*$', '', q, flags=re.IGNORECASE)
        q = re.sub(r'[_\s]*fp16[\w]*$', '', q, flags=re.IGNORECASE)
        q = re.sub(r'[_\s]*fp32[\w]*$', '', q, flags=re.IGNORECASE)
        q = q.replace('_', ' ')
        q = re.sub(r'\s+', ' ', q).strip()
        return q
