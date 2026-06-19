import os
import shutil

src_file = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/models.py"
dest_dir = "/home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/models"
os.makedirs(dest_dir, exist_ok=True)

with open(src_file, "r") as f:
    content = f.read()

sections = content.split("# ============================================================================")
if len(sections) < 23:
    print(f"Error: expected 23 sections, got {len(sections)}")
    exit(1)

imports_common = """from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends

from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_session_sync
from services.model_service import ModelServiceV2
from core.exceptions import NotFoundError, ValidationError, ComfyError
from infrastructure.logging import model_logger

logger = model_logger()

router = APIRouter()

def get_model_service(session: Session) -> ModelServiceV2:
    return ModelServiceV2(session)
"""

def write_module(name, sect_indices, extra_imports=""):
    with open(os.path.join(dest_dir, f"{name}.py"), "w") as f:
        f.write(imports_common + extra_imports + "\n\n")
        # Add BaseModel definitions from sections 1,2 to ALL modules because they might be needed?
        # Actually, let's just write the sections we need
        for idx in sect_indices:
            f.write("# ============================================================================")
            f.write(sections[idx])

# 1. crud.py
# Section 1, 2 (REQUEST MODELS)
# Section 5, 6 (MODEL ENDPOINTS)
# Section 7, 8 (VERSION ENDPOINTS)
write_module("crud", [1, 2, 5, 6, 7, 8])

# 2. provider_sync.py
# Section 9, 10 (PROVIDER STATUS ENDPOINTS)
# Section 11, 12 (RECONCILIATION ENDPOINTS)
# Section 13, 14 (BATCH UPDATES)
# Section 19, 20 (SYNC PROGRESS)
write_module("provider_sync", [9, 10, 11, 12, 13, 14, 19, 20], extra_imports="from .crud import UpdateProviderStatusRequest\n")
# Update UpdateProviderStatusRequest since it was defined in Section 2
# Wait, let's just copy Section 1,2 into crud.py and let provider_sync import it.

# 3. maintenance.py
# Section 15, 16 (MAINTENANCE ENDPOINTS)
# Section 21, 22 (BACKFILL UTILITY)
write_module("maintenance", [15, 16, 21, 22])

# 4. preview.py
# Section 17, 18 (PREVIEW IMAGES)
preview_imports = """
from services.model_preview_service import get_preview_deduplicated, prefetch_stale_model_previews
"""
write_module("preview", [17, 18], extra_imports=preview_imports)

# Fix missing UpdateProviderStatusRequest in provider_sync.py
# Section 2 contains AddModelRequest, UpdateProviderStatusRequest, SetDefaultVersionRequest, CheckInstalledBatchRequest
# We can just put them in a schemas.py
schemas_content = """from typing import Dict, Any, Optional, List
from pydantic import BaseModel

""" + "# ============================================================================" + sections[1] + "# ============================================================================" + sections[2]
with open(os.path.join(dest_dir, "schemas.py"), "w") as f:
    f.write(schemas_content)

# And now rewrite modules to import schemas
def add_schema_import(name):
    path = os.path.join(dest_dir, f"{name}.py")
    with open(path, "r") as f:
        c = f.read()
    with open(path, "w") as f:
        f.write("from .schemas import *\n" + c)

add_schema_import("crud")
add_schema_import("provider_sync")
add_schema_import("maintenance")
add_schema_import("preview")

# Remove sections 1,2 from crud.py
crud_path = os.path.join(dest_dir, "crud.py")
with open(crud_path, "r") as f:
    crud_content = f.read()
crud_content = crud_content.replace("# ============================================================================" + sections[1], "")
crud_content = crud_content.replace("# ============================================================================" + sections[2], "")
with open(crud_path, "w") as f:
    f.write(crud_content)


# __init__.py
init_content = """from fastapi import APIRouter

from .crud import router as crud_router
from .provider_sync import router as provider_sync_router
from .maintenance import router as maintenance_router
from .preview import router as preview_router

router = APIRouter(prefix="/api/v2/models", tags=["models-v2"])

router.include_router(crud_router)
router.include_router(provider_sync_router)
router.include_router(maintenance_router)
router.include_router(preview_router)
"""

with open(os.path.join(dest_dir, "__init__.py"), "w") as f:
    f.write(init_content)

print("Split completed successfully!")
