

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlmodel import Session, delete, select

from api.deps import (
    get_model_service_v2,
    get_session,
    get_session_context,
)
from api.routes.websocket import broadcast_to_all
from core.exceptions import ComfyError, NotFoundError, ValidationError
from infrastructure.http_client import get_http_client
from infrastructure.logging import model_logger

from .schemas import *  # noqa: F401, F403

logger = model_logger()

router = APIRouter()

# Tag provenance. CivitAI owns the rows it scraped and replaces them wholesale
# on resync; `user` rows are hand-typed and must survive that. See
# core.entities.ModelTag.
MODEL_TAG_SOURCE_CIVITAI = "civitai"
MODEL_TAG_SOURCE_USER = "user"

# Long enough for "pose: kneeling hands up, 4h, hires, character-loRA" and short
# enough that the whole table stays a reasonable tag list in the UI.
MAX_TAG_LENGTH = 64


def _normalize_user_tag(raw_tag: str) -> str:
    """Trim and length-bound a user-typed tag, or raise."""
    tag = " ".join((raw_tag or "").split())
    if not tag:
        raise ValidationError("Tag must not be empty")
    if len(tag) > MAX_TAG_LENGTH:
        raise ValidationError(f"Tag must be {MAX_TAG_LENGTH} characters or fewer")
    return tag


def add_user_model_tag(session: Session, model_id: str, raw_tag: str) -> dict:
    """Attach a `source='user'` tag to a model.

    Idempotent: re-adding an existing tag returns it unchanged rather than
    tripping `uq_model_tag`. A tag CivitAI also reports is kept as the single
    existing row instead of being duplicated, matching the one-row-per
    (model_id, tag) constraint.
    """
    from core.entities import ModelTag, ModelV2

    if not session.get(ModelV2, model_id):
        raise NotFoundError("Model", f"Model '{model_id}' not found")

    tag = _normalize_user_tag(raw_tag)

    existing = session.exec(
        select(ModelTag).where(ModelTag.model_id == model_id, ModelTag.tag == tag)
    ).first()
    if existing:
        return {"tag": existing.tag, "source": existing.source, "created": False}

    session.add(ModelTag(model_id=model_id, tag=tag, source=MODEL_TAG_SOURCE_USER))
    session.commit()
    return {"tag": tag, "source": MODEL_TAG_SOURCE_USER, "created": True}


def remove_user_model_tag(session: Session, model_id: str, raw_tag: str) -> bool:
    """Remove a `source='user'` tag. Returns True if a row was deleted.

    Refuses to touch a CivitAI-owned row: a user must not be able to strip a
    scraped tag that the next resync would put straight back.
    """
    from core.entities import ModelTag, ModelV2

    if not session.get(ModelV2, model_id):
        raise NotFoundError("Model", f"Model '{model_id}' not found")

    tag = _normalize_user_tag(raw_tag)
    row = session.exec(
        select(ModelTag).where(
            ModelTag.model_id == model_id,
            ModelTag.tag == tag,
            ModelTag.source == MODEL_TAG_SOURCE_USER,
        )
    ).first()
    if not row:
        return False

    session.delete(row)
    session.commit()
    return True


def list_model_tags(session: Session, model_id: str) -> list[dict]:
    """All tags on a model with their provenance, for the UI to group by."""
    from core.entities import ModelTag, ModelV2

    if not session.get(ModelV2, model_id):
        raise NotFoundError("Model", f"Model '{model_id}' not found")

    rows = session.exec(
        select(ModelTag).where(ModelTag.model_id == model_id).order_by(ModelTag.tag)
    ).all()
    return [{"tag": r.tag, "source": r.source} for r in rows]


