"""Transport-aware provider telemetry and a per-provider status engine.

Every 30s (``COMFY_PROVIDER_TELEMETRY_INTERVAL_SECONDS``) the poller walks the
enabled providers and runs the cheapest probe each transport allows:

* **remote / direct** — a real ``engine.check_health()`` round trip, plus — for
  remote workers that expose an agent — a ``GET {agent_url}/vram/status``
  (Bearer token) sampled into an in-memory ring buffer (~2h at 30s). A real
  health round trip is what these transports already pay per dispatch, so
  polling them is free honesty.
* **modal / beam** — the engine's config-only ``check_health()`` only. Any live
  probe of a serverless worker boots a container, which is a GPU bill on every
  poll, so this never happens. Warm/cooling/cold lifecycle for these
  transports is *inferred* on demand from the last completed job (see
  ``compute_serverless_lifecycle``), never probed.

The poller owns a per-provider status machine
(``online`` / ``offline``, starting from the first observation): a provider
goes offline after ``OFFLINE_AFTER_MISSES`` consecutive missed probes or
timeouts and back online on the first success. Both transitions:

* emit the existing ``EventType.PROVIDER_STATUS`` event so the UI's realtime
  layer can toast the flip, and
* write the verdict into the load balancer's 15s health cache via
  ``services.load_balancer.set_poller_health`` so an offline provider is
  skipped at dispatch through the existing cache path (no dispatch-time wake
  ping — waking a remote worker to prove it is awake is the cost we are
  avoiding).

The in-memory state (status + ring buffer) is lost on backend restart. That is
explicitly accepted: it costs no schema and nothing in the data layer depends
on surviving a restart.

Blocking I/O (DB reads, engine construction, the VRAM sample) runs off the
event loop via ``asyncio.to_thread`` or an awaited httpx call, and one
provider's failure must never break the loop.
"""

import asyncio
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.entities import Job, JobStatus
from infrastructure.deps import get_session_sync
from infrastructure.logging import get_logger
from infrastructure.repositories import ProviderRepository
from services.engines.engine_factory import can_create_engine, get_engine
from services.engines.registry import resolve_transport
from services.provider_utils import extract_deploy_config

logger = get_logger("provider_telemetry")

TELEMETRY_INTERVAL_SECONDS = float(
    os.getenv("COMFY_PROVIDER_TELEMETRY_INTERVAL_SECONDS", "30.0")
)
TELEMETRY_TIMEOUT_SECONDS = float(
    os.getenv("COMFY_PROVIDER_TELEMETRY_TIMEOUT_SECONDS", "10.0")
)

#: ``/vram/status`` sample budget. Separate from (and well below) the health
#: timeout: the agent may be healthy on the main URL while its VRAM endpoint is
#: slow, and a slow sample must not read as a missed health probe.
VRAM_SAMPLE_TIMEOUT_SECONDS = float(
    os.getenv("COMFY_PROVIDER_VRAM_SAMPLE_TIMEOUT_SECONDS", "8.0")
)

#: Ring length ≈ 2h of samples at the default 30s cadence, per provider.
VRAM_HISTORY_MAX_ENTRIES = int(os.getenv("COMFY_PROVIDER_VRAM_HISTORY_ENTRIES", "240"))

#: Fail 2 consecutive probes (miss or timeout) → offline. One success → online.
OFFLINE_AFTER_MISSES = 2

#: Serverless transports never get a liveness state machine — they have no
#: persistent process to be "online". Their lifecycle is the warm window.
SERVERLESS_TRANSPORTS = ("modal", "beam")

#: Deploy-time scaledown tells the truth server-side; the provider's
#: ``deploy_config.scaledown_window`` (seconds) wins when present, otherwise
#: this fallback. Env-overridable because deployments tune their scaledown.
WARM_WINDOW_FALLBACK_SECONDS = float(
    os.getenv("COMFY_PROVIDER_WARM_WINDOW_FALLBACK_SECONDS", "300")
)

#: "On demand" per the plan — no extra polling — but a card view refreshes on
#: every open, so results are reused briefly instead of queried per keystroke.
LIFECYCLE_CACHE_TTL_SECONDS = 15.0

