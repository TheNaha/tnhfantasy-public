import re
filepath = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/providers.py"

with open(filepath, "r") as f:
    content = f.read()

# Replace HTTPException with appropriate ComfyError / ValidationError
content = re.sub(
    r'raise HTTPException\(status_code=503,\s*detail="(.*?)"\)',
    r'raise ComfyError("\1", code="UNAVAILABLE")',
    content
)

content = re.sub(
    r'raise HTTPException\(status_code=status_code,\s*detail=detail\)',
    r'raise ComfyError(detail)',
    content
)

content = re.sub(
    r'raise HTTPException\(status_code=409,\s*detail="(.*?)"\)',
    r'raise ValidationError("\1")',
    content
)

content = re.sub(
    r'raise HTTPException\(status_code=exc.response.status_code,\s*detail=str\(exc\)\)',
    r'raise ProviderError(provider_id, f"Worker error: {str(exc)}")',
    content
)

content = re.sub(
    r'raise HTTPException\(status_code=409,\s*detail=result.get\("(.*?)",\s*"(.*?)"\)\)',
    r'raise ValidationError(result.get("\1", "\2"))',
    content
)

content = re.sub(
    r'raise HTTPException\(status_code=exc.response.status_code,\s*detail="(.*?)"\)',
    r'raise ProviderError(provider_id, "\1")',
    content
)

# Remove unused HTTPException
content = re.sub(r'from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request', r'from fastapi import APIRouter, Depends, Header, Query, Request', content)

with open(filepath, "w") as f:
    f.write(content)
print("Done")
