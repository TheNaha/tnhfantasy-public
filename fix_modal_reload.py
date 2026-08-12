import re
import os

helper_code = """
def safe_vol_reload():
    try:
        vol.reload()
    except Exception as e:
        logger.warning(f"vol.reload failed: {e}")

async def safe_vol_reload_aio():
    try:
        await vol.reload.aio()
    except Exception as e:
        logger.warning(f"vol.reload.aio failed: {e}")
"""

files_to_fix = [
    "provider_containers/image_worker/engines/modal/modal_app.py",
    "provider_containers/llm_worker/engines/modal/modal_app.py"
]

for filepath in files_to_fix:
    with open(filepath, "r") as f:
        content = f.read()
    
    if "def safe_vol_reload()" in content:
        print(f"Skipping {filepath} (already patched)")
        continue

    # Insert helper code after imports
    insert_pos = content.find("\n# =============================================================================")
    if insert_pos == -1:
        insert_pos = content.find("app = modal.App")
    
    if insert_pos != -1:
        content = content[:insert_pos] + "\n" + helper_code + "\n" + content[insert_pos:]
    else:
        print(f"Could not find insertion point in {filepath}")
        continue

    # Replace occurrences
    content = content.replace("await vol.reload.aio()", "await safe_vol_reload_aio()")
    content = content.replace("vol.reload()", "safe_vol_reload()")

    with open(filepath, "w") as f:
        f.write(content)
    
    print(f"Patched {filepath}")

