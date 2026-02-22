import os
import glob
import time
import threading
import re
from typing import List, Dict, Any, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from infrastructure.logging import get_logger

logger = get_logger("gallery_indexer")

class _GalleryEventHandler(FileSystemEventHandler):
    """Handles file system events for the gallery indexer."""
    def __init__(self, indexer):
        self.indexer = indexer

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.png'):
            if '/thumb/' not in event.src_path.replace('\\', '/'):
                self.indexer.add_file(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.png'):
            self.indexer.remove_file(event.src_path)

    def on_moved(self, event):
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
        self.sorted_keys_date_desc: List[str] = []
        
        self.lock = threading.RLock()
        self.observer = None
        self._initialized = True
        self.is_ready = False

    def start(self):
        """Start the background indexer."""
        if self.observer:
            return
            
        logger.info("gallery_indexer_starting", directory=self.output_dir)
        
        # Initial scan
        self._perform_initial_scan()
        
        # Start watchdog
        event_handler = _GalleryEventHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.output_dir, recursive=True)
        self.observer.start()
        logger.info("gallery_indexer_started")

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
                metadata = read_image_metadata(filepath)
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
                "preview": f"/api/view/output/{base_name}",
                "thumbnail": f"/api/thumbnail/medium/{base_name}",
                "thumbnail_medium": f"/api/thumbnail/medium/{base_name}",
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
        
        all_files = []
        for pattern in ["*.png", "**/*.png"]:
            all_files.extend(glob.glob(os.path.join(self.output_dir, pattern), recursive=True))
            
        all_files = list(set([f for f in all_files if '/thumb/' not in f.replace('\\', '/')]))
        
        processed_files = {}
        for filepath in all_files:
            data = self._process_file(filepath)
            if data:
                processed_files[filepath] = data
                
        with self.lock:
            self.files = processed_files
            self._rebuild_sort_index()
            self.is_ready = True
            
        logger.info("gallery_indexer_scan_complete", 
                   count=len(self.files), 
                   duration_seconds=round(time.time() - start_time, 2))

    def _rebuild_sort_index(self):
        """Rebuild sorting indices."""
        sorted_items = sorted(self.files.items(), key=lambda x: x[1]['date'], reverse=True)
        self.sorted_keys_date_desc = [k for k, v in sorted_items]

    def add_file(self, filepath: str):
        """Add a newly created file to the index."""
        # Wait a tiny bit for the file to finish writing
        time.sleep(0.1)
        data = self._process_file(filepath)
        if data:
            with self.lock:
                self.files[filepath] = data
                self._rebuild_sort_index()
                logger.debug("gallery_indexer_added", file=os.path.basename(filepath))

    def remove_file(self, filepath: str):
        """Remove a deleted file from the index."""
        with self.lock:
            if filepath in self.files:
                del self.files[filepath]
                if filepath in self.sorted_keys_date_desc:
                    self.sorted_keys_date_desc.remove(filepath)
                logger.debug("gallery_indexer_removed", file=os.path.basename(filepath))
                
    def get_files(self, limit: int = 20, offset: int = 0, sort: str = "date_desc", search: Optional[str] = None):
        """Query the in-memory index."""
        # Optional wait if not ready
        wait_count = 0
        while not self.is_ready and wait_count < 50: # max wait 5 seconds
            time.sleep(0.1)
            wait_count += 1
            
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
            
            # Copy to avoid mutation issues outside
            import copy
            return {"files": copy.deepcopy(result), "total": total}

# Singleton instance
gallery_indexer = GalleryIndexer()
