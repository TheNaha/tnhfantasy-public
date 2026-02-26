
import os
import json
import time
import shutil
import asyncio
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from datetime import datetime

# Import the function to test
# We need to mock the OUTPUT_DIR in the module or monkeypatch it
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Create a dummy statistics module that mimics the real one but allows us to point to a test dir
from api.routes import statistics
from infrastructure.cache import invalidate_cache

async def benchmark_detailed_stats(num_files=100):
    """
    Benchmark the get_detailed_statistics function with a set number of files.
    """

    # Setup test directory
    test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../test_output_stats"))
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir)

    print(f"Generating {num_files} test images in {test_dir}...")

    # Generate test images with metadata
    for i in range(num_files):
        # Create a small image
        img = Image.new('RGB', (64, 64), color = 'red')

        # Create metadata
        metadata = {
            "metadata_version": "2.0",
            "job": {
                "completed_at": time.time(),
                "duration_seconds": 1.5
            },
            "checkpoint": {
                "name": "sd_xl_base_1.0.safetensors"
            },
            "loras": [
                {"name": "test_lora.safetensors", "weight": 0.8}
            ],
            "sampler": "euler_a",
            "scheduler": "normal",
            "steps": 20,
            "cfg": 7.0,
            "width": 1024,
            "height": 1024,
            "seed": 12345,
            "prompt": "a beautiful landscape",
            "negativePrompt": "ugly, blurry"
        }

        # Save with metadata
        pnginfo = PngInfo()
        pnginfo.add_text("comfy_metadata", json.dumps(metadata))

        # Spread files across a few directories to simulate date structure
        subdir = os.path.join(test_dir, f"subdir_{i % 5}")
        os.makedirs(subdir, exist_ok=True)

        img.save(os.path.join(subdir, f"image_{i}.png"), pnginfo=pnginfo)

    print("Generation complete. Running benchmark...")

    # Monkeypatch OUTPUT_DIR
    original_output_dir = statistics.OUTPUT_DIR
    statistics.OUTPUT_DIR = test_dir

    # Clear cache before starting
    invalidate_cache("stats")

    try:
        # Run 1: Cold start (uncached)
        start_time = time.time()
        result1 = await statistics.get_detailed_statistics()
        end_time = time.time()
        duration1 = end_time - start_time

        print(f"Run 1 (Cold): {result1.get('total_images', 0)} images.")
        print(f"Time taken: {duration1:.4f} seconds")
        print(f"Rate: {result1.get('total_images', 0) / duration1:.2f} images/second")

        # Run 2: Cached
        start_time = time.time()
        result2 = await statistics.get_detailed_statistics()
        end_time = time.time()
        duration2 = end_time - start_time

        print(f"Run 2 (Cached): {result2.get('total_images', 0)} images.")
        print(f"Time taken: {duration2:.4f} seconds")

        # Verify result consistency
        if result1 != result2:
            print("WARNING: Cached result differs from cold result!")

        if duration2 < duration1 * 0.1:
            print("SUCCESS: Caching is effective.")
        else:
            print("WARNING: Caching might not be effective.")

        return duration1, duration2

    finally:
        # Cleanup
        statistics.OUTPUT_DIR = original_output_dir
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(benchmark_detailed_stats(200))