def _apply_civitai_metadata(model, civitai_data: dict, session) -> None:
    """
    Apply CivitAI API response data to a model entity and its related tags/versions.
    Shared by single-model resync and background resync.
    """
    from core.entities import ModelTag

    stats = civitai_data.get("stats") or {}
    creator = civitai_data.get("creator") or {}

    model.name = civitai_data.get("name") or model.name
    model.description = civitai_data.get("description", model.description)
    model.nsfw = civitai_data.get("nsfw", model.nsfw)

    new_nsfw_level = civitai_data.get("nsfwLevel")
    if new_nsfw_level is not None:
        model.nsfw_level = new_nsfw_level

    model.creator_username = creator.get("username")
    model.creator_image = creator.get("image")
    model.stats_downloads = stats.get("downloadCount") or 0
    model.stats_thumbs_up = stats.get("thumbsUpCount") or 0
    model.stats_thumbs_down = stats.get("thumbsDownCount") or 0
    model.stats_comments = stats.get("commentCount") or 0

    # Update tags - delete ONLY the CivitAI-owned rows. The previous blanket
    # delete by model_id destroyed every user-typed tag on every resync, and
    # there was no writer path to put one back.
    session.exec(
        delete(ModelTag).where(
            ModelTag.model_id == model.id,
            ModelTag.source == MODEL_TAG_SOURCE_CIVITAI,
        )
    )
    # Re-read rather than trusting the delete: a surviving user row with the
    # same text would violate uq_model_tag on insert, and is deliberately
    # skipped — one row per (model_id, tag), owned by whoever got there first.
    known = set(session.exec(select(ModelTag.tag).where(ModelTag.model_id == model.id)).all())
    for tag in civitai_data.get("tags", []):
        name = " ".join((tag or "").split()) if isinstance(tag, str) else ""
        if not name or name in known:
            continue
        session.add(ModelTag(model_id=model.id, tag=name, source=MODEL_TAG_SOURCE_CIVITAI))
        known.add(name)

    # Update file sizes from versions
    civitai_versions = civitai_data.get("modelVersions", [])
    if civitai_versions:
        local_versions = model.versions
        for lv in local_versions:
            cv = next((v for v in civitai_versions if v.get("id") == lv.civitai_version_id), None)
            if not cv:
                cv = next((v for v in civitai_versions if v.get("name", "").lower() == lv.name.lower()), None)
            if cv:
                civitai_files = cv.get("files", [])
                if civitai_files:
                    primary_civitai = next((f for f in civitai_files if f.get("primary")), civitai_files[0])
                    civitai_size_kb = primary_civitai.get("sizeKB")
                    if civitai_size_kb is not None:
                        local_files = lv.files
                        for lf in local_files:
                            if not lf.size_kb or lf.size_kb == 0:
                                lf.size_kb = float(civitai_size_kb)
                                session.add(lf)

    session.add(model)


# ============================================================================
# MAINTENANCE ENDPOINTS
# ============================================================================

@router.post("/cleanup-orphans")
def cleanup_orphan_models(session: Session = Depends(get_session)):
    """
    Remove models that have no versions (orphaned during failed imports or migration).
    These models cannot be used and should be cleaned up.
    """
    from sqlmodel import delete

    # Find all models with no versions using a LEFT JOIN in a single query
    from api.deps import get_model_repo_v2
    from core.entities import ModelTag
    repo = get_model_repo_v2(session)
    orphans = repo.get_orphan_models()
    
    # Delete orphans
    deleted = []
    if orphans:
        orphan_ids = [model.id for model, _ in orphans]
        session.exec(delete(ModelTag).where(ModelTag.model_id.in_(orphan_ids)))
        for model, _ in orphans:
            session.delete(model)
            deleted.append(model.name)
    
    session.commit()
    
    return {
        "status": "success",
        "message": f"Cleaned up {len(deleted)} orphan models",
        "deleted_models": deleted
    }


