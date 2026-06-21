import os
import json
import logging
import hashlib
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
        
    def _scan_directory():
        file_entries = []
        entry_set = set()
        try:
            with os.scandir(target_dir) as it:
                for entry in it:
                    if entry.is_file():
                        entry_set.add(entry.name)
                        if not (entry.name.endswith('.json') or entry.name.endswith('.preview.png') or entry.name.endswith('.sha256')):
                            file_entries.append((entry.name, entry.stat().st_size))
        except Exception as e:
            logger.warning(f"Failed to scandir {target_dir}: {e}")
            return [], set()
        return file_entries, entry_set

    file_entries, entry_set = await asyncio.to_thread(_scan_directory)
    if not file_entries:
        return []

    def _compute_hash_sync(filepath: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
        
    files = []
    for name, file_size in file_entries:
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
        
        sha256_name = f"{name}.sha256"
        sha256_path = os.path.join(target_dir, sha256_name)
        if sha256_name in entry_set:
            try:
                async with aiofiles.open(sha256_path, 'r') as f:
                    file_data["sha256"] = (await f.read()).strip()
            except Exception as e:
                logger.warning(f"Failed to read hash for {name}: {e}")
        else:
            # Need to compute hash
            logger.info(f"Computing SHA256 for {name}...")
            try:
                target_filepath = os.path.join(target_dir, name)
                computed_hash = await asyncio.to_thread(_compute_hash_sync, target_filepath)
                file_data["sha256"] = computed_hash
                # Save sidecar
                async with aiofiles.open(sha256_path, 'w') as f:
                    await f.write(computed_hash)
                logger.info(f"Saved SHA256 sidecar for {name}: {computed_hash}")
            except Exception as e:
                logger.warning(f"Failed to compute/save hash for {name}: {e}")
                
        files.append(file_data)
        
    return files
