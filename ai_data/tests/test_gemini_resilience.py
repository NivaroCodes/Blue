import unittest
from unittest.mock import patch, MagicMock
from email.utils import formatdate
import time

from ai_data.llm_client import (
    call_gemini_api,
    AIAnalysisError,
    AIQuotaError,
    _compute_backoff_delay,
    _parse_retry_after,
    _sanitize_error_msg,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_BASE_DELAY,
    DEFAULT_MAX_DELAY,
)
from ai_data.models import RiskLevelEnum, AnalysisResult


class TestGeminiResilience(unittest.TestCase):
    """
    Unit tests for Gemini exponential backoff, jitter, Retry-After,
    and resilience against 503 and 429 errors.
    All tests use mocks — NO real network requests are made.
    """

    def _make_200_response(self, text_content: str = None) -> MagicMock:
        if text_content is None:
            text_content = (
                '{"risk_score": 85, "risk_level": "HIGH", '
                '"reasons": [{"code": "GUARANTEED_PROFIT", "evidence": "100% гарантия дохода"}], '
                '"explanation": "Пирамида", "confidence": 0.95}'
            )
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": text_content}]
                }
            }]
        }
        return resp

    def _make_503_response(self, message: str = "This model is currently experiencing high demand.", retry_after: str = None) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 503
        resp.headers = {"Retry-After": retry_after} if retry_after else {}
        resp.text = f'{{"error": {{"code": 503, "message": "{message}", "status": "UNAVAILABLE"}}}}'
        resp.json.return_value = {
            "error": {
                "code": 503,
                "message": message,
                "status": "UNAVAILABLE"
            }
        }
        return resp

    def _make_429_response(self, message: str = "Resource has been exhausted (e.g. check quota).", retry_after: str = None) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {"Retry-After": retry_after} if retry_after else {}
        resp.text = f'{{"error": {{"code": 429, "message": "{message}", "status": "RESOURCE_EXHAUSTED"}}}}'
        resp.json.return_value = {
            "error": {
                "code": 429,
                "message": message,
                "status": "RESOURCE_EXHAUSTED"
            }
        }
        return resp

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_503_503_success_recovery(self, mock_post, mock_sleep):
        """
        Sequence: 503 -> 503 -> 200 (Success).
        Client retries with backoff and jitter, recovering successfully on 3rd attempt.
        """
        mock_post.side_effect = [
            self._make_503_response("High demand spike 1"),
            self._make_503_response("High demand spike 2"),
            self._make_200_response(),
        ]

        result = call_gemini_api(
            text="100% гарантия дохода каждый день",
            api_key="test-key-safe",
            model="gemini-3.8-flash",
            max_attempts=4,
            base_delay=1.0,
        )

        self.assertIsInstance(result, AnalysisResult)
        self.assertEqual(result.risk_level, RiskLevelEnum.HIGH)
        self.assertEqual(result.risk_score, 85)
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

        # Verify sleeps were called with reasonable exponential delays > 0
        sleep_durations = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertGreater(sleep_durations[0], 0.5)
        self.assertGreater(sleep_durations[1], 1.0)

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_persistent_503_raises_controlled_error(self, mock_post, mock_sleep):
        """
        Sequence: 503 -> 503 -> 503 -> 503 (Persistent outage).
        Client raises AIAnalysisError without creating fake analysis results.
        """
        mock_post.side_effect = [
            self._make_503_response(),
            self._make_503_response(),
            self._make_503_response(),
            self._make_503_response(),
        ]

        with self.assertRaises(AIAnalysisError) as ctx:
            call_gemini_api(
                text="вложите деньги",
                api_key="test-key-safe",
                model="gemini-3.8-flash",
                max_attempts=4,
                base_delay=1.0,
            )

        err_msg = str(ctx.exception)
        self.assertIn("503", err_msg)
        self.assertIn("UNAVAILABLE", err_msg)
        self.assertIn("failed after 4 attempts", err_msg)
        self.assertEqual(mock_post.call_count, 4)
        self.assertEqual(mock_sleep.call_count, 3)

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_429_quota_and_rate_limit_diagnostics(self, mock_post, mock_sleep):
        """
        429 stops immediately, distinguishing a daily quota from a short rate limit.
        """
        # Case 1: Quota exhausted
        mock_post.side_effect = [self._make_429_response("RequestsPerDay quota exceeded")]

        with self.assertRaises(AIQuotaError) as ctx:
            call_gemini_api(
                text="тест",
                api_key="test-key-safe",
                model="gemini-3.8-flash",
                max_attempts=2,
                base_delay=0.1,
            )
        self.assertTrue(ctx.exception.daily)
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

        # Case 2: Pure rate limit
        mock_post.reset_mock()
        mock_post.side_effect = [self._make_429_response("Too many requests per minute")]

        with self.assertRaises(AIQuotaError) as ctx:
            call_gemini_api(
                text="тест",
                api_key="test-key-safe",
                model="gemini-3.8-flash",
                max_attempts=2,
                base_delay=0.1,
            )
        self.assertFalse(ctx.exception.daily)
        self.assertIn("429", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 1)

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_retry_after_header_respected(self, mock_post, mock_sleep):
        """
        When server sends Retry-After: 3, client respects server guidance.
        """
        mock_post.side_effect = [
            self._make_503_response("High demand", retry_after="3"),
            self._make_200_response(),
        ]

        res = call_gemini_api(
            text="100% гарантия дохода каждый день",
            api_key="test-key-safe",
            model="gemini-3.8-flash",
            max_attempts=3,
        )
        self.assertIsInstance(res, AnalysisResult)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

        slept = mock_sleep.call_args[0][0]
        # Should be at least 3.0 seconds plus slight jitter
        self.assertGreaterEqual(slept, 3.0)
        self.assertLess(slept, 4.0)

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_retry_after_http_date_respected(self, mock_post, mock_sleep):
        """
        When server sends Retry-After as an HTTP date, it is parsed and converted to seconds.
        """
        # Future date 5 seconds from now
        future_time = time.time() + 5.0
        http_date = formatdate(future_time, usegmt=True)

        mock_post.side_effect = [
            self._make_503_response("High demand", retry_after=http_date),
            self._make_200_response(),
        ]

        res = call_gemini_api(
            text="100% гарантия дохода каждый день",
            api_key="test-key-safe",
            model="gemini-3.8-flash",
            max_attempts=3,
        )
        self.assertIsInstance(res, AnalysisResult)
        self.assertEqual(mock_sleep.call_count, 1)
        slept = mock_sleep.call_args[0][0]
        self.assertGreaterEqual(slept, 2.5)
        self.assertLessEqual(slept, 6.5)

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_excessive_retry_after_aborts_immediately(self, mock_post, mock_sleep):
        """
        If server sends an excessively long Retry-After (e.g. 120s),
        the client aborts immediately to avoid hanging the background worker or holding DB lock.
        """
        mock_post.side_effect = [
            self._make_503_response("Over capacity", retry_after="120"),
        ]

        with self.assertRaises(AIAnalysisError) as ctx:
            call_gemini_api(
                text="тест",
                api_key="test-key-safe",
                model="gemini-3.8-flash",
                max_attempts=3,
            )

        err_msg = str(ctx.exception)
        self.assertIn("exceeding maximum allowed retry window", err_msg)
        self.assertIn("120.0s", err_msg)
        # Did not sleep!
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_max_total_wait_cap_aborts_retries(self, mock_post, mock_sleep):
        """
        If cumulative delay would exceed max_total_wait, retries abort early.
        """
        mock_post.side_effect = [
            self._make_503_response(),
            self._make_503_response(),
            self._make_503_response(),
        ]

        with self.assertRaises(AIAnalysisError):
            call_gemini_api(
                text="тест",
                api_key="test-key-safe",
                model="gemini-3.8-flash",
                max_attempts=5,
                base_delay=1.8,
                max_total_wait=3.0,  # Cap at 3.0s so after 1st retry (delay in [1.8, 2.8]) it sleeps, then 2nd retry (>3.6s) aborts
            )

        # First delay ~2.0s is slept, second delay exceeds 3.0s budget, so aborts
        self.assertEqual(mock_sleep.call_count, 1)


    def test_secret_sanitization(self):
        """
        Verifies that API keys, tokens, and secret patterns are sanitized and never exposed.
        """
        sensitive_key = "AQ.DummySecretKeyPattern_SampleForTestingSanitizer123"
        err_raw = f"Error connecting to https://generativelanguage.googleapis.com?key={sensitive_key} with header x-goog-api-key: {sensitive_key}"

        sanitized = _sanitize_error_msg(err_raw)
        self.assertNotIn(sensitive_key, sanitized)
        self.assertIn("[REDACTED", sanitized)

    def test_jitter_is_randomized(self):
        """
        Verifies that delay computation includes random jitter and is not purely deterministic.
        """
        delays = [_compute_backoff_delay(attempt=1, base_delay=2.0) for _ in range(10)]
        # Not all delays should be identical
        self.assertGreater(len(set(delays)), 1)
        # All delays should be >= 2.0 (base * 2^1)
        for d in delays:
            self.assertGreaterEqual(d, 2.0)
            self.assertLessEqual(d, DEFAULT_MAX_DELAY)

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_timeout_exception_diagnostics(self, mock_post, mock_sleep):
        """
        Verifies that httpx.ReadTimeout and other TimeoutExceptions are classified
        specifically as Timeout (<Type>) and distinct from 429/503.
        """
        import httpx
        mock_post.side_effect = [
            httpx.ReadTimeout("The read operation timed out"),
            httpx.ReadTimeout("The read operation timed out"),
        ]

        with self.assertRaises(AIAnalysisError) as ctx:
            call_gemini_api(
                text="тест",
                api_key="test-key-safe",
                model="gemini-3.8-flash",
                max_attempts=2,
                base_delay=0.1,
                max_total_wait=10.0,
            )

        err_msg = str(ctx.exception)
        self.assertIn("Timeout (ReadTimeout)", err_msg)
        self.assertIn("The read operation timed out", err_msg)
        self.assertEqual(mock_post.call_count, 2)

    @patch("time.sleep")
    @patch("httpx.Client.post")
    def test_deterministic_wall_clock_budget_enforcement(self, mock_post, mock_sleep):
        """
        Uses controlled monotonic timestamps to deterministically prove that:
        1. Remaining budget dynamically constrains HTTP timeout on each attempt.
        2. Attempts abort immediately when operation deadline is reached.
        """
        # Timeline:
        # Start: 100.0 (deadline = 110.0, budget = 10.0s)
        # Attempt 1 check: 100.0 -> remaining = 10.0s
        # Attempt 1 post finishes: 104.0 (took 4s)
        # Attempt 1 backoff check: remaining = 110.0 - 104.0 = 6.0s. Delay = 2.0s
        # Attempt 2 check: 106.0 -> remaining = 4.0s
        # Attempt 2 post finishes: 109.5 (took 3.5s)
        # Attempt 2 backoff check: remaining = 110.0 - 109.5 = 0.5s. Delay = 4.0s -> aborts backoff!
        # Final elapsed check: 110.0
        time_values = iter([100.0, 100.0, 104.0, 106.0, 106.0, 109.5, 110.0, 110.0])

        with patch("time.monotonic", side_effect=lambda: next(time_values)):
            mock_post.side_effect = [
                self._make_503_response("Overloaded 1"),
                self._make_503_response("Overloaded 2"),
                self._make_200_response(),
            ]

            with self.assertRaises(AIAnalysisError) as ctx:
                call_gemini_api(
                    text="тест",
                    api_key="test-key-safe",
                    model="gemini-3.8-flash",
                    max_attempts=4,
                    base_delay=2.0,
                    max_total_wait=10.0,
                    per_request_timeout=8.0,
                )

            # Exactly 2 attempts were made before budget exhausted
            self.assertEqual(mock_post.call_count, 2)

            # Check timeout passed to first post: constrained to per_request_timeout (8.0s)
            first_timeout = mock_post.call_args_list[0][1]["timeout"]
            self.assertEqual(first_timeout.read, 8.0)

            # Check timeout passed to second post: remaining budget was 4.0s, so read was constrained to 4.0s!
            second_timeout = mock_post.call_args_list[1][1]["timeout"]
            self.assertEqual(second_timeout.read, 4.0)

            err_msg = str(ctx.exception)
            self.assertIn("budget: 10.0s", err_msg)

    @patch("httpx.Client.post")
    def test_real_clock_wall_clock_budget_tolerance(self, mock_post):
        """
        Verifies with real wall-clock that multiple slow attempts
        never exceed the scheduled budget inside call_gemini_api.
        """
        import httpx
        import re

        # Simulates slow requests that time out after 0.08s each
        def slow_timeout(*args, **kwargs):
            time.sleep(0.08)
            raise httpx.ReadTimeout("Socket read timed out")

        mock_post.side_effect = slow_timeout

        budget = 0.40  # 400ms total budget
        with self.assertRaises(AIAnalysisError) as ctx:
            call_gemini_api(
                text="тест",
                api_key="test-key-safe",
                model="gemini-3.8-flash",
                max_attempts=5,
                base_delay=0.02,
                max_total_wait=budget,
                per_request_timeout=0.15,
            )

        err_msg = str(ctx.exception)
        self.assertIn("budget: 0.4s", err_msg)
        m = re.search(r"elapsed:\s+([0-9\.]+)s", err_msg)
        self.assertIsNotNone(m)
        elapsed_val = float(m.group(1))
        # Total elapsed inside call_gemini_api must be strictly within budget + small tick tolerance
        self.assertLessEqual(elapsed_val, budget + 0.05)





if __name__ == "__main__":
    unittest.main()
