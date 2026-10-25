"""Cloud runtime guards, bounded PostgreSQL connections and non-destructive release setup."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import TimeoutError

from ai_data.tests.test_db_helper import TEST_DB_URL, get_clean_test_session
from ai_data.db.models import init_db, MessageRecord, make_message_pk, utc_now
from ai_data.media import storage_backend, MediaError
import ai_data.api_server as api
import run


class TestFlyRuntime(unittest.TestCase):
    def test_fly_ingestion_fails_closed_even_if_production_flag_was_omitted(self):
        with patch.dict(os.environ, {"FLY_APP_NAME": "test-blue", "PRODUCTION": "0", "INGEST_API_TOKEN": ""}):
            response = TestClient(api.app).post("/api/messages", json={
                "chat_id": "synthetic-test", "message_id": "1", "sender_hash": "fictional",
                "text": "[SYNTHETIC] Test message",
            })
        self.assertEqual(response.status_code, 503)

    def test_fly_rejects_isolated_local_media(self):
        with patch.dict(os.environ, {"FLY_APP_NAME": "test-blue", "MEDIA_STORAGE": "local"}):
            with self.assertRaises(MediaError):
                storage_backend()

    def test_production_never_enables_development_reload(self):
        with patch.dict(os.environ, {"FLY_APP_NAME": "test-blue", "RELOAD": "true", "HOST": "0.0.0.0", "PORT": "8000"}), \
                patch("sys.argv", ["run.py", "api"]), patch("uvicorn.run") as server:
            run.main()
        self.assertFalse(server.call_args.kwargs["reload"])

    def test_small_pool_caps_simultaneous_database_connections(self):
        with patch.dict(os.environ, {"DB_POOL_SIZE": "2", "DB_MAX_OVERFLOW": "0", "DB_POOL_TIMEOUT": "1"}):
            engine = init_db(TEST_DB_URL).kw["bind"]
        try:
            with engine.connect(), engine.connect():
                with self.assertRaises(TimeoutError):
                    engine.connect()
        finally:
            engine.dispose()

    def test_release_initialization_preserves_existing_messages(self):
        session = get_clean_test_session()
        pk = make_message_pk("telegram", "synthetic-test", "release-preserve")
        try:
            session.add(MessageRecord(id=pk, platform="telegram", chat_id="synthetic-test",
                                      message_id="release-preserve", sender_hash="fictional",
                                      text="[SYNTHETIC] Preserve existing row", timestamp=utc_now(), status="PENDING"))
            session.commit()
            with patch.dict(os.environ, {"DATABASE_URL": TEST_DB_URL}), patch("sys.argv", ["run.py", "init-db"]):
                run.main()
            session.expire_all()
            self.assertIsNotNone(session.get(MessageRecord, pk))
            self.assertEqual(session.query(MessageRecord).count(), 1)
        finally:
            session.close()
