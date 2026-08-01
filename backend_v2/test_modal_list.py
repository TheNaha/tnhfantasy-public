import asyncio
import modal
import sys
import os

MODAL_APP_NAME = "comfy-modal-stack"

async def main():
    f = modal.Function.from_name(MODAL_APP_NAME, "list_models_with_metadata")
    files = await f.remote.aio("models/checkpoints")
    print(f"models/checkpoints: {len(files)} files")
    if files:
        print(files[0])

if __name__ == "__main__":
    asyncio.run(main())