@router.post("/{model_id}/check-dependencies")
async def check_dependencies(
    model_id: str,
    session: Session = Depends(get_session)
):
    """
    Check for and auto-download dependencies (CLIP, VAE) for a model.
    Useful for Flux/AuraFlow models if dependencies failed to download initially.
    """
    
    service = get_model_service_v2(session)

    # Get model to check existence. Synchronous repository read behind a
    # decorative `async def` in the service, so it went through `to_thread`
    # rather than running inline on the event loop.
    model = await asyncio.to_thread(service.get_model, model_id)

    # Get base model from default version
    versions = model.get("versions", [])
    if not versions:
        raise ValidationError("Model has no versions")
        
    default_v = next((v for v in versions if v.get("is_default")), versions[0])
    base_model = default_v.get("base_model")
    
    if not base_model:
        raise ValidationError("Model has no base model information")
    
    # Trigger check
    result = await service.check_and_trigger_dependencies(base_model_name=base_model)
    
    return {
        "status": "success",
        "result": result
    }


@router.post("/{model_id}/resync")
async def resync_model_from_civitai(
    model_id: str,
    session: Session = Depends(get_session)
):
    """
    Re-sync a model's metadata from CivitAI.
    This can fix models that were imported with incomplete data.
    
    Note: This only updates model-level metadata (name, description, stats).
    Version/file data cannot be updated without re-downloading.
    """
    from core.entities import ModelV2

    # The route awaits CivitAI, so the model lookup before it and the metadata
    # write after it both run in a worker thread.
    civitai_model_id = await asyncio.to_thread(_civitai_id_for_resync, session, model_id)

    # Fetch fresh data from CivitAI
    url = f"https://civitai.com/api/v1/models/{civitai_model_id}"
    try:
        http_client = get_http_client()
        response = await http_client.get(url, timeout=30.0)
        if response.status_code != 200:
            raise ComfyError(f"CivitAI API error: {response.status_code}")
        civitai_data = response.json()
    except Exception as e:
        raise ComfyError(f"Failed to fetch from CivitAI: {e!s}")

    # Apply metadata using shared helper
    return await asyncio.to_thread(
        _apply_resync_sync, session, model_id, civitai_data
    )


def _civitai_id_for_resync(session: Session, model_id: str) -> str:
    """The model's CivitAI id, or 404/422. Runs off the event loop."""
    from core.entities import ModelV2

    model = session.get(ModelV2, model_id)
    if not model:
        raise NotFoundError("Resource", "Model not found")

    if not model.civitai_model_id:
        raise ValidationError("Model has no CivitAI ID - cannot resync")
    return model.civitai_model_id


def _apply_resync_sync(session: Session, model_id: str, civitai_data: dict) -> dict:
    """Apply fetched CivitAI metadata to the model and build the response."""
    from core.entities import ModelV2

    model = session.get(ModelV2, model_id)
    if not model:
        raise NotFoundError("Resource", "Model not found")

    _apply_civitai_metadata(model, civitai_data, session)
    session.commit()

    # Get service for dict conversion
    service = get_model_service_v2(session)

    return {
        "status": "success",
        "message": f"Resynced model '{model.name}' from CivitAI",
        "model": service.repo.model_to_dict(model)
    }


# ============================================================================
# MODEL TAGS (user-authored)
# ============================================================================

class AddUserTagRequest(BaseModel):
    """Body for adding a hand-typed tag to a model."""
    tag: str


@router.get("/{model_id}/tags")
def list_model_tags_endpoint(
    model_id: str,
    session: Session = Depends(get_session)
):
    """List a model's tags with their provenance (`civitai` or `user`)."""
    return {"tags": list_model_tags(session, model_id)}


@router.post("/{model_id}/tags", status_code=201)
def add_user_model_tag_endpoint(
    model_id: str,
    request: AddUserTagRequest,
    session: Session = Depends(get_session)
):
    """
    Add a `source='user'` tag to a model.

    This is the writer path that used not exist: `ModelTag` rows could only ever
    come from a CivitAI resync, which then deleted them on the next resync, so
    there was no way to record "this LoRA is the one for Character X" anywhere
    the tag search could see. User tags survive resyncs; `PUT`-style overwrite
    of a CivitAI tag is deliberately not offered, because the next resync would
    undo it.
    """
    result = add_user_model_tag(session, model_id, request.tag)
    return {"status": "success", "model_id": model_id, **result}


