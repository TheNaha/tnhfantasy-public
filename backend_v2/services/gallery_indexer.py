# Gallery Indexer - In-memory index for fast image gallery browsing
#
# DESIGN:
#   Instead of scanning the output directory on every gallery request (slow for
#   thousands of images), GalleryIndexer maintains an in-memory dict of all
#   known PNG files and uses watchdog to keep it up-to-date in real time.
#
#   The singleton instance is started once during application startup and stays
#   alive for the lifetime of the process.
#
# INDEX STRUCTURE:
#   files: { absolute_path -> file_data_dict }
#   relative_path_index: { relative_path -> absolute_path }
#   filename_index: { filename -> set(absolute_paths) }
#   sorted_keys_date_desc: [absolute_path, ...] sorted newest-first
#
# THREAD SAFETY:
#   All mutations to `files` and `sorted_keys_date_desc` are guarded by
#   `self.lock` (threading.RLock) because watchdog fires events from a
#   background thread while API requests read from the main thread.

import os
import time
import threading
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from infrastructure.logging import get_logger

logger = get_logger("gallery_indexer")

class _GalleryEventHandler(FileSystemEventHandler):
    """
    Watchdog event handler that forwards file-system events to GalleryIndexer.

    Only PNG files outside thumb sub-directories are considered, because
    thumbnails are generated derivatives and should not appear in the gallery.
    """
    def __init__(self, indexer):
        self.indexer = indexer

    def on_created(self, event):
        """Called when a new file is created in the watched directory tree."""
        if not event.is_directory and event.src_path.lower().endswith('.png'):
            if '/thumb/' not in event.src_path.replace('\\', '/'):
                self.indexer.add_file(event.src_path)

    def on_deleted(self, event):
        """Called when a file is removed from the watched directory tree."""
        if not event.is_directory and event.src_path.lower().endswith('.png'):
            self.indexer.remove_file(event.src_path)

    def on_moved(self, event):
        """Called when a file is renamed/moved within the watched directory tree."""
        if not event.is_directory:
            if event.src_path.lower().endswith('.png'):
                self.indexer.remove_file(event.src_path)
            if event.dest_path.lower().endswith('.png'):
                if '/thumb/' not in event.dest_path.replace('\\', '/'):
                    self.indexer.add_file(event.dest_path)

