import re

with open('w:/hl-tsukiyo/home/containers/stacks/comfyui/backend_v2/api/routes/models.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove from 'def _resolve_preview_cache_dir' down to 'def get_model_preview_image'
pattern = re.compile(r'def _resolve_preview_cache_dir\(\) -> str:.*?@router\.get\("/preview/\{model_id\}"\)\nasync def get_model_preview_image\(model_id: int, version_id: int = None, image_index: int = 0\):', re.DOTALL)

replacement = '''from services.model_preview_service import get_preview_deduplicated, prefetch_stale_model_previews

@router.get("/preview/{model_id}")
async def get_model_preview_image(model_id: int, version_id: int = None, image_index: int = 0):'''

new_content = pattern.sub(replacement, content)

# update get_model_preview_image implementation
old_impl = '''    if image_index < 0:
        raise HTTPException(status_code=400, detail="image_index must be >= 0")

    dedup_key = make_key(
        "civitai_preview",
        model_id,
        version_id if version_id is not None else "default",
        image_index,
    )
    image_data, content_type, cache_hit = await deduplicated(
        dedup_key,
        lambda: fetch_civitai_preview(model_id, version_id, image_index),
    )'''

new_impl = '''    if image_index < 0:
        raise HTTPException(status_code=400, detail="image_index must be >= 0")

    image_data, content_type, cache_hit = await get_preview_deduplicated(
        model_id, version_id, image_index
    )'''

new_content = new_content.replace(old_impl, new_impl)

with open('w:/hl-tsukiyo/home/containers/stacks/comfyui/backend_v2/api/routes/models.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
