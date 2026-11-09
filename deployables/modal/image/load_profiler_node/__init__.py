"""
TNH Load Profiler — Custom ComfyUI Node
=======================================
Monkey-patches ComfyUI's checkpoint/LoRA loaders and model management to emit
precise stage timers. All wrappers use **kwargs to be forward-compatible with
any ComfyUI version without risking TypeError on unknown keyword arguments.

Output: JSON lines to stderr, captured in Modal function logs.
  [TNH_TIMER] {"tag":"TNH_TIMER","stage":"...","elapsed_s":...,"cumulative_s":...,"extra":{...}}

Stages:
  checkpoint_load_start/done  total checkpoint load wall time
  lora_apply_done             per-LoRA apply time
  load_models_gpu             VRAM transfer time + before/after MB
  free_memory                 when/how much ComfyUI evicts
  load_torch_file             disk→CPU read time + key count
"""

import time
import json
import sys
import logging
import threading

logger = logging.getLogger("tnh_load_profiler")

_t0_global = time.perf_counter()
_patch_lock = threading.Lock()
_already_patched: set = set()


def _emit(stage: str, elapsed_s: float, extra: dict = None):
    cumulative = time.perf_counter() - _t0_global
    line = json.dumps({
        "tag": "TNH_TIMER",
        "stage": stage,
        "elapsed_s": round(elapsed_s, 4),
        "cumulative_s": round(cumulative, 4),
        "extra": extra or {},
    })
    print(f"[TNH_TIMER] {line}", file=sys.stderr, flush=True)


def _patch_checkpoint_loader():
    with _patch_lock:
        if "checkpoint_loader" in _already_patched:
            return
        _already_patched.add("checkpoint_loader")
    try:
        import comfy.sd as _sd
    except ImportError:
        return

    _orig = _sd.load_checkpoint_guess_config

    def _timed(*args, **kwargs):
        ckpt_path = args[0] if args else kwargs.get("ckpt_path", "?")
        extra = {"ckpt_path": str(ckpt_path)}
        _emit("checkpoint_load_start", 0.0, extra)
        t0 = time.perf_counter()
        result = _orig(*args, **kwargs)
        _emit("checkpoint_load_done", time.perf_counter() - t0, extra)
        return result

    _sd.load_checkpoint_guess_config = _timed
    logger.info("[TNH_PROFILER] Patched load_checkpoint_guess_config")


def _patch_lora_loader():
    with _patch_lock:
        if "lora_loader" in _already_patched:
            return
        _already_patched.add("lora_loader")
    try:
        import comfy.sd as _sd
    except ImportError:
        return

    _orig = _sd.load_lora_for_models

    def _timed(*args, **kwargs):
        t0 = time.perf_counter()
        result = _orig(*args, **kwargs)
        _emit("lora_apply_done", time.perf_counter() - t0, {})
        return result

    _sd.load_lora_for_models = _timed
    logger.info("[TNH_PROFILER] Patched load_lora_for_models")


def _patch_model_management():
    with _patch_lock:
        if "model_management" in _already_patched:
            return
        _already_patched.add("model_management")
    try:
        import comfy.model_management as _mm
        import torch
    except ImportError:
        return

    def _vram_mb():
        try:
            return torch.cuda.memory_allocated() // (1024 * 1024) if torch.cuda.is_available() else 0
        except Exception:
            return -1

    if hasattr(_mm, "load_models_gpu"):
        _orig_load = _mm.load_models_gpu

        def _timed_load(*args, **kwargs):
            before = _vram_mb()
            t0 = time.perf_counter()
            result = _orig_load(*args, **kwargs)
            after = _vram_mb()
            n = len(args[0]) if args and hasattr(args[0], "__len__") else "?"
            _emit("load_models_gpu", time.perf_counter() - t0, {
                "n_models": n,
                "vram_before_mb": before,
                "vram_after_mb": after,
                "vram_delta_mb": after - before,
            })
            return result

        _mm.load_models_gpu = _timed_load
        logger.info("[TNH_PROFILER] Patched load_models_gpu")

    if hasattr(_mm, "free_memory"):
        _orig_free = _mm.free_memory

        def _timed_free(*args, **kwargs):
            before = _vram_mb()
            t0 = time.perf_counter()
            result = _orig_free(*args, **kwargs)
            after = _vram_mb()
            req = args[0] if args else kwargs.get("memory_required", "?")
            dev = args[1] if len(args) > 1 else kwargs.get("device", "?")
            _emit("free_memory", time.perf_counter() - t0, {
                "requested_bytes": req,
                "device": str(dev),
                "vram_before_mb": before,
                "vram_after_mb": after,
                "freed_mb": before - after,
            })
            return result

        _mm.free_memory = _timed_free
        logger.info("[TNH_PROFILER] Patched free_memory")


def _patch_safetensors_loader():
    with _patch_lock:
        if "safetensors" in _already_patched:
            return
        _already_patched.add("safetensors")
    try:
        import comfy.utils as _utils
        if not hasattr(_utils, "load_torch_file"):
            return
    except ImportError:
        return

    _orig = _utils.load_torch_file

    def _timed(*args, **kwargs):
        ckpt = args[0] if args else "?"
        t0 = time.perf_counter()
        result = _orig(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        # result may be state_dict OR (state_dict, metadata) tuple
        sd = result[0] if isinstance(result, tuple) else result
        n_keys = len(sd) if hasattr(sd, "__len__") else "?"
        _emit("load_torch_file", elapsed, {
            "path": str(ckpt),
            "n_keys": n_keys,
            "kwargs": list(kwargs.keys()),
        })
        return result

    _utils.load_torch_file = _timed
    logger.info("[TNH_PROFILER] Patched load_torch_file")

def _patch_save_image():
    with _patch_lock:
        if "save_image" in _already_patched:
            return
        _already_patched.add("save_image")
    try:
        import nodes
        if hasattr(nodes, "SaveImage"):
            _orig_init = nodes.SaveImage.__init__
            def _fast_init(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                self.compress_level = 1
            nodes.SaveImage.__init__ = _fast_init
            logger.info("[TNH_PROFILER] Patched SaveImage.compress_level = 1 for fast lossless encoding")
    except Exception as e:
        logger.warning(f"[TNH_PROFILER] Could not patch SaveImage: {e}")


# ─── Apply all patches at import time via a deferred background thread ─────────
_emit("profiler_init", 0.0, {"pid": __import__("os").getpid()})


def _deferred_patch():
    time.sleep(2)  # Wait for ComfyUI core modules to finish importing
    _patch_checkpoint_loader()
    _patch_lora_loader()
    _patch_model_management()
    _patch_safetensors_loader()
    _patch_save_image()
    _emit("profiler_patches_applied", 0.0)


threading.Thread(target=_deferred_patch, daemon=True).start()


# ─── Dummy node (required to register the custom node) ────────────────────────
class TNHLoadProfiler:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "noop"
    CATEGORY = "TNH/Debug"
    OUTPUT_NODE = True

    def noop(self):
        try:
            import torch
            vram_mb = torch.cuda.memory_allocated() // (1024 * 1024) if torch.cuda.is_available() else -1
        except Exception:
            vram_mb = -1
        return (f"TNH Load Profiler active | VRAM={vram_mb}MB",)


NODE_CLASS_MAPPINGS = {"TNHLoadProfiler": TNHLoadProfiler}
NODE_DISPLAY_NAME_MAPPINGS = {"TNHLoadProfiler": "TNH Load Profiler"}
