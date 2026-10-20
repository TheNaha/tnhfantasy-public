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
from core.pipeline_limits import DIRECTOR_TIMEOUT_SECONDS
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
from services.laya_questions import resolve_stage_questions
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
            logger.warning("director_remote_agent_lookup_failed", error=str(exc))
        return None

    async def _try_remote_agent(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str,
        allow_image_generation: bool,
        state_snapshot: Optional[Dict[str, Any]] = None,
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
            async with httpx.AsyncClient(timeout=DIRECTOR_TIMEOUT_SECONDS) as client:
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
                logger.warning(
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
                state_snapshot=state_snapshot,
                context_text=context_text,
            )
        except Exception as exc:
            logger.warning(
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
        state_snapshot: Optional[Dict[str, Any]] = None,
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
                        timeout=DIRECTOR_TIMEOUT_SECONDS,
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
                            state_snapshot=state_snapshot,
                            context_text=context_text,
                        )
        except Exception as exc:
            logger.warning("director_modal_laya_call_failed", error=str(exc))
        return None

    async def _try_beam_laya(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str,
        allow_image_generation: bool,
        state_snapshot: Optional[Dict[str, Any]] = None,
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
                        timeout=DIRECTOR_TIMEOUT_SECONDS,
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
                            state_snapshot=state_snapshot,
                            context_text=context_text,
                        )
        except Exception as exc:
            logger.warning("director_beam_laya_call_failed", error=str(exc))
        return None

    async def _try_local_laya(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        model_id: str,
        allow_image_generation: bool,
        state_snapshot: Optional[Dict[str, Any]] = None,
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
                state_snapshot=state_snapshot,
                context_text=context_text,
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
        state_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[DirectorDecisionResult]:
        """Tier 3: Evaluate via the active `util` LLM provider using JSON output."""
        provider = await self._select_healthy_llm_provider()
        if not provider:
            return None
        provider_id = provider.id

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
            async for event in engine.inference(workflow, timeout=DIRECTOR_TIMEOUT_SECONDS):
                if not isinstance(event, dict):
                    continue
                # Canonical TaskEvent dialect. The engines emit `delta` and
                # `completed`; the older `event == "token"` / `status ==
                # "success"` dialect this used to read is emitted by nothing in
                # the backend, so `full_text` stayed empty and Tier 3 always
                # returned None — the cascade fell through to the Tier 4
                # heuristic every single time, whatever the provider was doing.
                event_kind = event.get("event")
                if event_kind == "delta":
                    if event.get("text"):
                        full_text += str(event["text"])
                elif event_kind == "completed":
                    outputs = event.get("outputs") or []
                    first = outputs[0] if outputs and isinstance(outputs[0], dict) else {}
                    content = first.get("content") or first.get("text")
                    if content:
                        full_text = str(content)

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
                state_snapshot=state_snapshot,
                context_text=context_text,
            )
        except Exception as exc:
            logger.warning("director_generative_fallback_failed", error=str(exc))
            return None

    async def _select_healthy_llm_provider(self) -> Optional[Provider]:
        """Pick an LLM provider for Tier 3, preferring one that is actually up.

        This used to call `resolve_default_provider`, which reads the
        configured default and ignores provider health entirely: if that one
        provider was down, Tier 3 failed instead of trying another, and the
        Director silently degraded to the Tier 4 keyword scorer. The
        LoadBalancer already knows which providers are enabled, un-striped by
        failure streak, so route through it and keep the configured default as
        the fallback.
        """
        try:
            from services.load_balancer_factory import create_load_balancer

            lb = create_load_balancer(self.session, task_type="llm")
            provider = await lb.get_next_provider(task_type="llm")
            if provider is not None:
                return provider
        except Exception as exc:
            logger.warning("director_llm_provider_selection_failed", error=str(exc))

        try:
            resolved = resolve_default_provider(self.session)
        except Exception as exc:
            logger.warning("director_default_provider_lookup_failed", error=str(exc))
            return None
        if not resolved:
            return None
        provider_id, _ = resolved
        provider = self.session.get(Provider, provider_id)
        if not provider or not provider.enabled:
            return None
        return provider

    def _get_available_agents(self) -> List[Dict[str, Any]]:
        """Fetch enabled AgentProfile rows from the database."""
        if not self.session:
            return []
        try:
            from core.entities import AgentProfile
            stmt = select(AgentProfile).where(AgentProfile.enabled == True)  # noqa: E712
            rows = self.session.exec(stmt).all()
            return [
                {
                    "id": a.id,
                    "slug": a.slug,
                    "name": a.name,
                    "agent_type": a.agent_type,
                    "description": a.description,
                    "system_prompt_template": a.system_prompt_template,
                    "model_target": a.model_target,
                    "model_override": a.model_override,
                }
                for a in rows
            ]
        except Exception as exc:
            logger.warning("get_available_agents_failed", error=str(exc))
            return []

    def _finalize_result(
        self,
        res: DirectorDecisionResult,
        *,
        stage: str,
        questions: List[Dict[str, Any]],
        state_snapshot: Optional[Dict[str, Any]],
        context_text: str,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        turn: int = 1,
    ) -> DirectorDecisionResult:
        res.workflow_stage = stage
        res = resolve_fate_check(res, state_snapshot=state_snapshot, context_text=context_text)

        # Inspect raw_answers for sub-variant choice if not already resolved
        if not res.selected_variant and res.raw_answers:
            target_variant_key = f"{res.selected_agent}_variant"
            if target_variant_key in res.raw_answers:
                choice = res.raw_answers[target_variant_key]
                val = (choice.get("choice") or choice.get("selected")) if isinstance(choice, dict) else choice
                if val and val != "default":
                    res.selected_variant = str(val)
            elif res.selected_agent == "narrator" and "narrator_variant" in res.raw_answers:
                choice = res.raw_answers["narrator_variant"]
                val = (choice.get("choice") or choice.get("selected")) if isinstance(choice, dict) else choice
                if val and val != "default":
                    res.selected_variant = str(val)
            elif "character_variant" in res.raw_answers and res.selected_agent not in ("narrator", "user"):
                choice = res.raw_answers["character_variant"]
                val = (choice.get("choice") or choice.get("selected")) if isinstance(choice, dict) else choice
                if val and val != "default":
                    res.selected_variant = str(val)

        # Process custom directives from custom questions
        if res.raw_answers:
            for q in questions:
                if q.get("is_custom") and q.get("directive"):
                    k = q["key"]
                    ans = res.raw_answers.get(k)
                    prob = 0.0
                    if isinstance(ans, dict):
                        prob = float(ans.get("probability", ans.get("true_probability", ans.get("yes", 0.0))))
                    elif isinstance(ans, (int, float)):
                        prob = float(ans)
                    elif isinstance(ans, bool):
                        prob = 1.0 if ans else 0.0
                    threshold = float(q.get("threshold", 0.60))
                    if prob >= threshold:
                        res.custom_directives.append({
                            "key": k,
                            "directive": q["directive"],
                            "probability": prob,
                        })

        # Record DirectorTrace if chat_id provided
        if chat_id and self.session:
            try:
                from core.entities import DirectorTrace
                trace = DirectorTrace(
                    chat_id=chat_id,
                    message_id=message_id,
                    stage=stage,
                    turn=turn,
                    selected_agent=res.selected_agent,
                    selected_variant=res.selected_variant,
                    decision=res.to_dict(),
                    extra={"engine_used": res.engine_used, "model_id": res.model_id, "latency_ms": res.latency_ms},
                )
                self.session.add(trace)
                self.session.commit()
            except Exception as exc:
                logger.warning("record_director_trace_failed", chat_id=chat_id, error=str(exc))

        return res

    async def _run_cascade(
        self,
        *,
        context_text: str,
        questions: List[Dict[str, Any]],
        state_snapshot: Optional[Dict[str, Any]] = None,
        last_speaker: str = "user",
        has_secondary_character: bool = False,
        allow_image_generation: bool = True,
        allow_narration: bool = True,
        model_override: Optional[str] = None,
        stage: str = "full",
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        turn: int = 1,
    ) -> DirectorDecisionResult:
        started = time.perf_counter()
        active_model = model_override or self._active_decisions_model()

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
            return self._finalize_result(
                res,
                stage=stage,
                questions=questions,
                state_snapshot=state_snapshot,
                context_text=context_text,
                chat_id=chat_id,
                message_id=message_id,
                turn=turn,
            )

        # Tier 1: Remote Providers (remote_agent, modal_llm, beam_llm) CPU/RAM Laya
        if active_model != "same_as_util":
            remote_res = await self._try_remote_agent(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
                state_snapshot=state_snapshot,
            )
            if remote_res is not None:
                return self._finalize_result(
                    remote_res,
                    stage=stage,
                    questions=questions,
                    state_snapshot=state_snapshot,
                    context_text=context_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    turn=turn,
                )

            modal_res = await self._try_modal_laya(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
                state_snapshot=state_snapshot,
            )
            if modal_res is not None:
                return self._finalize_result(
                    modal_res,
                    stage=stage,
                    questions=questions,
                    state_snapshot=state_snapshot,
                    context_text=context_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    turn=turn,
                )

            beam_res = await self._try_beam_laya(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
                state_snapshot=state_snapshot,
            )
            if beam_res is not None:
                return self._finalize_result(
                    beam_res,
                    stage=stage,
                    questions=questions,
                    state_snapshot=state_snapshot,
                    context_text=context_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    turn=turn,
                )

            # Tier 2: Local Backend CPU LayaRunner
            local_res = await self._try_local_laya(
                context_text=context_text,
                questions=questions,
                model_id=active_model,
                allow_image_generation=allow_image_generation,
                state_snapshot=state_snapshot,
            )
            if local_res is not None:
                return self._finalize_result(
                    local_res,
                    stage=stage,
                    questions=questions,
                    state_snapshot=state_snapshot,
                    context_text=context_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    turn=turn,
                )

        # Tier 3: Generative JSON fallback on active `util` LLM provider
        gen_res = await self._try_generative_util_fallback(
            context_text=context_text,
            has_secondary_character=has_secondary_character,
            allow_image_generation=allow_image_generation,
            allow_narration=allow_narration,
            state_snapshot=state_snapshot,
        )
        if gen_res is not None:
            return self._finalize_result(
                gen_res,
                stage=stage,
                questions=questions,
                state_snapshot=state_snapshot,
                context_text=context_text,
                chat_id=chat_id,
                message_id=message_id,
                turn=turn,
            )

        # Tier 4: Deterministic Heuristic Fallback
        heur = heuristic_director_decision(
            context_text,
            last_speaker=last_speaker,
            has_secondary_character=has_secondary_character,
            allow_image_generation=allow_image_generation,
            allow_narration=allow_narration,
            latency_ms=(time.perf_counter() - started) * 1000,
            state_snapshot=state_snapshot,
        )
        return self._finalize_result(
            heur,
            stage=stage,
            questions=questions,
            state_snapshot=state_snapshot,
            context_text=context_text,
            chat_id=chat_id,
            message_id=message_id,
            turn=turn,
        )

    async def evaluate_pre_generation_triage(
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
        allow_narration: bool = True,
        model_override: Optional[str] = None,
        primary_character_slug: str = "character",
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        turn: int = 1,
    ) -> DirectorDecisionResult:
        """Stage 1: Pre-generation triage routing to Character, Narrator, or Custom Agents."""
        context_text = format_director_context(
            character_name=character_name,
            user_name=user_name,
            story_location=story_location,
            story_time=story_time,
            state_snapshot=state_snapshot,
            recent_messages=recent_messages,
            last_speaker=last_speaker,
        )
        available_agents = self._get_available_agents()
        questions = resolve_stage_questions(
            self.session,
            "triage",
            available_agents=available_agents,
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
            primary_character_slug=primary_character_slug,
        )
        return await self._run_cascade(
            context_text=context_text,
            questions=questions,
            state_snapshot=state_snapshot,
            last_speaker=last_speaker,
            has_secondary_character=has_secondary_character,
            allow_image_generation=False,
            allow_narration=allow_narration,
            model_override=model_override,
            stage="triage",
            chat_id=chat_id,
            message_id=message_id,
            turn=turn,
        )

    async def evaluate_post_generation_audit(
        self,
        *,
        generated_text: str,
        character_name: str = "Character",
        user_name: str = "User",
        story_location: Optional[str] = None,
        story_time: Optional[str] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        recent_messages: Optional[List[Dict[str, str]]] = None,
        last_speaker: str = "character",
        allow_image_generation: bool = True,
        model_override: Optional[str] = None,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        turn: int = 1,
    ) -> DirectorDecisionResult:
        """Stage 2: Post-generation audit evaluating completion, illustration triggers, and 16 gates."""
        msgs = list(recent_messages or [])
        if generated_text:
            msgs.append({"role": last_speaker, "content": generated_text})
        context_text = format_director_context(
            character_name=character_name,
            user_name=user_name,
            story_location=story_location,
            story_time=story_time,
            state_snapshot=state_snapshot,
            recent_messages=msgs,
            last_speaker=last_speaker,
        )
        questions = resolve_stage_questions(self.session, "audit")
        return await self._run_cascade(
            context_text=context_text,
            questions=questions,
            state_snapshot=state_snapshot,
            last_speaker=last_speaker,
            allow_image_generation=allow_image_generation,
            model_override=model_override,
            stage="audit",
            chat_id=chat_id,
            message_id=message_id,
            turn=turn,
        )

    async def evaluate_turn_chaining(
        self,
        *,
        character_name: str = "Character",
        user_name: str = "User",
        story_location: Optional[str] = None,
        story_time: Optional[str] = None,
        state_snapshot: Optional[Dict[str, Any]] = None,
        recent_messages: Optional[List[Dict[str, str]]] = None,
        last_speaker: str = "character",
        has_secondary_character: bool = False,
        allow_narration: bool = True,
        model_override: Optional[str] = None,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        turn: int = 1,
    ) -> DirectorDecisionResult:
        """Stage 3: Turn chaining check deciding who should take the next autonomous turn."""
        context_text = format_director_context(
            character_name=character_name,
            user_name=user_name,
            story_location=story_location,
            story_time=story_time,
            state_snapshot=state_snapshot,
            recent_messages=recent_messages,
            last_speaker=last_speaker,
        )
        available_agents = self._get_available_agents()
        questions = resolve_stage_questions(
            self.session,
            "chaining",
            available_agents=available_agents,
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
        )
        return await self._run_cascade(
            context_text=context_text,
            questions=questions,
            state_snapshot=state_snapshot,
            last_speaker=last_speaker,
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
            model_override=model_override,
            stage="chaining",
            chat_id=chat_id,
            message_id=message_id,
            turn=turn,
        )

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
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        turn: int = 1,
    ) -> DirectorDecisionResult:
        """Unified Director evaluation across all questions for backward compatibility."""
        context_text = format_director_context(
            character_name=character_name,
            user_name=user_name,
            story_location=story_location,
            story_time=story_time,
            state_snapshot=state_snapshot,
            recent_messages=recent_messages,
            last_speaker=last_speaker,
        )
        available_agents = self._get_available_agents()
        questions = build_director_questions(
            has_secondary_character=has_secondary_character,
            allow_narration=allow_narration,
            available_agents=available_agents,
        )
        return await self._run_cascade(
            context_text=context_text,
            questions=questions,
            state_snapshot=state_snapshot,
            last_speaker=last_speaker,
            has_secondary_character=has_secondary_character,
            allow_image_generation=allow_image_generation,
            allow_narration=allow_narration,
            model_override=model_override,
            stage="full",
            chat_id=chat_id,
            message_id=message_id,
            turn=turn,
        )

