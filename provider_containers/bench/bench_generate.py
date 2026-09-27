"""
TNH Modal Benchmark — Real Image Generation + Load Profiling
============================================================
Runs a suite of timed image generation experiments against the deployed
ComfyUIStable app to characterise:

  1. Cold-start latency (first call on a fresh container)
  2. Warm repeat latency (same checkpoint, same LoRAs)
  3. LoRA-threshold effect (0→4 LoRAs, same checkpoint)
  4. VRAM fragmentation (25 consecutive runs to stress the KSampler hang)

Usage (from provider_containers/bench/ with venv active)
-------------------------------------------------------
  modal run bench_generate.py                  # LoRA sweep (default)
  modal run bench_generate.py --suite cold     # cold-start + warm repeats
  modal run bench_generate.py --suite lora     # LoRA 0→4 threshold sweep
  modal run bench_generate.py --suite stress   # 25-run KSampler hang test
  modal run bench_generate.py --suite all      # everything

Results → local JSON file (printed path at end)
Profiler → modal app logs comfy-modal-stack | grep TNH_TIMER
VRAM     → modal app logs comfy-modal-stack | grep VRAM

Design note: This file must NOT import from modal_app.py at module level.
Modal re-imports this file inside the save_to_volume container where
modal_app.py does not exist. All cross-app references use from_name().
"""

import modal
import json
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── App + volume references (by name — no local import) ─────────────────────
MODAL_APP_NAME   = "comfy-modal-stack"
MODAL_CLS_NAME   = "ComfyUIStable"
VOLUME_NAME      = "comfy-storage-v2"

_bench_app = modal.App("bench-generate")
_bench_vol = modal.Volume.from_name(VOLUME_NAME)

# ─── Benchmark parameters ─────────────────────────────────────────────────────
CHECKPOINT = "nova_anime_xl_il_v190_2940478.safetensors"

# 4 Illustrious-compatible LoRAs confirmed on the volume
LORA_CANDIDATES = [
    ("breast_size_slider_lora_illust_v10_-_initial_release_1309969.safetensors", 0.7),
    ("arched_back_v10_592264.safetensors", 0.6),
    ("archer_pose_-_poses_booru_2066997.safetensors", 0.6),
    ("aomori_mine_bluearchive_ilxl_k_v10_1822400.safetensors", 0.8),
]

POSITIVE_PROMPT = (
    "masterpiece, best quality, very aesthetic, absurdres, "
    "1girl, solo, standing, looking at viewer, smile, "
    "long hair, school uniform, outdoors, blue sky"
)
NEGATIVE_PROMPT = "ugly, bad quality, lowres, blur, worst quality, blurry details"

# Fast settings — exercises checkpoint/LoRA load + KSampler without wasting GPU time
BENCH_STEPS = 6
BENCH_CFG   = 1.0
BENCH_W     = 896
BENCH_H     = 1152


# ─── Workflow builder ─────────────────────────────────────────────────────────

def _build_workflow(seed: int, loras: list[tuple[str, float]] = None) -> dict:
    """
    Minimal ComfyUI API-JSON workflow.
    LoRAs are chained between the checkpoint and the CLIP/KSampler nodes.
    """
    nodes: dict = {}
    loras = loras or []

    # Checkpoint
    nodes["4"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": CHECKPOINT},
    }
    model_ref = ["4", 0]
    clip_ref  = ["4", 1]

    # LoRA chain
    for i, (lora_name, strength) in enumerate(loras):
        nid = str(11 + i)
        nodes[nid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model":         model_ref,
                "clip":          clip_ref,
                "lora_name":     lora_name,
                "strength_model": strength,
                "strength_clip":  strength,
            },
        }
        model_ref = [nid, 0]
        clip_ref  = [nid, 1]

    # CLIP encode
    nodes["6"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"text": POSITIVE_PROMPT, "clip": clip_ref}}
    nodes["7"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"text": NEGATIVE_PROMPT, "clip": clip_ref}}

    # Latent + sampler
    nodes["5"]  = {"class_type": "EmptyLatentImage",
                   "inputs": {"width": BENCH_W, "height": BENCH_H, "batch_size": 1}}
    nodes["10"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref, "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0], "seed": seed,
            "steps": BENCH_STEPS, "cfg": BENCH_CFG,
            "sampler_name": "euler_ancestral", "scheduler": "normal",
            "denoise": 1.0,
        },
    }

    # Decode + save
    nodes["8"] = {"class_type": "VAEDecode",
                  "inputs": {"samples": ["10", 0], "vae": ["4", 2]}}
    nodes["9"] = {"class_type": "SaveImage",
                  "inputs": {"images": ["8", 0], "filename_prefix": "bench_"}}
    return nodes


