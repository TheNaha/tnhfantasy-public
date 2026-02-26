# Collections API - CRUD for user-curated image collections (albums)
#
# Collections allow users to organise gallery images into named groups.
# Images are linked via the `collection_images` join table – the actual
# PNG files live in the output directory and are referenced by filename.
#
# KEY ENDPOINTS:
#   GET    /api/collections                      – List all collections with image counts
#   POST   /api/collections                      – Create a collection
#   GET    /api/collections/{id}                 – Get collection (optionally with images)
#   PUT    /api/collections/{id}                 – Update collection name/color/description
#   DELETE /api/collections/{id}                 – Delete collection (images NOT deleted)
#   POST   /api/collections/{id}/images          – Add images to collection
#   DELETE /api/collections/{id}/images          – Remove images from collection
#   POST   /api/collections/import               – Bulk import (for localStorage migration)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from sqlalchemy import text, func
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from infrastructure.database import get_session
from core.entities import Collection, CollectionImage


router = APIRouter(prefix="/api/collections", tags=["collections"])


# Request/Response models
class CollectionCreate(BaseModel):
    name: str
    color: str = "#3B82F6"
    description: Optional[str] = None


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class AddImages(BaseModel):
    images: List[str]  # List of image filenames


class CollectionBulkImport(BaseModel):
    """For migrating from localStorage."""
    collections: List[dict]  # { name, color, images: [filenames] }


# CRUD endpoints

@router.get("")
async def list_collections(session: Session = Depends(get_session)):
    """List all collections with image counts."""
    # Get collections with image counts
    query = text("""
        SELECT c.*, COUNT(ci.id) as image_count
        FROM collections c
        LEFT JOIN collection_images ci ON c.id = ci.collection_id
        GROUP BY c.id
        ORDER BY c.updated_at DESC
    """)
    
    result = session.execute(query)
    collections = []
    for row in result:
        row_dict = dict(row._mapping)
        collections.append(row_dict)
    
    return {"collections": collections}


@router.get("/{collection_id}")
async def get_collection(
    collection_id: int, 
    include_images: bool = Query(True),
    session: Session = Depends(get_session)
):
    """Get a single collection with its images."""
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    result = {
        "id": collection.id,
        "name": collection.name,
        "color": collection.color,
        "description": collection.description,
        "thumbnail": collection.thumbnail,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
    }
    
    if include_images:
        # Get all images in this collection
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id
        ).order_by(CollectionImage.added_at.desc())
        images = session.exec(stmt).all()
        result["images"] = [img.image_filename for img in images]
        result["image_count"] = len(images)
    
    return result


@router.post("")
async def create_collection(data: CollectionCreate, session: Session = Depends(get_session)):
    """Create a new collection."""
    collection = Collection(
        name=data.name,
        color=data.color,
        description=data.description
    )
    session.add(collection)
    session.commit()
    session.refresh(collection)
    
    return collection


@router.put("/{collection_id}")
async def update_collection(
    collection_id: int, 
    data: CollectionUpdate, 
    session: Session = Depends(get_session)
):
    """Update a collection's name, color, or description."""
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(collection, key, value)
    
    collection.updated_at = datetime.utcnow()
    session.add(collection)
    session.commit()
    session.refresh(collection)
    
    return collection


@router.delete("/{collection_id}")
async def delete_collection(collection_id: int, session: Session = Depends(get_session)):
    """Delete a collection (images are NOT deleted, only the association)."""
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    # Delete all image associations first
    session.execute(
        text("DELETE FROM collection_images WHERE collection_id = :id"),
        {"id": collection_id}
    )
    
    # Delete the collection
    session.delete(collection)
    session.commit()
    
    return {"success": True, "message": f"Collection {collection_id} deleted"}


@router.post("/{collection_id}/images")
async def add_images_to_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    """Add images to a collection."""
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    added = []
    for filename in data.images:
        # Check if already exists
        existing = session.exec(
            select(CollectionImage).where(
                CollectionImage.collection_id == collection_id,
                CollectionImage.image_filename == filename
            )
        ).first()
        
        if not existing:
            ci = CollectionImage(
                collection_id=collection_id,
                image_filename=filename
            )
            session.add(ci)
            added.append(filename)
    
    # Update collection thumbnail to newest image
    if added:
        collection.thumbnail = added[0]
        collection.updated_at = datetime.utcnow()
        session.add(collection)
    
    session.commit()
    
    return {"success": True, "added": len(added), "images": added}


@router.delete("/{collection_id}/images")
async def remove_images_from_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    """Remove images from a collection."""
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    removed = 0
    for filename in data.images:
        result = session.execute(
            text("""
                DELETE FROM collection_images 
                WHERE collection_id = :col_id AND image_filename = :filename
            """),
            {"col_id": collection_id, "filename": filename}
        )
        removed += result.rowcount
    
    # Update thumbnail if needed
    remaining = session.exec(
        select(CollectionImage).where(
            CollectionImage.collection_id == collection_id
        ).order_by(CollectionImage.added_at.desc()).limit(1)
    ).first()
    
    collection.thumbnail = remaining.image_filename if remaining else None
    collection.updated_at = datetime.utcnow()
    session.add(collection)
    session.commit()
    
    return {"success": True, "removed": removed}


@router.post("/import")
async def import_collections(data: CollectionBulkImport, session: Session = Depends(get_session)):
    """Bulk import collections (for migration from localStorage)."""
    imported = []
    
    for col_data in data.collections:
        # Create collection
        collection = Collection(
            name=col_data.get("name", "Untitled"),
            color=col_data.get("color", "#3B82F6"),
            description=col_data.get("description")
        )
        session.add(collection)
        session.flush()  # Get the ID
        
        # Add images
        images = col_data.get("images", [])
        for filename in images:
            ci = CollectionImage(
                collection_id=collection.id,
                image_filename=filename
            )
            session.add(ci)
        
        # Set thumbnail
        if images:
            collection.thumbnail = images[0]
        
        imported.append({
            "id": collection.id,
            "name": collection.name,
            "image_count": len(images)
        })
    
    session.commit()
    
    return {
        "success": True,
        "imported": len(imported),
        "collections": imported
    }


@router.get("/export")
async def export_collections(session: Session = Depends(get_session)):
    """Export all collections (for backup)."""
    collections = session.exec(select(Collection)).all()
    
    result = []
    for col in collections:
        images = session.exec(
            select(CollectionImage).where(CollectionImage.collection_id == col.id)
        ).all()
        
        result.append({
            "id": col.id,
            "name": col.name,
            "color": col.color,
            "description": col.description,
            "images": [img.image_filename for img in images],
            "created_at": col.created_at.isoformat(),
            "updated_at": col.updated_at.isoformat()
        })
    
    return {"collections": result}
