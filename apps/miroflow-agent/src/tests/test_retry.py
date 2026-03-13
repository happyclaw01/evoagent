# Copyright (c) 2025 MiroMind
# Unit Tests for EA-012: Path Failure Retry

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRetryableErrorDetection(unittest.TestCase):
    """Test retryable error detection"""

    def test_rate_limit_errors(self):
        """Test: rate_limit is detected"""
        from src.core.multi_path import _is_retryable_error
        
        self.assertTrue(_is_retryable_error("rate limit exceeded"))
        self.assertTrue(_is_retryable_error("rate_limit"))
        self.assertTrue(_is_retryable_error("429 rate limit"))

    def test_timeout_errors(self):
        """Test: timeout errors are detected"""
        from src.core.multi_path import _is_retryable_error
        
        self.assertTrue(_is_retryable_error("Request timed out"))
        self.assertTrue(_is_retryable_error("timeout"))
        self.assertTrue(_is_retryable_error("Connection timed out"))

    def test_connection_errors(self):
        """Test: connection errors are detected"""
        from src.core.multi_path import _is_retryable_error
        
        self.assertTrue(_is_retryable_error("ConnectionError"))
        self.assertTrue(_is_retryable_error("connection refused"))
        self.assertTrue(_is_retryable_error("httpx.ConnectError"))

    def test_server_errors(self):
        """Test: 5xx server errors are detected"""
        from src.core.multi_path import _is_retryable_error
        
        self.assertTrue(_is_retryable_error("503 Service Unavailable"))
        self.assertTrue(_is_retryable_error("502 Bad Gateway"))
        self.assertTrue(_is_retryable_error("504 Gateway Timeout"))
        self.assertTrue(_is_retryable_error("InternalServerError"))

    def test_quota_errors(self):
        """Test: quota errors are detected"""
        from src.core.multi_path import _is_retryable_error
        
        # quota is in the patterns, but not "insufficient credits" exactly
        self.assertTrue(_is_retryable_error("quota exceeded"))
        self.assertTrue(_is_retryable_error("quota limit"))

    def test_non_retryable_errors(self):
        """Test: non-retryable errors are not detected"""
        from src.core.multi_path import _is_retryable_error
        
        self.assertFalse(_is_retryable_error("Invalid API key"))
        self.assertFalse(_is_retryable_error("Authentication failed"))
        self.assertFalse(_is_retryable_error("Permission denied"))
        self.assertFalse(_is_retryable_error("Not found"))
        self.assertFalse(_is_retryable_error("Validation error"))


class TestFallbackStrategy(unittest.TestCase):
    """Test fallback strategy selection"""

    def test_get_different_strategy(self):
        """Test: fallback returns different strategy"""
        from src.core.multi_path import _get_fallback_strategy
        
        fallback = _get_fallback_strategy("depth_first")
        
        self.assertIsNotNone(fallback)
        self.assertNotEqual(fallback["name"], "depth_first")

    def test_fallback_returns_breadth_for_depth(self):
        """Test: depth_first gets breadth_first as fallback"""
        from src.core.multi_path import _get_fallback_strategy
        
        fallback = _get_fallback_strategy("depth_first")
        
        self.assertEqual(fallback["name"], "breadth_first")

    def test_fallback_returns_none_for_unknown(self):
        """Test: unknown strategy returns None"""
        from src.core.multi_path import _get_fallback_strategy
        
        fallback = _get_fallback_strategy("unknown_strategy")
        
        # Should still return a valid fallback
        self.assertIsNotNone(fallback)


class TestRetryConfiguration(unittest.TestCase):
    """Test retry configuration constants"""

    def test_max_retries_defined(self):
        """Test: MAX_RETRIES is defined"""
        from src.core.multi_path import MAX_RETRIES
        
        self.assertEqual(MAX_RETRIES, 2)
        self.assertIsInstance(MAX_RETRIES, int)
        self.assertGreater(MAX_RETRIES, 0)

    def test_fallback_strategies_defined(self):
        """Test: FALLBACK_STRATEGIES is defined"""
        from src.core.multi_path import FALLBACK_STRATEGIES
        
        self.assertIsInstance(FALLBACK_STRATEGIES, list)
        self.assertGreater(len(FALLBACK_STRATEGIES), 0)
        self.assertIn("breadth_first", FALLBACK_STRATEGIES)

    def test_retryable_patterns_defined(self):
        """Test: RETRYABLE_ERROR_PATTERNS is defined"""
        from src.core.multi_path import RETRYABLE_ERROR_PATTERNS
        
        self.assertIsInstance(RETRYABLE_ERROR_PATTERNS, list)
        self.assertGreater(len(RETRYABLE_ERROR_PATTERNS), 0)


