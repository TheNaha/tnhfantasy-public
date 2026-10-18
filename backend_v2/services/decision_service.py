"""System 1 Decision Maker ("Director") service with 4-tier provider cascade.

Cascade order:
  1. Remote Agent (`remote_hybrid` / `remote_llm` / Colab) via `POST /v1/decisions`
     running Laya on CPU/RAM (`/dev/shm/tnh_ram_cache/decisions`) with 0 MB GPU VRAM.
  2. Backend In-Process CPU `LayaRunner` (`services/laya_runner.py`) when `laya` is
     installed locally or when using cloud/API providers (`modal_llm`, `beam_llm`,
     `openai_compat`, `ollama`, `anthropic`, `google`).
  3. Structured Generative JSON Fallback on the active `util` LLM provider (when
     `active_decisions == "same_as_util"` or when Laya is not installed locally).
  4. Deterministic Heuristic Fallback (`heuristic_director_decision`) so the
     Director never fails or blocks a roleplay turn.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx
from sqlmodel import Session, select

from core.entities import Provider
from infrastructure.logging import get_logger
from services.decision_schema import (
    DirectorDecisionResult,
    build_director_questions,
    build_generative_fallback_prompt,
    format_director_context,
    heuristic_director_decision,
    parse_director_result,
    parse_generative_fallback_json,
    resolve_fate_check,
)
from services.laya_runner import get_laya_runner
from services.llm_config import get_active_models, resolve_default_provider

logger = get_logger("decision_service")


class DecisionService:
    """Evaluates the 13-question Director rubric across any configured provider."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _active_decisions_model(self) -> str:
        active = get_active_models()
        return active.get("decisions") or "laya_multilingual"

    def _find_remote_agent_target(self) -> Optional[tuple[str, str, str]]:
        """Return `(provider_id, agent_url, agent_token)` for an enabled remote worker."""
        try:
            from services.engines.engine_factory import get_engine

            providers = self.session.exec(
                select(Provider)
                .where(
                    Provider.worker_type.in_(["llm", "hybrid"]),
                    Provider.enabled == True,  # noqa: E712
                )
                .order_by(Provider.priority, Provider.id)
            ).all()
            for provider in providers:
                if provider.type not in ("remote_hybrid", "remote_llm"):
                    continue
                engine = get_engine(provider.id, provider)
                if engine is None:
                    continue
                agent_url = getattr(engine, "agent_url", None) or getattr(engine, "base_url", None)
                agent_token = getattr(engine, "agent_token", None) or ""
                if agent_url:
                    return provider.id, str(agent_url).rstrip("/"), str(agent_token)
        except Exception as exc:
            logger.debug("director_remote_agent_lookup_failed", error=str(exc))
        return None

    async def _try_remote_agent(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str,
        allow_image_generation: bool,
    ) -> Optional[DirectorDecisionResult]:
        """Tier 1: Dispatch to `remote_agent` `/v1/decisions` on CPU/RAM."""
        target = self._find_remote_agent_target()
        if not target:
            return None
        provider_id, agent_url, agent_token = target
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if agent_token:
            headers["X-Worker-Token"] = agent_token
            headers["Authorization"] = f"Bearer {agent_token}"

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{agent_url}/v1/decisions",
                    headers=headers,
                    json={
                        "model": model_id,
                        "context": context_text,
                        "questions": questions,
                    },
                )
            if resp.status_code >= 400:
                logger.debug(
                    "director_remote_agent_unavailable",
                    provider_id=provider_id,
                    status_code=resp.status_code,
                )
                return None
            payload = resp.json()
            answers = payload.get("answers") or payload
            latency_ms = float(payload.get("latency_ms") or ((time.perf_counter() - started) * 1000))
            agent_engine = str(payload.get("engine_used") or f"remote_laya_{payload.get('device', 'cpu')}")
            engine_used_str = agent_engine if ":" in agent_engine else f"{agent_engine}:{provider_id}"
            return parse_director_result(
                answers,
                engine_used=engine_used_str,
                model_id=str(payload.get("model_id") or model_id),
                latency_ms=latency_ms,
                allow_image_generation=allow_image_generation,
            )
        except Exception as exc:
            logger.debug(
                "director_remote_agent_call_failed",
                provider_id=provider_id,
                error=str(exc),
            )
            return None

    async def _try_modal_laya(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str,
        allow_image_generation: bool,
    ) -> Optional[DirectorDecisionResult]:
        """Dispatch to Modal CPU function `evaluate_decisions`."""
        try:
            from services.engines.engine_factory import get_engine

            providers = self.session.exec(
                select(Provider)
                .where(
                    Provider.type == "modal_llm",
                    Provider.enabled == True,  # noqa: E712
                )
                .order_by(Provider.priority, Provider.id)
            ).all()
            for provider in providers:
                engine = get_engine(provider.id, provider)
                if engine and hasattr(engine, "evaluate_decisions"):
                    started = time.perf_counter()
                    res = await engine.evaluate_decisions(
                        model_id=model_id,
                        context_text=context_text,
                        questions=questions,
                        timeout=15.0,
                    )
                    if res and res.get("status") == "success":
                        answers = res.get("answers") or res
                        latency_ms = float(res.get("latency_ms") or ((time.perf_counter() - started) * 1000))
                        return parse_director_result(
                            answers,
                            engine_used=f"modal_laya_cpu:{provider.id}",
                            model_id=str(res.get("model_id") or model_id),
                            latency_ms=latency_ms,
                            allow_image_generation=allow_image_generation,
                        )
        except Exception as exc:
            logger.debug("director_modal_laya_call_failed", error=str(exc))
        return None

    async def _try_beam_laya(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str,
        allow_image_generation: bool,
    ) -> Optional[DirectorDecisionResult]:
        """Dispatch to Beam `/v1/decisions` on CPU."""
        try:
            from services.engines.engine_factory import get_engine

            providers = self.session.exec(
                select(Provider)
                .where(
                    Provider.type == "beam_llm",
                    Provider.enabled == True,  # noqa: E712
                )
                .order_by(Provider.priority, Provider.id)
            ).all()
            for provider in providers:
                engine = get_engine(provider.id, provider)
                if engine and hasattr(engine, "evaluate_decisions"):
                    started = time.perf_counter()
                    res = await engine.evaluate_decisions(
                        model_id=model_id,
                        context_text=context_text,
                        questions=questions,
                        timeout=15.0,
                    )
                    if res and res.get("status") == "success":
                        answers = res.get("answers") or res
                        latency_ms = float(res.get("latency_ms") or ((time.perf_counter() - started) * 1000))
                        return parse_director_result(
                            answers,
                            engine_used=f"beam_laya_cpu:{provider.id}",
                            model_id=str(res.get("model_id") or model_id),
                            latency_ms=latency_ms,
                            allow_image_generation=allow_image_generation,
                        )
        except Exception as exc:
            logger.debug("director_beam_laya_call_failed", error=str(exc))
        return None

    async def _try_local_laya(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str,
        allow_image_generation: bool,
    ) -> Optional[DirectorDecisionResult]:
        """Tier 2: Evaluate in-process on backend CPU via `LayaRunner`."""
        runner = get_laya_runner()
        if not runner.is_available():
            return None
        try:
            import asyncio

            res = await asyncio.to_thread(
                runner.evaluate,
                context_text=context_text,
                questions=questions,
                model_id=model_id,
            )
            return parse_director_result(
                res.get("answers") or {},
                engine_used="local_laya_cpu",
                model_id=str(res.get("model_id") or model_id),
                latency_ms=float(res.get("latency_ms") or 0.0),
                allow_image_generation=allow_image_generation,
            )
        except Exception as exc:
            logger.warning("director_local_laya_failed", model_id=model_id, error=str(exc))
            return None

    async def _try_generative_util_fallback(
        self,
        *,
        context_text: str,
        has_secondary_character: bool,
        allow_image_generation: bool,
        allow_narration: bool,
    ) -> Optional[DirectorDecisionResult]:
        """Tier 3: Evaluate via the active `util` LLM provider using JSON output."""
        resolved = resolve_default_provider(self.session)
        if not resolved:
            return None
        provider_id, _ = resolved
        provider = self.session.get(Provider, provider_id)
        if not provider or not provider.enabled:
            return None

        try:
            from services.engines.engine_factory import get_engine
            from services.llm_config import model_for_kind

            engine = get_engine(provider.id, provider)
            if engine is None:
                return None

            util_model = model_for_kind("tool_call", None, self.session)
            prompt = build_generative_fallback_prompt(
                context_text,
                has_secondary_character=has_secondary_character,
                allow_narration=allow_narration,
            )
            workflow = {
                "type": "decisions",
                "model": util_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a precise JSON-only roleplay scene router. Output valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_output_tokens": 350,
            }

            started = time.perf_counter()
            full_text = ""
            async for event in engine.inference(workflow, timeout=15.0):
                if not isinstance(event, dict):
                    continue
                if event.get("event") == "token" and event.get("text"):
                    full_text += str(event["text"])
                elif event.get("status") == "success":
                    output = event.get("output") or {}
                    if isinstance(output, dict) and output.get("text"):
                        full_text = str(output["text"])
                    elif event.get("text"):
                        full_text = str(event["text"])

            if not full_text.strip():
                return None

            parsed = parse_generative_fallback_json(full_text)
            latency_ms = (time.perf_counter() - started) * 1000
            return parse_director_result(
                parsed,
                engine_used=f"util_llm_json:{provider_id}",
                model_id=util_model,
                latency_ms=latency_ms,
                allow_image_generation=allow_image_generation,
            )
        except Exception as exc:
            logger.debug("director_generative_fallback_failed", error=str(exc))
            return None

    async def evaluate_scene(
        self,
        *,
        character_name: str = "Character",
        user_name: str = "User",
        story_location: Optional[str] = None,
        story_time: Optional[str] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        recent_messages: Optional[List[Dict[str, str]]] = None,
        last_speaker: str = "user",
        has_secondary_character: bool = False,
        allow_image_generation: bool = True,
        allow_narration: bool = True,
        model_override: Optional[str] = None,
    ) -> DirectorDecisionResult:
        """Run the 13-question Director evaluation across the 4-tier provider cascade."""
        started = time.perf_counter()
        active_model = model_override or self._active_decisions_model()

        context_text = format_director_context(
            character_name=character_name,
            user_name=user_name,
            story_location=story_location,
            story_time=story_time,
            state_snapshot=state_snapshot,
            recent_messages=recent_messages,
            last_speaker=last_speaker,
        )

        if active_model == "disabled":
            res = heuristic_director_decision(
                context_text,
                last_speaker=last_speaker,
                has_secondary_character=has_secondary_character,
                allow_image_generation=allow_image_generation,
                allow_narration=allow_narration,
                latency_ms=(time.perf_counter() - started) * 1000,
                state_snapshot=state_snapshot,
            )
            res.engine_used = "disabled"
            res.model_id = "disabled"
            return res

        questions = build_director_questions(
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
        )

        # Explicit "same_as_util" bypasses Laya and goes straight to Tier 3
        if active_model != "same_as_util":
            # Tier 1: Remote Providers (remote_agent, modal_llm, beam_llm) CPU/RAM Laya
            remote_res = await self._try_remote_agent(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
            )
            if remote_res is not None:
                return resolve_fate_check(remote_res, state_snapshot=state_snapshot, context_text=context_text)

            modal_res = await self._try_modal_laya(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
            )
            if modal_res is not None:
                return resolve_fate_check(modal_res, state_snapshot=state_snapshot, context_text=context_text)

            beam_res = await self._try_beam_laya(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
            )
            if beam_res is not None:
                return resolve_fate_check(beam_res, state_snapshot=state_snapshot, context_text=context_text)

            # Tier 2: Local Backend CPU LayaRunner
            local_res = await self._try_local_laya(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
            )
            if local_res is not None:
                return resolve_fate_check(local_res, state_snapshot=state_snapshot, context_text=context_text)

        # Tier 3: Generative JSON fallback on active `util` LLM provider
        # Attempted when explicitly requested ("same_as_util") OR as fallback when Tier 1 & Tier 2 both failed
        gen_res = await self._try_generative_util_fallback(
            context_text=context_text,
            has_secondary_character=has_secondary_character,
            allow_image_generation=allow_image_generation,
            allow_narration=allow_narration,
        )
        if gen_res is not None:
            return resolve_fate_check(gen_res, state_snapshot=state_snapshot, context_text=context_text)

        # Tier 4: Deterministic Heuristic Fallback
        return heuristic_director_decision(
            context_text,
            last_speaker=last_speaker,
            has_secondary_character=has_secondary_character,
            allow_image_generation=allow_image_generation,
            allow_narration=allow_narration,
            latency_ms=(time.perf_counter() - started) * 1000,
            state_snapshot=state_snapshot,
        )
