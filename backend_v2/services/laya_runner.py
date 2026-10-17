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
    "laya_multilingual": "convaiinnovations/laya-multilingual",
    "laya_typed_decisions": "convaiinnovations/laya-typed-decisions",
    "laya_english": "convaiinnovations/laya",
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

        questions_dict: Dict[str, Any] = {}
        min_rubric_val: Dict[str, int] = {}
        for q in questions:
            key = q["key"]
            q_type = q.get("type")
            if q_type == "choice":
                opts = q.get("options")
                if isinstance(opts, dict):
                    criteria = opts
                elif isinstance(opts, list):
                    criteria = opts
                else:
                    criteria = []
                questions_dict[key] = {
                    "type": "choice",
                    "instructions": q.get("question") or q.get("prompt") or "",
                    "criteria": criteria,
                }
            elif q_type == "score":
                rubric_raw = q.get("rubric") or {}
                if isinstance(rubric_raw, dict):
                    sorted_keys = sorted(rubric_raw.keys(), key=lambda x: int(x))
                    min_rubric_val[key] = int(sorted_keys[0]) if sorted_keys else 1
                    criteria = [rubric_raw[k] for k in sorted_keys]
                else:
                    min_rubric_val[key] = 1
                    criteria = [str(x) for x in (q.get("options") or [])]
                questions_dict[key] = {
                    "type": "score",
                    "instructions": q.get("question") or q.get("prompt") or "",
                    "criteria": criteria or ["1", "2", "3", "4", "5"],
                }
            elif q_type in ("noul", "yes_no"):
                questions_dict[key] = {
                    "type": "noul",
                    "instructions": q.get("statement") or q.get("prompt") or q.get("question") or "",
                }

        raw_result = model.predict(context_text, questions_dict)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        raw_answers = raw_result.get("answers", {}) if isinstance(raw_result, dict) else {}
        answers: Dict[str, Any] = {}
        for q in questions:
            key = q["key"]
            q_type = q.get("type")
            ans = raw_answers.get(key)
            if ans is None:
                continue
            if q_type == "choice":
                choice_val = ans.get("choice") or ans.get("selected")
                probs_val = ans.get("probabilities") or ans.get("probs") or {}
                answers[key] = {
                    "choice": str(choice_val) if choice_val is not None else "",
                    "probabilities": dict(probs_val or {}),
                }
            elif q_type == "score":
                score_raw = ans.get("score")
                if score_raw is None:
                    score_raw = ans.get("expected", 0.0)
                # Laya scores expected 0-based index: sum(p_i * i). Map to rubric start if needed:
                score_num = float(score_raw)
                offset = min_rubric_val.get(key, 0)
                if offset > 0:
                    score_num += float(offset)
                answers[key] = {"score": round(score_num, 2)}
            elif q_type in ("noul", "yes_no"):
                prob_val = ans.get("noul") if "noul" in ans else ans.get("probability", 0.0)
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