# ─── Single run helper ────────────────────────────────────────────────────────

def _run_one(instance, label: str, loras: list,
             seed: Optional[int] = None) -> dict:
    seed = seed if seed is not None else random.randint(0, 2**32 - 1)
    workflow = _build_workflow(seed, loras)
    t0 = time.perf_counter()
    final_status = "unknown"
    n_progress = 0
    last_node = None
    error_msg = None

    try:
        for update in instance.run.remote_gen(workflow):
            if not isinstance(update, dict):
                continue
            st = update.get("status")
            if st == "progress":
                n_progress += 1
            elif st == "executing":
                last_node = update.get("node")
            elif st == "success":
                final_status = "success"
            elif st == "error":
                final_status = "error"
                error_msg = update.get("message", "")
    except Exception as exc:
        final_status = "exception"
        error_msg = str(exc)

    elapsed = time.perf_counter() - t0
    lora_short = ",".join(n.split("_")[0] for n, _ in loras[:2])
    lora_display = f"{len(loras)}L" + (f"({lora_short}...)" if loras else "")

    entry = {
        "label": label, "seed": seed,
        "lora_count": len(loras),
        "loras": [n for n, _ in loras],
        "status": final_status, "error": error_msg,
        "wall_s": round(elapsed, 2),
        "n_progress_ticks": n_progress,
        "last_node": last_node,
    }

    flag = " ← SLOW!" if elapsed > 60 and final_status == "success" else \
           " ← ERROR" if final_status != "success" else ""
    print(
        f"  [{label:<28}] {final_status:<10} {elapsed:6.1f}s  {lora_display}{flag}",
        flush=True,
    )
    if error_msg:
        print(f"    error: {error_msg}", flush=True)
    return entry


# ─── Volume save helper (runs remotely — must NOT import modal_app) ───────────

@_bench_app.function(
    image=modal.Image.debian_slim(python_version="3.13"),
    volumes={"/mnt/data": _bench_vol},
    timeout=30,
)
def _save_to_volume(content: str, rel_path: str) -> str:
    """Write JSON results to the Modal volume under /mnt/data/<rel_path>."""
    import pathlib
    p = pathlib.Path("/mnt/data") / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _bench_vol.commit()
    return str(p)


# ─── Summary printer ──────────────────────────────────────────────────────────

def _print_summary(results: dict):
    W = 68
    print("\n" + "=" * W)
    print(f"BENCHMARK SUMMARY — suite={results['suite']}")
    print(f"  checkpoint : {results['checkpoint']}")
    print(f"  workflow   : {results['steps']} steps, CFG={results['cfg']}, "
          f"{results['width']}x{results['height']}")
    print("=" * W)
    print(f"  {'label':<30} {'status':<12} {'wall_s':>7} {'loras':>5}")
    print("  " + "-" * (W - 2))
    for r in results["runs"]:
        flag = " ★ SLOW" if r["wall_s"] > 60 and r["status"] == "success" else \
               " ✗ FAIL" if r["status"] != "success" else ""
        print(f"  {r['label']:<30} {r['status']:<12} {r['wall_s']:>7.1f}"
              f" {r['lora_count']:>5}{flag}")
    print("=" * W)

    # LoRA threshold analysis
    lora_first = [r for r in results["runs"]
                  if r["label"].startswith("lora_") and r["label"].endswith("_first")]
    if len(lora_first) >= 2:
        print("\n  LoRA threshold (first-run wall times):")
        prev = None
        for r in lora_first:
            n, w = r["lora_count"], r["wall_s"]
            jump = f"  ← +{w - prev:.0f}s JUMP" if prev and (w - prev) > 30 else ""
            print(f"    {n} LoRA(s): {w:.1f}s{jump}")
            prev = w

    # Stress analysis
    stress = [r for r in results["runs"] if r["label"].startswith("stress_")]
    if stress:
        ok = [r for r in stress if r["status"] == "success"]
        fail = [r for r in stress if r["status"] != "success"]
        print(f"\n  Stress: {len(ok)}/{len(stress)} succeeded")
        if fail:
            print(f"    First fail: {fail[0]['label']} — {fail[0]['status']}")
        if ok:
            times = [r["wall_s"] for r in ok]
            print(f"    Times min/avg/max: "
                  f"{min(times):.1f}s / {sum(times)/len(times):.1f}s / {max(times):.1f}s")
    print()


