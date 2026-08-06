# Prompts API - Saved prompt library with CRUD and FTS5 full-text search
#
# Prompts are server-side (SQLite `prompts` table) for cross-device sync.
# SQLite FTS5 virtual table (`prompts_fts`) keeps the full-text search index
# automatically up to date via INSERT/UPDATE/DELETE triggers.
#
# KEY ENDPOINTS:
#   GET    /api/prompts          – List / search prompts (supports q, category, favorite)
#   POST   /api/prompts          – Create a new prompt
#   GET    /api/prompts/{id}     – Get a single prompt
#   PUT    /api/prompts/{id}     – Replace a prompt
#   DELETE /api/prompts/{id}     – Delete a prompt
#   POST   /api/prompts/{id}/use – Increment usage counter
#   GET    /api/prompts/categories – List all distinct categories
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, or_, select

from api.deps import get_logger, get_session
from core.entities import Prompt
from core.exceptions import ComfyError, NotFoundError

logger = get_logger("prompts_route")


router = APIRouter(prefix="/api/prompts", tags=["prompts"])


# Request/Response models
class PromptCreate(BaseModel):
    name: str = ""
    text: str
    negative: str | None = None
    category: str = "Custom"
    description: str | None = None
    tags: list[str] = []
    favorite: bool = False
    settings: dict | None = None


class PromptUpdate(BaseModel):
    name: str | None = None
    text: str | None = None
    negative: str | None = None
    category: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    favorite: bool | None = None
    settings: dict | None = None


class PromptBulkImport(BaseModel):
    prompts: list[PromptCreate]


class PromptMagicRequest(BaseModel):
    prompt: str


# CRUD endpoints

@router.get("")
async def list_prompts(
    q: str | None = Query(None, description="Search query for FTS5"),
    category: str | None = Query(None, description="Filter by category"),
    favorite: bool | None = Query(None, description="Filter favorites only"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session)
):
    """
    List prompts with optional search and filtering.
    Uses FTS5 for fast full-text search when query is provided.
    """
    try:
        # Use simple ILIKE search for now until full text search is optimized
        if q and q.strip():
            search_query = f"%{q.strip()}%"
            stmt = select(Prompt).where(
                or_(
                    Prompt.name.ilike(search_query),
                    Prompt.text.ilike(search_query),
                    Prompt.description.ilike(search_query),
                )
            )
            if category:
                stmt = stmt.where(Prompt.category == category)
            if favorite is not None:
                stmt = stmt.where(Prompt.favorite == favorite)
            
            stmt = stmt.order_by(Prompt.updated_at.desc()).limit(limit).offset(offset)
            prompts = session.exec(stmt).all()
        else:
            # No search query - simple listing with filters
            stmt = select(Prompt)
            
            if category:
                stmt = stmt.where(Prompt.category == category)
            if favorite is not None:
                stmt = stmt.where(Prompt.favorite == favorite)
            
            stmt = stmt.order_by(Prompt.updated_at.desc()).limit(limit).offset(offset)
            prompts = session.exec(stmt).all()
        
        return {
            "prompts": prompts,
            "count": len(prompts)
        }
    
    except Exception as e:
        raise ComfyError(str(e))


@router.get("/categories")
async def get_categories(session: Session = Depends(get_session)):
    """Get all unique categories."""
    result = session.execute(text("SELECT DISTINCT category FROM prompts ORDER BY category"))
    categories = [row[0] for row in result]
    # Always include default categories
    defaults = ['All', 'Portrait', 'Landscape', 'Anime', 'Abstract', 'Realistic', 'Custom']
    all_cats = list(set(defaults + categories))
    return {"categories": sorted(all_cats)}


@router.get("/favorites")
async def get_favorites(
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session)
):
    """Get favorite prompts."""
    from api.deps import get_prompt_repo
    repo = get_prompt_repo(session)
    prompts = repo.get_favorite_prompts(limit)
    return {"prompts": prompts}


@router.get("/most-used")
async def get_most_used(
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session)
):
    """Get most frequently used prompts."""
    from api.deps import get_prompt_repo
    repo = get_prompt_repo(session)
    prompts = repo.get_top_prompts(limit)
    return {"prompts": prompts}


