def provider_container_name(provider_id: str) -> str:
    return f"tnhcomfy-{provider_id}"


def get_provider_worker_base_url(provider_id: str, port: int = 8000) -> str:
    return f"http://tnhcomfy-{provider_id}:{port}"
