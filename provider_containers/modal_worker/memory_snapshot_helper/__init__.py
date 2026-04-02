import os


def _get_prompt_server():
    try:
        from server import PromptServer
    except Exception:
        return None
    return PromptServer


def _get_aiohttp_web():
    try:
        from aiohttp import web
    except Exception:
        return None
    return web


async def set_current_device(request):
    """Re-enable CUDA device after memory snapshot restore."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

    web = _get_aiohttp_web()
    payload = {"status": "success"}
    if web is not None and hasattr(web, "json_response"):
        return web.json_response(payload)
    return payload


def register_cuda_device_route() -> bool:
    """Register the CUDA reset route when running inside a ComfyUI server."""
    prompt_server = _get_prompt_server()
    routes = getattr(getattr(prompt_server, "instance", None), "routes", None)
    if routes is None or not hasattr(routes, "post"):
        return False

    routes.post("/cuda/set_device")(set_current_device)
    return True


register_cuda_device_route()

# Empty node mappings (required by ComfyUI custom node system)
NODE_CLASS_MAPPINGS = {}
