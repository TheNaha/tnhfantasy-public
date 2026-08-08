import modal
import time

app = modal.App("volume-prewarm-bench")
vol = modal.Volume.from_name("comfy-storage-v2")  # match your real volume name

image = modal.Image.debian_slim().pip_install("torch", "safetensors")

@app.function(image=image, volumes={"/mnt/data": vol}, gpu="L4", timeout=600)
def bench_lazy_load(checkpoint_path: str, prewarm: bool):
    import os
    from safetensors import safe_open
    import torch

    full_path = f"/mnt/data/{checkpoint_path}"
    size_gb = os.path.getsize(full_path) / (1024**3)

    prewarm_s = 0.0
    if prewarm:
        t0 = time.perf_counter()
        with open(full_path, "rb") as f:
            while f.read(64 * 1024 * 1024):
                pass
        prewarm_s = time.perf_counter() - t0

    # This mirrors what ComfyUI actually does: open once, then pull
    # tensors out one key at a time (lazy access), not one big read.
    t1 = time.perf_counter()
    tensors = {}
    with safe_open(full_path, framework="pt", device="cpu") as f:
        for key in f.keys():
            tensors[key] = f.get_tensor(key)
    lazy_load_s = time.perf_counter() - t1

    t2 = time.perf_counter()
    gpu_tensors = {k: v.to("cuda") for k, v in tensors.items()}
    torch.cuda.synchronize()
    gpu_transfer_s = time.perf_counter() - t2

    return {
        "prewarm": prewarm,
        "size_gb": round(size_gb, 3),
        "num_tensors": len(tensors),
        "prewarm_s": round(prewarm_s, 3),
        "lazy_load_s": round(lazy_load_s, 3),
        "gpu_transfer_s": round(gpu_transfer_s, 3),
        "total_s": round(prewarm_s + lazy_load_s + gpu_transfer_s, 3),
    }

@app.local_entrypoint()
def main(checkpoint_path: str = "models/checkpoints/nova_anime_xl_il_v190_2940478.safetensors"):
    print("=== COLD, no prewarm (true cold-cache — what production sees on first load) ===")
    result_cold = bench_lazy_load.remote(checkpoint_path, prewarm=False)
    print(result_cold)

    print("\n=== WARM, with prewarm sequential read first ===")
    result_warm = bench_lazy_load.remote(checkpoint_path, prewarm=True)
    print(result_warm)

    cold_total = result_cold["total_s"]
    warm_total = result_warm["total_s"]
    print(f"\n=== SUMMARY ===")
    print(f"  cold total : {cold_total:.2f}s")
    print(f"  warm total : {warm_total:.2f}s")
    print(f"  speedup    : {cold_total / warm_total:.1f}x")
    print()
    print("NOTE: Production ComfyUI loads ~4 files in sequence (UNet + CLIP-G + CLIP-L + VAE).")
    print("Multiply single-file numbers by ~3-4x for a rough real-world estimate.")
    print("Use bench_generate.py for an end-to-end wall-clock measurement with real inference.")