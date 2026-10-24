import os
import re
from typing import Optional
from urllib.parse import urlparse

# Strict test database name pattern:
# Must start with 'test_' (e.g. 'test_safenet'),
# end with '_test' (e.g. 'safenet_test'), or equal 'test'.
# Substrings inside words like 'contest' or 'testament' will strictly fail.
TEST_DB_NAME_PATTERN = re.compile(r"^(test(_[a-z0-9_]+)?|[a-z0-9_]+_test)$", re.IGNORECASE)


def assert_is_test_database(url: Optional[str]) -> str:
    """
    Strict safety guard: ensures automated tests only clean/mutate
    isolated test databases.
    Raises ValueError if url is missing or empty.
    Raises RuntimeError if database name is unsafe or ambiguous.
    """
    if not url or not str(url).strip():
        raise ValueError("TEST_DATABASE_URL is not set or empty.")
    
    parsed = urlparse(str(url).strip())
    db_name = parsed.path.lstrip("/").split("?")[0].strip()
    if not db_name:
        raise ValueError(f"Could not extract database name from URL: '{url}'")

    if not TEST_DB_NAME_PATTERN.match(db_name):
        raise RuntimeError(
            f"SAFETY ABORT: Refusing to clean or mutate database '{db_name}'. "
            "Test database name must strictly start with 'test_' (e.g. 'test_safenet'), "
            "end with '_test' (e.g. 'safenet_test'), or equal 'test'. "
            "Names containing 'test' as a substring inside other words (such as 'contest' or 'testament') are strictly rejected."
        )
    return db_name


def check_destructive_cleanup_allowed() -> None:
    """
    Verifies explicit permission for destructive test cleanup.
    Set ALLOW_DESTRUCTIVE_TEST_CLEANUP=0 to block all test database truncations.
    """
    flag = os.getenv("ALLOW_DESTRUCTIVE_TEST_CLEANUP", "1").strip().lower()
    if flag in ("0", "false", "no", "disabled"):
        raise RuntimeError(
            f"SAFETY ABORT: Destructive test cleanup is disabled by ALLOW_DESTRUCTIVE_TEST_CLEANUP='{flag}'. "
            "Refusing to delete records."
        )


def clean_test_database(session, url: Optional[str] = None) -> None:
    """
    Single unified protective function for all test data cleanup operations.
    Validates database name and permission before deleting records in foreign key order.
    """
    target_url = url or TEST_DB_URL
    assert_is_test_database(target_url)
    check_destructive_cleanup_allowed()

    from ai_data.db.models import EntityRecord, ReviewRecord, AnalysisRecord, MessageRecord
    session.query(EntityRecord).delete()
    session.query(ReviewRecord).delete()
    session.query(AnalysisRecord).delete()
    session.query(MessageRecord).delete()
    session.commit()


# Prioritize TEST_DATABASE_URL over DATABASE_URL for tests
TEST_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
if not TEST_DB_URL:
    TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/safenet_test"

assert_is_test_database(TEST_DB_URL)
os.environ["DATABASE_URL"] = TEST_DB_URL

from ai_data.db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord

_SessionFactory = None


def get_test_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        assert_is_test_database(TEST_DB_URL)
        _SessionFactory = init_db(TEST_DB_URL)
    return _SessionFactory


def get_clean_test_session():
    assert_is_test_database(TEST_DB_URL)
    Session = get_test_session_factory()
    session = Session()
    clean_test_database(session, TEST_DB_URL)
    return session
