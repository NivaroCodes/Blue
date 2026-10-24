import os
from urllib.parse import urlparse

def assert_is_test_database(url: str) -> None:
    """
    Strict safety guard: ensures automated tests only clean/mutate
    isolated test databases (e.g. safenet_test).
    """
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/").split("?")[0].lower()
    if "test" not in db_name:
        raise RuntimeError(
            f"SAFETY ABORT: Refusing to clean or mutate database '{db_name}'. "
            "Automated test suites are only permitted on databases whose name explicitly contains 'test' (e.g. safenet_test)."
        )

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
    session.query(EntityRecord).delete()
    session.query(ReviewRecord).delete()
    session.query(AnalysisRecord).delete()
    session.query(MessageRecord).delete()
    session.commit()
    return session
