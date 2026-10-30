"""Tests for critical bugs identified in audit."""
import pytest
import asyncio
import sys
import os

# Add backend_v2 to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.events import redact_secrets


class TestCriticalBugs:
    """Test cases for critical bugs."""

    @pytest.mark.asyncio
    async def test_path_traversal_vulnerability(self):
        """Test that path traversal is prevented."""
        # This test will be implemented after the fix
        pass

    def test_capability_cache_unbounded(self):
        """Test that _capability_cache is bounded."""
        # This test will be implemented after the fix
        pass

    def test_secret_redaction_in_exceptions(self):
        """Test that secrets are redacted from exception strings."""
        # Test that the redact_secrets function exists and works
        test_string = "Error with token=secret123abc"
        result = redact_secrets(test_string)
        assert "secret123abc" not in result
        assert "***REDACTED***" in result

    @pytest.mark.asyncio
    async def test_job_status_race_condition(self):
        """Test that _get_job_status handles concurrent access."""
        # This test will be implemented after the fix
        pass

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

    def test_websocket_memory_leaks(self):
        """Test that WebSocket listeners can be cleaned up."""
        # This test will be implemented after the fix
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
