import sys
import re

file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/infrastructure/repositories/model_repo_v2.py"
with open(file_path, "r") as f:
    content = f.read()

new_methods = """
    def get_models_needing_population(self) -> List[ModelV2]:
        stmt = select(ModelV2).where(
            ModelV2.description.like("%Auto-discovered%"),
            ModelV2.civitai_model_id.is_(None)
        )
        return self.session.exec(stmt).all()

    def get_auto_discovered_models(self) -> List[ModelV2]:
        stmt = select(ModelV2).where(ModelV2.description.like("%Auto-discovered%"))
        return self.session.exec(stmt).all()

    def get_all_storage_paths(self) -> List[str]:
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        )
        paths = []
        for file, version, model in self.session.exec(stmt).all():
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            paths.append(storage_path)
        return paths

    def get_models_by_civitai_ids(self, civitai_ids: List[int]) -> List[ModelV2]:
        stmt = select(ModelV2).where(ModelV2.civitai_model_id.in_(civitai_ids))
        return self.session.exec(stmt).all()

    def get_versions_for_models(self, model_ids: List[int]) -> List[ModelVersion]:
        stmt = select(ModelVersion).where(ModelVersion.model_id.in_(model_ids))
        return self.session.exec(stmt).all()
        
    def get_file_ids_by_storage_paths(self, paths: List[str]) -> Dict[str, int]:
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        )
        if paths:
            filenames = [p.split('/')[-1] for p in paths]
            stmt = stmt.where(ModelFile.storage_filename.in_(filenames))
            
        path_to_file_id = {}
        for file, version, model in self.session.exec(stmt).all():
            storage_path = f"models/{model.directory}/{file.storage_filename}"
            if not paths or storage_path in paths:
                path_to_file_id[storage_path] = file.id
        return path_to_file_id
"""

# Find get_all_models and insert after it
content = content.replace("    def get_all_models(self) -> List[ModelV2]:\n        \"\"\"Get all models.\"\"\"\n        stmt = select(ModelV2)\n        return self.session.exec(stmt).all()", 
    "    def get_all_models(self) -> List[ModelV2]:\n        \"\"\"Get all models.\"\"\"\n        stmt = select(ModelV2)\n        return self.session.exec(stmt).all()\n" + new_methods)

with open(file_path, "w") as f:
    f.write(content)