@router.delete("/{model_id}/tags/{tag}")
def remove_user_model_tag_endpoint(
    model_id: str,
    tag: str,
    session: Session = Depends(get_session)
):
    """
    Remove a `source='user'` tag. Returns 404 when there is no such user tag;
    a CivitAI-owned tag is never removed here.
    """
    if not remove_user_model_tag(session, model_id, tag):
        raise NotFoundError("Model tag", f"No user tag '{tag}' on model '{model_id}'")
    return {"status": "success", "model_id": model_id, "tag": tag}

async def run_background_resync():
    """Run a full metadata resync for all eligible models."""
    from api.deps import get_model_repo_v2
    from core.exceptions import ComfyError
    
    async with get_session_context() as bg_session:
        repo = get_model_repo_v2(bg_session)
        models = repo.get_models_for_resync()
        
        if not models:
            return {"success": 0, "failed": 0, "errors": []}
            
        results = {"success": 0, "failed": 0, "errors": []}
        total = len(models)
        
        await broadcast_to_all("RESYNC_PROGRESS", {
            "status": "started",
            "processed": 0,
            "total": total,
            "results": results,
            "current_model": "Starting..."
        })
        
        http_client = get_http_client()
        import asyncio

        batch_size = 5
        for i in range(0, len(models), batch_size):
            batch = models[i:i+batch_size]
            
            await broadcast_to_all("RESYNC_PROGRESS", {
                "status": "processing",
                "processed": i,
                "total": total,
                "results": results,
                "current_model": f"Batch {i//batch_size + 1}"
            })
            
            async def fetch_civitai(model):
                url = f"https://civitai.com/api/v1/models/{model.civitai_model_id}"
                try:
                    response = await http_client.get(url, timeout=30.0)
                    if response.status_code != 200:
                        return model, None, ComfyError(f"API error: {response.status_code}")
                    return model, response.json(), None
                except Exception as exc:
                    return model, None, exc
            
            fetch_tasks = [fetch_civitai(m) for m in batch]
            fetched_results = await asyncio.gather(*fetch_tasks)
            
            # Off the loop. A resync fetches every eligible model from CivitAI in
            # batches of five, and for a library of a few hundred that is minutes
            # of `await`s — with `_apply_civitai_metadata` and `commit` running
            # INLINE on the event loop between every batch. So the whole
            # application was stalled for the duration of a background job that no
            # user is waiting on. `api/lifecycle.py:290-295` also schedules this
            # function every 24 h, so this is not a rare path.
            def _apply_batch(rows, data_by_index):
                applied = 0
                failures = []
                for (model, _data, exc), data in zip(rows, data_by_index, strict=True):
                    if exc:
                        failures.append({"model_id": str(model.id), "error": str(exc)})
                        continue
                    if not data:
                        continue
                    try:
                        _apply_civitai_metadata(model, data, bg_session)
                        applied += 1
                    except Exception as e:
                        failures.append({"model_id": str(model.id), "error": str(e)})
                bg_session.commit()
                return applied, failures

            applied, failures = await asyncio.to_thread(
                _apply_batch, fetched_results, [r[1] for r in fetched_results]
            )
            results["success"] += applied
            results["errors"].extend(failures)
        
        await broadcast_to_all("RESYNC_PROGRESS", {
            "status": "completed",
            "processed": total,
            "total": total,
            "results": results,
            "current_model": "Done"
        })
        return results

