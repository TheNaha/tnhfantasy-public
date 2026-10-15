import os
import json
import logging
import hashlib
from typing import List, Dict, Any

from provider_worker_core.model_scan import scan_model_directory
from provider_core.utils import get_safe_path

import asyncio
import aiofiles

logger = logging.getLogger(__name__)

async def list_models_with_metadata_internal(base_path: str, directory: str, compute_hashes: bool = False) -> List[Dict[str, Any]]:
    """
    List models in a directory and attach metadata and preview URLs if they exist.

    An empty `directory` means the storage root, not an error: `get_safe_path`
    rejects an empty path outright ("path cannot be empty"), so this used to
    return [] with a "Path traversal blocked" warning for a perfectly ordinary
    request. That is the same "" -> base-path resolution
    deployables/modal/image/modal_app.py uses for its own listing, and it is why
    Beam's /list-models 400'd on the same request that the deleted `direct_url`
    container client answered in full.
    """
    if directory:
        try:
            target_dir = get_safe_path(base_path, directory)
        except Exception:
            logger.warning(f"[ListModels] Path traversal blocked: {directory}")
            return []
    else:
        target_dir = os.path.realpath(base_path)

    if not os.path.exists(target_dir):
        return []
        
    def _scan_directory():
        # Raises on a failed scandir or stat. This used to catch, log at
        # `warning`, and return `([], set())` — which reconciliation's step 3
        # cannot tell from "this directory holds no models", so it re-downloaded
        # every checkpoint in it. `remote_agent/server.py::_walk` has always
        # failed loud here, and every `_fetch_dir` closure already wraps a raise
        # into RuntimeError. See `provider_worker_core/model_scan.py`.
        return scan_model_directory(target_dir)

    file_entries, entry_set = await asyncio.to_thread(_scan_directory)
    if not file_entries:
        return []

    def _compute_hash_sync(filepath: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
        
    async def _process_file(name: str, file_size: int) -> Dict[str, Any]:
        file_path = f"{directory}/{name}" if directory else name
        file_data = {
            "name": name,
            "path": file_path,
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
            if compute_hashes:
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
            else:
                file_data["sha256"] = None
                
        return file_data

    tasks = [_process_file(name, file_size) for name, file_size in file_entries]
    files = await asyncio.gather(*tasks)
    return files
