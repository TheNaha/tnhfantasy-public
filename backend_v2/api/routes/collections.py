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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import get_collection_repo, get_session
from core.entities import Collection, CollectionImage
from core.exceptions import NotFoundError
from infrastructure.repositories.collection_repo import CollectionRepository

router = APIRouter(prefix="/api/collections", tags=["collections"])


# Request/Response models
class CollectionCreate(BaseModel):
    name: str
    color: str = "#3B82F6"
    description: str | None = None
    character_id: str | None = None
    workspace: str | None = None  # Scope album: 'image' | 'chat' | 'story' (issue #5)


class CollectionUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    description: str | None = None


class AddImages(BaseModel):
    images: list[str]  # List of image filenames


class CollectionBulkImport(BaseModel):
    """For migrating from localStorage."""
    collections: list[dict]  # { name, color, images: [filenames] }


class CollectionMove(BaseModel):
    """Move image filenames from one collection to another (cross-workspace)."""
    from_collection_id: str
    to_collection_id: str
    images: list[str]  # List of image filenames to move


# CRUD endpoints

@router.get("")
def list_collections(
    workspace: str | None = None,
    repo: CollectionRepository = Depends(get_collection_repo)
):
    """List all collections with image counts, optionally filtered by workspace."""
    return {"collections": repo.list_collections_with_counts(workspace=workspace)}


@router.post("/import")
def import_collections(data: CollectionBulkImport, session: Session = Depends(get_session), repo: CollectionRepository = Depends(get_collection_repo)):
    """Bulk import collections (for migration from localStorage)."""
    imported = []
    
    for col_data in data.collections:
        collection = Collection(
            name=col_data.get("name", "Untitled"),
            color=col_data.get("color", "#3B82F6"),
            description=col_data.get("description")
        )
        repo.create_collection(collection)
        
        images = col_data.get("images", [])
        new_images = []
        for filename in images:
            img = CollectionImage(
                collection_id=collection.id,
                image_filename=filename
            )
            new_images.append(img)
            
        if new_images:
            repo.add_collection_images(new_images)
            
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


@router.post("/move")
def move_images_between_collections(
    data: CollectionMove,
    session: Session = Depends(get_session),
    repo: CollectionRepository = Depends(get_collection_repo),
):
    """Move image filenames from one collection to another (cross-workspace).

    Images are added to the destination collection (skipping duplicates) and
    removed from the source collection in a single transaction. The actual PNG
    files are never copied or deleted — only the collection_images associations
    change (issue #5).
    """
    from datetime import datetime as _dt, timezone as _tz

    source = repo.get_collection(data.from_collection_id)
    if not source:
        raise NotFoundError("Collection", data.from_collection_id)
    destination = repo.get_collection(data.to_collection_id)
    if not destination:
        raise NotFoundError("Collection", data.to_collection_id)

    if data.from_collection_id == data.to_collection_id:
        return {"success": True, "moved": 0, "message": "source and destination are the same collection"}

    # Only images that actually belong to the source are movable — moving a
    # filename the source doesn't own is a no-op, never an add-to-destination.
    src_images = {img.image_filename for img in repo.get_collection_images_by_filenames(source.id, data.images)}
    movable = [fn for fn in data.images if fn in src_images]
    if not movable:
        return {
            "success": True,
            "moved": 0,
            "added_to_destination": 0,
            "removed_from_source": 0,
        }

    # Add to destination, skipping filenames already present there.
    existing = repo.get_collection_images_by_filenames(destination.id, movable)
    existing_filenames = {img.image_filename for img in existing}
    new_links = [
        CollectionImage(collection_id=destination.id, image_filename=filename)
        for filename in movable
        if filename not in existing_filenames
    ]
    repo.add_collection_images(new_links)

    # Remove from source.
    moved = repo.remove_collection_images(source.id, movable)

    now = _dt.now(_tz.utc)
    source.updated_at = now
    if new_links:
        destination.thumbnail = movable[0]
    destination.updated_at = now
    repo.update_collection(source)
    repo.update_collection(destination)
    session.commit()

    return {
        "success": True,
        "moved": moved,
        "added_to_destination": len(new_links),
        "removed_from_source": moved,
    }


