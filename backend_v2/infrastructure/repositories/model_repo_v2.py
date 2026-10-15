# Model Repository V2 - Version-aware data access layer
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import Session, and_, col, func, or_, select

from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
from core.entities import (
    DeletedFileTombstone,
    ModelFile,
    ModelImage,
    ModelTag,
    ModelV2,
    ModelVersion,
    ProviderVersionStatus,
    compute_storage_filename,
    get_directory_from_type,
    is_unet_only_model,
)
from infrastructure.logging import get_logger

logger = get_logger("model_repo_v2")

# A datetime whose fractional-second part is longer than 6 digits, captured with
# whatever follows it so an offset is preserved: "…:00.000+00:00".
_FRACTION_OVERLONG = re.compile(r"^(.*\.)(\d{7,})(.*)$")


def get_file_priority(f):
    """Lower is better. Prefer safetensors, avoid GGUF."""
    name = f.get("name", "").lower()
    score = 0
    if name.endswith(".safetensors"):
        score -= 100
    elif name.endswith(".gguf"):
        score -= 75
    elif name.endswith((".ckpt", ".pt", ".pth", ".bin")):
        score -= 50
    if f.get("primary", False):
        score -= 10
    return score


def parse_civitai_datetime(value: Any) -> datetime | None:
    """Parse a CivitAI datetime into a timezone-AWARE UTC datetime.

    Always returns an aware datetime (or None). This must never hand back a
    naive one: `civitai_published_at` and `civitai_created_at` are `UTCDateTime`
    columns, and SQLModel's bind processor raises
    "Datetime values must have timezone information" on a naive value. That
    turned "Add model" on the Discover page into a 500 for any model whose
    version carried a timestamp.

    Two things were wrong before:

    * `datetime.strptime(..., "...Z")` never attaches a tzinfo — the `Z` is
      just a literal in the format — so every strptime path produced a naive
      value.
    * the fallback stripped the offset it had just added
      (`.replace("Z", "+00:00").replace("+00:00", "")`), guaranteeing the same.

    CivitAI's model-version `publishedAt` is UTC serialised *without* an offset
    (e.g. `2026-04-10T07:59:57.750000`), so a missing offset is the common case
    and is interpreted as UTC, which is what CivitAI means.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        # Already parsed: normalise so a naive value is still accepted.
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"

    # `fromisoformat` handles 'Z' and explicit offsets on 3.11+, but chokes on a
    # fractional part longer than 6 digits, which CivitAI has been known to send.
    # Trim the fraction only, keeping whatever follows it (an offset, say).
    trimmed = _FRACTION_OVERLONG.match(candidate)
    if trimmed:
        candidate = f"{trimmed.group(1)}{trimmed.group(2)[:6]}{trimmed.group(3)}"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            logger.debug("civitai_datetime_unparsed", value=text)
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ModelRepositoryV2:
    """
    Version-aware data access layer for models.
    Replaces the flat ModelRepository with normalized operations.
    """
    
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _get_provider_key(status: ProviderVersionStatus) -> str:
        """Return provider ID."""
        return status.provider_id

    def _provider_match_clause(self, provider_key: str):
        """Build a provider filter."""
        return ProviderVersionStatus.provider_id == provider_key

    def _provider_match_clause_many(self, provider_keys: list[str]):
        """Build a provider filter for multiple providers."""
        return ProviderVersionStatus.provider_id.in_(provider_keys)
    
    # =========================================================================
    # MODEL CRUD
    # =========================================================================
    
    def create_model_with_versions(
        self,
        civitai_data: dict[str, Any],
        selected_version_ids: list[int]
    ) -> ModelV2:
        """
        Create a model with only the selected versions.
        
        Args:
            civitai_data: Full CivitAI API response
            selected_version_ids: List of version IDs to include
            
        Returns:
            Created ModelV2 instance
        """
        # Extract base model info
        stats = civitai_data.get("stats", {})
        creator = civitai_data.get("creator", {})
        model_type = civitai_data.get("type", "Checkpoint")
        
        # Get base_model from first selected version for directory routing
        # (Flux "Checkpoints" need to go to unet/ directory)
        first_version_base_model = None
        for version_data in civitai_data.get("modelVersions", []):
            if version_data.get("id") in selected_version_ids:
                first_version_base_model = version_data.get("baseModel")
                break
        
        # Create model
        model = ModelV2(
            civitai_model_id=civitai_data.get("id"),
            name=civitai_data.get("name", "Unknown"),
            type=model_type,
            directory=get_directory_from_type(model_type, first_version_base_model),

            description=civitai_data.get("description"),
            nsfw=civitai_data.get("nsfw", False),
            nsfw_level=civitai_data.get("nsfwLevel", 1),
            creator_username=creator.get("username"),
            creator_image=creator.get("image"),
            stats_downloads=stats.get("downloadCount", 0),
            stats_thumbs_up=stats.get("thumbsUpCount", 0),
            stats_thumbs_down=stats.get("thumbsDownCount", 0),
            stats_comments=stats.get("commentCount", 0),
            source="civitai",
            source_url=f"https://civitai.com/models/{civitai_data.get('id')}"
        )
        self.session.add(model)
        self.session.flush()  # Get model ID
        
        # Create tags
        for tag in civitai_data.get("tags", []):
            tag_obj = ModelTag(model_id=model.id, tag=tag)
            self.session.add(tag_obj)
        
        # Create selected versions
        is_first = True
        for version_data in civitai_data.get("modelVersions", []):
            if version_data.get("id") not in selected_version_ids:
                continue
            
            trained_words = version_data.get("trainedWords", [])
            
            version = ModelVersion(
                model_id=model.id,
                civitai_version_id=version_data.get("id"),
                name=version_data.get("name", "v1.0"),
                base_model=version_data.get("baseModel"),
                base_model_type=version_data.get("baseModelType"),
                description=version_data.get("description"),
                is_enabled=True,
                is_default=is_first,  # First selected version is default
                trained_words=json.dumps(trained_words) if trained_words else None,
                civitai_created_at=parse_civitai_datetime(version_data.get("createdAt")),
                civitai_published_at=parse_civitai_datetime(version_data.get("publishedAt"))
            )
            self.session.add(version)
            self.session.flush()
            is_first = False
            
            # Create files - prefer safetensors format
            files_list = version_data.get("files", [])
            
            sorted_files = sorted(files_list, key=get_file_priority)

            # Only store the primary (best) file - no need for multiple formats
            for i, file_data in enumerate(sorted_files[:1]):  # Take only the first (best) file
                hashes = file_data.get("hashes", {})
                
                # Force safetensors extension if the selected file is safetensors
                original_name = file_data.get("name", "model.safetensors")
                storage_filename = compute_storage_filename(
                    model.name,
                    version.name,
                    version_data.get("id"),
                    original_name
                )
                
                file = ModelFile(
                    version_id=version.id,
                    civitai_file_id=file_data.get("id"),
                    original_filename=original_name,
                    storage_filename=storage_filename,
                    size_kb=file_data.get("sizeKB", 0),
                    format=file_data.get("metadata", {}).get("format") if file_data.get("metadata") else None,
                    hash_sha256=hashes.get("SHA256"),
                    hash_autov2=hashes.get("AutoV2"),
                    hash_blake3=hashes.get("BLAKE3"),
                    hash_crc32=hashes.get("CRC32"),
                    download_url=file_data.get("downloadUrl"),
                    is_primary=True,  # Always primary since we only store one file
                    file_type=file_data.get("type", "Model")
                )
                self.session.add(file)
            
            # Create images
            for i, img_data in enumerate(version_data.get("images", [])):
                image = ModelImage(
                    version_id=version.id,
                    url=img_data.get("url"),
                    width=img_data.get("width"),
                    height=img_data.get("height"),
                    blurhash=img_data.get("hash"),
                    type=img_data.get("type", "image"),
                    nsfw_level=img_data.get("nsfwLevel", 1),
                    has_meta=img_data.get("hasMeta", False),
                    has_positive_prompt=img_data.get("hasPositivePrompt", False),
                    sort_order=i
                )
                self.session.add(image)
        
        self.session.commit()
        self.session.refresh(model)
        return model
    
    def add_versions_to_model(
        self,
        model: ModelV2,
        civitai_data: dict[str, Any],
        selected_version_ids: list[int]
    ) -> list[ModelVersion]:
        """
        Add new versions to an existing model.
        
        Args:
            model: Existing ModelV2 instance
            civitai_data: Full CivitAI API response
            selected_version_ids: List of version IDs to add
            
        Returns:
            List of created ModelVersion instances
        """
        created_versions = []
        
        for version_data in civitai_data.get("modelVersions", []):
            if version_data.get("id") not in selected_version_ids:
                continue
            
            trained_words = version_data.get("trainedWords", [])
            
            version = ModelVersion(
                model_id=model.id,
                civitai_version_id=version_data.get("id"),
                name=version_data.get("name", "v1.0"),
                base_model=version_data.get("baseModel"),
                base_model_type=version_data.get("baseModelType"),
                description=version_data.get("description"),
                is_enabled=True,
                is_default=False,  # Don't change default for added versions
                trained_words=json.dumps(trained_words) if trained_words else None,
                civitai_created_at=parse_civitai_datetime(version_data.get("createdAt")),
                civitai_published_at=parse_civitai_datetime(version_data.get("publishedAt"))
            )
            self.session.add(version)
            self.session.flush()
            
            # Create files - prefer safetensors format
            files_list = version_data.get("files", [])
            
            sorted_files = sorted(files_list, key=get_file_priority)

            for file_data in sorted_files[:1]:
                hashes = file_data.get("hashes", {})
                original_name = file_data.get("name", "model.safetensors")
                storage_filename = compute_storage_filename(
                    model.name,
                    version.name,
                    version_data.get("id"),
                    original_name
                )
                
                file = ModelFile(
                    version_id=version.id,
                    civitai_file_id=file_data.get("id"),
                    original_filename=original_name,
                    storage_filename=storage_filename,
                    size_kb=file_data.get("sizeKB", 0),
                    format=file_data.get("metadata", {}).get("format") if file_data.get("metadata") else None,
                    hash_sha256=hashes.get("SHA256"),
                    hash_autov2=hashes.get("AutoV2"),
                    hash_blake3=hashes.get("BLAKE3"),
                    hash_crc32=hashes.get("CRC32"),
                    download_url=file_data.get("downloadUrl"),
                    is_primary=True,
                    file_type=file_data.get("type", "Model")
                )
                self.session.add(file)
            
            # Create images
            for i, img_data in enumerate(version_data.get("images", [])[:10]):
                image = ModelImage(
                    version_id=version.id,
                    url=img_data.get("url"),
                    width=img_data.get("width"),
                    height=img_data.get("height"),
                    blurhash=img_data.get("hash"),
                    type=img_data.get("type", "image"),
                    nsfw_level=img_data.get("nsfwLevel", 1),
                    has_meta=img_data.get("hasMeta", False),
                    has_positive_prompt=img_data.get("hasPositivePrompt", False),
                    sort_order=i
                )
                self.session.add(image)
            
            created_versions.append(version)
        
        self.session.commit()
        return created_versions
    
    def get_model(self, model_id: int) -> ModelV2 | None:
        """Get a model by ID."""
        return self.session.get(ModelV2, model_id)
    
    def get_model_by_civitai_id(self, civitai_id: int) -> ModelV2 | None:
        """Get a model by CivitAI model ID."""
        stmt = select(ModelV2).where(ModelV2.civitai_model_id == civitai_id)
        return self.session.exec(stmt).first()
    
    def get_all_models(self) -> list[ModelV2]:
        """Get all models."""
        stmt = select(ModelV2).order_by(col(ModelV2.updated_at).desc())
        return list(self.session.exec(stmt).all())
    
    # ── the directory listing, filtered and paged in SQL ─────────────────────
    #
    # This listing was, until 2026-10-05, `get_models_by_directory(directory)`
    # followed by filtering, sorting and slicing in the route. That cost
    # 7,062 B and ~1.2 s for one 484-model page, and it charged every request the
    # whole directory: `?limit=2` measured 543 ms and a search for a string that
    # does not exist measured the same 0.9 s before returning `{"files": []}`.
    #
    # So the four things the route was doing by hand live here now, where the
    # database can index them, and the route only projects. The filters are
    # built by one function so the page query and `count_models_by_directory`
    # cannot drift — a `total` that disagrees with its own rows is worse than no
    # total at all.
    #
    # `_default_version_file` is a correlated subquery rather than a join because
    # the sort key is *the default version's primary file*, which is not a
    # column of `models_v2`. Ordering by `models_v2.name` instead would look
    # equivalent and is not: on this deployment the two differ for every row
    # (484/484 in `models/loras`, 15/15 in `models/checkpoints`), because
    # `models_v2.name` is the CivitAI title and the sort key is the filename on
    # disk. That sort is what the Model Manager's LoRA tab sends, so getting it
    # wrong would reorder every list in the UI.

    def _default_version_id(self):
        return (
            select(ModelVersion.id)
            .where(ModelVersion.model_id == ModelV2.id)
            .where(ModelVersion.is_default.is_(True))
            .limit(1)
            .correlate(ModelV2)
            .scalar_subquery()
        )

    def _default_version_file(self, column):
        return (
            select(column)
            .where(ModelFile.version_id == self._default_version_id())
            .order_by(ModelFile.is_primary.desc(), ModelFile.id)
            .limit(1)
            .correlate(ModelV2)
            .scalar_subquery()
        )

    def _directory_filters(
        self,
        directory: str,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        model_type: str | None = None,
        base_model: str | None = None,
        show_nsfw: bool = True,
    ) -> list:
        """The WHERE clauses for one directory listing, shared by page and count."""
        clauses = [ModelV2.directory == directory]
        if not show_nsfw:
            clauses.append(ModelV2.nsfw.is_(False))
        if model_type:
            clauses.append(ModelV2.type == model_type)
        if search:
            like = like_contains(search)
            # The same fields the route used to join into one string: the model's
            # name, its creator, its description, its tags, and — the part that is
            # easy to miss — its versions' trained words and filenames. Trained
            # words are the *only* vocabulary a HuggingFace-sourced LoRA has, and
            # `ModelSelector.jsx` documents the backend search as covering
            # "name, display name, tags, trained words and description".
            clauses.append(
                or_(
                    ModelV2.name.ilike(like),
                    ModelV2.creator_username.ilike(like),
                    ModelV2.description.ilike(like),
                    ModelV2.id.in_(
                        select(ModelTag.model_id).where(ModelTag.tag.ilike(like))
                    ),
                    ModelV2.id.in_(
                        select(ModelVersion.model_id).where(
                            or_(
                                ModelVersion.description.ilike(like),
                                ModelVersion.trained_words.ilike(like),
                            )
                        )
                    ),
                    ModelV2.id.in_(
                        select(ModelVersion.model_id)
                        .join(ModelFile, ModelFile.version_id == ModelVersion.id)
                        .where(ModelFile.storage_filename.ilike(like))
                    ),
                )
            )
        for tag in tags or []:
            clauses.append(
                ModelV2.id.in_(
                    select(ModelTag.model_id).where(ModelTag.tag == tag)
                )
            )
        if base_model:
            # The route filtered on the *default* version's base model, so this
            # does too, with the same fallback it had for a model whose versions
            # carry no `is_default` flag at all: the flag is nullable and the
            # Python was `next(is_default, versions[0])`. Flat `in_` subqueries
            # rather than nested `exists`, because a correlated `exists` inside a
            # `model_versions` subquery that is itself correlated to `models_v2`
            # makes the correlation ambiguous to read and to resolve.
            has_default = ModelV2.id.in_(
                select(ModelVersion.model_id).where(ModelVersion.is_default.is_(True))
            )
            default_matches = ModelV2.id.in_(
                select(ModelVersion.model_id).where(
                    ModelVersion.is_default.is_(True),
                    ModelVersion.base_model == base_model,
                )
            )
            any_version_matches = ModelV2.id.in_(
                select(ModelVersion.model_id).where(
                    ModelVersion.base_model == base_model
                )
            )
            # For the unflagged fallback the SQL accepts *any* version's base
            # model where the Python used `versions[0]` specifically. There are no
            # such models on this deployment (`set_default_version` writes the
            # flag; measured 0 of 516 across every directory), and preferring a
            # match over silently hiding the model is the safer of the two
            # readings.
            clauses.append(or_(default_matches, and_(~has_default, any_version_matches)))
        return clauses

    # `name`/`size` resolve through `_default_version_file`, so they are built on
    # demand rather than stored in a module-level map next to the column sorts.
    _DIRECTORY_COLUMN_SORTS = {
        "date_desc": ModelV2.updated_at,
        "date_asc": ModelV2.updated_at,
        "rating_desc": ModelV2.stats_thumbs_up,
    }

    def _directory_order(self, sort: str | None, descending: bool):
        if sort is None:
            # Deterministic, and the same order `random[:seed]` shuffles over, so a
            # seeded shuffle keeps producing the page it produced before.
            return ModelV2.id.desc() if descending else ModelV2.id.asc()
        if sort in ("name_asc", "name_desc"):
            key = self._default_version_file(ModelFile.storage_filename)
            return key.desc() if sort.endswith("_desc") else key.asc()
        if sort == "size_desc":
            return self._default_version_file(ModelFile.size_kb).desc()
        column = self._DIRECTORY_COLUMN_SORTS.get(sort)
        if column is None:
            raise ValueError(f"Unsupported directory sort: {sort!r}")
        return column.desc() if descending else column.asc()

    def get_models_by_directory(
        self,
        directory: str,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        model_type: str | None = None,
        base_model: str | None = None,
        show_nsfw: bool = True,
        sort: str | None = None,
        descending: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ModelV2]:
        """Get models in a specific directory, filtered and paged in the database.

        Every argument is optional and defaults to today's behaviour, so the
        callers that want the whole directory (`/directory/{directory}`) are
        unaffected by the paging machinery they never pass.
        """
        stmt = select(ModelV2).where(
            *self._directory_filters(
                directory,
                search=search,
                tags=tags,
                model_type=model_type,
                base_model=base_model,
                show_nsfw=show_nsfw,
            )
        )
        stmt = stmt.order_by(self._directory_order(sort, descending))
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.exec(stmt).all())

    def get_models_by_ids(self, ids: list[int]) -> list[ModelV2]:
        """Models by id, for a caller that already chose the page itself.

        For the sorts the database cannot evaluate — `random[:seed]` shuffles the
        whole directory and then takes one page — the ids are decided outside the
        query, and this fetches exactly those rows.
        """
        if not ids:
            return []
        stmt = select(ModelV2).where(ModelV2.id.in_(ids))
        return list(self.session.exec(stmt).all())

    def get_model_ids_by_directory(
        self,
        directory: str,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        model_type: str | None = None,
        base_model: str | None = None,
        show_nsfw: bool = True,
    ) -> list[int]:
        """Just the ids, in id order — for a sort the database cannot express.

        `random[:seed]` shuffles the whole directory before slicing it, so it has
        to see every id even though it only hydrates one page. Selecting ids is
        cheap; selecting, hydrating and then discarding the models is what it
        used to do.
        """
        stmt = select(ModelV2.id).where(
            *self._directory_filters(
                directory,
                search=search,
                tags=tags,
                model_type=model_type,
                base_model=base_model,
                show_nsfw=show_nsfw,
            )
        ).order_by(ModelV2.id)
        return list(self.session.exec(stmt).all())

    def count_models_by_directory(
        self,
        directory: str,
        *,
        search: str | None = None,
        tags: list[str] | None = None,
        model_type: str | None = None,
        base_model: str | None = None,
        show_nsfw: bool = True,
    ) -> int:
        """How many models a directory listing matches, before paging.

        Shares `_directory_filters` with the page query, so `total` cannot
        describe a different set than `files`.
        """
        stmt = select(func.count()).select_from(ModelV2).where(
            *self._directory_filters(
                directory,
                search=search,
                tags=tags,
                model_type=model_type,
                base_model=base_model,
                show_nsfw=show_nsfw,
            )
        )
        return int(self.session.exec(stmt).one())

    def get_models_by_type(self, model_type: str) -> list[ModelV2]:
        """Get models of a specific type."""
        stmt = select(ModelV2).where(ModelV2.type == model_type)
        return list(self.session.exec(stmt).all())
    
    def delete_model(self, model_id: int) -> bool:
        """Delete a model and all related data (cascades)."""
        from sqlmodel import delete
        model = self.get_model(model_id)
        if not model:
            return False
        
        # Manual cascade since SQLite doesn't always respect FK cascades
        versions = self.get_versions_for_model(model_id)
        version_ids = [v.id for v in versions]
        
        if version_ids:
            # Get all file IDs across all versions
            stmt = select(ModelFile.id).where(ModelFile.version_id.in_(version_ids))
            file_ids = list(self.session.exec(stmt).all())
            
            if file_ids:
                # Bulk delete provider statuses
                self.session.exec(delete(ProviderVersionStatus).where(ProviderVersionStatus.file_id.in_(file_ids)))
                # Bulk delete files
                self.session.exec(delete(ModelFile).where(ModelFile.id.in_(file_ids)))
            
            # Bulk delete images
            self.session.exec(delete(ModelImage).where(ModelImage.version_id.in_(version_ids)))
            
            # Bulk delete versions
            self.session.exec(delete(ModelVersion).where(ModelVersion.id.in_(version_ids)))
        
        # Bulk delete tags
        self.session.exec(delete(ModelTag).where(ModelTag.model_id == model_id))
        
        self.session.delete(model)
        self.session.commit()
        return True
    
    # =========================================================================
    # VERSION OPERATIONS
    # =========================================================================
    
    def get_versions_for_model(self, model_id: int) -> list[ModelVersion]:
        """Get all versions for a model."""
        stmt = select(ModelVersion).where(ModelVersion.model_id == model_id)
        return list(self.session.exec(stmt).all())
    
    def get_default_version(self, model_id: int) -> ModelVersion | None:
        """Get the default version for a model."""
        stmt = select(ModelVersion).where(
            and_(ModelVersion.model_id == model_id, ModelVersion.is_default == True)
        )
        return self.session.exec(stmt).first()
    
    def get_version_by_civitai_id(self, civitai_version_id: int) -> ModelVersion | None:
        """Get a version by CivitAI version ID."""
        stmt = select(ModelVersion).where(
            ModelVersion.civitai_version_id == civitai_version_id
        )
        return self.session.exec(stmt).first()
    
    def set_default_version(self, model_id: int, version_id: int) -> bool:
        """Set a version as the default for a model."""
        target = self.session.get(ModelVersion, version_id)
        if not target or str(target.model_id) != str(model_id):
            return False
        versions = self.get_versions_for_model(model_id)
        for v in versions:
            v.is_default = (v.id == version_id)
        self.session.commit()
        return True
    
    def toggle_version_enabled(self, version_id: int) -> ModelVersion | None:
        """Toggle whether a version is enabled."""
        version = self.session.get(ModelVersion, version_id)
        if version:
            version.is_enabled = not version.is_enabled
            self.session.commit()
            self.session.refresh(version)
        return version
    
    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    
    def get_files_for_version(self, version_id: int) -> list[ModelFile]:
        """Get all files for a version."""
        stmt = select(ModelFile).where(ModelFile.version_id == version_id)
        return list(self.session.exec(stmt).all())
    
    def get_files_for_model(self, model_id: int) -> list[ModelFile]:
        """Get all files for all versions of a model in a single query."""
        stmt = select(ModelFile).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).where(ModelVersion.model_id == model_id)
        return list(self.session.exec(stmt).all())
    
    def get_primary_file_for_version(self, version_id: int) -> ModelFile | None:
        """Get the primary file for a version."""
        stmt = select(ModelFile).where(
            and_(ModelFile.version_id == version_id, ModelFile.is_primary == True)
        )
        return self.session.exec(stmt).first()
    
    def get_file_by_storage_path(self, directory: str, filename: str) -> ModelFile | None:
        """Get a file by its storage path components."""
        norm_nfc = unicodedata.normalize("NFC", filename)
        norm_nfd = unicodedata.normalize("NFD", filename)
        candidates = list(dict.fromkeys([filename, norm_nfc, norm_nfd]))
        stmt = select(ModelFile).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        ).where(
            ModelFile.storage_filename.in_(candidates),
            ModelV2.directory == directory
        )
        return self.session.exec(stmt).first()
    
    def add_tombstone(self, storage_path: str):
        existing = self.session.exec(select(DeletedFileTombstone).where(DeletedFileTombstone.storage_path == storage_path)).first()
        if not existing:
            self.session.add(DeletedFileTombstone(storage_path=storage_path))
            self.session.commit()
            
    def is_tombstoned(self, storage_path: str) -> bool:
        return self.session.exec(select(DeletedFileTombstone).where(DeletedFileTombstone.storage_path == storage_path)).first() is not None
    
    def create_system_dependency(
        self,
        name: str,
        model_type: str,
        directory: str,
        filename: str,
        download_url: str,
        size_mb: float = 0,
        description: str = "",
        base_model: str = ""
    ) -> ModelV2 | None:
        """
        Create a system dependency model (CLIP, VAE for Flux/AuraFlow).
        
        These are auto-downloaded dependencies with source='system' to 
        distinguish them from user-added models.
        
        Args:
            name: Display name (e.g., "T5-XXL Text Encoder")
            model_type: Type (e.g., "CLIP", "VAE")
            directory: Storage directory (e.g., "clip", "vae")
            filename: Storage filename
            download_url: URL to download from
            size_mb: Size in MB
            description: Description text
            base_model: Base model compatibility (e.g., "Flux.1 D")
            
        Returns:
            Created ModelV2 or None if already exists
        """
        # Check if this dependency already exists by looking for the file
        existing_file = self.get_file_by_storage_path(directory, filename)
        if existing_file:
            # Check if URL needs update (e.g. converting from gated to public mirror)
            if existing_file.download_url != download_url:
                logger.info("dependency_url_updated", filename=filename, old_url=existing_file.download_url, new_url=download_url)
                existing_file.download_url = download_url
                self.session.add(existing_file)
                self.session.commit()
                self.session.refresh(existing_file)
            
            # Already exists
            return None
        
        # Create the model
        model = ModelV2(
            name=name,
            type=model_type,
            directory=directory,
            description=description,
            source="system",  # Mark as system dependency
            source_url=download_url,
            nsfw=False,
            nsfw_level=1,
        )
        self.session.add(model)
        self.session.flush()  # Get the ID
        
        # Create a single version
        version = ModelVersion(
            model_id=model.id,
            name="v1.0",
            base_model=base_model,
            base_model_type="Standard",
            description=description,
            is_enabled=True,
            is_default=True,
        )
        self.session.add(version)
        self.session.flush()
        
        # Create the file entry
        file = ModelFile(
            version_id=version.id,
            original_filename=filename,
            storage_filename=filename,  # Use same name for system files
            size_kb=size_mb * 1024,
            format="SafeTensor",
            download_url=download_url,
            is_primary=True,
            file_type="Model",
        )
        self.session.add(file)
        
        self.session.commit()
        logger.info("system_dependency_created", name=name, directory=directory, filename=filename)
        
        return model

    
    # =========================================================================
    # PROVIDER STATUS OPERATIONS
    # =========================================================================
    
    def get_pending_downloads(self, provider_id: str) -> list[dict[str, Any]]:
        """
        Get files pending download for a provider.
        Returns file info with version and model context.
        """
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        ).outerjoin(
            ProviderVersionStatus,
            and_(
                ProviderVersionStatus.file_id == ModelFile.id,
                self._provider_match_clause(provider_id)
            )
        ).where(
            ModelVersion.is_enabled == True,
            ModelFile.download_url != None,
            ModelFile.download_url != "",
            or_(
                ProviderVersionStatus.id == None,
                ProviderVersionStatus.status != "ready"
            )
        )
        
        results = []
        for file, version, model in self.session.exec(stmt).all():
            results.append({
                "file_id": file.id,
                "version_id": version.id,
                "model_id": model.id,
                "model_name": model.name,
                "version_name": version.name,
                "storage_filename": file.storage_filename,
                "storage_path": f"models/{model.directory}/{file.storage_filename}",
                "download_url": file.download_url,
                "size_kb": file.size_kb,
                "hash_sha256": file.hash_sha256
            })
        return results
    
    def get_provider_status(
        self, 
        file_id: str, 
        provider_id: str
    ) -> ProviderVersionStatus | None:
        """Get provider status for a specific file."""
        stmt = select(ProviderVersionStatus).where(
            and_(
                ProviderVersionStatus.file_id == file_id,
                self._provider_match_clause(provider_id)
            )
        )
        return self.session.exec(stmt).first()

    def get_provider_statuses_for_files(
        self,
        file_ids: list[str],
        provider_id: str,
    ) -> dict[int, ProviderVersionStatus]:
        """Get provider statuses for many files in one query."""
        if not file_ids:
            return {}

        stmt = select(ProviderVersionStatus).where(
            and_(
                ProviderVersionStatus.file_id.in_(file_ids),
                self._provider_match_clause(provider_id),
            )
        )
        statuses = self.session.exec(stmt).all()
        return {status.file_id: status for status in statuses}
    
    def update_provider_status(
        self,
        file_id: str,
        provider_id: str,
        status: str,
        storage_path: str | None = None,
        size_bytes: int | None = None,
        error_message: str | None = None,
        force_create: bool = False,
    ) -> ProviderVersionStatus | None:
        """Update or create provider status for a file."""
        existing = self.get_provider_status(file_id, provider_id)
        
        if existing:
            if not existing.provider_id:
                existing.provider_id = provider_id
            
            existing.status = status
            if status == "downloading":
                existing.queued_at = datetime.now(timezone.utc)
            if storage_path:
                existing.storage_path = storage_path
            if size_bytes:
                existing.size_bytes = size_bytes
            if error_message is not None:
                existing.error_message = error_message
            elif status != "failed":
                existing.error_message = None
            if status == "ready":
                existing.downloaded_at = datetime.now(timezone.utc)
            elif status == "failed":
                existing.retry_count += 1
            self.session.commit()
            self.session.refresh(existing)
            return existing
        else:
            # If the status is pending and we didn't explicitly force_create it, 
            # do NOT create a new record. This prevents workers from marking ALL missing files as pending.
            if status == "pending" and not force_create:
                return None
            
            new_status = ProviderVersionStatus(
                file_id=file_id,
                provider_id=provider_id,
                status=status,
                storage_path=storage_path,
                size_bytes=size_bytes,
                error_message=error_message,
                queued_at=datetime.now(timezone.utc),
                downloaded_at=datetime.now(timezone.utc) if status == "ready" else None,
                retry_count=0
            )
            self.session.add(new_status)
            self.session.commit()
            self.session.refresh(new_status)
            return new_status
    
    def get_provider_statuses_for_model(
        self, 
        model_id: int
    ) -> dict[str, dict[str, Any]]:
        """
        Get all provider statuses for a model's files.
        Returns dict keyed by provider_id.
        Provider-level status is aggregated from all file statuses.
        """
        stmt = select(ProviderVersionStatus, ModelFile, ModelVersion).join(
            ModelFile, ProviderVersionStatus.file_id == ModelFile.id
        ).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).where(ModelVersion.model_id == model_id)
        
        result: dict[str, dict[str, Any]] = {}
        for status, file, version in self.session.exec(stmt).all():
            provider_key = self._get_provider_key(status)
            if not provider_key:
                continue

            if provider_key not in result:
                result[provider_key] = {
                    "status": status.status,
                    "files": [],
                    "total_size": 0,
                    "_file_statuses": [],
                }
            result[provider_key]["files"].append({
                "file_id": file.id,
                "filename": file.storage_filename,
                "status": status.status,
                "size_bytes": status.size_bytes
            })
            result[provider_key]["_file_statuses"].append(status.status)
            if status.size_bytes:
                result[provider_key]["total_size"] += status.size_bytes
        
        for provider_data in result.values():
            provider_data["status"] = self._aggregate_provider_status(provider_data.pop("_file_statuses"))
        
        return result
    
    @staticmethod
    def _aggregate_provider_status(file_statuses: list[str]) -> str:
        """Aggregate per-file statuses into a single provider-level status."""
        if not file_statuses:
            return "pending"
        ready_count = sum(1 for s in file_statuses if s == "ready")
        if ready_count == len(file_statuses):
            return "ready"
        if ready_count == 0:
            first = file_statuses[0]
            return first if first in ("downloading", "failed") else "pending"
        return "partial"
    
    def delete_all_statuses_for_provider(self, provider_id: str, *, commit: bool = True) -> int:
        """
        Delete all ProviderVersionStatus records for a given provider.
        Used when deleting a provider to cascade cleanup.

        `commit=False` lets a caller that is sweeping several providers pay one
        commit for the whole sweep instead of one each.

        Returns:
            Number of records deleted
        """
        stmt = select(ProviderVersionStatus).where(
            self._provider_match_clause(provider_id)
        )
        statuses = list(self.session.exec(stmt).all())
        count = len(statuses)

        for status in statuses:
            self.session.delete(status)

        if count > 0 and commit:
            self.session.commit()

        return count
    
    def cleanup_orphaned_provider_statuses(self, active_provider_names: list[str]) -> dict[str, int]:
        """
        Delete ProviderVersionStatus records for providers that no longer exist.
        
        Args:
            active_provider_names: List of provider names/IDs that currently exist
            
        Returns:
            Dict with 'deleted_count' and 'orphaned_providers' list
        """
        from sqlalchemy import distinct
        
        # Get all unique provider identifiers in ProviderVersionStatus.
        stmt = select(distinct(ProviderVersionStatus.provider_id))
        all_provider_names = {
            provider_key
            for provider_key in self.session.exec(stmt).all()
            if provider_key
        }
        
        # Find orphaned provider names (in status table but not in active providers)
        active_set = set(active_provider_names)
        orphaned_providers = list(all_provider_names - active_set)
        
        total_deleted = 0
        for provider_id in orphaned_providers:
            count = self.delete_all_statuses_for_provider(provider_id, commit=False)
            total_deleted += count
        # One commit for the whole sweep. The per-provider commit meant N
        # round-trips and N fsyncs for a single logical operation, and left the
        # caller unable to reason about it as atomic.
        if total_deleted > 0:
            self.session.commit()

        return {
            "deleted_count": total_deleted,
            "orphaned_providers": orphaned_providers
        }

    def reset_stale_downloading_statuses(
        self,
        *,
        stale_before: datetime,
        provider_names: list[str] | None = None,
    ) -> int:
        """
        Reset stale downloading statuses back to pending.

        A status is considered stale when it is still marked as downloading
        and its queued_at timestamp is older than ``stale_before``.
        """
        if provider_names is not None and len(provider_names) == 0:
            return 0

        stmt = select(ProviderVersionStatus).where(
            ProviderVersionStatus.status == "downloading",
            ProviderVersionStatus.queued_at < stale_before,
        )

        if provider_names is not None:
            stmt = stmt.where(self._provider_match_clause_many(provider_names))

        stale_statuses = list(self.session.exec(stmt).all())
        if not stale_statuses:
            return 0

        reset_at = datetime.now(timezone.utc)
        for status in stale_statuses:
            status.status = "pending"
            status.queued_at = reset_at
            status.error_message = "Reset stale downloading status during startup cleanup"
            self.session.add(status)

        self.session.commit()
        return len(stale_statuses)
    
    # =========================================================================
    # IMAGE OPERATIONS
    # =========================================================================
    
    def get_images_for_version(self, version_id: int) -> list[ModelImage]:
        """Get all images for a version."""
        stmt = select(ModelImage).where(
            ModelImage.version_id == version_id
        ).order_by(ModelImage.sort_order)
        return list(self.session.exec(stmt).all())
    
    # =========================================================================
    # TAG OPERATIONS
    # =========================================================================
    
    def get_tags_for_model(self, model_id: int) -> list[str]:
        """Get all tags for a model."""
        stmt = select(ModelTag.tag).where(ModelTag.model_id == model_id)
        return list(self.session.exec(stmt).all())
    
    def search_by_tag(self, tag: str) -> list[ModelV2]:
        """Search models by tag."""
        stmt = select(ModelV2).join(
            ModelTag, ModelV2.id == ModelTag.model_id
        ).where(ModelTag.tag.ilike(like_contains(tag), escape=LIKE_ESCAPE_CHAR))
        return list(self.session.exec(stmt).all())
    
    # =========================================================================
    # SERIALIZATION
    # =========================================================================
    
    # =========================================================================
    # BULK LOADING (eliminates N+1 queries)
    # =========================================================================

    def _bulk_load_tags(self, model_ids: list[int]) -> dict[int, list[str]]:
        """Load all tags for multiple models in one query."""
        if not model_ids:
            return {}
        stmt = select(ModelTag).where(ModelTag.model_id.in_(model_ids))
        result: dict[int, list[str]] = {mid: [] for mid in model_ids}
        for tag in self.session.exec(stmt).all():
            result.setdefault(tag.model_id, []).append(tag.tag)
        return result

    def _bulk_load_versions(self, model_ids: list[int]) -> dict[int, list[ModelVersion]]:
        """Load all versions for multiple models in one query."""
        if not model_ids:
            return {}
        stmt = select(ModelVersion).where(ModelVersion.model_id.in_(model_ids))
        result: dict[int, list[ModelVersion]] = {mid: [] for mid in model_ids}
        for version in self.session.exec(stmt).all():
            result.setdefault(version.model_id, []).append(version)
        return result

    def _bulk_load_files(self, version_ids: list[int]) -> dict[int, list[ModelFile]]:
        """Load all files for multiple versions in one query."""
        if not version_ids:
            return {}
        stmt = select(ModelFile).where(ModelFile.version_id.in_(version_ids))
        from collections import defaultdict
        result: dict[int, list[ModelFile]] = defaultdict(list)
        for file in self.session.exec(stmt).all():
            result[file.version_id].append(file)
        return dict(result)

    def _bulk_load_images(self, version_ids: list[int]) -> dict[int, list[ModelImage]]:
        """Load all images for multiple versions in one query, ordered by sort_order."""
        if not version_ids:
            return {}
        stmt = select(ModelImage).where(ModelImage.version_id.in_(version_ids)).order_by(ModelImage.sort_order)
        from collections import defaultdict
        result: dict[int, list[ModelImage]] = defaultdict(list)
        for image in self.session.exec(stmt).all():
            result[image.version_id].append(image)
        return dict(result)

    def _bulk_load_provider_statuses_by_model(
        self, model_ids: list[int]
    ) -> dict[int, dict[str, dict[str, Any]]]:
        """Load all provider statuses for multiple models in one query."""
        if not model_ids:
            return {}
        stmt = select(ProviderVersionStatus, ModelFile, ModelVersion).join(
            ModelFile, ProviderVersionStatus.file_id == ModelFile.id
        ).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).where(ModelVersion.model_id.in_(model_ids))

        result: dict[int, dict[str, dict[str, Any]]] = {}
        for status, file, version in self.session.exec(stmt).all():
            model_id = version.model_id
            if model_id not in result:
                result[model_id] = {}
            provider_key = self._get_provider_key(status)
            if not provider_key:
                continue
            if provider_key not in result[model_id]:
                result[model_id][provider_key] = {
                    "status": status.status,
                    "files": [],
                    "total_size": 0,
                    "_file_statuses": [],
                }
            result[model_id][provider_key]["files"].append({
                "file_id": file.id,
                "filename": file.storage_filename,
                "status": status.status,
                "size_bytes": status.size_bytes,
            })
            result[model_id][provider_key]["_file_statuses"].append(status.status)
            if status.size_bytes:
                result[model_id][provider_key]["total_size"] += status.size_bytes

        for model_data in result.values():
            for provider_data in model_data.values():
                provider_data["status"] = self._aggregate_provider_status(provider_data.pop("_file_statuses"))
        
        return result

    def model_to_dict(
        self,
        model: ModelV2,
        include_versions: bool = True,
        *,
        _tags_map: dict[int, list[str]] | None = None,
        _versions_map: dict[int, list[ModelVersion]] | None = None,
        _files_map: dict[int, list[ModelFile]] | None = None,
        _images_map: dict[int, list[ModelImage]] | None = None,
        _statuses_map: dict[int, dict[str, dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Convert model to dictionary for API response.
        
        Accepts optional pre-loaded bulk data to avoid N+1 queries.
        """
        mid = model.id
        tags = _tags_map.get(mid, []) if _tags_map is not None else self.get_tags_for_model(mid)
        versions = _versions_map.get(mid, []) if _versions_map is not None else self.get_versions_for_model(mid)

        result = {
            "id": mid,
            "civitai_model_id": model.civitai_model_id,
            "name": model.name,
            "type": model.type,
            "directory": model.directory,
            "description": model.description,
            "nsfw": model.nsfw,
            "nsfw_level": model.nsfw_level,
            "creator": {
                "username": model.creator_username,
                "image": model.creator_image
            },
            "stats": {
                "downloads": model.stats_downloads,
                "thumbsUp": model.stats_thumbs_up,
                "thumbsDown": model.stats_thumbs_down,
                "comments": model.stats_comments
            },
            "source": model.source,
            "source_url": model.source_url,
            "tags": tags,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None
        }

        if include_versions:
            result["versions"] = [
                self._version_to_dict(v, _files_map=_files_map, _images_map=_images_map)
                for v in versions
            ]

        # Primary image: first image of the default version
        primary_image = None
        default_version = next((v for v in versions if v.is_default), versions[0] if versions else None)
        if default_version:
            version_images = (
                _images_map.get(default_version.id, [])
                if _images_map is not None
                else self.get_images_for_version(default_version.id)
            )
            if version_images:
                primary_image = version_images[0]
        if primary_image:
            result["preview_image"] = {
                "url": primary_image.url,
                "width": primary_image.width,
                "height": primary_image.height,
                "blurhash": primary_image.blurhash
            }

        # Provider statuses
        if _statuses_map is not None:
            result["provider_statuses"] = _statuses_map.get(mid, {})
        else:
            result["provider_statuses"] = self.get_provider_statuses_for_model(mid)

        return result

    def models_to_dict(
        self,
        models: list[ModelV2],
        include_versions: bool = True,
    ) -> list[dict[str, Any]]:
        """Convert multiple models to dicts with bulk-loaded related data.
        
        Eliminates the N+1 query problem by loading all tags, versions,
        files, images, and provider statuses in 5 total queries regardless
        of how many models are passed in.
        """
        if not models:
            return []

        model_ids = [m.id for m in models]
        tags_map = self._bulk_load_tags(model_ids)
        versions_map = self._bulk_load_versions(model_ids)

        all_version_ids = [v.id for versions in versions_map.values() for v in versions]
        files_map = self._bulk_load_files(all_version_ids)
        images_map = self._bulk_load_images(all_version_ids)
        statuses_map = self._bulk_load_provider_statuses_by_model(model_ids)

        return [
            self.model_to_dict(
                m,
                include_versions=include_versions,
                _tags_map=tags_map,
                _versions_map=versions_map,
                _files_map=files_map,
                _images_map=images_map,
                _statuses_map=statuses_map,
            )
            for m in models
        ]

    def _version_to_dict(
        self,
        version: ModelVersion,
        *,
        _files_map: dict[int, list[ModelFile]] | None = None,
        _images_map: dict[int, list[ModelImage]] | None = None,
    ) -> dict[str, Any]:
        """Convert version to dictionary, accepting optional pre-loaded data."""
        vid = version.id
        files = _files_map.get(vid, []) if _files_map is not None else self.get_files_for_version(vid)
        images = _images_map.get(vid, []) if _images_map is not None else self.get_images_for_version(vid)

        primary_file = next((f for f in files if f.is_primary), files[0] if files else None)

        return {
            "id": vid,
            "civitai_version_id": version.civitai_version_id,
            "name": version.name,
            "base_model": version.base_model,
            "base_model_type": version.base_model_type,
            "is_unet_only": is_unet_only_model(version.base_model),
            "description": version.description,
            "is_enabled": version.is_enabled,
            "is_default": version.is_default,
            "trained_words": json.loads(version.trained_words) if version.trained_words else [],
            "file": {
                "id": primary_file.id,
                "filename": primary_file.storage_filename,
                "size_kb": primary_file.size_kb,
                "hash": primary_file.hash_sha256
            } if primary_file else None,
            "images": [
                {
                    "url": img.url,
                    "width": img.width,
                    "height": img.height,
                    "blurhash": img.blurhash,
                    "type": img.type,
                    "nsfw_level": img.nsfw_level
                }
                for img in images
            ],
            "created_at": version.created_at.isoformat() if version.created_at else None
        }
    
    def get_grouped_by_directory(self) -> dict[str, list[dict[str, Any]]]:
        """Get all models grouped by directory (bulk-loaded, no N+1)."""
        models = self.get_all_models()
        dicts = self.models_to_dict(models, include_versions=False)
        result: dict[str, list[dict[str, Any]]] = {}
        for d in dicts:
            directory = d.get("directory", "other")
            if directory not in result:
                result[directory] = []
            result[directory].append(d)
        return result
    
    def migrate_unet_only_models(self) -> dict[str, Any]:
        """
        Migration function: Find UNET-only models incorrectly stored in 'checkpoints'
        and move them to 'unet' directory.
        
        This fixes models added before the UNET routing was implemented.
        
        Returns:
            Dict with migration results: {'migrated': [...], 'count': N}
        """
        from core.entities import is_unet_only_model
        
        # Find all Checkpoint type models in checkpoints directory
        stmt = select(ModelV2).where(
            and_(
                ModelV2.type == "Checkpoint",
                ModelV2.directory == "checkpoints"
            )
        )
        models = list(self.session.exec(stmt).all())
        
        migrated = []
        if not models:
            return {"migrated": migrated, "count": 0}
            
        model_ids = [m.id for m in models]
        versions_stmt = select(ModelVersion).where(ModelVersion.model_id.in_(model_ids))
        all_versions = self.session.exec(versions_stmt).all()
        versions_by_model = {}
        for v in all_versions:
            versions_by_model.setdefault(v.model_id, []).append(v)
        
        for model in models:
            # Get the default version to check base_model
            versions = versions_by_model.get(model.id, [])
            if not versions:
                continue
            
            # Check if any version is UNET-only
            for version in versions:
                if is_unet_only_model(version.base_model):
                    # This model should be in 'unet' directory
                    old_dir = model.directory
                    model.directory = "unet"
                    self.session.add(model)
                    
                    migrated.append({
                        "id": model.id,
                        "name": model.name,
                        "base_model": version.base_model,
                        "old_directory": old_dir,
                        "new_directory": "unet"
                    })
                    logger.info("migration_model_moved", model_name=model.name, old_directory=old_dir, new_directory="unet", base_model=version.base_model)
                    break  # Only need to find one UNET-only version
        
        if migrated:
            self.session.commit()
        
        logger.info("migration_complete", migrated_count=len(migrated))
        return {"migrated": migrated, "count": len(migrated)}

    def garbage_collect_auto_discovered(self) -> int:
        stmt = select(ModelV2).where(ModelV2.description.like("%Auto-discovered%"))
        models = self.session.exec(stmt).all()
        if not models:
            return 0
            
        model_ids = [m.id for m in models]
        statuses_map = self._bulk_load_provider_statuses_by_model(model_ids)
        
        deleted = 0
        for m in models:
            has_active = False
            provider_data = statuses_map.get(m.id, {})
            for p_key, p_info in provider_data.items():
                for f in p_info.get("files", []):
                    if f.get("status") in ["ready", "downloading", "pending"]:
                        has_active = True
                        break
                if has_active:
                    break
            
            if not has_active:
                self.delete_model(m.id)
                deleted += 1
        return deleted

    def cleanup_orphaned_models(self) -> int:
        """Remove models whose files have NO provider status records at all.
        
        This is a conservative cleanup: only delete models where every file has
        literally zero ProviderVersionStatus records. Models with any status
        (including failed) are preserved — they may be in progress or retriable.
        
        Models created in the last 24 hours are always skipped to avoid race
        conditions with download initialization.
        """
        stmt = select(ModelV2)
        models = self.session.exec(stmt).all()
        if not models:
            return 0
            
        model_ids = [m.id for m in models]
        statuses_map = self._bulk_load_provider_statuses_by_model(model_ids)
        
        deleted = 0
        from datetime import datetime, timedelta, timezone
        recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        for m in models:
            # Skip models created recently to avoid race conditions with initial download.
            # SQLite may store datetimes as naive, so normalize before comparing.
            if m.created_at:
                created = m.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created > recent_threshold:
                    continue
                
            has_viable = False
            if statuses_map.get(m.id):
                has_viable = True
                
            if not has_viable:
                self.delete_model(m.id)
                deleted += 1
        return deleted



    def get_orphan_models(self) -> list[tuple]:
        from sqlmodel import func
        stmt = select(ModelV2, func.count(ModelVersion.id).label("version_count")) \
            .outerjoin(ModelVersion, ModelVersion.model_id == ModelV2.id) \
            .group_by(ModelV2.id) \
            .having(func.count(ModelVersion.id) == 0)
        return self.session.exec(stmt).all()

    def get_models_for_resync(self, include_relations: bool = True) -> list[ModelV2]:
        stmt = select(ModelV2) \
            .where(ModelV2.civitai_model_id != None) \
            .where(ModelV2.description.not_like("%Auto-discovered%"))
            
        if include_relations:
            stmt = stmt.options(selectinload(ModelV2.versions).selectinload(ModelVersion.files))
            
        return self.session.exec(stmt).all()


    def get_existing_filenames(self, filenames: list[str]) -> list[str]:
        stmt = select(ModelFile.storage_filename).where(ModelFile.storage_filename.in_(filenames))
        return [row for row in self.session.exec(stmt).all()]

    def get_models_needing_population(self) -> list[ModelV2]:
        stmt = select(ModelV2).where(
            ModelV2.description.like("%Auto-discovered%"),
            ModelV2.civitai_model_id.is_(None)
        )
        return self.session.exec(stmt).all()

    def get_auto_discovered_models(self) -> list[ModelV2]:
        stmt = select(ModelV2).where(ModelV2.description.like("%Auto-discovered%"))
        return self.session.exec(stmt).all()

    def _iter_file_model_paths(self, paths: list[str] | None = None):
        """Yield (file, version, model) tuples for files joined with their model info."""
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        )
        if paths:
            filenames = []
            for p in paths:
                fname = p.split('/')[-1]
                filenames.extend([fname, unicodedata.normalize("NFC", fname), unicodedata.normalize("NFD", fname)])
            filenames = list(dict.fromkeys(filenames))
            stmt = stmt.where(ModelFile.storage_filename.in_(filenames))

        norm_paths = {unicodedata.normalize("NFC", p): p for p in paths} if paths else None

        for file, version, model in self.session.exec(stmt).all():
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            norm_storage_path = unicodedata.normalize("NFC", storage_path)
            if norm_paths is not None and norm_storage_path not in norm_paths and storage_path not in norm_paths:
                continue
            yield file, version, model, storage_path

    def get_all_storage_paths(self) -> list[str]:
        return [unicodedata.normalize("NFC", p) for _, _, _, p in self._iter_file_model_paths()]

    def get_models_by_civitai_ids(self, civitai_ids: list[int]) -> list[ModelV2]:
        stmt = select(ModelV2).where(ModelV2.civitai_model_id.in_(civitai_ids))
        return self.session.exec(stmt).all()

    def get_versions_for_models(self, model_ids: list[int]) -> list[ModelVersion]:
        stmt = select(ModelVersion).where(ModelVersion.model_id.in_(model_ids))
        return self.session.exec(stmt).all()
        
    def get_file_ids_by_storage_paths(self, paths: list[str]) -> dict[str, int]:
        result = {}
        for file, _, _, path in self._iter_file_model_paths(paths):
            result[path] = file.id
            result[unicodedata.normalize("NFC", path)] = file.id
            result[unicodedata.normalize("NFD", path)] = file.id
        return result
