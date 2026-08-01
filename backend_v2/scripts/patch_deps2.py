
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/deps.py"
with open(file_path, "r") as f:
    content = f.read()

new_deps = """
def get_prompt_repo(session: Session):
    from infrastructure.repositories.prompt_repo import PromptRepository
    return PromptRepository(session)
"""

if "get_prompt_repo" not in content:
    with open(file_path, "a") as f:
        f.write("\n" + new_deps)
