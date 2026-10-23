import os

# Default to local PostgreSQL test database for automated test suite if not specified in environment
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/safenet_test"

from ai_data.db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord

TEST_DB_URL = os.getenv("DATABASE_URL")
_SessionFactory = None


def get_test_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = init_db(TEST_DB_URL)
    return _SessionFactory


def get_clean_test_session():
    Session = get_test_session_factory()
    session = Session()
    session.query(EntityRecord).delete()
    session.query(ReviewRecord).delete()
    session.query(AnalysisRecord).delete()
    session.query(MessageRecord).delete()
    session.commit()
    return session
