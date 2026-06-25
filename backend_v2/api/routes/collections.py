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
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from sqlalchemy import text, func
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel

from api.deps import get_session
from core.entities import Collection, CollectionImage
from core.exceptions import NotFoundError


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
def list_collections(session: Session = Depends(get_session)):
    """List all collections with image counts."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    return {"collections": repo.list_collections_with_counts()}


@router.post("/import")
def import_collections(data: CollectionBulkImport, session: Session = Depends(get_session)):
    """Bulk import collections (for migration from localStorage)."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    imported = []
    
    for col_data in data.collections:
        collection = Collection(
            name=col_data.get("name", "Untitled"),
            color=col_data.get("color", "#3B82F6"),
            description=col_data.get("description")
        )
        repo.create_collection(collection)
        
        images = col_data.get("images", [])
        for filename in images:
            img = CollectionImage(
                collection_id=collection.id,
                image_filename=filename
            )
            repo.add_collection_image(img)
            
        if images:
            collection.thumbnail = images[0]
            repo.update_collection(collection)
            
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


@router.get("/{collection_id}")
def get_collection(
    collection_id: int, 
    include_images: bool = Query(True),
    session: Session = Depends(get_session)
):
    """Get a single collection with its images."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
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
        images = repo.get_collection_images(collection_id)
        result["images"] = [img.image_filename for img in images]
        result["image_count"] = len(images)
    
    return result


@router.post("")
def create_collection(data: CollectionCreate, session: Session = Depends(get_session)):
    """Create a new collection."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    collection = Collection(
        name=data.name,
        color=data.color,
        description=data.description
    )
    repo.create_collection(collection)
    session.commit()
    session.refresh(collection)
    
    return collection


@router.put("/{collection_id}")
def update_collection(
    collection_id: int, 
    data: CollectionUpdate, 
    session: Session = Depends(get_session)
):
    """Update a collection's name, color, or description."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(collection, key, value)
    
    collection.updated_at = datetime.now(timezone.utc)
    repo.update_collection(collection)
    session.commit()
    session.refresh(collection)
    
    return collection


@router.delete("/{collection_id}")
def delete_collection(collection_id: int, session: Session = Depends(get_session)):
    """Delete a collection (images are NOT deleted, only the association)."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    repo.delete_collection(collection)
    session.commit()
    
    return {"success": True, "message": f"Collection {collection_id} deleted"}


@router.post("/{collection_id}/images")
def add_images_to_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    """Add images to a collection."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    added = []
    for filename in data.images:
        existing = repo.get_collection_image(collection_id, filename)
        
        if not existing:
            ci = CollectionImage(
                collection_id=collection_id,
                image_filename=filename
            )
            repo.add_collection_image(ci)
            added.append(filename)
    
    if added:
        collection.thumbnail = added[0]
        collection.updated_at = datetime.now(timezone.utc)
        repo.update_collection(collection)
    
    session.commit()
    
    return {"success": True, "added": len(added), "images": added}


@router.delete("/{collection_id}/images")
def remove_images_from_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    """Remove images from a collection."""
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    removed = repo.remove_collection_images(collection_id, data.images)
    
    remaining = repo.get_latest_collection_image(collection_id)
    collection.thumbnail = remaining.image_filename if remaining else None
    collection.updated_at = datetime.now(timezone.utc)
    repo.update_collection(collection)
    session.commit()
    
    return {"success": True, "removed": removed}




@router.get("/export")
def export_collections(session: Session = Depends(get_session)):
    """Export all collections (for backup)."""
    from collections import defaultdict
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)

    collections = repo.get_all_collections()
    if not collections:
        return {"collections": []}

    collection_ids = [c.id for c in collections]
    all_images = repo.get_images_for_collections(collection_ids)

    images_by_collection = defaultdict(list)
    for img in all_images:
        images_by_collection[img.collection_id].append(img.image_filename)

    result = []
    for col in collections:
        result.append({
            "id": col.id,
            "name": col.name,
            "color": col.color,
            "description": col.description,
            "images": images_by_collection.get(col.id, []),
            "created_at": col.created_at.isoformat(),
            "updated_at": col.updated_at.isoformat()
        })
    
    return {"collections": result}
