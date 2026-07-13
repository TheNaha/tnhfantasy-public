import sys
import re

file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/models/autopopulate.py"
with open(file_path, "r") as f:
    content = f.read()

# Replace _get_models_needing_population
old_func = """def _get_models_needing_population(session: Session) -> list:
    return session.exec(
        select(ModelV2)
        .where(ModelV2.description.like("%Auto-discovered%"))
        .where(ModelV2.civitai_model_id.is_(None))
    ).all()"""
new_func = """def _get_models_needing_population(session: Session) -> list:
    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    return repo.get_models_needing_population()"""
content = content.replace(old_func, new_func)

# Replace select in search_autopopulate_candidates
old_search_select = """    model = session.exec(select(ModelV2).where(ModelV2.id == model_id)).first()"""
new_search_select = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    model = repo.get_model(model_id)"""
content = content.replace(old_search_select, new_search_select)

# Replace select in get_autopopulate_status
old_status_select = """    total = session.exec(
        select(ModelV2).where(ModelV2.description.like("%Auto-discovered%"))
    ).all()"""
new_status_select = """    from api.deps import get_model_repo_v2
    repo = get_model_repo_v2(session)
    total = repo.get_auto_discovered_models()"""
content = content.replace(old_status_select, new_status_select)

with open(file_path, "w") as f:
    f.write(content)
