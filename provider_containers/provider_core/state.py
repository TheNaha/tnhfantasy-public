"""
Reconciliation state management for provider workers.
Thread-safe state tracking for reconciliation progress.
"""

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Any, Optional, Set
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
    by_directory: Dict[str, int] = field(default_factory=dict)


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

    # Orphan sightings, keyed by provider and held on the class rather than the
    # instance: a `ReconciliationState` is built per `run_reconciliation_v2` call,
    # so an instance attribute would only ever hold the current run's list and
    # "seen in two consecutive reconciliations" could never be evaluated.
    #
    # Process-scoped, not persisted to the backend: a worker restart therefore
    # costs one extra tick before anything becomes deletable, which is the safe
    # direction to be wrong in.
    _orphan_sightings: Dict[str, Set[str]] = {}
    _orphan_sightings_lock = threading.Lock()

    def promote_stable_orphans(self, paths: Iterable[str]) -> List[str]:
        """Return the orphans reported in this run AND the previous one.

        `RECONCILIATION_DELETE_ORPHANS` is the one switch that arms mass deletion,
        and until this existed the only guard was `calculate_safe_deletion_limit`
        (`max(20, total // 5)`) — so a 100-model provider lost 20 files every
        7200 s tick with no confirmation, and a single mis-scoped
        `list_existing_files` (a wrong prefix, an empty listing, a provider whose
        storage endpoint is serving someone else's volume) made *every* file in the
        directory "orphaned" and armed the lot.

        Two consecutive identical reports is the cheapest signal that separates
        "this file is genuinely not in the database" from "this run did not see the
        database". A one-tick gap is enough: the listing is not a sampling error
        once in any other sense, and the size guard remains as a second limit.
        """
        current = {str(path) for path in paths}
        with type(self)._orphan_sightings_lock:
            previous = type(self)._orphan_sightings.get(self.provider_id, set())
            type(self)._orphan_sightings[self.provider_id] = current
        return sorted(previous & current)

    def peek_orphan_sightings(self) -> Set[str]:
        """The previous run's orphan set, for tests and diagnostics."""
        with type(self)._orphan_sightings_lock:
            return set(type(self)._orphan_sightings.get(self.provider_id, set()))

    def reset_orphan_sightings(self) -> None:
        """Forget the history, so the next run starts from nothing again."""
        with type(self)._orphan_sightings_lock:
            type(self)._orphan_sightings.pop(self.provider_id, None)

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
            "by_directory": self._stats.by_directory.copy(),
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

    def set_by_directory(self, by_directory: Dict[str, int]):
        """Set the directory breakdown."""
        with self._lock:
            self._stats.by_directory = by_directory.copy()
    
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


# Global state instances (keyed by provider_id for multi-provider support)
_reconciliation_states: Dict[str, ReconciliationState] = {}


def get_reconciliation_state(provider_id: str) -> ReconciliationState:
    """Get or create a reconciliation state for the given provider_id."""
    global _reconciliation_states
    if provider_id not in _reconciliation_states:
        _reconciliation_states[provider_id] = ReconciliationState(provider_id)
    return _reconciliation_states[provider_id]
