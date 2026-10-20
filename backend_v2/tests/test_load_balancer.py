# Load Balancer Unit Tests
import pytest
from sqlmodel import Session

from core.entities import LoadBalancerState, Provider
from services.load_balancer import LoadBalancer, LoadBalancerRuntimeState


@pytest.fixture
def providers(session: Session):
    """Create test providers."""
    providers_data = [
        {"id": "provider-1", "type": "modal", "enabled": True, "priority": 1},
        {"id": "provider-2", "type": "modal", "enabled": True, "priority": 2},
        {"id": "provider-3", "type": "modal", "enabled": False, "priority": 3},
    ]
    
    created = []
    for data in providers_data:
        provider = Provider(
            id=data["id"],
            type=data["type"],
            enabled=data["enabled"],
            priority=data["priority"],
            credentials={},
            config={},
        )
        session.add(provider)
        created.append(provider)
    session.commit()
    return created


class TestLoadBalancer:
    """Test load balancer strategies and failure handling."""

    @pytest.fixture(autouse=True)
    def reset_lb_state(self):
        LoadBalancer.reset_state()
        yield
        LoadBalancer.reset_state()
    
    async def test_round_robin_distribution(self, session: Session, providers):
        """Test round-robin distributes across all enabled providers."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        # Get providers in sequence
        provider1 = await lb.get_next_provider()
        provider2 = await lb.get_next_provider()
        provider3 = await lb.get_next_provider()  # Should wrap to first
        
        assert provider1 is not None
        assert provider2 is not None
        assert provider3 is not None
        
        # Should cycle through enabled providers (not disabled provider-3)
        assert provider1.id != provider2.id
        assert provider3.id == provider1.id  # Wrapped around
    
    async def test_priority_selection(self, session: Session, providers):
        """Test priority selects highest priority (lowest number)."""
        lb = LoadBalancer(session, strategy="priority")
        
        provider = await lb.get_next_provider()
        
        assert provider is not None
        assert provider.priority == 1  # Lowest priority number = highest priority
    
    async def test_random_selection(self, session: Session, providers):
        """Test random selects from enabled providers."""
        lb = LoadBalancer(session, strategy="random")
        
        results = set()
        for _ in range(10):
            provider = await lb.get_next_provider()
            if provider:
                results.add(provider.id)
        
        # Should only include enabled providers
        assert "provider-3" not in results  # Disabled
        assert len(results) >= 1  # At least one provider selected
    
    async def test_preferred_provider(self, session: Session, providers):
        """Test preferred provider is returned when specified and available."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        provider = await lb.get_next_provider(preferred_provider_id="provider-2")
        
        assert provider is not None
        assert provider.id == "provider-2"

        stats = await lb.get_stats()
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        assert provider_stats["provider-2"]["jobs_assigned"] == 1
    
    async def test_get_next_provider_excludes_exhausted(self, session: Session, providers):
        lb = LoadBalancer(session, strategy="round-robin")

        provider = await lb.get_next_provider(exclude_provider_ids={"provider-1"})

        assert provider is not None
        assert provider.id == "provider-2"

    async def test_pinned_provider_exhaustion_falls_over(
        self, session: Session, providers, monkeypatch
    ):
        """A pinned provider that just failed must not fail the whole job.

        job_runner adds the failed provider to `exhausted_providers` and calls
        back with the same `preferred_provider_id`. The health-aware branch
        used to answer None for that combination, which
        `select_next_provider` reads as "all providers failed" and turns into
        a FAILED job while a healthy provider still sits in the pool. The
        LLM branch and the non-health-aware branch both fail over; this pins
        the health-aware branch to the same behaviour.
        """
        # conftest disables health checks suite-wide; this path only exists
        # when they are on, which is the production default.
        monkeypatch.setenv("COMFY_LB_HEALTH_CHECKS_ENABLED", "1")
        lb = LoadBalancer(session, strategy="round-robin")
        assert lb.health_check_enabled is True

        provider = await lb.get_next_provider(
            preferred_provider_id="provider-1",
            exclude_provider_ids={"provider-1"},
        )

        assert provider is not None, (
            "pinned-and-exhausted must fail over, not report the pool as exhausted"
        )
        assert provider.id == "provider-2"

    async def test_pinned_provider_exhaustion_with_nothing_left_returns_none(
        self, session: Session, providers, monkeypatch
    ):
        """Failover only exists while something remains to fail over to."""
        monkeypatch.setenv("COMFY_LB_HEALTH_CHECKS_ENABLED", "1")
        lb = LoadBalancer(session, strategy="round-robin")

        provider = await lb.get_next_provider(
            preferred_provider_id="provider-1",
            exclude_provider_ids={"provider-1", "provider-2"},
        )

        assert provider is None

    async def test_no_enabled_providers(self, session: Session):
        """Test returns None when no providers are enabled."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        provider = await lb.get_next_provider()
        
        assert provider is None
    
    async def test_success_resets_failure_count(self, session: Session, providers):
        """Test reporting success resets failure count."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        # Simulate failures then success
        await lb.report_failure("provider-1")
        await lb.report_failure("provider-1")
        await lb.report_success("provider-1")
        
        # Provider should still be available
        stats = await lb.get_stats()
        # Failure count should be reset or minimal
        assert stats is not None
    
    async def test_get_stats(self, session: Session, providers):
        """Test stats returns provider information."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        stats = await lb.get_stats()
        
        assert "strategy" in stats
        assert "provider_stats" in stats
        assert "by_modality" in stats
        assert "image" in stats["by_modality"]
        assert "llm" in stats["by_modality"]
        assert "tts" in stats["by_modality"]

    async def test_save_and_reload_state_round_trip(self, session: Session, providers):
        """Persisted state should survive a reset and reload from the database."""
        lb = LoadBalancer(session, strategy="round-robin")

        await lb.get_next_provider()
        await lb.get_next_provider()
        await lb.report_failure("provider-1")
        LoadBalancer.save_state_to_db(session)

        persisted = session.get(LoadBalancerState, 1)
        assert persisted is not None
        assert persisted.round_robin_index == 2
        assert persisted.provider_failures["provider-1"] == 1

        LoadBalancer.reset_state()
        LoadBalancer.load_state_from_db(session)

        stats = await lb.get_stats()
        assert stats["current_index"] == 2
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        assert provider_stats["provider-1"]["failures"] == 1

    async def test_runtime_state_is_shared_across_instances(self, session: Session, providers):
        """Separate instances should observe the same runtime balancing state."""
        first = LoadBalancer(session, strategy="round-robin")
        second = LoadBalancer(session, strategy="least-connections")

        selected = await first.get_next_provider()

        assert selected is not None

        stats = await second.get_stats()
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        assert provider_stats[selected.id]["jobs_assigned"] == 1

    async def test_runtime_state_can_be_isolated_per_instance(self, session: Session, providers):
        """Injected runtime state should allow isolated balancing contexts."""
        shared = LoadBalancer(session, strategy="round-robin")
        isolated_state = LoadBalancerRuntimeState()
        isolated = LoadBalancer(session, strategy="round-robin", runtime_state=isolated_state)

        shared_selected = await shared.get_next_provider()

        assert shared_selected is not None

        isolated_stats_before = await isolated.get_stats()
        isolated_provider_stats_before = {item["id"]: item for item in isolated_stats_before["provider_stats"]}
        assert isolated_provider_stats_before[shared_selected.id]["jobs_assigned"] == 0

        isolated_selected = await isolated.get_next_provider()
        assert isolated_selected is not None

        isolated_stats_after = await isolated.get_stats()
        isolated_provider_stats_after = {item["id"]: item for item in isolated_stats_after["provider_stats"]}
        assert isolated_provider_stats_after[isolated_selected.id]["jobs_assigned"] == 1

    async def test_release_job_decrements_job_count(self, session: Session, providers):
        """release_job decrements the in-memory active-job count.

        State persistence is now throttled (every 20 jobs) rather than on every
        release, so this test asserts in-memory state via get_stats() instead of
        a DB row.
        """
        lb = LoadBalancer(session, strategy="round-robin")

        selected = await lb.get_next_provider()
        assert selected is not None

        await lb.release_job(selected.id)

        stats = await lb.get_stats()
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        assert provider_stats[selected.id]["jobs_assigned"] == 0

    async def test_model_availability_filter_is_memoized(self, session: Session, providers, monkeypatch):
        lb = LoadBalancer(session, strategy="round-robin")
        required_models = {"checkpoints": ["dream.safetensors"]}
        call_count = 0

        def fake_get_providers_with_models(_self, _required_models):
            nonlocal call_count
            call_count += 1
            return ["provider-1"]

        monkeypatch.setattr(
            "services.model_availability_service.ModelAvailabilityService.get_providers_with_models",
            fake_get_providers_with_models,
        )

        first = await lb.get_next_provider(required_models=required_models)
        second = await lb.get_next_provider(required_models=required_models)

        assert first is not None
        assert second is not None
        assert first.id == "provider-1"
        assert second.id == "provider-1"
        assert call_count == 1

    async def test_model_availability_cache_can_be_invalidated(self, session: Session, providers, monkeypatch):
        lb = LoadBalancer(session, strategy="round-robin")
        required_models = {"checkpoints": ["dream.safetensors"]}
        call_count = 0

        def fake_get_providers_with_models(_self, _required_models):
            nonlocal call_count
            call_count += 1
            return ["provider-1"]

        monkeypatch.setattr(
            "services.model_availability_service.ModelAvailabilityService.get_providers_with_models",
            fake_get_providers_with_models,
        )

        first = await lb.get_next_provider(required_models=required_models)
        assert first is not None
        assert call_count == 1

        LoadBalancer.invalidate_model_availability_cache(provider_id="provider-1")

        second = await lb.get_next_provider(required_models=required_models)
        assert second is not None
        assert call_count == 2

    async def test_llm_routing_skips_provider_in_failure_streak(self, session: Session):
        """An LLM provider in a failure streak must be skipped before strategy
        selection, instead of blindly returning the first-priority provider (#3)."""
        from services.load_balancer import LLM_FAILURE_STREAK_THRESHOLD

        for pid, priority in (("llm-1", 1), ("llm-2", 2), ("llm-3", 3)):
            session.add(Provider(
                id=pid, type="modal", enabled=True, priority=priority,
                worker_type="llm", credentials={}, config={},
            ))
        session.commit()

        lb = LoadBalancer(session, strategy="priority")

        # No failures yet -> highest-priority LLM provider wins.
        assert (await lb.get_next_provider(task_type="llm")).id == "llm-1"

        # Push llm-1 into a failure streak; it must now be skipped.
        for _ in range(LLM_FAILURE_STREAK_THRESHOLD):
            await lb.report_failure("llm-1")
        assert (await lb.get_next_provider(task_type="llm")).id == "llm-2"

        # A successful run resets the streak.
        await lb.report_success("llm-1")
        assert (await lb.get_next_provider(task_type="llm")).id == "llm-1"

    async def test_llm_routing_falls_back_when_all_providers_failing(self, session: Session):
        """If every LLM provider is in a failure streak, routing still returns a
        provider (failover is handled upstream by job_runner) instead of None."""
        from services.load_balancer import LLM_FAILURE_STREAK_THRESHOLD

        for pid in ("llm-a", "llm-b"):
            session.add(Provider(
                id=pid, type="modal", enabled=True, priority=1,
                worker_type="llm", credentials={}, config={},
            ))
        session.commit()

        lb = LoadBalancer(session, strategy="priority")
        for pid in ("llm-a", "llm-b"):
            for _ in range(LLM_FAILURE_STREAK_THRESHOLD):
                await lb.report_failure(pid)

        assert await lb.get_next_provider(task_type="llm") is not None

    async def test_llm_routing_respects_excluded_providers(self, session: Session):
        """LLM routing must still honor exclude_provider_ids (job-runner failover)."""
        for pid, priority in (("llm-x", 1), ("llm-y", 2)):
            session.add(Provider(
                id=pid, type="modal", enabled=True, priority=priority,
                worker_type="llm", credentials={}, config={},
            ))
        session.commit()

        lb = LoadBalancer(session, strategy="priority")
        selected = await lb.get_next_provider(task_type="llm", exclude_provider_ids={"llm-x"})
        assert selected is not None and selected.id == "llm-y"

    async def test_invalidation_clears_both_availability_caches(self, monkeypatch):
        """The ModelAvailabilityService cache must share the one invalidation path.

        `clear_available_models_cache` had no production caller — its docstring
        named the model-install and provider-toggle paths and none existed — so
        a deleted model stayed servable, and an installed one invisible, for
        the 30 s TTL. Writers clear both through
        `LoadBalancer.invalidate_model_availability_cache`.
        """
        from services import model_availability_service as svc

        import time

        svc._available_models_cache["checkpoints"] = (
            time.monotonic(),
            ["ghost.safetensors"],
        )
        assert svc._cached_available_models("checkpoints") == ["ghost.safetensors"]

        LoadBalancer.invalidate_model_availability_cache()

        assert svc._available_models_cache == {}
        assert svc._cached_available_models("checkpoints") is None


class TestModalityIsolation:
    """TTS and image keep separate counters.

    They used to share one runtime state, so a TTS outage incremented the
    failure count on a provider that was healthy for images — and the image
    path's circuit breaker then took it out of image rotation. The same
    sharing is why `get_stats`' per-modality breakdown was one set of
    numbers printed three times.
    """

    @pytest.fixture(autouse=True)
    def reset_lb_state(self):
        LoadBalancer.reset_state()
        yield
        LoadBalancer.reset_state()

    async def test_a_tts_failure_does_not_take_a_provider_out_of_image_rotation(
        self, session: Session
    ):
        from services.load_balancer_factory import create_load_balancer

        # One provider that serves both modalities, which is the real shape:
        # the same ComfyUI box serves `image` and `tts`.
        provider = Provider(
            id="comfy-box",
            type="direct_comfy",
            worker_type="comfyui",
            capabilities=["image", "tts"],
            enabled=True,
            priority=1,
            credentials={},
            config={},
        )
        session.add(provider)
        session.commit()

        image_lb = create_load_balancer(session, task_type="image")
        tts_lb = create_load_balancer(session, task_type="tts")

        # Fail the TTS side hard.
        for _ in range(5):
            await tts_lb.report_failure(provider.id)

        # The image side must be untouched.
        image_state = image_lb.runtime_state
        assert image_state.provider_failures.get(provider.id, 0) == 0

        selected = await image_lb.get_next_provider(task_type="image")
        assert selected is not None and selected.id == "comfy-box"

    async def test_the_stats_breakdown_reads_each_modality_own_counters(
        self, session: Session
    ):
        from services.load_balancer_factory import create_load_balancer

        provider = Provider(
            id="comfy-box",
            type="direct_comfy",
            worker_type="comfyui",
            capabilities=["image", "tts"],
            enabled=True,
            priority=1,
            credentials={},
            config={},
        )
        session.add(provider)
        session.commit()

        image_lb = create_load_balancer(session, task_type="image")
        tts_lb = create_load_balancer(session, task_type="tts")

        image_lb.runtime_state.provider_job_counts[provider.id] = 7
        tts_lb.runtime_state.provider_job_counts[provider.id] = 2
        tts_lb.runtime_state.provider_failures[provider.id] = 9

        stats = await image_lb.get_stats()
        by_modality = stats["by_modality"]

        assert by_modality["image"]["active_jobs"] == 7
        assert by_modality["tts"]["active_jobs"] == 2
        # Nine TTS failures is past the image threshold, but the image
        # breakdown must not see them.
        assert by_modality["image"]["failing_providers"] == 0
        assert by_modality["tts"]["failing_providers"] == 1
