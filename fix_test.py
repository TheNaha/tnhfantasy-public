import re

with open('backend_v2/tests/test_provider_streaming.py', 'r') as f:
    content = f.read()

# Add import if missing
if 'JobStatus' not in content:
    content = content.replace('from api.provider_client import', 'from core.entities import JobStatus\nfrom api.provider_client import')

# Replace the specific calls
content = re.sub(r'job_service\.update_job\.assert_any_call\((.*?), message="Queued in ComfyUI\.\.\."\)',
                 r'job_service.update_job.assert_any_call(\1, status=JobStatus.PRE_GENERATION, message="Queued in ComfyUI...")',
                 content)

with open('backend_v2/tests/test_provider_streaming.py', 'w') as f:
    f.write(content)
