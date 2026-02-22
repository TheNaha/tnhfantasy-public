import os
from aiohttp import web
from server import PromptServer

# ------- CUDA Device Reset Endpoint -------
# Called after snapshot restore to re-enable GPU

@PromptServer.instance.routes.post("/cuda/set_device")
async def set_current_device(request):
    """Re-enable CUDA device after memory snapshot restore."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    return web.json_response({"status": "success"})


# Empty node mappings (required by ComfyUI custom node system)
NODE_CLASS_MAPPINGS = {}