# ─── Local entrypoint ─────────────────────────────────────────────────────────

@_bench_app.local_entrypoint()
def main(suite: str = "lora"):
    """
    Run benchmark against the deployed comfy-modal-stack.

    --suite lora    LoRA 0→4 threshold sweep, each with a warm repeat (default)
    --suite cold    Cold-start (0 LoRAs vs 3 LoRAs) + 3 warm repeats
    --suite stress  25 consecutive 3-LoRA runs to hit the KSampler hang
    --suite all     Everything above in sequence
    """
    print(f"\nTNH Benchmark  suite={suite}")
    print(f"App/class    : {MODAL_APP_NAME}/{MODAL_CLS_NAME}")
    print(f"Checkpoint   : {CHECKPOINT}")
    print(f"Workflow     : {BENCH_STEPS} steps, CFG={BENCH_CFG}, {BENCH_W}×{BENCH_H}")
    print(f"Started      : {datetime.now(timezone.utc).isoformat()}")
    print()
    print("Tip: In another terminal run:")
    print("  modal app logs comfy-modal-stack | grep -E 'TNH_TIMER|VRAM:'")
    print()

    # Look up the already-deployed class by name (no local import needed)
    ComfyUIStable = modal.Cls.from_name(MODAL_APP_NAME, MODAL_CLS_NAME)
    instance = ComfyUIStable()

    results = {
        "suite": suite,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint": CHECKPOINT,
        "steps": BENCH_STEPS, "cfg": BENCH_CFG,
        "width": BENCH_W, "height": BENCH_H,
        "runs": [],
    }

    # ── Cold start ────────────────────────────────────────────────────────
    if suite in ("all", "cold"):
        print("=== COLD START ===")
        results["runs"].append(_run_one(instance, "cold_0lora", []))
        results["runs"].append(_run_one(instance, "cold_3lora", LORA_CANDIDATES[:3]))
        print("\n=== WARM REPEAT (0 LoRAs, 3×) ===")
        for i in range(3):
            results["runs"].append(_run_one(instance, f"warm_{i+1}", []))

    # ── LoRA threshold sweep ──────────────────────────────────────────────
    if suite in ("all", "lora"):
        print("\n=== LORA THRESHOLD SWEEP (0→4 LoRAs) ===")
        print(f"  {'label':<30} {'status':<10} {'wall_s':>7}  loras")
        for n in range(5):
            loras = LORA_CANDIDATES[:n]
            results["runs"].append(_run_one(instance, f"lora_{n}L_first", loras))
            results["runs"].append(_run_one(instance, f"lora_{n}L_warm",  loras))

    # ── Stress test ───────────────────────────────────────────────────────
    if suite in ("all", "stress"):
        print("\n=== STRESS: 25 runs with 3 LoRAs ===")
        for i in range(25):
            entry = _run_one(instance, f"stress_{i+1:02d}", LORA_CANDIDATES[:3])
            results["runs"].append(entry)
            if entry["status"] != "success":
                print(f"  !! Stopped at run {i+1}: {entry['status']}", flush=True)
                break

    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    _print_summary(results)

    # Save locally
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    local_path = Path(__file__).parent / f"bench_results_{ts}.json"
    local_path.write_text(json.dumps(results, indent=2))
    print(f"Local results  : {local_path}")

    # Save to volume
    rel = f"diagnostics/bench/bench_{ts}.json"
    try:
        vol_path = _save_to_volume.remote(json.dumps(results, indent=2), rel)
        print(f"Volume results : {vol_path}")
    except Exception as exc:
        print(f"Volume save skipped: {exc}")

    print("\nDone!")
    print("Check Modal logs for [TNH_TIMER] stage timings and VRAM lines.")
