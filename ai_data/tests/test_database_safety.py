import os
import unittest
from ai_data.tests.test_db_helper import (
    assert_is_test_database,
    check_destructive_cleanup_allowed,
    clean_test_database,
    get_clean_test_session,
)


class TestDatabaseSafetyAssertions(unittest.TestCase):
    def test_safe_database_names_accepted(self):
        safe_urls = [
            "postgresql://postgres:postgres@localhost:5432/safenet_test",
            "postgresql://user:pass@127.0.0.1:5432/test_safenet",
            "postgresql://localhost/test",
            "postgresql://localhost/safenet_kz_test",
            "postgresql+psycopg2://localhost:5432/blue_backend_test",
        ]
        for url in safe_urls:
            db_name = assert_is_test_database(url)
            self.assertTrue("test" in db_name.lower())

    def test_unsafe_database_names_rejected(self):
        unsafe_urls = [
            "postgresql://postgres:postgres@localhost:5432/contest",
            "postgresql://localhost/contest_db",
            "postgresql://localhost/testament",
            "postgresql://localhost/safenet",
            "postgresql://localhost/production_db",
            "postgresql://localhost/latest_test_data",  # 'test' in the middle, neither start nor end
            "postgresql://localhost/main_db",
        ]
        for url in unsafe_urls:
            with self.assertRaises(RuntimeError, msg=f"Should have rejected unsafe url: {url}"):
                assert_is_test_database(url)

    def test_missing_or_empty_database_url_rejected(self):
        for invalid_url in [None, "", "   ", "postgresql://localhost/"]:
            with self.assertRaises(ValueError, msg=f"Should have rejected invalid url: {invalid_url}"):
                assert_is_test_database(invalid_url)

    def test_destructive_cleanup_disabled_permission_check(self):
        original_flag = os.environ.get("ALLOW_DESTRUCTIVE_TEST_CLEANUP")
        try:
            # When explicitly set to 0, false, no, or disabled -> abort
            for disabled_val in ["0", "false", "no", "disabled"]:
                os.environ["ALLOW_DESTRUCTIVE_TEST_CLEANUP"] = disabled_val
                with self.assertRaises(RuntimeError, msg=f"Should raise for {disabled_val}"):
                    check_destructive_cleanup_allowed()

            # When set to 1 or true -> allowed
            for enabled_val in ["1", "true", "yes"]:
                os.environ["ALLOW_DESTRUCTIVE_TEST_CLEANUP"] = enabled_val
                check_destructive_cleanup_allowed()
        finally:
            if original_flag is not None:
                os.environ["ALLOW_DESTRUCTIVE_TEST_CLEANUP"] = original_flag
            else:
                os.environ.pop("ALLOW_DESTRUCTIVE_TEST_CLEANUP", None)

    def test_clean_test_database_aborts_on_unsafe_url(self):
        # Mock session
        class FakeSession:
            def query(self, *args):
                raise AssertionError("Should never reach query on unsafe database")

        fake_session = FakeSession()
        with self.assertRaises(RuntimeError):
            clean_test_database(fake_session, "postgresql://localhost/contest")

    def test_clean_test_database_aborts_when_destructive_cleanup_disabled(self):
        class FakeSession:
            def query(self, *args):
                raise AssertionError("Should never reach query when cleanup disabled")

        original_flag = os.environ.get("ALLOW_DESTRUCTIVE_TEST_CLEANUP")
        try:
            os.environ["ALLOW_DESTRUCTIVE_TEST_CLEANUP"] = "0"
            fake_session = FakeSession()
            with self.assertRaises(RuntimeError):
                clean_test_database(fake_session, "postgresql://localhost/safenet_test")
        finally:
            if original_flag is not None:
                os.environ["ALLOW_DESTRUCTIVE_TEST_CLEANUP"] = original_flag
            else:
                os.environ.pop("ALLOW_DESTRUCTIVE_TEST_CLEANUP", None)


if __name__ == "__main__":
    unittest.main()
