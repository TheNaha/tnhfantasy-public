import os
import json
import logging
from typing import List, Dict, Any

from .utils import get_safe_path

logger = logging.getLogger(__name__)

def list_models_with_metadata_internal(base_path: str, directory: str) -> List[Dict[str, Any]]:
    """
    List models in a directory and attach metadata and preview URLs if they exist.
    """
    try:
        target_dir = get_safe_path(base_path, directory)
    except Exception:
        logger.warning(f"[ListModels] Path traversal blocked: {directory}")
        return []
    
    if not os.path.exists(target_dir):
        return []
        
    entries = os.listdir(target_dir)
    files = []
    
    # Create a map for quick lookup
    entry_set = set(entries)
    
    for name in entries:
        # Skip metadata/preview files themselves
        if name.endswith('.json') or name.endswith('.preview.png'):
            continue
            
        full_path = os.path.join(target_dir, name)
        if not os.path.isfile(full_path):
            continue
            
        file_data = {
            "name": name,
            "type": "file",
            "size": os.path.getsize(full_path)
        }
        
        # Check for preview
        preview_name = f"{os.path.splitext(name)[0]}.preview.png"
        if preview_name in entry_set:
            file_data["preview"] = f"/api/view/{directory}/{preview_name}"
            
        # Check and READ metadata
        meta_name = f"{os.path.splitext(name)[0]}.json"
        if meta_name in entry_set:
            file_data["metadata_url"] = f"/api/view/{directory}/{meta_name}"
            try:
                with open(os.path.join(target_dir, meta_name), 'r') as f:
                    file_data["metadata"] = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read metadata for {name}: {e}")
                
        files.append(file_data)
        
    return files
