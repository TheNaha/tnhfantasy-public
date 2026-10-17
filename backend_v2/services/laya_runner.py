"""In-process CPU runner for TurnstileLabs Laya System 1 decision models.

Used as Tier 2 in the Director cascade when the active LLM provider is a
cloud/API service (Modal, Beam, OpenAI-compatible, Anthropic, Google, Ollama)
rather than a `remote_agent` worker with its own `/v1/decisions` endpoint.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from infrastructure.logging import get_logger

logger = get_logger("laya_runner")

_MODEL_REPO_BY_ID: Dict[str, str] = {
    "laya_multilingual": "TurnstileLabs/laya-multilingual-tuned",
    "laya_typed_decisions": "TurnstileLabs/laya-typed-decisions",
    "laya_english": "TurnstileLabs/laya-english-tuned",
}


class LayaRunner:
    """Thread-safe lazy singleton for running Laya System 1 decisions on CPU."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded_repo: Optional[str] = None
        self._model: Any = None
        self._laya_mod: Any = None

    @staticmethod
    def is_available() -> bool:
        """Return True if the `laya` package is importable in this Python environment."""
        try:
            import laya  # noqa: F401

            return True
        except Exception:
            return False

    def resolve_repo_or_path(self, model_id: str) -> str:
        """Resolve a registry model_id (e.g. `laya_multilingual`) to a local path or HF repo."""
        ram_dir = os.path.join("/dev/shm/tnh_ram_cache/decisions", model_id)
        if os.path.isdir(ram_dir) and os.listdir(ram_dir):
            return ram_dir
        data_dir = os.path.join(os.environ.get("DATA_DIR", "/data"), "models", "decisions", model_id)
        if os.path.isdir(data_dir) and os.listdir(data_dir):
            return data_dir
        try:
            from services.llm_router import get_router

            reg = get_router().registry
            if model_id in reg.models and reg.models[model_id].repo:
                return reg.models[model_id].repo
        except Exception:
            pass
        return _MODEL_REPO_BY_ID.get(model_id, model_id)

    def _ensure_loaded(self, model_id: str) -> tuple[Any, Any]:
        import laya

        target = self.resolve_repo_or_path(model_id)
        with self._lock:
            if self._model is not None and self._loaded_repo == target:
                return self._laya_mod, self._model
            started = time.perf_counter()
            model = laya.load(target, device="cpu")
            self._laya_mod = laya
            self._model = model
            self._loaded_repo = target
            logger.info(
                "laya_cpu_model_loaded",
                model_id=model_id,
                source=target,
                load_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return laya, model

    def evaluate(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str = "laya_multilingual",
    ) -> Dict[str, Any]:
        """Evaluate all typed questions in parallel against `context_text` on CPU."""
        laya, model = self._ensure_loaded(model_id)
        started = time.perf_counter()

        decide_kwargs: Dict[str, Any] = {}
        for q in questions:
            key = q["key"]
            q_type = q["type"]
            if q_type == "choice":
                decide_kwargs[key] = laya.choice(
                    question=q["question"],
                    options=q["options"],
                )
            elif q_type == "score":
                rubric = {int(k): v for k, v in (q.get("rubric") or {}).items()}
                decide_kwargs[key] = laya.score(
                    question=q["question"],
                    rubric=rubric,
                )
            elif q_type == "noul":
                decide_kwargs[key] = laya.noul(statement=q["statement"])

        raw_result = model.decide(state=context_text, **decide_kwargs)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        answers: Dict[str, Any] = {}
        for q in questions:
            key = q["key"]
            q_type = q["type"]
            ans = raw_result[key] if isinstance(raw_result, dict) else getattr(raw_result, key, None)
            if ans is None:
                continue
            if q_type == "choice":
                choice_val = getattr(ans, "choice", getattr(ans, "selected", None))
                probs_val = getattr(ans, "probabilities", getattr(ans, "probs", None))
                if isinstance(ans, dict):
                    choice_val = ans.get("choice") or ans.get("selected")
                    probs_val = ans.get("probabilities") or ans.get("probs") or {}
                answers[key] = {
                    "choice": str(choice_val) if choice_val is not None else "",
                    "probabilities": dict(probs_val or {}),
                }
            elif q_type == "score":
                score_val = getattr(ans, "score", getattr(ans, "expected", None))
                if isinstance(ans, dict):
                    score_val = ans.get("score", ans.get("expected", 0.0))
                answers[key] = {"score": float(score_val) if score_val is not None else 0.0}
            elif q_type == "noul":
                prob_val = getattr(ans, "probability", getattr(ans, "true_probability", None))
                if isinstance(ans, dict):
                    prob_val = ans.get("probability", ans.get("true_probability", 0.0))
                elif isinstance(ans, (int, float)):
                    prob_val = float(ans)
                answers[key] = {"probability": float(prob_val) if prob_val is not None else 0.0}

        return {
            "answers": answers,
            "model_id": model_id,
            "engine_used": "local_laya_cpu",
            "latency_ms": latency_ms,
        }


_RUNNER: Optional[LayaRunner] = None


def get_laya_runner() -> LayaRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = LayaRunner()
    return _RUNNER