@router.get("/{prompt_id}")
async def get_prompt(prompt_id: str, session: Session = Depends(get_session)):
    """Get a single prompt by ID."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise NotFoundError("Resource", "Prompt not found")
    return prompt


@router.post("")
async def create_prompt(data: PromptCreate, session: Session = Depends(get_session)):
    """Create a new prompt."""
    prompt = Prompt(
        name=data.name,
        text=data.text,
        negative=data.negative,
        category=data.category,
        description=data.description,
        tags=data.tags,
        favorite=data.favorite,
        settings=data.settings
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


@router.put("/{prompt_id}")
async def update_prompt(prompt_id: str, data: PromptUpdate, session: Session = Depends(get_session)):
    """Update an existing prompt."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise NotFoundError("Resource", "Prompt not found")
    
    # Update only provided fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prompt, key, value)
    
    prompt.updated_at = datetime.now(timezone.utc)
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: str, session: Session = Depends(get_session)):
    """Delete a prompt."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise NotFoundError("Resource", "Prompt not found")
    session.delete(prompt)
    session.commit()
    
    return {"success": True, "message": f"Prompt {prompt_id} deleted"}


@router.post("/{prompt_id}/use")
async def increment_usage(prompt_id: str, session: Session = Depends(get_session)):
    """Increment usage count for a prompt (called when prompt is used)."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise NotFoundError("Resource", "Prompt not found")
    
    prompt.usage_count += 1
    prompt.updated_at = datetime.now(timezone.utc)
    session.add(prompt)
    session.commit()
    
    return {"usage_count": prompt.usage_count}


@router.post("/import")
async def import_prompts(data: PromptBulkImport, session: Session = Depends(get_session)):
    """Bulk import prompts (for migration from localStorage)."""
    imported = []
    
    for prompt_data in data.prompts:
        prompt = Prompt(
            name=prompt_data.name,
            text=prompt_data.text,
            negative=prompt_data.negative,
            category=prompt_data.category,
            description=prompt_data.description,
            tags=prompt_data.tags,
            favorite=prompt_data.favorite,
            settings=prompt_data.settings
        )
        session.add(prompt)
        imported.append(prompt)
    
    session.commit()
    
    # Refresh to get IDs
    for prompt in imported:
        session.refresh(prompt)
    session.commit()
    
    return {
        "success": True,
        "imported": len(imported),
        "prompts": imported
    }


@router.get("/export")
async def export_prompts(session: Session = Depends(get_session)):
    """Export all prompts as JSON (for backup)."""
    from api.deps import get_prompt_repo
    repo = get_prompt_repo(session)
    prompts = repo.get_all_prompts()
    return {"prompts": prompts}

@router.post("/magic")
async def magic_prompt(
    request: PromptMagicRequest,
    session: Session = Depends(get_session)
):
    """
    Enriches a simple prompt into a highly detailed ComfyUI prompt using the LLM worker.
    """
    from core.entities import JobStatus
    from core.events import wait_for_job_completion
    from services.job_queue import queue_manager
    from services.job_service import JobService
    
    job_service = JobService(session)
    
    system_prompt = (
        "You are an expert AI image generation prompt engineer. "
        "Your task is to take a simple user idea and expand it into a highly detailed, "
        "comma-separated list of Danbooru-style tags and visual descriptions suitable for Stable Diffusion / ComfyUI. "
        "Include lighting, camera angles, quality modifiers (masterpiece, best quality, ultra-detailed), "
        "and specific subject details. "
        "Return ONLY the expanded prompt text, nothing else. No conversational text."
    )
    
    workflow = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.prompt}
        ]
    }
    
    job = await job_service.create_job(
        task_type="llm",
        workflow=workflow,
        metadata={"source": "magic_prompt"}
    )
    
    await queue_manager.enqueue(job.id, task_type="llm")
    
    # Wait for the LLM job to complete (enqueue + event-bus wait, no busy polling)
    status, output = await wait_for_job_completion(job.id, timeout=60.0)
    
    if status == JobStatus.COMPLETED.value or status == "job.completed":
        if output:
            enriched_text = output.get("content") or output.get("text") or ""
            if enriched_text and enriched_text.strip():
                return {"enriched_prompt": enriched_text.strip()}
        return {"enriched_prompt": request.prompt}
    
    raise ComfyError(f"Magic prompt failed: {status}")