@router.post("/resync-all")
def resync_all(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Fetch latest metadata from CivitAI for all non-auto-discovered models."""
    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    
    # Get all models that are NOT auto-discovered and HAVE a civitai ID
    models = repo.get_models_for_resync(include_relations=False)
    
    if not models:
        return {"status": "no_models", "count": 0}
        
    background_tasks.add_task(run_background_resync)
    
    return {"status": "processing", "count": len(models)}


# ============================================================================
# BACKFILL UTILITY
# ============================================================================

@router.post("/backfill-statuses")
async def backfill_provider_statuses(
    session: Session = Depends(get_session)
):
    """
    Backfill provider_statuses for all models by querying each provider.
    Useful for migrating existing models or after worker issues.
    """
    from infrastructure.http_client import get_http_client
    from services.model_reconciliation import _DIRECTORY_TO_MODEL_TYPE
    from services.provider_runtime import resolve_provider_runtime_async

    service = get_model_service_v2(session)

    from api.deps import get_provider_service
    provider_service = get_provider_service(session)
    providers = provider_service.get_enabled_providers()

    all_models = await service.list_models(include_versions=True)
    all_files_by_path = {}
    for model in all_models:
        for version in model.get("versions", []):
            file = version.get("file")
            if not file:
                continue
            storage_path = f"models/{model['directory']}/{file['filename']}"
            all_files_by_path[storage_path] = file["id"]
    
    results = {
        "providers_checked": 0,
        "models_updated": 0,
        "errors": []
    }
    
    http_client = get_http_client()
    
    MODEL_DIRECTORIES = [
        f"models/{d}" for d in _DIRECTORY_TO_MODEL_TYPE
    ]
    
    import asyncio
    
    tasks = []

    async def check_directory(provider_id, directory, worker_url):
        try:
            response = await http_client.post(
                f"{worker_url}/list-models",
                json={"directory": directory},
                timeout=60.0
            )
            if response.status_code != 200:
                return []
            
            data = response.json()
            return _collect_ready_updates(provider_id, directory, data.get("files", []))
        except Exception as e:
            results["errors"].append(f"Failed to query {provider_id} at {directory}: {e!s}")
            return []

    def _collect_ready_updates(provider_id, directory, provider_files):
        updates = []
        for provider_file in provider_files or []:
            if not isinstance(provider_file, dict):
                continue
            storage_path = provider_file.get("path") or provider_file.get("storage_path")
            if not storage_path:
                name = provider_file.get("name")
                if not name:
                    continue
                storage_path = f"{directory}/{name}"

            file_id = all_files_by_path.get(storage_path)
            if file_id:
                updates.append((provider_id, file_id))
        return updates

    async def check_directory_engine(provider_id, directory, engine):
        try:
            files = await engine.list_models(directory)
        except Exception as e:
            results["errors"].append(f"Failed to query {provider_id} at {directory}: {e!s}")
            return []
        return _collect_ready_updates(provider_id, directory, files)
    
    for provider in providers:
        runtime = await resolve_provider_runtime_async(provider)
        if getattr(runtime, "mode", "") == "in_process":
            from services.engines.engine_factory import get_engine

            engine = get_engine(provider.id, provider)
            # LLM/TTS engines own no model tree; querying them wastes one
            # upstream call per image directory, same reason the container
            # path skips llm worker_types below. A plain Direct ComfyUI has
            # no mutation surface but still reports loadables via
            # /object_info, so it stays in for discovery.
            if engine is None:
                continue
            if not getattr(engine, "manages_model_files", False) and not getattr(
                engine, "supports_discovery_reconcile", False
            ):
                continue

            results["providers_checked"] += 1

            for directory in MODEL_DIRECTORIES:
                tasks.append(check_directory_engine(provider.id, directory, engine))
            continue

        if runtime.mode not in ("container_http", "discovery"):
            continue

        # LLM workers don't manage image model files; querying them wastes
        # upstream API calls (one per image directory).
        if getattr(provider, "worker_type", "image") == "llm":
            continue

        worker_url = runtime.worker_url
        
        results["providers_checked"] += 1
        
        for directory in MODEL_DIRECTORIES:
            tasks.append(check_directory(provider.id, directory, worker_url))
            
    all_updates = await asyncio.gather(*tasks)
    
    for directory_updates in all_updates:
        for provider_id, file_id in directory_updates:
            try:
                # Synchronous upsert + commit; this handler is `async def`
                # because of the provider fan-out above it, so the write needs
                # the thread hop.
                await asyncio.to_thread(
                    service.update_provider_file_status,
                    provider_id=provider_id,
                    file_id=file_id,
                    status="ready",
                )
                results["models_updated"] += 1
            except Exception as e:
                results["errors"].append(str(e))
    
    return results