class GalleryIndexer:
    """
    Maintains an in-memory index of gallery images to avoid slow disk scanning.
    Uses watchdog to stay synchronized with the file system.
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(GalleryIndexer, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, output_dir: str = None):
        if self._initialized:
            return
            
        self.output_dir = output_dir or os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "../../output"))
        self.files: Dict[str, Dict[str, Any]] = {}
        self.relative_path_index: Dict[str, str] = {}
        self.filename_index: Dict[str, Set[str]] = defaultdict(set)
        self.sorted_keys_date_desc: List[str] = []
        
        self.lock = threading.RLock()
        self.observer = None
        self._initialized = True
        self.is_ready = False
        self._ready_event = threading.Event()

    @staticmethod
    def _compact_checkpoint_metadata(value: Any) -> Any:
        """Reduce checkpoint metadata to UI/statistics-relevant fields."""
        if not isinstance(value, dict):
            return value

        compact: Dict[str, Any] = {}
        for key in ["name", "display_name", "filename", "type", "size", "id"]:
            if key in value:
                compact[key] = value.get(key)

        if not compact:
            fallback_name = value.get("name") or value.get("filename") or value.get("display_name")
            if fallback_name:
                compact["name"] = fallback_name
        return compact

    @staticmethod
    def _compact_lora_entry(value: Any) -> Any:
        """Reduce a LoRA entry to display and reuse parameters."""
        if isinstance(value, str):
            return {"name": value, "strength": 1.0}
        if not isinstance(value, dict):
            return value

        compact: Dict[str, Any] = {}
        for key in ["name", "display_name", "filename", "strength", "weight", "id"]:
            if key in value:
                compact[key] = value.get(key)

        if "strength" not in compact and "weight" in compact:
            compact["strength"] = compact.get("weight")
        if "weight" not in compact and "strength" in compact:
            compact["weight"] = compact.get("strength")

        if not compact:
            fallback_name = value.get("name") or value.get("filename")
            if fallback_name:
                compact["name"] = fallback_name
        return compact

    @classmethod
    def _compact_metadata(cls, metadata: Any) -> Dict[str, Any]:
        """
        Keep scalar metadata and compact known heavy nested structures.

        This prevents large model payloads from ballooning RSS while preserving
        fields used by gallery UI and statistics endpoints.
        """
        if not isinstance(metadata, dict):
            return {}

        compact: Dict[str, Any] = {}
        passthrough_dict_keys = {"job", "dimensions", "thumbnails"}
        passthrough_list_keys = {"embeddings", "tags"}

        for key, value in metadata.items():
            if key == "checkpoint":
                compact[key] = cls._compact_checkpoint_metadata(value)
                continue

            if key == "loras":
                if isinstance(value, list):
                    compact[key] = [cls._compact_lora_entry(item) for item in value]
                continue

            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[key] = value
                continue

            if isinstance(value, dict) and key in passthrough_dict_keys:
                compact[key] = value
                continue

            if isinstance(value, list) and key in passthrough_list_keys:
                compact[key] = value
                continue

        return compact

    def start(self):
        """Start the background indexer asynchronously so it doesn't block startup."""
        if self.observer:
            return
            
        logger.info("gallery_indexer_starting", directory=self.output_dir)
        
        import threading
        
        def background_init():
            # Initial scan
            self._perform_initial_scan()
            
            # Start watchdog
            event_handler = _GalleryEventHandler(self)
            self.observer = Observer()
            self.observer.schedule(event_handler, self.output_dir, recursive=True)
            self.observer.start()
            logger.info("gallery_indexer_started")
            
        threading.Thread(target=background_init, daemon=True).start()

    def stop(self):
        """Stop the background indexer."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            logger.info("gallery_indexer_stopped")

    def _get_sort_timestamp(self, filepath: str) -> float:
        """Extract generation timestamp from file."""
        try:
            mtime = os.path.getmtime(filepath)
            if mtime > 0:
                return mtime
        except OSError:
            pass
            
        basename = os.path.basename(filepath)
        datetime_match = re.search(r'(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})', basename)
        if datetime_match:
            year, month, day, hour, minute, second = map(int, datetime_match.groups())
            from datetime import datetime
            try:
                dt = datetime(year, month, day, hour, minute, second)
                return dt.timestamp()
            except ValueError:
                pass
        return 0

    def _process_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Extract metadata and info for a single file."""
        try:
            name = os.path.relpath(filepath, self.output_dir).replace("\\", "/")
            
            # Skip non-relevant files
            if name.endswith('.json') or name.endswith('.preview.png'):
                return None
            if '.thumb.' in name or '.medium.' in name:
                return None
            if not os.path.isfile(filepath):
                return None
                
            stat = os.stat(filepath)
            generation_time = self._get_sort_timestamp(filepath)
            
            # Try to read metadata safely
            metadata = {}
            blurhash = None
            try:
                from infrastructure.image_processor import read_image_metadata
                metadata = self._compact_metadata(read_image_metadata(filepath))
                blurhash = metadata.get('blurhash')
            except Exception:
                pass
                
            base_name = os.path.basename(filepath)
            
            file_data = {
                "name": base_name,
                "relative_path": name,
                "full_path": filepath,
                "size": stat.st_size,
                "date": generation_time,
                "mtime": stat.st_mtime,
                "modified_time": generation_time,
                "type": "image",
                "preview": f"/api/view/output/{name}",
                "thumbnail": f"/api/thumbnail/medium/{name}",
                "thumbnail_medium": f"/api/thumbnail/medium/{name}",
                "metadata": metadata
            }
            if blurhash:
                file_data["blurhash"] = blurhash
                
            return file_data
        except Exception as e:
            logger.error("gallery_indexer_process_error", filepath=filepath, error=str(e))
            return None

    def _perform_initial_scan(self):
        """Scan the directory initially."""
        if not os.path.exists(self.output_dir):
            return
            
        logger.info("gallery_indexer_scanning")
        start_time = time.time()
        
        processed_files = {}
        processed_relative_index = {}
        processed_filename_index: Dict[str, Set[str]] = defaultdict(set)
        for root, dirs, files in os.walk(self.output_dir):
            if "thumb" in dirs:
                dirs.remove("thumb")

            for filename in files:
                if not filename.lower().endswith(".png"):
                    continue

                filepath = os.path.join(root, filename)
                data = self._process_file(filepath)
                if data:
                    processed_files[filepath] = data
                    processed_relative_index[data["relative_path"]] = filepath
                    processed_filename_index[data["name"]].add(filepath)
                
        with self.lock:
            self.files = processed_files
            self.relative_path_index = processed_relative_index
            self.filename_index = processed_filename_index
            self._rebuild_sort_index()
            self.is_ready = True
            self._ready_event.set()
            
        logger.info("gallery_indexer_scan_complete", 
                   count=len(self.files), 
                   duration_seconds=round(time.time() - start_time, 2))

    def _rebuild_sort_index(self):
        """Rebuild sorting indices."""
        sorted_items = sorted(self.files.items(), key=lambda x: x[1]['date'], reverse=True)
        self.sorted_keys_date_desc = [k for k, v in sorted_items]

    def add_file(self, filepath: str):
        """Add a newly created file to the index."""
        data = self._process_file(filepath)
        if data:
            with self.lock:
                self.files[filepath] = data
                self.relative_path_index[data["relative_path"]] = filepath
                self.filename_index[data["name"]].add(filepath)
                self._rebuild_sort_index()
                logger.debug("gallery_indexer_added", file=os.path.basename(filepath))

    def remove_file(self, filepath: str):
        """Remove a deleted file from the index."""
        with self.lock:
            if filepath in self.files:
                filename = self.files[filepath]['name']
                relative_path = self.files[filepath]["relative_path"]
                del self.files[filepath]
                self.relative_path_index.pop(relative_path, None)
                filename_paths = self.filename_index.get(filename)
                if filename_paths:
                    filename_paths.discard(filepath)
                    if not filename_paths:
                        del self.filename_index[filename]

                if filepath in self.sorted_keys_date_desc:
                    self.sorted_keys_date_desc.remove(filepath)
                logger.debug("gallery_indexer_removed", file=os.path.basename(filepath))

    def _wait_until_ready(self):
        if not self.is_ready:
            self._ready_event.wait(timeout=5.0)

    def get_path_by_relative_path(self, relative_path: str) -> Optional[str]:
        """Get the absolute path for an exact relative path."""
        self._wait_until_ready()
        normalized = relative_path.lstrip("/\\").replace("\\", "/")

        with self.lock:
            return self.relative_path_index.get(normalized)

    def get_path_by_filename(self, filename: str) -> Optional[str]:
        """
        Get the absolute path for a basename only when it is unambiguous.
        Thread-safe.
        """
        self._wait_until_ready()

        with self.lock:
            matches = self.filename_index.get(filename, set())
            if len(matches) == 1:
                return next(iter(matches))
            return None

    def get_path(self, relative_or_filename: str) -> Optional[str]:
        """Resolve a file path by exact relative path first, then safe basename fallback."""
        normalized = relative_or_filename.lstrip("/\\").replace("\\", "/")
        if "/" in normalized:
            path = self.get_path_by_relative_path(normalized)
            if path:
                return path
        return self.get_path_by_filename(os.path.basename(normalized))
                
    def get_files(self, limit: int = 20, offset: int = 0, sort: str = "date_desc", search: Optional[str] = None):
        """
        Query the in-memory index with optional search, sort, and pagination.

        Blocks for up to 5 seconds if the initial scan is still in progress,
        then returns whatever is available.

        IMPORTANT: This method uses time.sleep and may block for up to 5s.
        When called from an async context (e.g. FastAPI async route handlers),
        callers MUST wrap this call with ``await asyncio.to_thread(...)`` to
        avoid blocking the event loop.

        Args:
            limit:  Maximum number of file records to return (page size).
            offset: Number of records to skip (for cursor-style pagination).
            sort:   Sort order – one of:
                    - "date_desc"  newest first (default)
                    - "date_asc"   oldest first
                    - "name_asc"   alphabetical A→Z
                    - "name_desc"  reverse alphabetical Z→A
            search: Optional string to filter results.  Matches against filename
                    and any string-valued metadata field (case-insensitive).

        Returns:
            Dict with:
                "files": list[dict]  – file records for the current page
                "total": int         – total matching files (before pagination)
        """
        # Optional wait if not ready
        if not self.is_ready:
            self._ready_event.wait(timeout=5.0)
            
        with self.lock:
            # 1. Get base list
            if sort == "date_desc":
                keys = self.sorted_keys_date_desc
            elif sort == "date_asc":
                keys = list(reversed(self.sorted_keys_date_desc))
            elif sort == "name_asc":
                keys = sorted(self.files.keys(), key=lambda k: self.files[k]['name'])
            elif sort == "name_desc":
                keys = sorted(self.files.keys(), key=lambda k: self.files[k]['name'], reverse=True)
            else:
                keys = self.sorted_keys_date_desc
                
            # 2. Filter if search provided
            if search:
                from api.routes.files import matches_search
                filtered_keys = []
                for k in keys:
                    file_data = self.files[k]
                    # We can use the existing matches_search or simple string tracking
                    search_lower = search.lower()
                    if search_lower in file_data['name'].lower():
                        filtered_keys.append(k)
                        continue
                        
                    found = False
                    for val in file_data.get('metadata', {}).values():
                        if isinstance(val, str) and search_lower in val.lower():
                            found = True
                            break
                    if found:
                        filtered_keys.append(k)
                keys = filtered_keys
                
            # 3. Paginate
            total = len(keys)
            paginated_keys = keys[offset : offset + limit]
            
            # Format output
            result = [self.files[k] for k in paginated_keys]
            
            # Shallow copy - callers only read dicts during JSON serialization
            return {"files": list(result), "total": total}

    def get_all_files(self) -> List[Dict[str, Any]]:
        """
        Get all file metadata from the index.
        Thread-safe method for statistics generation.

        IMPORTANT: This method uses time.sleep and may block for up to 5s.
        When called from an async context (e.g. FastAPI async route handlers),
        callers MUST wrap this call with ``await asyncio.to_thread(...)`` to
        avoid blocking the event loop.

        Returns:
            List[Dict]: List of all file metadata dictionaries (shallow copies)
        """
        # Optional wait if not ready
        if not self.is_ready:
            self._ready_event.wait(timeout=5.0)

        with self.lock:
            # Return shallow copies as stats calculations don't modify the nested structure
            # and performance is critical for large galleries.
            # Using list(self.files.values()) is sufficient because callers only read.
            return list(self.files.values())

# Singleton instance
gallery_indexer = GalleryIndexer()
