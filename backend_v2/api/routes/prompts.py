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
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, or_
from sqlalchemy import text
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel

from api.deps import get_session
from core.entities import Prompt


router = APIRouter(prefix="/api/prompts", tags=["prompts"])


# Request/Response models
class PromptCreate(BaseModel):
    name: str
    text: str
    negative: Optional[str] = None
    category: str = "Custom"
    description: Optional[str] = None
    tags: List[str] = []
    favorite: bool = False
    settings: Optional[dict] = None


class PromptUpdate(BaseModel):
    name: Optional[str] = None
    text: Optional[str] = None
    negative: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    favorite: Optional[bool] = None
    settings: Optional[dict] = None


class PromptBulkImport(BaseModel):
    prompts: List[PromptCreate]


# CRUD endpoints

@router.get("")
async def list_prompts(
    q: Optional[str] = Query(None, description="Search query for FTS5"),
    category: Optional[str] = Query(None, description="Filter by category"),
    favorite: Optional[bool] = Query(None, description="Filter favorites only"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session)
):
    """
    List prompts with optional search and filtering.
    Uses FTS5 for fast full-text search when query is provided.
    """
    try:
        # Check if FTS5 table exists and use it for search
        if q and q.strip():
            # Use FTS5 MATCH query for fast full-text search
            search_query = q.strip()
            # Escape FTS5 special chars and add prefix matching
            search_term = search_query.replace('"', '""')
            
            fts_query = text("""
                SELECT p.* FROM prompts p
                JOIN prompts_fts ON p.id = prompts_fts.rowid
                WHERE prompts_fts MATCH :search
                ORDER BY rank
                LIMIT :limit OFFSET :offset
            """)
            
            try:
                result = session.execute(
                    fts_query, 
                    {"search": f'"{search_term}"*', "limit": limit, "offset": offset}
                )
                prompts = [dict(row._mapping) for row in result]
            except Exception:
                # FTS5 table might not exist yet, fall back to LIKE search
                stmt = select(Prompt).where(
                    or_(
                        Prompt.name.contains(search_query),
                        Prompt.text.contains(search_query),
                        Prompt.description.contains(search_query) if search_query else False
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
        raise HTTPException(status_code=500, detail=str(e))


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
    stmt = select(Prompt).where(Prompt.favorite == True).order_by(Prompt.usage_count.desc()).limit(limit)
    prompts = session.exec(stmt).all()
    return {"prompts": prompts}


@router.get("/most-used")
async def get_most_used(
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session)
):
    """Get most frequently used prompts."""
    stmt = select(Prompt).order_by(Prompt.usage_count.desc()).limit(limit)
    prompts = session.exec(stmt).all()
    return {"prompts": prompts}


@router.get("/{prompt_id}")
async def get_prompt(prompt_id: int, session: Session = Depends(get_session)):
    """Get a single prompt by ID."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
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
    
    # Update FTS5 index
    try:
        session.execute(text("""
            INSERT INTO prompts_fts(rowid, name, text, negative, description, tags)
            VALUES (:id, :name, :text, :negative, :description, :tags)
        """), {
            "id": prompt.id,
            "name": prompt.name,
            "text": prompt.text,
            "negative": prompt.negative or "",
            "description": prompt.description or "",
            "tags": ",".join(prompt.tags) if prompt.tags else ""
        })
        session.commit()
    except Exception:
        pass  # FTS5 might not exist yet
    
    return prompt


@router.put("/{prompt_id}")
async def update_prompt(prompt_id: int, data: PromptUpdate, session: Session = Depends(get_session)):
    """Update an existing prompt."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    # Update only provided fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prompt, key, value)
    
    prompt.updated_at = datetime.now(timezone.utc)
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    
    # Update FTS5 index
    try:
        session.execute(text("""
            UPDATE prompts_fts SET 
                name = :name, text = :text, negative = :negative, 
                description = :description, tags = :tags
            WHERE rowid = :id
        """), {
            "id": prompt.id,
            "name": prompt.name,
            "text": prompt.text,
            "negative": prompt.negative or "",
            "description": prompt.description or "",
            "tags": ",".join(prompt.tags) if prompt.tags else ""
        })
        session.commit()
    except Exception:
        pass
    
    return prompt


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: int, session: Session = Depends(get_session)):
    """Delete a prompt."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    # Delete from FTS5 first
    try:
        session.execute(text("DELETE FROM prompts_fts WHERE rowid = :id"), {"id": prompt_id})
    except Exception:
        pass
    
    session.delete(prompt)
    session.commit()
    
    return {"success": True, "message": f"Prompt {prompt_id} deleted"}


@router.post("/{prompt_id}/use")
async def increment_usage(prompt_id: int, session: Session = Depends(get_session)):
    """Increment usage count for a prompt (called when prompt is used)."""
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
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
        # Add to FTS5
        try:
            session.execute(text("""
                INSERT INTO prompts_fts(rowid, name, text, negative, description, tags)
                VALUES (:id, :name, :text, :negative, :description, :tags)
            """), {
                "id": prompt.id,
                "name": prompt.name,
                "text": prompt.text,
                "negative": prompt.negative or "",
                "description": prompt.description or "",
                "tags": ",".join(prompt.tags) if prompt.tags else ""
            })
        except Exception:
            pass
    
    session.commit()
    
    return {
        "success": True,
        "imported": len(imported),
        "prompts": imported
    }


@router.get("/export")
async def export_prompts(session: Session = Depends(get_session)):
    """Export all prompts as JSON (for backup)."""
    prompts = session.exec(select(Prompt)).all()
    return {"prompts": prompts}
