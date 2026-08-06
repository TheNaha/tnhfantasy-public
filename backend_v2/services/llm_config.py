"""Shared LLM configuration helpers used by chats and stories routes."""

import json
import os


_CONFIG_PATH = "/data/llm_config.json"


def get_default_llm_model() -> str:
    """Read the user-selected LLM model from llm_config.json. Returns 'default' if not set."""
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
                return data.get("model_id") or "default"
        except Exception:
            pass
    return "default"
