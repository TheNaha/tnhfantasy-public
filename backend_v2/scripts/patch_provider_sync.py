
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/models/provider_sync.py"
with open(file_path, "r") as f:
    content = f.read()

# Replace batch_update_status
old_batch = """    from sqlmodel import select
    from core.entities import ModelFile, ModelVersion, ModelV2
    
    service = get_model_service_v2(session)
    provider_key = request.provider_id or request.provider_name
    if not provider_key:
        raise ValidationError("provider_id or provider_name is required")
    
    paths = [u.storage_path for u in request.updates if u.file_id is None and u.storage_path]
    path_to_file_id = None
    
    if paths:
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        )
        filenames = [p.split('/')[-1] for p in paths]
        stmt = stmt.where(ModelFile.storage_filename.in_(filenames))
        
        path_to_file_id = {}
        for file, version, model in session.exec(stmt).all():
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            path_to_file_id[storage_path] = file.id"""

new_batch = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    service = get_model_service_v2(session)
    provider_key = request.provider_id or request.provider_name
    if not provider_key:
        raise ValidationError("provider_id or provider_name is required")
    
    paths = [u.storage_path for u in request.updates if u.file_id is None and u.storage_path]
    path_to_file_id = None
    
    if paths:
        path_to_file_id = repo.get_file_ids_by_storage_paths(paths)"""
content = content.replace(old_batch, new_batch)

# Replace receive_batch_sync_progress
old_sync = """    from sqlmodel import select
    from core.entities import ModelFile, ModelVersion, ModelV2

    service = get_model_service_v2(session)
    file_id_by_key = {}
    stmt = select(ModelFile, ModelVersion, ModelV2).join(
        ModelVersion, ModelFile.version_id == ModelVersion.id
    ).join(
        ModelV2, ModelVersion.model_id == ModelV2.id
    )
    for file, _version, model in session.exec(stmt).all():
        file_id_by_key[(model.directory, file.storage_filename)] = file.id"""

new_sync = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    service = get_model_service_v2(session)
    
    # We can pass empty list to get all of them
    path_to_file_id = repo.get_file_ids_by_storage_paths([])
    file_id_by_key = {}
    for path, file_id in path_to_file_id.items():
        # path is models/directory/filename
        parts = path.split('/')
        if len(parts) >= 3:
            file_id_by_key[(parts[1], parts[2])] = file_id"""
content = content.replace(old_sync, new_sync)

with open(file_path, "w") as f:
    f.write(content)
