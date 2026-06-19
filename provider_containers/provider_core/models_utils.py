import os
import json
import logging
from typing import List, Dict, Any

from .utils import get_safe_path

import aiofiles
import asyncio

logger = logging.getLogger(__name__)

async def list_models_with_metadata_internal(base_path: str, directory: str) -> List[Dict[str, Any]]:
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
        
    # Use scandir to avoid stat overhead and block event loop less
    try:
        entries = await asyncio.to_thread(os.listdir, target_dir)
    except Exception as e:
        logger.warning(f"Failed to listdir {target_dir}: {e}")
        return []
        
    files = []
    entry_set = set(entries)
    
    for name in entries:
        if name.endswith('.json') or name.endswith('.preview.png'):
            continue
            
        full_path = os.path.join(target_dir, name)
        try:
            file_size = await asyncio.to_thread(os.path.getsize, full_path)
        except Exception:
            continue
            
        file_data = {
            "name": name,
            "type": "file",
            "size": file_size
        }
        
        preview_name = f"{os.path.splitext(name)[0]}.preview.png"
        if preview_name in entry_set:
            file_data["preview"] = f"/api/view/{directory}/{preview_name}"
            
        meta_name = f"{os.path.splitext(name)[0]}.json"
        if meta_name in entry_set:
            file_data["metadata_url"] = f"/api/view/{directory}/{meta_name}"
            try:
                async with aiofiles.open(os.path.join(target_dir, meta_name), 'r') as f:
                    content = await f.read()
                    file_data["metadata"] = json.loads(content)
            except Exception as e:
                logger.warning(f"Failed to read metadata for {name}: {e}")
                
        files.append(file_data)
        
    return files
