
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/models/crud.py"
with open(file_path, "r") as f:
    content = f.read()

# Replace get_all_storage_paths
old_storage_paths = """    from sqlmodel import select
    from core.entities import ModelFile, ModelVersion, ModelV2
    
    # Query all files with their model directory
    stmt = select(ModelFile, ModelVersion, ModelV2).join(
        ModelVersion, ModelFile.version_id == ModelVersion.id
    ).join(
        ModelV2, ModelVersion.model_id == ModelV2.id
    )
    
    paths = []
    for file, version, model in session.exec(stmt).all():
        storage_path = f"models/{model.directory}/{file.storage_filename}"
        paths.append(storage_path)"""

new_storage_paths = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    paths = repo.get_all_storage_paths()"""
content = content.replace(old_storage_paths, new_storage_paths)

# Replace select in check_installed_versions
old_check = """    from sqlmodel import select
    from core.entities import ModelV2, ModelVersion
    
    # Check if model exists
    model = session.exec(
        select(ModelV2).where(ModelV2.civitai_model_id == civitai_model_id)
    ).first()"""
new_check = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    
    # Check if model exists
    model = repo.get_model_by_civitai_id(civitai_model_id)"""
content = content.replace(old_check, new_check)

old_check_versions = """    # Get installed versions for this model
    versions = session.exec(
        select(ModelVersion).where(ModelVersion.model_id == model.id)
    ).all()"""
new_check_versions = """    # Get installed versions for this model
    versions = repo.get_versions_for_model(model.id)"""
content = content.replace(old_check_versions, new_check_versions)

# Replace select in check_installed_versions_batch
old_batch1 = """    from sqlmodel import select
    from core.entities import ModelV2, ModelVersion

    requested_ids = [mid for mid in request.civitai_model_ids if isinstance(mid, int)]
    if not requested_ids:
        return {"models": {}}

    unique_ids = sorted(set(requested_ids))
    models = session.exec(
        select(ModelV2).where(ModelV2.civitai_model_id.in_(unique_ids))
    ).all()"""
new_batch1 = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)

    requested_ids = [mid for mid in request.civitai_model_ids if isinstance(mid, int)]
    if not requested_ids:
        return {"models": {}}

    unique_ids = sorted(set(requested_ids))
    models = repo.get_models_by_civitai_ids(unique_ids)"""
content = content.replace(old_batch1, new_batch1)

old_batch2 = """    model_ids = [model.id for model in models if model.id is not None]
    versions = session.exec(
        select(ModelVersion).where(ModelVersion.model_id.in_(model_ids))
    ).all()"""
new_batch2 = """    model_ids = [model.id for model in models if model.id is not None]
    versions = repo.get_versions_for_models(model_ids)"""
content = content.replace(old_batch2, new_batch2)

# Replace select in add_model
old_add_model = """    from core.entities import ModelVersion
    from sqlmodel import select
    
    service = get_model_service_v2(session)
    
    # Extract version IDs from request
    selected_version_ids = [v["version_id"] for v in request.selected_versions]
    
    if not selected_version_ids:
        raise ValidationError("At least one version must be selected")
    
    # Check for already installed versions
    already_installed = []
    new_version_ids = []
    
    for version_id in selected_version_ids:
        existing = session.exec(
            select(ModelVersion).where(ModelVersion.civitai_version_id == version_id)
        ).first()"""
new_add_model = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    
    service = get_model_service_v2(session)
    
    # Extract version IDs from request
    selected_version_ids = [v["version_id"] for v in request.selected_versions]
    
    if not selected_version_ids:
        raise ValidationError("At least one version must be selected")
    
    # Check for already installed versions
    already_installed = []
    new_version_ids = []
    
    for version_id in selected_version_ids:
        existing = repo.get_version_by_civitai_id(version_id)"""
content = content.replace(old_add_model, new_add_model)

with open(file_path, "w") as f:
    f.write(content)