@router.get("/by-character/{character_id}")
def get_character_collection(
    character_id: str,
    include_images: bool = Query(True),
    repo: CollectionRepository = Depends(get_collection_repo),
):
    """Get or create the auto-generated collection for a character."""
    collection = repo.get_collection_by_character_id(character_id)
    if not collection:
        return None

    result = {
        "id": collection.id,
        "name": collection.name,
        "color": collection.color,
        "description": collection.description,
        "thumbnail": collection.thumbnail,
        "character_id": collection.character_id,
        "workspace": collection.workspace,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
    }

    if include_images:
        images = repo.get_collection_images(collection.id)
        result["images"] = [img.image_filename for img in images]
        result["image_count"] = len(images)

    return result


@router.get("/{collection_id}")
def get_collection(
    collection_id: str, 
    include_images: bool = Query(True),
    repo: CollectionRepository = Depends(get_collection_repo)
):
    """Get a single collection with its images."""
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    result = {
        "id": collection.id,
        "name": collection.name,
        "color": collection.color,
        "description": collection.description,
        "thumbnail": collection.thumbnail,
        "character_id": collection.character_id,
        "workspace": collection.workspace,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
    }
    
    if include_images:
        images = repo.get_collection_images(collection_id)
        result["images"] = [img.image_filename for img in images]
        result["image_count"] = len(images)
    
    return result


@router.post("")
def create_collection(data: CollectionCreate, session: Session = Depends(get_session), repo: CollectionRepository = Depends(get_collection_repo)):
    """Create a new collection."""
    collection = Collection(
        name=data.name,
        color=data.color,
        description=data.description,
        character_id=data.character_id,
        workspace=data.workspace
    )
    repo.create_collection(collection)
    session.commit()
    session.refresh(collection)

    return collection


@router.put("/{collection_id}")
def update_collection(
    collection_id: str, 
    data: CollectionUpdate, 
    session: Session = Depends(get_session),
    repo: CollectionRepository = Depends(get_collection_repo)
):
    """Update a collection's name, color, or description."""
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
def delete_collection(collection_id: str, session: Session = Depends(get_session), repo: CollectionRepository = Depends(get_collection_repo)):
    """Delete a collection (images are NOT deleted, only the association)."""
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    repo.delete_collection(collection)
    session.commit()
    
    return {"success": True, "message": f"Collection {collection_id} deleted"}


@router.post("/{collection_id}/images")
def add_images_to_collection(
    collection_id: str, 
    data: AddImages, 
    session: Session = Depends(get_session),
    repo: CollectionRepository = Depends(get_collection_repo)
):
    """Add images to a collection."""
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    added = []
    existing_images = repo.get_collection_images_by_filenames(collection_id, data.images)
    existing_filenames = {img.image_filename for img in existing_images}
    
    new_images = []
    for filename in data.images:
        if filename not in existing_filenames:
            ci = CollectionImage(
                collection_id=collection_id,
                image_filename=filename
            )
            new_images.append(ci)
            added.append(filename)
            
    repo.add_collection_images(new_images)
    
    if added:
        collection.thumbnail = added[0]
        collection.updated_at = datetime.now(timezone.utc)
        repo.update_collection(collection)
    
    session.commit()
    
    return {"success": True, "added": len(added), "images": added}


@router.delete("/{collection_id}/images")
def remove_images_from_collection(
    collection_id: str, 
    data: AddImages, 
    session: Session = Depends(get_session),
    repo: CollectionRepository = Depends(get_collection_repo)
):
    """Remove images from a collection."""
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
def export_collections(repo: CollectionRepository = Depends(get_collection_repo)):
    """Export all collections (for backup)."""
    from collections import defaultdict

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
