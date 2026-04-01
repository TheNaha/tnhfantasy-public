def get_provider_worker_base_url(provider_id: str, port: int = 8000) -> str:
    return f"http://comfy-provider-{provider_id}:{port}"
