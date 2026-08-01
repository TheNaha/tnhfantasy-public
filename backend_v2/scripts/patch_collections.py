
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/collections.py"
with open(file_path, "r") as f:
    content = f.read()

# Replace list_collections
old_list = """@router.get("")
def list_collections(session: Session = Depends(get_session)):
    \"\"\"List all collections with image counts.\"\"\"
    # Get collections with image counts
    query = text(\"\"\"
        SELECT c.*, COUNT(ci.id) as image_count
        FROM collections c
        LEFT JOIN collection_images ci ON c.id = ci.collection_id
        GROUP BY c.id
        ORDER BY c.updated_at DESC
    \"\"\")
    
    result = session.execute(query)
    collections = []
    for row in result:
        row_dict = dict(row._mapping)
        collections.append(row_dict)
    
    return {"collections": collections}"""

new_list = """@router.get("")
def list_collections(session: Session = Depends(get_session)):
    \"\"\"List all collections with image counts.\"\"\"
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    return {"collections": repo.list_collections_with_counts()}"""
content = content.replace(old_list, new_list)

# Replace import_collections
# Need to use repo for import_collections
old_import = """@router.post("/import")
def import_collections(data: CollectionBulkImport, session: Session = Depends(get_session)):
    \"\"\"Bulk import collections (for migration from localStorage).\"\"\"
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
            img = CollectionImage(
                collection_id=collection.id,
                image_filename=filename
            )
            session.add(img)
            
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
    }"""

new_import = """@router.post("/import")
def import_collections(data: CollectionBulkImport, session: Session = Depends(get_session)):
    \"\"\"Bulk import collections (for migration from localStorage).\"\"\"
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
    }"""
content = content.replace(old_import, new_import)

# Replace get_collection
old_get = """@router.get("/{collection_id}")
def get_collection(
    collection_id: int, 
    include_images: bool = Query(True),
    session: Session = Depends(get_session)
):
    \"\"\"Get a single collection with its images.\"\"\"
    collection = session.get(Collection, collection_id)
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
        # Get all images in this collection
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id
        ).order_by(CollectionImage.added_at.desc())
        images = session.exec(stmt).all()
        result["images"] = [img.image_filename for img in images]
        result["image_count"] = len(images)
    
    return result"""

new_get = """@router.get("/{collection_id}")
def get_collection(
    collection_id: int, 
    include_images: bool = Query(True),
    session: Session = Depends(get_session)
):
    \"\"\"Get a single collection with its images.\"\"\"
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
    
    return result"""
content = content.replace(old_get, new_get)


old_create = """@router.post("")
def create_collection(data: CollectionCreate, session: Session = Depends(get_session)):
    \"\"\"Create a new collection.\"\"\"
    collection = Collection(
        name=data.name,
        color=data.color,
        description=data.description
    )
    session.add(collection)
    session.commit()
    session.refresh(collection)
    
    return collection"""

new_create = """@router.post("")
def create_collection(data: CollectionCreate, session: Session = Depends(get_session)):
    \"\"\"Create a new collection.\"\"\"
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
    
    return collection"""
content = content.replace(old_create, new_create)


old_update = """@router.put("/{collection_id}")
def update_collection(
    collection_id: int, 
    data: CollectionUpdate, 
    session: Session = Depends(get_session)
):
    \"\"\"Update a collection's name, color, or description.\"\"\"
    collection = session.get(Collection, collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(collection, key, value)
    
    collection.updated_at = datetime.now(timezone.utc)
    session.add(collection)
    session.commit()
    session.refresh(collection)
    
    return collection"""

new_update = """@router.put("/{collection_id}")
def update_collection(
    collection_id: int, 
    data: CollectionUpdate, 
    session: Session = Depends(get_session)
):
    \"\"\"Update a collection's name, color, or description.\"\"\"
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
    
    return collection"""
content = content.replace(old_update, new_update)


old_delete = """@router.delete("/{collection_id}")
def delete_collection(collection_id: int, session: Session = Depends(get_session)):
    \"\"\"Delete a collection (images are NOT deleted, only the association).\"\"\"
    collection = session.get(Collection, collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    # Delete all image associations first
    session.execute(
        text("DELETE FROM collection_images WHERE collection_id = :id"),
        {"id": collection_id}
    )
    
    # Delete the collection
    session.delete(collection)
    session.commit()
    
    return {"success": True, "message": f"Collection {collection_id} deleted"}"""

new_delete = """@router.delete("/{collection_id}")
def delete_collection(collection_id: int, session: Session = Depends(get_session)):
    \"\"\"Delete a collection (images are NOT deleted, only the association).\"\"\"
    from api.deps import get_collection_repo
    repo = get_collection_repo(session)
    collection = repo.get_collection(collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    repo.delete_collection(collection)
    session.commit()
    
    return {"success": True, "message": f"Collection {collection_id} deleted"}"""
content = content.replace(old_delete, new_delete)


old_add_images = """@router.post("/{collection_id}/images")
def add_images_to_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    \"\"\"Add images to a collection.\"\"\"
    collection = session.get(Collection, collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
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
        collection.updated_at = datetime.now(timezone.utc)
        session.add(collection)
    
    session.commit()
    
    return {"success": True, "added": len(added), "images": added}"""

new_add_images = """@router.post("/{collection_id}/images")
def add_images_to_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    \"\"\"Add images to a collection.\"\"\"
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
    
    return {"success": True, "added": len(added), "images": added}"""
content = content.replace(old_add_images, new_add_images)


old_remove_images = """@router.delete("/{collection_id}/images")
def remove_images_from_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    \"\"\"Remove images from a collection.\"\"\"
    collection = session.get(Collection, collection_id)
    if not collection:
        raise NotFoundError("Collection", str(collection_id))
    
    removed = 0
    for filename in data.images:
        result = session.execute(
            text(\"\"\"
                DELETE FROM collection_images 
                WHERE collection_id = :col_id AND image_filename = :filename
            \"\"\"),
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
    collection.updated_at = datetime.now(timezone.utc)
    session.add(collection)
    session.commit()
    
    return {"success": True, "removed": removed}"""

new_remove_images = """@router.delete("/{collection_id}/images")
def remove_images_from_collection(
    collection_id: int, 
    data: AddImages, 
    session: Session = Depends(get_session)
):
    \"\"\"Remove images from a collection.\"\"\"
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
    
    return {"success": True, "removed": removed}"""
content = content.replace(old_remove_images, new_remove_images)


old_export = """@router.get("/export")
def export_collections(session: Session = Depends(get_session)):
    \"\"\"Export all collections (for backup).\"\"\"
    from collections import defaultdict

    collections = session.exec(select(Collection)).all()
    if not collections:
        return {"collections": []}

    collection_ids = [c.id for c in collections]
    all_images = session.exec(
        select(CollectionImage).where(CollectionImage.collection_id.in_(collection_ids))
    ).all()

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
    
    return {"collections": result}"""

new_export = """@router.get("/export")
def export_collections(session: Session = Depends(get_session)):
    \"\"\"Export all collections (for backup).\"\"\"
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
    
    return {"collections": result}"""
content = content.replace(old_export, new_export)

with open(file_path, "w") as f:
    f.write(content)
