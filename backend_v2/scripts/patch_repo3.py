
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/infrastructure/repositories/model_repo_v2.py"
with open(file_path, "r") as f:
    content = f.read()

new_methods = """
    def get_orphan_models(self) -> List[tuple]:
        from sqlmodel import func
        stmt = select(ModelV2, func.count(ModelVersion.id).label("version_count")) \\
            .outerjoin(ModelVersion, ModelVersion.model_id == ModelV2.id) \\
            .group_by(ModelV2.id) \\
            .having(func.count(ModelVersion.id) == 0)
        return self.session.exec(stmt).all()

    def get_models_for_resync(self, include_relations: bool = True) -> List[ModelV2]:
        from sqlalchemy.orm import selectinload
        stmt = select(ModelV2) \\
            .where(ModelV2.civitai_model_id != None) \\
            .where(ModelV2.description.not_like("%Auto-discovered%"))
            
        if include_relations:
            stmt = stmt.options(selectinload(ModelV2.versions).selectinload(ModelVersion.files))
            
        return self.session.exec(stmt).all()
"""

# Append
if "get_orphan_models" not in content:
    with open(file_path, "a") as f:
        f.write("\n" + new_methods)
