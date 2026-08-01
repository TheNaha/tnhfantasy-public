
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/deps.py"
with open(file_path, "r") as f:
    content = f.read()

new_deps = """
def get_collection_repo(session: Session):
    from infrastructure.repositories.collection_repo import CollectionRepository
    return CollectionRepository(session)
"""

# Append to file if not present
if "get_collection_repo" not in content:
    with open(file_path, "a") as f:
        f.write("\n" + new_deps)
