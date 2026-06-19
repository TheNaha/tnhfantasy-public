import re
import os

for root, _, files in os.walk("/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes"):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            with open(path, "r") as f:
                content = f.read()
            
            new_content = content.replace("HTTPException, ", "").replace(", HTTPException", "").replace(" HTTPException", "")
            
            if new_content != content:
                with open(path, "w") as f:
                    f.write(new_content)
                print(f"Updated {path}")
