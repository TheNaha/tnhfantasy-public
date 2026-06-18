from typing import Dict, Any
from core.entities import Provider

from services.provider_utils import (
    ensure_provider_v2_shape,
    extract_runtime_config,
    extract_deploy_config,
    clean_dict
)

def build_provider_environment(provider: Provider) -> Dict[str, str]:
    provider = ensure_provider_v2_shape(provider)
    runtime_config = extract_runtime_config(provider.type, provider.container_config, provider.config or {}) or {}
    deploy_config = extract_deploy_config(provider.type, provider.config or {})
    credentials = clean_dict(provider.credentials)

    env_vars: Dict[str, str] = {}
    worker_config = clean_dict(runtime_config.get("worker"))
    if "max_concurrent_downloads" in worker_config:
        env_vars["MAX_CONCURRENT_DOWNLOADS"] = str(worker_config["max_concurrent_downloads"])
    if "reconciliation_interval_seconds" in worker_config:
        env_vars["RECONCILIATION_INTERVAL_SECONDS"] = str(int(float(worker_config["reconciliation_interval_seconds"])))
    elif "reconciliation_interval_hours" in worker_config:
        env_vars["RECONCILIATION_INTERVAL_SECONDS"] = str(
            int(float(worker_config["reconciliation_interval_hours"]) * 3600)
        )
    if "reconciliation_startup_delay_seconds" in worker_config:
        env_vars["RECONCILIATION_STARTUP_DELAY_SECONDS"] = str(
            int(float(worker_config["reconciliation_startup_delay_seconds"]))
        )
    if "validation_timeout_seconds" in worker_config:
        env_vars["VALIDATION_TIMEOUT_SECONDS"] = str(worker_config["validation_timeout_seconds"])

    if "hf_token" in credentials:
        env_vars["HF_TOKEN"] = credentials["hf_token"]
    if "civitai_token" in credentials:
        env_vars["CIVITAI_TOKEN"] = credentials["civitai_token"]

    if provider.type == "modal":
        if "token_id" in credentials:
            env_vars["MODAL_TOKEN_ID"] = credentials["token_id"]
        if "token_secret" in credentials:
            env_vars["MODAL_TOKEN_SECRET"] = credentials["token_secret"]
        if "username" in credentials:
            env_vars["MODAL_USERNAME"] = credentials["username"]
        if "app_name" in deploy_config:
            env_vars["MODAL_APP_NAME"] = deploy_config["app_name"]
        if "enable_memory_snapshot" in deploy_config:
            env_vars["ENABLE_MEMORY_SNAPSHOT"] = str(bool(deploy_config["enable_memory_snapshot"])).lower()

        comfyui = clean_dict(clean_dict(deploy_config.get("functions")).get("comfyui"))
        if "gpu_type" in comfyui:
            env_vars["MODAL_GPU_TYPE"] = comfyui["gpu_type"]
        if "cpu" in comfyui:
            env_vars["MODAL_GPU_CPU"] = str(comfyui["cpu"])
        if "timeout_seconds" in comfyui:
            env_vars["MODAL_GPU_TIMEOUT"] = str(comfyui["timeout_seconds"])
        if "max_containers" in comfyui:
            env_vars["MODAL_GPU_MAX_CONTAINERS"] = str(comfyui["max_containers"])
        if "scaledown_window_seconds" in comfyui:
            env_vars["MODAL_GPU_SCALEDOWN"] = str(comfyui["scaledown_window_seconds"])
        if "stall_timeout_seconds" in comfyui:
            env_vars["MODAL_COMFYUI_STALL_TIMEOUT_SECONDS"] = str(comfyui["stall_timeout_seconds"])
        if "max_runs_before_restart" in comfyui:
            env_vars["MODAL_COMFYUI_MAX_RUNS_BEFORE_RESTART"] = str(comfyui["max_runs_before_restart"])
        if "healthcheck_timeout_seconds" in comfyui:
            env_vars["MODAL_COMFYUI_HEALTHCHECK_TIMEOUT_SECONDS"] = str(comfyui["healthcheck_timeout_seconds"])
        if "capture_stall_diagnostics" in comfyui:
            env_vars["MODAL_COMFYUI_CAPTURE_STALL_DIAGNOSTICS"] = str(bool(comfyui["capture_stall_diagnostics"])).lower()
        if "stall_diagnostics_timeout_seconds" in comfyui:
            env_vars["MODAL_COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS"] = str(comfyui["stall_diagnostics_timeout_seconds"])
        if "stall_diagnostics_max_chars" in comfyui:
            env_vars["MODAL_COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS"] = str(comfyui["stall_diagnostics_max_chars"])

        download = clean_dict(clean_dict(deploy_config.get("functions")).get("download"))
        if "timeout_seconds" in download:
            env_vars["MODAL_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
        if "max_containers" in download:
            env_vars["MODAL_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])

        storage = clean_dict(clean_dict(deploy_config.get("functions")).get("storage"))
        if "timeout_seconds" in storage:
            env_vars["MODAL_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
        if "max_containers" in storage:
            env_vars["MODAL_STORAGE_MAX_CONTAINERS"] = str(storage["max_containers"])

    elif provider.type == "beam":
        if "api_key" in credentials:
            env_vars["BEAM_API_KEY"] = credentials["api_key"]
        if "workspace_id" in credentials:
            env_vars["BEAM_WORKSPACE_ID"] = credentials["workspace_id"]

        beta9_token = credentials.get("beta9_token") or credentials.get("api_key")
        if beta9_token:
            env_vars["BETA9_TOKEN"] = beta9_token
            env_vars["BEAM_TOKEN"] = beta9_token

        beta9_gateway_host = (
            deploy_config.get("beta9_gateway_host")
            or deploy_config.get("gateway_host")
            or "gateway.beam.cloud"
        )
        beta9_gateway_port = (
            deploy_config.get("beta9_gateway_port")
            or deploy_config.get("gateway_port")
            or 443
        )
        env_vars["BETA9_GATEWAY_HOST"] = str(beta9_gateway_host)
        env_vars["BETA9_GATEWAY_PORT"] = str(beta9_gateway_port)
        env_vars["GATEWAY_HOST"] = str(beta9_gateway_host)
        env_vars["GATEWAY_PORT"] = str(beta9_gateway_port)

        beta9_api_host = deploy_config.get("api_host") or "app.beam.cloud"
        beta9_api_port = deploy_config.get("api_port") or 443
        env_vars["API_HOST"] = str(beta9_api_host)
        env_vars["API_PORT"] = str(beta9_api_port)

        if "gpu_url" in deploy_config:
            env_vars["BEAM_GPU_URL"] = deploy_config["gpu_url"]
        if "storage_url" in deploy_config:
            env_vars["BEAM_STORAGE_URL"] = deploy_config["storage_url"]
        if "download_url" in deploy_config:
            env_vars["BEAM_DOWNLOAD_URL"] = deploy_config["download_url"]
        if "gpu_type" in deploy_config:
            env_vars["BEAM_GPU_TYPE"] = deploy_config["gpu_type"]

        beam_functions = clean_dict(deploy_config.get("functions"))
        gpu_func = clean_dict(beam_functions.get("comfyui"))
        if "gpu_type" in gpu_func:
            env_vars["BEAM_GPU_TYPE"] = gpu_func["gpu_type"]
        if "cpu" in gpu_func:
            env_vars["BEAM_GPU_CPU"] = str(gpu_func["cpu"])
        if "memory" in gpu_func:
            env_vars["BEAM_GPU_MEMORY"] = str(gpu_func["memory"])
        if "timeout_seconds" in gpu_func:
            env_vars["BEAM_GPU_TIMEOUT"] = str(gpu_func["timeout_seconds"])
        if "keep_warm_seconds" in gpu_func:
            env_vars["BEAM_GPU_KEEP_WARM"] = str(gpu_func["keep_warm_seconds"])
        if "concurrent_requests" in gpu_func:
            env_vars["BEAM_GPU_CONCURRENT"] = str(gpu_func["concurrent_requests"])

        download = clean_dict(beam_functions.get("download"))
        if "cpu" in download:
            env_vars["BEAM_DOWNLOAD_CPU"] = str(download["cpu"])
        if "memory" in download:
            env_vars["BEAM_DOWNLOAD_MEMORY"] = str(download["memory"])
        if "timeout_seconds" in download:
            env_vars["BEAM_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
        if "max_containers" in download:
            env_vars["BEAM_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])

        storage = clean_dict(beam_functions.get("storage"))
        if "cpu" in storage:
            env_vars["BEAM_STORAGE_CPU"] = str(storage["cpu"])
        if "memory" in storage:
            env_vars["BEAM_STORAGE_MEMORY"] = str(storage["memory"])
        if "timeout_seconds" in storage:
            env_vars["BEAM_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
        if "concurrent_requests" in storage:
            env_vars["BEAM_STORAGE_CONCURRENT"] = str(storage["concurrent_requests"])

    return env_vars
