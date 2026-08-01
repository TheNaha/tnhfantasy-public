
file_path = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/prompts.py"
with open(file_path, "r") as f:
    content = f.read()

# Replace search prompts
old_search = """    if query or tag:
        # Complex search handled locally or by DB
        if query:
            # We'll do a simple ILIKE for query and exact match for tag
            if tag:
                stmt = select(Prompt).where(
                    or_(
                        Prompt.text.contains(query),
                        Prompt.tags.contains(tag)
                    )
                )
            else:
                stmt = select(Prompt).where(Prompt.text.contains(query))
        else:
            # Just tag
            stmt = select(Prompt).where(Prompt.tags.contains(tag))
            
        if not include_nsfw:
            stmt = stmt.where(Prompt.is_nsfw == False)
            
        stmt = stmt.order_by(Prompt.updated_at.desc())
        prompts = session.exec(stmt).all()
    else:
        # Fast path for empty search
        stmt = select(Prompt)
        if not include_nsfw:
            stmt = stmt.where(Prompt.is_nsfw == False)
        stmt = stmt.order_by(Prompt.updated_at.desc()).limit(100)
        prompts = session.exec(stmt).all()"""

new_search = """    from api.deps import get_prompt_repo
    repo = get_prompt_repo(session)
    prompts = repo.search_prompts(query=query, include_nsfw=include_nsfw, tag=tag)
    
    if not query and not tag:
        # limit to 100 for fast path
        prompts = prompts[:100]"""

content = content.replace(old_search, new_search)

# Replace favorite and top queries
old_favorites = """    stmt = select(Prompt).where(Prompt.favorite == True).order_by(Prompt.usage_count.desc()).limit(limit)
    prompts = session.exec(stmt).all()"""
new_favorites = """    from api.deps import get_prompt_repo
    repo = get_prompt_repo(session)
    prompts = repo.get_favorite_prompts(limit)"""
content = content.replace(old_favorites, new_favorites)

old_top = """    stmt = select(Prompt).order_by(Prompt.usage_count.desc()).limit(limit)
    prompts = session.exec(stmt).all()"""
new_top = """    from api.deps import get_prompt_repo
    repo = get_prompt_repo(session)
    prompts = repo.get_top_prompts(limit)"""
content = content.replace(old_top, new_top)

# Replace export
old_export = """    prompts = session.exec(select(Prompt)).all()"""
new_export = """    from api.deps import get_prompt_repo
    repo = get_prompt_repo(session)
    prompts = repo.get_all_prompts()"""
content = content.replace(old_export, new_export)

with open(file_path, "w") as f:
    f.write(content)
