"""Tiered Models-in-RAM Manager with Anchor Protection and LRU Eviction.

Provides high-speed System RAM caching (/dev/shm or memory buffer) for models
stored on persistent storage (Google Drive / local disk), enabling sub-second
model loading and hot-switching on GPUs (such as NVIDIA L4).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger("ram_manager")


def drop_page_cache() -> None:
    """Flush and drop kernel page cache after large I/O to restore available system RAM."""
    try:
        subprocess.run(["sync"], check=False)
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3\n")
    except Exception:
        pass


def ensure_shm_capacity(needed_bytes: int = 0) -> None:
    """Expand /dev/shm filesystem capacity beyond Linux 50% default if running with privileges."""
    try:
        if not os.path.exists("/dev/shm"):
            return
        usage = shutil.disk_usage("/dev/shm")
        if usage.free < needed_bytes or usage.free < (10 * 1024 * 1024 * 1024):
            total_ram, _ = _get_system_ram_info()
            max_shm_gb = min(45, int((total_ram * 0.82) / (1024**3)))
            current_total_gb = int(usage.total / (1024**3))
            if max_shm_gb > current_total_gb:
                subprocess.run(["mount", "-o", f"remount,size={max_shm_gb}G", "/dev/shm"], check=False)
                logger.info("shm_capacity_expanded", extra={"new_size_gb": max_shm_gb})
    except Exception as exc:
        logger.debug(f"Could not expand /dev/shm: {exc}")


def _get_system_ram_info() -> tuple[int, int]:
    """Return (total_bytes, available_bytes) from system."""
    try:
        import psutil

        vm = psutil.virtual_memory()
        return vm.total, vm.available
    except Exception:
        # Fallback reading /proc/meminfo
        total = 0
        available = 0
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        available = int(line.split()[1]) * 1024
        except Exception:
            pass
        return total or (50 * 1024 * 1024 * 1024), available or (40 * 1024 * 1024 * 1024)


@dataclass
class CacheEntry:
    model_id: str
    role: str
    source_path: str
    ram_path: str
    size_bytes: int
    is_anchor: bool
    last_used: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "role": self.role,
            "source_path": self.source_path,
            "ram_path": self.ram_path,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / (1024 * 1024), 2),
            "is_anchor": self.is_anchor,
            "last_used": self.last_used,
            "last_used_ago_s": round(time.time() - self.last_used, 1),
        }


class RamModelManager:
    """Manages high-speed RAM caching of model files with LRU eviction and anchor protection."""

    def __init__(
        self,
        ram_dir: Optional[str] = None,
        budget_gb: Optional[float] = None,
        min_system_reserve_gb: float = 8.0,
    ) -> None:
        # 1. Resolve RAM Directory
        candidate_ram = ram_dir or os.getenv("RAM_CACHE_DIR", "/dev/shm/tnh_ram_cache")
        try:
            p = Path(candidate_ram)
            p.mkdir(parents=True, exist_ok=True)
            # Test write access
            test_f = p / ".ram_test"
            test_f.write_text("ok")
            test_f.unlink()
            self.ram_dir = p
        except Exception as exc:
            logger.warning(f"Could not use {candidate_ram} for RAM cache: {exc}. Falling back to /tmp/tnh_ram_cache")
            fallback = Path("/tmp/tnh_ram_cache")
            fallback.mkdir(parents=True, exist_ok=True)
            self.ram_dir = fallback

        # 2. Resolve Budget
        sys_total, sys_avail = _get_system_ram_info()
        self.min_reserve_bytes = int(min_system_reserve_gb * 1024 * 1024 * 1024)

        if budget_gb is not None and budget_gb > 0:
            self.budget_bytes = int(budget_gb * 1024 * 1024 * 1024)
        else:
            env_budget = os.getenv("RAM_CACHE_BUDGET_GB")
            if env_budget:
                self.budget_bytes = int(float(env_budget) * 1024 * 1024 * 1024)
            else:
                # Default: 75% of total system RAM, but leave at least min_reserve_bytes
                default_target = int(sys_total * 0.75)
                self.budget_bytes = min(default_target, max(sys_total - self.min_reserve_bytes, 1024 * 1024 * 1024))

        self.entries: Dict[str, CacheEntry] = {}
        self.anchors: Set[str] = set()

        # Rescan ram_dir if files already exist
        self._rescan_ram_dir()

    def _rescan_ram_dir(self) -> None:
        """Discover any files already resident in ram_dir."""
        if not self.ram_dir.exists():
            return
        for item in self.ram_dir.glob("*"):
            if item.is_file() and not item.name.endswith(".tmp"):
                mid = item.name
                sz = item.stat().st_size
                mtime = item.stat().st_mtime
                self.entries[mid] = CacheEntry(
                    model_id=mid,
                    role="cached",
                    source_path=str(item),
                    ram_path=str(item),
                    size_bytes=sz,
                    is_anchor=False,
                    last_used=mtime,
                )

    @property
    def current_usage_bytes(self) -> int:
        return sum(e.size_bytes for e in self.entries.values())

    @property
    def free_budget_bytes(self) -> int:
        return max(0, self.budget_bytes - self.current_usage_bytes)

    def set_anchors(self, anchor_ids: Iterable[str]) -> None:
        """Mark given model IDs as protected anchors (immune to LRU eviction)."""
        self.anchors = {str(a).strip() for a in anchor_ids if a and str(a).strip()}
        for mid, entry in self.entries.items():
            entry.is_anchor = mid in self.anchors or any(a in mid for a in self.anchors)

    def is_cached(self, model_id: str) -> bool:
        entry = self.entries.get(model_id)
        if not entry:
            return False
        return Path(entry.ram_path).exists()

    def touch(self, model_id: str) -> None:
        """Mark model as recently used."""
        if model_id in self.entries:
            self.entries[model_id].last_used = time.time()

    def evict_lru(self, needed_bytes: int) -> int:
        """Evict least-recently-used non-anchor models to free up needed_bytes."""
        freed = 0
        unpinned = [e for e in self.entries.values() if not e.is_anchor]
        unpinned.sort(key=lambda x: x.last_used)

        for entry in unpinned:
            if self.current_usage_bytes + needed_bytes <= self.budget_bytes:
                break
            try:
                p = Path(entry.ram_path)
                if p.exists():
                    p.unlink()
                sz = entry.size_bytes
                freed += sz
                del self.entries[entry.model_id]
                logger.info(
                    "ram_cache_lru_evicted",
                    extra={"model_id": entry.model_id, "size_mb": round(sz / (1024 * 1024), 1)},
                )
            except Exception as exc:
                logger.warning(f"Could not evict {entry.ram_path}: {exc}")

        return freed

    def evict_model(self, model_id: str, force: bool = False) -> bool:
        """Explicitly evict a single model from RAM."""
        entry = self.entries.get(model_id)
        if not entry:
            return False
        if entry.is_anchor and not force:
            logger.warning(f"Refusing to evict anchor model {model_id} without force=True")
            return False
        try:
            p = Path(entry.ram_path)
            if p.exists():
                p.unlink()
            del self.entries[model_id]
            logger.info("ram_cache_model_evicted", extra={"model_id": model_id})
            return True
        except Exception as exc:
            logger.warning(f"Failed to evict {model_id}: {exc}")
            return False

    def ensure_in_ram(
        self,
        source_path: str,
        model_id: Optional[str] = None,
        role: str = "general",
        is_anchor: bool = False,
    ) -> Path:
        """Ensure the model at source_path is pre-warmed and resident in high-speed RAM.

        Returns the Path inside RAM cache.
        """
        src = Path(source_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Source model file does not exist: {source_path}")

        mid = model_id or src.name
        is_anchor = is_anchor or (mid in self.anchors)

        # 1. Check if already cached in RAM
        if mid in self.entries:
            entry = self.entries[mid]
            ram_p = Path(entry.ram_path)
            if ram_p.exists() and ram_p.stat().st_size == src.stat().st_size:
                entry.last_used = time.time()
                entry.is_anchor = entry.is_anchor or is_anchor
                return ram_p

        # 2. Determine file size and check headroom
        size_bytes = src.stat().st_size
        needed = size_bytes

        # Check system available memory to prevent kernel OOM
        _, sys_avail = _get_system_ram_info()
        if sys_avail - needed < self.min_reserve_bytes:
            # Need to free aggressively
            self.evict_lru(needed + self.min_reserve_bytes)

        if self.current_usage_bytes + needed > self.budget_bytes:
            self.evict_lru(needed)

        # Ensure physical filesystem mount (/dev/shm) has capacity
        ensure_shm_capacity(needed)
        try:
            while shutil.disk_usage(self.ram_dir).free < needed:
                freed = self.evict_lru(needed)
                if freed == 0:
                    break
        except Exception:
            pass

        # 3. Stream / Copy into RAM cache atomically
        dest_filename = f"{mid}_{src.name}" if not src.name.startswith(mid) else src.name
        dest_path = self.ram_dir / dest_filename
        tmp_path = self.ram_dir / f".{dest_filename}.tmp"

        start_time = time.time()
        logger.info(
            "ram_cache_prewarming_start",
            extra={
                "model_id": mid,
                "size_mb": round(size_bytes / (1024 * 1024), 1),
                "is_anchor": is_anchor,
            },
        )

        try:
            # Stream with large 16MB buffer across FUSE/NVMe
            with open(src, "rb") as fsrc, open(tmp_path, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst, length=16 * 1024 * 1024)
            os.replace(tmp_path, dest_path)
        except Exception as exc:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Failed to copy {src} to RAM cache {dest_path}: {exc}") from exc

        elapsed = max(time.time() - start_time, 0.01)
        mb = size_bytes / (1024 * 1024)
        logger.info(
            "ram_cache_prewarmed",
            extra={
                "model_id": mid,
                "size_mb": round(mb, 1),
                "elapsed_s": round(elapsed, 2),
                "speed_mb_s": round(mb / elapsed, 1),
                "is_anchor": is_anchor,
            },
        )

        # 4. Record cache entry
        self.entries[mid] = CacheEntry(
            model_id=mid,
            role=role,
            source_path=str(src),
            ram_path=str(dest_path),
            size_bytes=size_bytes,
            is_anchor=is_anchor,
            last_used=time.time(),
        )

        drop_page_cache()

        return dest_path

    def prewarm_models(
        self,
        models: List[Dict[str, Any]],
        max_spare_gb: Optional[float] = None,
    ) -> List[str]:
        """Pre-warm anchor models first, then opportunistic secondary models if space permits.

        `models` is an ordered list of dicts:
        [{ "id": "...", "source_path": "...", "role": "rp", "is_anchor": True/False }, ...]
        """
        prewarmed: List[str] = []

        # 1. Anchors first (priority)
        anchors = [m for m in models if m.get("is_anchor")]
        for spec in anchors:
            mid = spec.get("id") or Path(spec["source_path"]).name
            try:
                self.ensure_in_ram(
                    source_path=spec["source_path"],
                    model_id=mid,
                    role=spec.get("role", "anchor"),
                    is_anchor=True,
                )
                prewarmed.append(mid)
            except Exception as exc:
                logger.warning(f"Could not prewarm anchor {mid}: {exc}")

        # 2. Secondary non-anchor models if space allows
        secondaries = [m for m in models if not m.get("is_anchor")]
        spare_limit_bytes = (
            int(max_spare_gb * 1024 * 1024 * 1024)
            if max_spare_gb is not None
            else self.free_budget_bytes
        )

        for spec in secondaries:
            src = Path(spec["source_path"])
            if not src.exists():
                continue
            sz = src.stat().st_size
            if sz <= self.free_budget_bytes and sz <= spare_limit_bytes:
                mid = spec.get("id") or src.name
                try:
                    self.ensure_in_ram(
                        source_path=str(src),
                        model_id=mid,
                        role=spec.get("role", "secondary"),
                        is_anchor=False,
                    )
                    prewarmed.append(mid)
                    spare_limit_bytes -= sz
                except Exception as exc:
                    logger.debug(f"Could not prewarm secondary model {mid}: {exc}")

        return prewarmed

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive status of RAM cache and system memory."""
        sys_total, sys_avail = _get_system_ram_info()
        used = self.current_usage_bytes
        budget = self.budget_bytes

        anchors_list = []
        spare_list = []
        for e in sorted(self.entries.values(), key=lambda x: x.last_used, reverse=True):
            if e.is_anchor:
                anchors_list.append(e.to_dict())
            else:
                spare_list.append(e.to_dict())

        return {
            "ram_dir": str(self.ram_dir),
            "budget_bytes": budget,
            "budget_gb": round(budget / (1024 * 1024 * 1024), 2),
            "used_bytes": used,
            "used_gb": round(used / (1024 * 1024 * 1024), 2),
            "free_budget_gb": round(max(0, budget - used) / (1024 * 1024 * 1024), 2),
            "percent_used": round((used / budget) * 100, 1) if budget else 0.0,
            "system_ram": {
                "total_gb": round(sys_total / (1024 * 1024 * 1024), 2),
                "available_gb": round(sys_avail / (1024 * 1024 * 1024), 2),
            },
            "anchors": list(self.anchors),
            "models_count": len(self.entries),
            "anchor_models": anchors_list,
            "spare_cached_models": spare_list,
        }


# Global singleton instance
_RAM_MANAGER: Optional[RamModelManager] = None


def get_ram_manager() -> RamModelManager:
    global _RAM_MANAGER
    if _RAM_MANAGER is None:
        _RAM_MANAGER = RamModelManager()
    return _RAM_MANAGER