#: Inside the window, "warm" while more than ~25% of it (or ≥ 60s) remains,
#: then "cooling" for the tail. Outside the window → cold.
_COOLING_MIN_SECONDS = 60.0
_COOLING_WINDOW_FRACTION = 0.25


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderTelemetryService:
    """Polls providers on a background interval and runs the status machine."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        # provider_id -> {"status": "online"|"offline"|None, "last_seen_at": iso, "missed_probes": int}
        # ``status`` is None for serverless transports (no liveness probes).
        self._status: dict[str, dict[str, Any]] = {}
        # provider_id -> deque of {ts, vram_used_mb, vram_total_mb, devices}
        self._vram_history: dict[str, deque] = {}
        # provider_id -> (monotonic stamp, lifecycle dict) for the warm window
        self._lifecycle_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Lifecycle of the background loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._poll_loop(), name="provider_telemetry"
        )
        logger.info(
            "provider_telemetry_started",
            interval_seconds=TELEMETRY_INTERVAL_SECONDS,
        )

    async def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("provider_telemetry_stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_once()
            except Exception as exc:  # never crash the loop
                logger.warning(
                    "provider_telemetry_poll_failed", error=str(exc)
                )
            await asyncio.sleep(TELEMETRY_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # One polling pass
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        """One polling pass over all enabled providers."""

        def _list_enabled() -> list[Any]:
            session = get_session_sync()
            try:
                repo = ProviderRepository(session)
                return repo.get_enabled()
            finally:
                session.close()

        providers = await asyncio.to_thread(_list_enabled)

        for provider in providers:
            try:
                await self._poll_provider(provider)
            except Exception as exc:  # one provider must not break the rest
                logger.debug(
                    "provider_telemetry_provider_failed",
                    provider_id=getattr(provider, "id", "?"),
                    error=str(exc),
                )

    async def _poll_provider(self, provider: Any) -> None:
        """Poll one provider with the cheapest probe its transport allows.

        ``can_create_engine`` guards on credentials/config, so providers
        that aren't configured are skipped without a health probe (and
        without flipping the status machine — a provider configured away
        is not a worker that went down).
        """
        if not can_create_engine(provider):
            return

        transport = resolve_transport(provider.type)
        engine = get_engine(provider.id, provider)
        if engine is None:
            return

        if transport in SERVERLESS_TRANSPORTS:
            await self._poll_serverless(provider)
            if transport == "modal":
                await self._probe_management(provider)
            return

        await self._poll_liveness(provider)
        await self._sample_vram(provider, engine)

    async def _poll_serverless(self, provider: Any) -> None:
        """Modal/Beam: config-only check, no liveness state, no state machine.

        ``check_health()`` on these engines is deliberately free (no RPC): the
        verdict is CONFIG validity and the intended UI reading is "configured",
        not "reachable".
        """
        try:
            await asyncio.wait_for(
                self._cast_engine(provider), timeout=TELEMETRY_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.debug("provider_telemetry_timeout", provider_id=provider.id)
        except Exception as exc:
            logger.debug(
                "provider_telemetry_check_failed",
                provider_id=provider.id,
                error=str(exc),
            )

    async def _cast_engine(self, provider: Any) -> Any:
        """Run the engine's health check for its side effects on the engine."""
        engine = get_engine(provider.id, provider)
        if engine is None:
            return None
        # Engines store ``_last_health``, ``detected_gpu``,
        # ``concurrency_policy``, ``warm_workload``, ``components`` during
        # ``check_health()``. The provider status card reads these from
        # ``_ENGINE_CACHE``, so nothing else needs to change.
        _ = await engine.check_health()
        return None

    async def _probe_management(self, provider: Any) -> None:
        """Best-effort Modal management-plane metadata probe (P4 spike).

        ``App.lookup(create_if_missing=False).info()`` are FREE metadata RPCs:
        no container boot, no bill, ever. The result lands in the probe
        module's cache and reaches the status card as ``telemetry.management``
        — confirming the deployment exists and catching revoked tokens that
        the config-only check_health answers "healthy" for.
        """
        try:
            from services.provider_probe import probe_modal_management_cached

            engine = get_engine(provider.id, provider)
            if engine is None or not callable(getattr(engine, "get_client_async", None)):
                return
            await probe_modal_management_cached(provider.id, engine)
        except Exception as exc:
            # A spike must never break the poll loop.
            logger.debug(
                "modal_management_probe_error",
                provider_id=provider.id,
                error=str(exc),
            )

    async def _poll_liveness(self, provider: Any) -> None:
        """Remote/direct: a real health round trip feeds the status machine.

        Misses (probe failure or timeout) increment ``missed_probes``;
        after ``OFFLINE_AFTER_MISSES`` the provider flips offline. A single
        success flips it back online. Transitions emit the provider status
        event and are forwarded into the load balancer's health cache.
        """
        now = _utcnow()
        healthy = False
        reason: str | None = None
        try:
            await asyncio.wait_for(
                self._cast_engine(provider), timeout=TELEMETRY_TIMEOUT_SECONDS
            )
            healthy = True
        except asyncio.TimeoutError:
            reason = "timeout"
        except Exception as exc:
            reason = str(exc)

        state = self._status.setdefault(
            provider.id,
            {"status": None, "last_seen_at": None, "missed_probes": 0},
        )
        previous = state.get("status")

        if healthy:
            state["status"] = "online"
            state["last_seen_at"] = now.isoformat()
            state["missed_probes"] = 0
        else:
            state["missed_probes"] = int(state.get("missed_probes") or 0) + 1
            if state["missed_probes"] >= OFFLINE_AFTER_MISSES:
                state["status"] = "offline"
            logger.debug(
                "provider_telemetry_miss",
                provider_id=provider.id,
                reason=reason,
                missed_probes=state["missed_probes"],
            )

        if state["status"] != previous:
            await self._emit_transition(provider.id, state)

    async def _emit_transition(self, provider_id: str, state: dict[str, Any]) -> None:
        """Announce an online/offline flip on the provider event channel."""
        new_status = state.get("status")
        if new_status not in ("online", "offline"):
            return  # first observation after startup — nothing to flip from
        # Imported here, not at module scope: `load_balancer` pulls in the
        # provider runtime stack, and the telemetry service must never make
        # startup depend on it.
        from services.load_balancer import set_poller_health

        set_poller_health(
            provider_id, healthy=new_status == "online",
            task_types=("image", "llm", "tts"),
        )
        try:
            from core.events import EventType, emit_provider_event

            await emit_provider_event(
                EventType.PROVIDER_STATUS,
                provider_id,
                {
                    "status": new_status,
                    "source": "telemetry",
                    "last_seen_at": state.get("last_seen_at"),
                    "missed_probes": state.get("missed_probes"),
                },
            )
        except Exception as exc:
            logger.debug(
                "provider_telemetry_transition_event_failed",
                provider_id=provider_id,
                error=str(exc),
            )
        logger.info("provider_status_transition", provider_id=provider_id, status=new_status)

    # ------------------------------------------------------------------
    # VRAM sampling
    # ------------------------------------------------------------------

    async def _sample_vram(self, provider: Any, engine: Any) -> None:
        """Sample the agent's ``/vram/status`` into the per-provider ring.

        Remote workers expose ``GET {agent_url}/vram/status`` (Bearer
        agent_token) on the same FastAPI app as ``/health``, so a healthy
        engine already reaches the process; the sample adds zero extra
        auth machinery. Only transports whose engine fronts an agent are
        asked — a plain hosted-API provider has no VRAM to report.
        """
        if not isinstance(getattr(engine, "agent_url", None), str):
            return
        agent_url = (engine.agent_url or "").strip().rstrip("/")
        if not agent_url:
            return
        token = (getattr(engine, "agent_token", "") or "").strip()

        sample: dict[str, Any] | None = None
        try:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            async with httpx.AsyncClient(
                timeout=VRAM_SAMPLE_TIMEOUT_SECONDS
            ) as client:
                resp = await client.get(f"{agent_url}/vram/status", headers=headers)
                resp.raise_for_status()
                data = resp.json()
            sample = {
                "ts": _utcnow().isoformat(),
                "vram_used_mb": data.get("vram_used_mb"),
                "vram_total_mb": data.get("vram_total_mb"),
                "devices": data.get("devices") or [],
            }
        except Exception as exc:
            # A slow or absent VRAM endpoint does not flip liveness — the
            # health probe owns that verdict. Log and move on.
            logger.debug(
                "provider_vram_sample_failed",
                provider_id=provider.id,
                error=str(exc),
            )
            return

        if sample is not None:
            self._append_vram_sample(provider.id, sample)

    def _append_vram_sample(self, provider_id: str, sample: dict[str, Any]) -> None:
        ring = self._vram_history.setdefault(
            provider_id, deque(maxlen=VRAM_HISTORY_MAX_ENTRIES)
        )
        ring.append(sample)

    # ------------------------------------------------------------------
    # Public accessors (P2 reads these)
    # ------------------------------------------------------------------

    def get_provider_status(self, provider_id: str) -> dict[str, Any]:
        """The poller's view of one provider: status, last seen, missed probes."""
        state = self._status.get(provider_id)
        if not state:
            return {"status": None, "last_seen_at": None, "missed_probes": 0}
        return dict(state)

    def get_vram_history(self, provider_id: str) -> list[dict[str, Any]]:
        """The ring buffer, oldest first."""
        return list(self._vram_history.get(provider_id) or ())

    def forget_provider(self, provider_id: str) -> None:
        """Drop a provider's in-memory telemetry (e.g. after deletion)."""
        self._status.pop(provider_id, None)
        self._vram_history.pop(provider_id, None)
        self._lifecycle_cache.pop(provider_id, None)
        try:
            from services.provider_probe import forget_probe

            forget_probe(provider_id)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Serverless warm-window lifecycle (modal/beam)
    # ------------------------------------------------------------------

    async def compute_serverless_lifecycle(self, provider: Any) -> dict[str, Any]:
        """Infer warm/cooling/cold for a serverless provider — never by probing.

        A Modal/Beam worker expires ``scaledown_window`` seconds after its last
        activity. The cheapest decisive proxy for "last activity" is the row of
        the most recent COMPLETED job the provider ran (``completed_at``). If
        the row is younger than the window the worker is almost surely warm,
        and subtracting from the window gives a countdown; once expired, the
        next dispatch pays the boot. This is an INFERENCE — deployments can
        scale down early — so every payload is labelled ``estimated: true``
        and callers/UI never promise.

        Computed on demand (no extra polling) and cached briefly.
        """
        cached = self._lifecycle_cache.get(provider.id)
        if cached is not None and time.monotonic() - cached[0] < LIFECYCLE_CACHE_TTL_SECONDS:
            return dict(cached[1])

        def _compute() -> dict[str, Any]:
            deploy_config = extract_deploy_config(provider.config or {})
            raw = deploy_config.get("scaledown_window")
            if raw is None or raw == "":
                window = WARM_WINDOW_FALLBACK_SECONDS
            else:
                try:
                    window = float(raw)
                except (TypeError, ValueError):
                    window = WARM_WINDOW_FALLBACK_SECONDS
            if window <= 0:
                # 0 means the deployment is configured to scale down
                # immediately: every dispatch pays the boot.
                window = 0.0

            session = get_session_sync()
            try:
                from sqlmodel import select

                row = session.exec(
                    select(Job.id, Job.completed_at)
                    .where(Job.provider_id == provider.id)
                    .where(Job.status == JobStatus.COMPLETED)
                    .order_by(Job.completed_at.desc())
                    .limit(1)
                ).first()
            finally:
                session.close()

            if row is None:
                return {
                    "state": "unknown",
                    "warm_until": None,
                    "estimated": True,
                    "window_seconds": window,
                }

            job_id, completed_at = row
            if completed_at is None:
                return {
                    "state": "unknown",
                    "warm_until": None,
                    "estimated": True,
                    "window_seconds": window,
                }

            now = _utcnow()
            warm_until = completed_at + timedelta(seconds=window)
            remaining = (warm_until - now).total_seconds()
            payload = {
                "estimated": True,
                "window_seconds": window,
                "last_completed_job_id": job_id,
                "last_completed_at": completed_at.isoformat(),
                "warm_until": warm_until.isoformat(),
                "seconds_left": max(round(remaining, 1), 0.0),
            }
            if remaining <= 0:
                payload["state"] = "cold"
            elif remaining > max(_COOLING_MIN_SECONDS, _COOLING_WINDOW_FRACTION * window):
                payload["state"] = "warm"
            else:
                payload["state"] = "cooling"
            return payload

        payload = await asyncio.to_thread(_compute)
        self._lifecycle_cache[provider.id] = (time.monotonic(), payload)
        return dict(payload)


# Module-level singleton
telemetry_service = ProviderTelemetryService()


async def start_telemetry_polling() -> None:
    """Entry point for application startup."""
    await telemetry_service.start()


async def stop_telemetry_polling() -> None:
    """Entry point for application shutdown."""
    await telemetry_service.stop()
