"""Tests for critical bugs identified in audit."""
import pytest
import sys
import os

# Add backend_v2 to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.events import redact_secrets


class TestCriticalBugs:
    """Test cases for critical bugs."""


    def test_capability_cache_bounded(self):
        """_capability_cache must exist and be bounded with a TTL.

        Regression: commit 27d74c3c deleted the definition while eight call
        sites (and engine_factory.invalidate_engine's import) still used it.
        """
        from services import load_balancer

        cache = load_balancer._capability_cache
        assert getattr(cache, "maxsize", None), "capability cache must be bounded"
        assert getattr(cache, "ttl", 0) > 0, "capability cache must expire"
        cache["bounded-probe"] = (0.0, {"samplers": ["KSampler"]})
        assert "bounded-probe" in cache

    def test_invalidate_engine_clears_health_and_capability_caches(self):
        """Provider rotation must clear health + capability verdicts.

        Regression: the import of `_capability_cache` in invalidate_engine sits
        inside a bare `try/except Exception: pass`, so when the definition was
        missing the ImportError was swallowed and rotation silently stopped
        clearing EVERY health-cache key along with it.
        """
        from services import load_balancer
        from services.engines import engine_factory

        pid = "rotated-provider"
        keys = [
            f"in_process:{pid}",
            f"in_process:{pid}:image",
            f"in_process:{pid}:llm",
            f"in_process:{pid}:tts",
        ]
        for key in keys:
            load_balancer._provider_health_cache[key] = True
        load_balancer._capability_cache[pid] = (0.0, {"samplers": ["KSampler"]})

        engine_factory.invalidate_engine(pid)

        for key in keys:
            assert key not in load_balancer._provider_health_cache, (
                f"stale health verdict survived rotation: {key}"
            )
        assert pid not in load_balancer._capability_cache, (
            "stale capability verdict survived rotation"
        )

    def test_secret_redaction_in_exceptions(self):
        """Test that secrets are redacted from exception strings."""
        # Test that the redact_secrets function exists and works
        test_string = "Error with token=secret123abc"
        result = redact_secrets(test_string)
        assert "secret123abc" not in result
        assert "***REDACTED***" in result


    def test_ksampler_coverage(self):
        """Test that all KSampler variants are covered."""
        from core.workflow_parser import KSAMPLER_NODE_CLASSES
        # Check for common KSampler variants
        expected_variants = [
            "KSampler",
            "KSampler (Efficient)", 
            "KSamplerAdvanced",
            "KSampler (Advanced)",  # Common variant
        ]
        for variant in expected_variants:
            assert variant in KSAMPLER_NODE_CLASSES, f"Missing KSampler variant: {variant}"

    def test_db_pool_recycle_too_aggressive(self):
        """Test that DB_POOL_RECYCLE is at least 3600 seconds."""
        from infrastructure.database import DB_POOL_RECYCLE
        assert DB_POOL_RECYCLE >= 3600, f"DB_POOL_RECYCLE is too aggressive: {DB_POOL_RECYCLE}s"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
