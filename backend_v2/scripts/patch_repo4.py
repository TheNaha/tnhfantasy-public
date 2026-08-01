
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/infrastructure/repositories/model_repo_v2.py"
with open(file_path, "r") as f:
    content = f.read()

new_method = """
    def get_existing_filenames(self, filenames: List[str]) -> List[str]:
        stmt = select(ModelFile.storage_filename).where(ModelFile.storage_filename.in_(filenames))
        return [row for row in self.session.exec(stmt).all()]
"""

if "get_existing_filenames" not in content:
    with open(file_path, "a") as f:
        f.write("\n" + new_method)