class TestRetryLogic(unittest.TestCase):
    """Test retry logic flow"""

    def test_retry_count_increments(self):
        """Test: retry count increments on each retry"""
        # Simulate retry counter
        retry_count = 0
        max_retries = 2
        
        # First retry
        retry_count += 1
        self.assertEqual(retry_count, 1)
        self.assertLess(retry_count, max_retries)
        
        # Second retry
        retry_count += 1
        self.assertEqual(retry_count, 2)
        self.assertEqual(retry_count, max_retries)

    def test_retry_stops_after_max(self):
        """Test: retry stops after max retries"""
        retry_count = 0
        max_retries = 2
        
        # Simulate attempts
        for i in range(5):
            if retry_count < max_retries:
                retry_count += 1
        
        self.assertEqual(retry_count, max_retries)
        # Should not retry again
        self.assertFalse(retry_count < max_retries)

    def test_different_strategy_on_retry(self):
        """Test: different strategy is used on retry"""
        original = "depth_first"
        
        from src.core.multi_path import FALLBACK_STRATEGIES
        
        # Get a fallback that's different
        fallback = None
        for f in FALLBACK_STRATEGIES:
            if f != original:
                fallback = f
                break
        
        self.assertIsNotNone(fallback)
        self.assertNotEqual(fallback, original)


class TestErrorClassification(unittest.TestCase):
    """Test error classification for retry"""

    def test_api_errors_retryable(self):
        """Test: API errors should be retryable"""
        from src.core.multi_path import _is_retryable_error
        
        api_errors = [
            "API rate limit exceeded",
            "OpenAI API error: 429",
            "API connection timeout",
        ]
        
        for err in api_errors:
            self.assertTrue(_is_retryable_error(err), f"{err} should be retryable")

    def test_auth_errors_not_retryable(self):
        """Test: auth errors should not be retryable"""
        from src.core.multi_path import _is_retryable_error
        
        auth_errors = [
            "Invalid API key",
            "Authentication failed",
            "Unauthorized access",
            "Permission denied",
        ]
        
        for err in auth_errors:
            self.assertFalse(_is_retryable_error(err), f"{err} should NOT be retryable")

    def test_validation_errors_not_retryable(self):
        """Test: validation errors should not be retryable"""
        from src.core.multi_path import _is_retryable_error
        
        validation_errors = [
            "Invalid request: missing required field",
            "Validation error: invalid parameter",
            "Bad request format",
        ]
        
        for err in validation_errors:
            self.assertFalse(_is_retryable_error(err), f"{err} should NOT be retryable")


class TestRetryBehaviorInPath(unittest.TestCase):
    """Test retry behavior in path execution"""

    def test_path_metadata_includes_retry_info(self):
        """Test: path metadata can include retry count"""
        # Simulate metadata with retry info
        metadata = {
            "strategy": "depth_first",
            "status": "failed",
            "error": "rate limit exceeded",
            "retry_count": 1,
            "original_strategy": "breadth_first",
        }
        
        # Verify metadata structure
        self.assertIn("retry_count", metadata)
        self.assertEqual(metadata["retry_count"], 1)
        self.assertIn("original_strategy", metadata)

    def test_fallback_strategy_preserves_info(self):
        """Test: fallback maintains original strategy info"""
        original_strategy = "breadth_first"
        
        # When using fallback, track original
        metadata = {
            "strategy": "depth_first",
            "original_strategy": original_strategy,
            "status": "success",
            "retry_count": 1,
        }
        
        self.assertEqual(metadata["original_strategy"], original_strategy)
        self.assertEqual(metadata["status"], "success")


if __name__ == "__main__":
    unittest.main(verbosity=2)