import os
import re

TARGET_DIR = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes"

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    original_content = content
    
    # Check if HTTPException is imported, if so, we need to add our imports
    if "HTTPException" in content:
        # Add imports if not present
        if "from core.exceptions import" not in content:
            # find a good place to put it
            content = re.sub(r'from fastapi import(.*)', r'from fastapi import\1\nfrom core.exceptions import NotFoundError, ValidationError, ComfyError', content, count=1)
        else:
            # ensure all are imported
            pass
            
        # Replace common HTTPExceptions
        content = re.sub(r'raise HTTPException\(\s*status_code=404,\s*detail=(.*?)\s*\)', r'raise NotFoundError("Resource", \1)', content)
        content = re.sub(r'raise HTTPException\(\s*status_code=400,\s*detail=(.*?)\s*\)', r'raise ValidationError(\1)', content)
        content = re.sub(r'raise HTTPException\(\s*status_code=403,\s*detail=(.*?)\s*\)', r'raise ValidationError(\1)', content)
        content = re.sub(r'raise HTTPException\(\s*403\)', r'raise ValidationError("Forbidden")', content)
        content = re.sub(r'raise HTTPException\(\s*status_code=500,\s*detail=(.*?)\s*\)', r'raise ComfyError(\1)', content)
        content = re.sub(r'raise HTTPException\(\s*status_code=502,\s*detail=(.*?)\s*\)', r'raise ComfyError(\1)', content)
        content = re.sub(r'raise HTTPException\(\s*status_code=422,\s*detail=(.*?)\s*\)', r'raise ValidationError(\1)', content)

    if content != original_content:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Updated {filepath}")

for root, _, files in os.walk(TARGET_DIR):
    for filename in files:
        if filename.endswith(".py"):
            process_file(os.path.join(root, filename))

print("Done")
