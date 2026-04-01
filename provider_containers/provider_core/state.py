"""
Reconciliation state management for provider workers.
Thread-safe state tracking for reconciliation progress.
"""

from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import threading


@dataclass
class ReconciliationStats:
    """Statistics for reconciliation progress."""
    total_models_in_storage: int = 0
    downloads_queued: int = 0
    downloads_completed: int = 0
    downloads_failed: int = 0
    deletions_completed: int = 0
    invalid_cleaned: int = 0
    missing_reported: int = 0


@dataclass
class CurrentDownload:
    """Information about the current download."""
    name: str = ""
    file_id: int = 0
    progress: float = 0.0
    index: int = 0
    total: int = 0
    active_count: int = 1
    started_at: Optional[str] = None


class ReconciliationState:
    """
    Thread-safe reconciliation state manager.
    
    Tracks reconciliation progress and provides atomic updates.
    """
    
    def __init__(self, provider_id: str):
        self.provider_id = provider_id
        self._lock = threading.Lock()
        self.reset()
    
    def reset(self):
        """Reset state to initial values."""
        with self._lock:
            self._status = "idle"  # idle|reconciling|completed|failed
            self._started_at: Optional[str] = None
            self._completed_at: Optional[str] = None
            self._phase: Optional[str] = None
            self._message: Optional[str] = None
            self._download_queue: List[Dict] = []
            self._deletion_queue: List[str] = []
            self._current_download: Optional[Dict] = None
            self._active_downloads: List[Dict] = []
            self._stats = ReconciliationStats()
            self._errors: List[str] = []
    
    @property
    def status(self) -> str:
        with self._lock:
            return self._status
    
    @status.setter
    def status(self, value: str):
        with self._lock:
            self._status = value
    
    def start_reconciliation(self):
        """Mark reconciliation as started."""
        with self._lock:
            self._status = "reconciling"
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._completed_at = None
            self._phase = "validating"
            self._message = None
            self._download_queue = []
            self._deletion_queue = []
            self._current_download = None
            self._active_downloads = []
            self._stats = ReconciliationStats()
            self._errors = []
    
    def complete_reconciliation(self, success: bool = True):
        """Mark reconciliation as completed."""
        with self._lock:
            self._status = "completed" if success else "failed"
            self._completed_at = datetime.now(timezone.utc).isoformat()
            self._current_download = None
            self._active_downloads = []
    
    def set_download_queue(self, queue: List[Dict]):
        """Set the download queue."""
        with self._lock:
            self._download_queue = queue
            self._stats.downloads_queued = len(queue)
    
    def set_current_download(self, download: Optional[Dict]):
        """Set current download info."""
        with self._lock:
            self._current_download = download

    def set_active_downloads(self, downloads: Optional[List[Dict]]):
        """Set the current list of active downloads."""
        with self._lock:
            self._active_downloads = list(downloads or [])

    def set_phase(self, phase: Optional[str]):
        """Set the current reconciliation phase."""
        with self._lock:
            self._phase = phase

    def set_message(self, message: Optional[str]):
        """Set the current reconciliation status message."""
        with self._lock:
            self._message = message

    def _build_stats_snapshot(self) -> Dict[str, int]:
        """Build a stats snapshot. Caller must hold the lock."""
        return {
            "total_models_in_storage": self._stats.total_models_in_storage,
            "downloads_queued": self._stats.downloads_queued,
            "downloads_completed": self._stats.downloads_completed,
            "downloads_failed": self._stats.downloads_failed,
            "deletions_completed": self._stats.deletions_completed,
            "invalid_cleaned": self._stats.invalid_cleaned,
            "missing_reported": self._stats.missing_reported,
        }
    
    def increment_downloads_completed(self):
        """Increment completed downloads counter."""
        with self._lock:
            self._stats.downloads_completed += 1
    
    def increment_downloads_failed(self):
        """Increment failed downloads counter."""
        with self._lock:
            self._stats.downloads_failed += 1
    
    def increment_deletions_completed(self):
        """Increment deletions completed counter."""
        with self._lock:
            self._stats.deletions_completed += 1
    
    def set_total_models(self, count: int):
        """Set total models in storage."""
        with self._lock:
            self._stats.total_models_in_storage = count
    
    def set_invalid_cleaned(self, count: int):
        """Set invalid models cleaned count."""
        with self._lock:
            self._stats.invalid_cleaned = count
    
    def set_missing_reported(self, count: int):
        """Set missing models reported count."""
        with self._lock:
            self._stats.missing_reported = count
    
    def add_error(self, error: str):
        """Add an error message."""
        with self._lock:
            self._errors.append(error)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for API response."""
        with self._lock:
            return {
                "provider_id": self.provider_id,
                "status": self._status,
                "phase": self._phase,
                "message": self._message,
                "started_at": self._started_at,
                "completed_at": self._completed_at,
                "download_queue": self._download_queue,
                "deletion_queue": self._deletion_queue,
                "current_download": self._current_download,
                "active_downloads": self._active_downloads,
                "stats": self._build_stats_snapshot(),
                "errors": self._errors,
            }
    
    def get_stats(self) -> Dict[str, int]:
        """Get current stats as dictionary."""
        with self._lock:
            return self._build_stats_snapshot()
    
    def get_status(self) -> str:
        """Get current reconciliation status."""
        with self._lock:
            return self._status
    
    def get_current_download(self) -> Optional[Dict]:
        """Get current download info."""
        with self._lock:
            return self._current_download
    
    def get_errors(self) -> List[str]:
        """Get list of errors."""
        with self._lock:
            return self._errors.copy()


# Global state instance (initialized per worker)
_reconciliation_state: Optional[ReconciliationState] = None


def get_reconciliation_state(provider_id: str) -> ReconciliationState:
    """Get or create the global reconciliation state."""
    global _reconciliation_state
    if _reconciliation_state is None:
        _reconciliation_state = ReconciliationState(provider_id)
    return _reconciliation_state
