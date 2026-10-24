"""
SafeNet KZ — Backend Reliability and Integration Test Suite
Verifies end-to-end correctness across all 10 required reliability criteria,
plus PostgreSQL compatibility and re-processing idempotency.
"""
import os
import re
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from ai_data.tests.test_db_helper import get_clean_test_session, get_test_session_factory, TEST_DB_URL
from fastapi.testclient import TestClient

import ai_data.api_server as api_server
from ai_data.db.models import (
    init_db,
    MessageRecord,
    AnalysisRecord,
    ReviewRecord,
    EntityRecord,
    serialize_to_alert_dict,
    parse_timestamp,
    format_timestamp,
    make_message_pk,
)
from ai_data.worker import process_pending_messages, claim_message, _sanitize_error
from ai_data.analyzer import analyze_message
from ai_data.llm_client import _parse_and_validate_llm_json, AIAnalysisError
from ai_data.models import AnalysisResult, ReasonItem, RiskLevelEnum


class TestReliabilityIntegration(unittest.TestCase):
    def setUp(self):
        self.Session = get_test_session_factory()
        _s = self.Session()
        _s.query(EntityRecord).delete()
        _s.query(ReviewRecord).delete()
        _s.query(AnalysisRecord).delete()
        _s.query(MessageRecord).delete()
        _s.commit()
        _s.close()
        self._orig_inline = api_server.INLINE_ANALYSIS
        api_server.INLINE_ANALYSIS = False

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        api_server.app.dependency_overrides[api_server.get_db] = override_get_db
        self.client = TestClient(api_server.app)

    def tearDown(self):
        api_server.app.dependency_overrides.clear()
        api_server.INLINE_ANALYSIS = self._orig_inline

    # -------------------------------------------------------------------------
    # 1. Message ingestion saves and initially receives PENDING status
    # -------------------------------------------------------------------------
    def test_ingest_pending_status(self):
        resp = self.client.post("/api/messages", json={
            "platform": "telegram",
            "chat_id": "tg_invest_kz",
            "chat_name": "Инвест Клуб",
            "message_id": "msg_001",
            "sender_hash": "sender_abc",
            "text": "Вложи 5 000 тг — удвой за 24ч",
            "timestamp": "2026-10-23T14:00:00+05:00",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "PENDING")
        self.assertEqual(data["message_id"], "msg_001")
        self.assertTrue(data["id"].startswith("alert_m_"))

        # Check in DB
        db = self.Session()
        rec = db.query(MessageRecord).filter(MessageRecord.message_id == "msg_001").first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, "PENDING")
        self.assertIsNone(rec.analysis)
        db.close()

    # -------------------------------------------------------------------------
    # 2. Worker processes message and persists results
    # -------------------------------------------------------------------------
    @patch("ai_data.analyzer.call_gemini_api")
    def test_worker_processes_and_stores(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=92,
            risk_level=RiskLevelEnum.HIGH,
            reasons=[ReasonItem(code="UNREALISTIC_RETURN", evidence="удвой за 24ч")],
            explanation="Обещание удвоения за сутки является признаком финансовой пирамиды.",
            confidence=0.95,
            model_version="gemini-3-flash-preview",
        )

        db = self.Session()
        pk = make_message_pk("telegram", "chat_1", "m_1")
        db.add(MessageRecord(
            id=pk, platform="telegram", chat_id="chat_1", chat_name="Chat 1",
            message_id="m_1", sender_hash="s_1", text="Вложи 5 000 тг — удвой за 24ч",
            timestamp=datetime.now(timezone.utc), status="PENDING",
        ))
        db.commit()

        count = process_pending_messages(db, limit=1, api_key="test_key", throttle_seconds=0)
        self.assertEqual(count, 1)

        rec = db.get(MessageRecord, pk)
        self.assertEqual(rec.status, "PROCESSED")
        self.assertIsNotNone(rec.analysis)
        self.assertEqual(rec.analysis.risk_score, 92)
        self.assertEqual(rec.analysis.risk_level, "HIGH")
        self.assertEqual(rec.analysis.review.review_status, "NEW")
        db.close()

    # -------------------------------------------------------------------------
    # 3. Repeated message ingestion does not create duplicate
    # -------------------------------------------------------------------------
    def test_repeated_ingestion_no_duplicate(self):
        payload = {
            "platform": "telegram",
            "chat_id": "chat_dedup",
            "chat_name": "Dedup Chat",
            "message_id": "msg_repeat",
            "sender_hash": "sender_dedup",
            "text": "Повторное сообщение",
            "timestamp": "2026-10-23T14:00:00+05:00",
        }
        r1 = self.client.post("/api/messages", json=payload)
        r2 = self.client.post("/api/messages", json=payload)

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["id"], r2.json()["id"])

        db = self.Session()
        count = db.query(MessageRecord).filter(
            MessageRecord.platform == "telegram",
            MessageRecord.chat_id == "chat_dedup",
            MessageRecord.message_id == "msg_repeat"
        ).count()
        self.assertEqual(count, 1)
        db.close()

    # -------------------------------------------------------------------------
    # 4. Two concurrent workers never process the same message simultaneously
    # -------------------------------------------------------------------------
    def test_concurrent_workers_exclusive_claims(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "concurrent_test.db"
            Session = get_test_session_factory()
            clean_s = Session()
            clean_s.query(EntityRecord).delete()
            clean_s.query(ReviewRecord).delete()
            clean_s.query(AnalysisRecord).delete()
            clean_s.query(MessageRecord).delete()
            clean_s.commit()
            clean_s.close()

            db = Session()
            now = datetime.now(timezone.utc)
            for i in range(8):
                db.add(MessageRecord(
                    id=f"concurrent_msg_{i}", platform="telegram", chat_id="c_conc",
                    chat_name="Conc Chat", message_id=str(i), sender_hash=f"sender_{i}",
                    text="Вложи 5000 тг", timestamp=now + timedelta(seconds=i),
                    status="PENDING",
                ))
            db.commit()
            db.close()

            def fake_gemini(text, **kwargs):
                time.sleep(0.01)
                return AnalysisResult(
                    risk_score=80, risk_level=RiskLevelEnum.HIGH,
                    reasons=[ReasonItem(code="MONEY_REQUEST", evidence="Вложи 5000 тг")],
                    explanation="Схема", confidence=0.9, model_version="test-model"
                )

            def worker_task(worker_id):
                s = Session()
                try:
                    while True:
                        claimed = process_pending_messages(s, limit=2, api_key="k", throttle_seconds=0, worker_id=worker_id)
                        if claimed == 0:
                            break
                finally:
                    s.close()

            with patch("ai_data.analyzer.call_gemini_api", side_effect=fake_gemini):
                t1 = threading.Thread(target=worker_task, args=("worker-alpha",))
                t2 = threading.Thread(target=worker_task, args=("worker-beta",))
                t1.start()
                t2.start()
                t1.join()
                t2.join()

            check_s = Session()
            all_recs = check_s.query(MessageRecord).filter(MessageRecord.chat_id == "c_conc").all()
            self.assertEqual(len(all_recs), 8)
            self.assertTrue(all(r.status == "PROCESSED" for r in all_recs))
            self.assertTrue(all(r.attempts == 1 for r in all_recs))
            check_s.close()


    # -------------------------------------------------------------------------
    # 5. Gemini error does not produce fake success result
    # -------------------------------------------------------------------------
    @patch("ai_data.analyzer.call_gemini_api")
    def test_gemini_error_produces_error_status(self, mock_gemini):
        mock_gemini.side_effect = AIAnalysisError("Gemini quota exceeded (HTTP 429) key=AIzaSySecretKey123")

        db = self.Session()
        pk = make_message_pk("telegram", "chat_err", "m_err")
        db.add(MessageRecord(
            id=pk, platform="telegram", chat_id="chat_err", chat_name="Err Chat",
            message_id="m_err", sender_hash="s_err", text="Вложи 1000 тг",
            timestamp=datetime.now(timezone.utc), status="PENDING",
        ))
        db.commit()

        process_pending_messages(db, limit=1, api_key="AIzaSySecretKey123", throttle_seconds=0)

        rec = db.get(MessageRecord, pk)
        self.assertEqual(rec.status, "ERROR")
        self.assertIsNone(rec.analysis)
        # Verify API key was sanitized from error message
        self.assertNotIn("AIzaSySecretKey123", rec.last_error)
        self.assertIn("key=[REDACTED]", rec.last_error)

        # Alert serialization for ERROR must have null risk_score and risk_level
        alert = serialize_to_alert_dict(rec)
        self.assertEqual(alert["status"], "ERROR")
        self.assertIsNone(alert["risk_score"])
        self.assertIsNone(alert["risk_level"])
        self.assertEqual(alert["reasons"], [])
        db.close()

    # -------------------------------------------------------------------------
    # 6. Invalid timestamp handled predictably
    # -------------------------------------------------------------------------
    def test_invalid_timestamp_rejected_with_422(self):
        # Empty string
        r1 = self.client.post("/api/messages", json={
            "platform": "telegram", "chat_id": "c_ts", "message_id": "ts_1",
            "sender_hash": "u1", "text": "Текст", "timestamp": "",
        })
        self.assertEqual(r1.status_code, 422)

        # Whitespace string
        r2 = self.client.post("/api/messages", json={
            "platform": "telegram", "chat_id": "c_ts", "message_id": "ts_2",
            "sender_hash": "u1", "text": "Текст", "timestamp": "   ",
        })
        self.assertEqual(r2.status_code, 422)

        # Invalid date string
        r3 = self.client.post("/api/messages", json={
            "platform": "telegram", "chat_id": "c_ts", "message_id": "ts_3",
            "sender_hash": "u1", "text": "Текст", "timestamp": "invalid-datetime",
        })
        self.assertEqual(r3.status_code, 422)

        # Valid timestamp converts cleanly
        r4 = self.client.post("/api/messages", json={
            "platform": "telegram", "chat_id": "c_ts", "message_id": "ts_4",
            "sender_hash": "u1", "text": "Текст", "timestamp": "2026-10-23T19:00:00+05:00",
        })
        self.assertEqual(r4.status_code, 200)

    # -------------------------------------------------------------------------
    # 7. API responses conform to frontend contract
    # -------------------------------------------------------------------------
    def test_api_responses_conform_to_contract(self):
        db = self.Session()
        now = datetime(2026, 10, 23, 14, 0, 0, tzinfo=timezone.utc)
        pk = make_message_pk("telegram", "contract_chat", "c_1")
        m = MessageRecord(
            id=pk, platform="telegram", chat_id="contract_chat", chat_name="Контракт Чат",
            message_id="c_1", sender_hash="s_contract", text="Вложи 5 000 тг — удвой за 24ч",
            timestamp=now, status="PROCESSED",
        )
        an = AnalysisRecord(
            id=f"an_{pk}", message_id=pk, risk_score=85, risk_level="HIGH",
            reasons_json='[{"code":"UNREALISTIC_RETURN","evidence":"удвой за 24ч"}]',
            explanation="Разбор схемы", confidence=0.92, model_version="gemini-3-flash-preview",
            analyzed_at=now,
        )
        rev = ReviewRecord(
            id=f"rev_{pk}", analysis_id=an.id, review_status="NEW", reviewer_note="",
        )
        db.add_all([m, an, rev])
        db.commit()
        db.close()

        # GET /api/alerts
        alerts_resp = self.client.get("/api/alerts")
        self.assertEqual(alerts_resp.status_code, 200)
        alerts = alerts_resp.json()
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]

        # Check required fields and types
        self.assertEqual(alert["id"], f"alert_{pk}")
        self.assertEqual(alert["platform"], "telegram")
        self.assertEqual(alert["chat_id"], "contract_chat")
        self.assertEqual(alert["status"], "PROCESSED")
        self.assertEqual(alert["risk_score"], 85)
        self.assertEqual(alert["risk_level"], "HIGH")
        self.assertEqual(alert["timestamp"], "2026-10-23T19:00:00+05:00")
        self.assertEqual(alert["reasons"], [{"code": "UNREALISTIC_RETURN", "evidence": "удвой за 24ч"}])
        self.assertEqual(alert["review_status"], "NEW")
        self.assertEqual(alert["model_version"], "gemini-3-flash-preview")

        # GET /api/alerts/{id}
        detail_resp = self.client.get(f"/api/alerts/{alert['id']}")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertEqual(detail_resp.json()["id"], alert["id"])

        # GET /api/stats
        stats_resp = self.client.get("/api/stats")
        self.assertEqual(stats_resp.status_code, 200)
        stats = stats_resp.json()
        self.assertEqual(stats["total_messages"], 1)
        self.assertEqual(stats["by_level"]["HIGH"], 1)
        self.assertEqual(stats["by_level"]["MEDIUM"], 0)
        self.assertEqual(stats["by_level"]["LOW"], 0)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["errors"], 0)

    # -------------------------------------------------------------------------
    # 8. Analyst review persists and rejects invalid reviews
    # -------------------------------------------------------------------------
    def test_analyst_review_lifecycle(self):
        db = self.Session()
        now = datetime.now(timezone.utc)
        pk = make_message_pk("telegram", "rev_chat", "msg_rev")
        m = MessageRecord(
            id=pk, platform="telegram", chat_id="rev_chat", chat_name="Review Chat",
            message_id="msg_rev", sender_hash="s_rev", text="Вложи 5 000 тг",
            timestamp=now, status="PROCESSED",
        )
        an = AnalysisRecord(
            id=f"an_{pk}", message_id=pk, risk_score=75, risk_level="HIGH",
            reasons_json="[]", explanation="Тест", confidence=0.85,
        )
        db.add_all([m, an])
        db.commit()
        db.close()

        # Submit review
        resp = self.client.post(f"/api/alerts/alert_{pk}/review", json={
            "review_status": "REVIEWED",
            "reviewer_note": "Подтверждено аналитиком: пирамида.",
            "reviewed_by": "analyst_danik"
        })
        self.assertEqual(resp.status_code, 200)
        updated = resp.json()
        self.assertEqual(updated["review_status"], "REVIEWED")
        self.assertEqual(updated["reviewer_note"], "Подтверждено аналитиком: пирамида.")
        self.assertEqual(updated["reviewed_by"], "analyst_danik")

        # Verify DB persistence
        db = self.Session()
        rev_db = db.query(ReviewRecord).filter(ReviewRecord.analysis_id == f"an_{pk}").first()
        self.assertIsNotNone(rev_db)
        self.assertEqual(rev_db.review_status, "REVIEWED")
        self.assertEqual(rev_db.reviewer_note, "Подтверждено аналитиком: пирамида.")
        db.close()

        # Cannot review PENDING alert (HTTP 400)
        db = self.Session()
        pk_pending = make_message_pk("telegram", "rev_chat", "msg_pend")
        db.add(MessageRecord(
            id=pk_pending, platform="telegram", chat_id="rev_chat", chat_name="Review Chat",
            message_id="msg_pend", sender_hash="s_pend", text="Тест",
            timestamp=now, status="PENDING",
        ))
        db.commit()
        db.close()

        err_rev = self.client.post(f"/api/alerts/alert_{pk_pending}/review", json={
            "review_status": "REVIEWED",
            "reviewer_note": "Нельзя",
        })
        self.assertEqual(err_rev.status_code, 400)

    # -------------------------------------------------------------------------
    # 9. Stats consistency formula holds
    # -------------------------------------------------------------------------
    def test_stats_consistency_formula(self):
        db = self.Session()
        now = datetime.now(timezone.utc)

        # 1 PENDING
        db.add(MessageRecord(
            id="m_p", platform="telegram", chat_id="c", chat_name="C", message_id="p",
            sender_hash="s", text="t", timestamp=now, status="PENDING"
        ))
        # 1 PROCESSING
        db.add(MessageRecord(
            id="m_pr", platform="telegram", chat_id="c", chat_name="C", message_id="pr",
            sender_hash="s", text="t", timestamp=now, status="PROCESSING"
        ))
        # 1 ERROR
        db.add(MessageRecord(
            id="m_e", platform="telegram", chat_id="c", chat_name="C", message_id="e",
            sender_hash="s", text="t", timestamp=now, status="ERROR", last_error="AI timeout"
        ))
        # 1 PROCESSED HIGH
        m_h = MessageRecord(id="m_h", platform="telegram", chat_id="c", chat_name="C", message_id="h",
                            sender_hash="s", text="t", timestamp=now, status="PROCESSED")
        a_h = AnalysisRecord(id="a_h", message_id="m_h", risk_score=80, risk_level="HIGH")
        # 1 PROCESSED MEDIUM
        m_m = MessageRecord(id="m_m", platform="telegram", chat_id="c", chat_name="C", message_id="m",
                            sender_hash="s", text="t", timestamp=now, status="PROCESSED")
        a_m = AnalysisRecord(id="a_m", message_id="m_m", risk_score=45, risk_level="MEDIUM")
        # 1 PROCESSED LOW
        m_l = MessageRecord(id="m_l", platform="telegram", chat_id="c", chat_name="C", message_id="l",
                            sender_hash="s", text="t", timestamp=now, status="PROCESSED")
        a_l = AnalysisRecord(id="a_l", message_id="m_l", risk_score=15, risk_level="LOW")

        db.add_all([m_h, a_h, m_m, a_m, m_l, a_l])
        db.commit()
        db.close()

        stats = self.client.get("/api/stats").json()
        total = stats["total_messages"]
        pending = stats["pending"]
        processing = stats["processing"]
        errors = stats["errors"]
        high = stats["by_level"]["HIGH"]
        med = stats["by_level"]["MEDIUM"]
        low = stats["by_level"]["LOW"]

        self.assertEqual(total, 6)
        self.assertEqual(pending, 1)
        self.assertEqual(processing, 1)
        self.assertEqual(errors, 1)
        self.assertEqual(high, 1)
        self.assertEqual(med, 1)
        self.assertEqual(low, 1)
        self.assertEqual(total, pending + processing + errors + high + med + low)

    # -------------------------------------------------------------------------
    # 10. Evidence is verified against source text
    # -------------------------------------------------------------------------
    def test_evidence_hallucination_prevention(self):
        text = "Вложи 5000 тг и получи удвоение завтра"
        raw_json = (
            '{"risk_score": 85, "risk_level": "HIGH", '
            '"reasons": ['
            '  {"code": "MONEY_REQUEST", "evidence": "Вложи 5000 тг"}, '
            '  {"code": "UNREALISTIC_RETURN", "evidence": "выдуманная цитата которой нет в тексте"}'
            '], '
            '"explanation": "Пирамида", "confidence": 0.9}'
        )
        res = _parse_and_validate_llm_json(raw_json, text, "test-model")
        self.assertEqual(len(res.reasons), 1)
        self.assertEqual(res.reasons[0].code, "MONEY_REQUEST")
        self.assertEqual(res.reasons[0].evidence, "Вложи 5000 тг")

    # -------------------------------------------------------------------------
    # 11. Re-processing idempotency preserves existing reviews
    # -------------------------------------------------------------------------
    @patch("ai_data.analyzer.call_gemini_api")
    def test_reprocessing_idempotency_preserves_review(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=90, risk_level=RiskLevelEnum.HIGH,
            reasons=[ReasonItem(code="MONEY_REQUEST", evidence="Вложи 5000 тг")],
            explanation="Обновленный анализ", confidence=0.95, model_version="gemini-re-eval"
        )

        db = self.Session()
        now = datetime.now(timezone.utc)
        pk = make_message_pk("telegram", "reproc_chat", "reproc_1")
        m = MessageRecord(
            id=pk, platform="telegram", chat_id="reproc_chat", chat_name="Reproc Chat",
            message_id="reproc_1", sender_hash="s_reproc", text="Вложи 5000 тг",
            timestamp=now, status="PROCESSED",
        )
        an = AnalysisRecord(
            id=f"analysis_{pk}", message_id=pk, risk_score=80, risk_level="HIGH",
            reasons_json="[]", explanation="Первоначальный анализ", confidence=0.85,
        )
        rev = ReviewRecord(
            id=f"rev_{pk}", analysis_id=an.id, review_status="REVIEWED",
            reviewer_note="Подтверждено старшим аналитиком", reviewed_by="chief_analyst"
        )
        db.add_all([m, an, rev])
        db.commit()

        # Re-queue message for re-analysis
        m.status = "PENDING"
        db.commit()

        # Run worker — must succeed without IntegrityError
        count = process_pending_messages(db, limit=1, api_key="k", throttle_seconds=0)
        self.assertEqual(count, 1)

        db.expire_all()
        reloaded = db.get(MessageRecord, pk)
        self.assertEqual(reloaded.status, "PROCESSED")
        self.assertEqual(reloaded.analysis.risk_score, 90)
        self.assertEqual(reloaded.analysis.model_version, "gemini-re-eval")

        # Crucial: the analyst's previous REVIEWED verdict is preserved!
        self.assertEqual(reloaded.analysis.review.review_status, "REVIEWED")
        self.assertEqual(reloaded.analysis.review.reviewer_note, "Подтверждено старшим аналитиком")
        self.assertEqual(reloaded.analysis.review.reviewed_by, "chief_analyst")
        db.close()


class TestPostgresReliability(unittest.TestCase):
    """
    Tests full PostgreSQL integration with FOR UPDATE SKIP LOCKED
    against local PostgreSQL (safenet_test).
    """
    @classmethod
    def setUpClass(cls):
        cls.db_url = "postgresql://postgres:postgres@localhost:5432/safenet_test"
        try:
            cls.Session = init_db(cls.db_url)
            # Verify connectivity
            s = cls.Session()
            s.execute(MessageRecord.__table__.select().limit(1))
            s.close()
            cls.postgres_available = True
        except Exception as e:
            cls.postgres_available = False
            cls.skip_reason = str(e)

    def setUp(self):
        if not self.postgres_available:
            self.skipTest(f"PostgreSQL not accessible: {self.skip_reason}")
        # Clean test tables
        s = self.Session()
        s.query(ReviewRecord).delete()
        s.query(AnalysisRecord).delete()
        s.query(MessageRecord).delete()
        s.commit()
        s.close()

    @patch("ai_data.analyzer.call_gemini_api")
    def test_postgres_full_flow_with_skip_locked(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=85, risk_level=RiskLevelEnum.HIGH,
            reasons=[ReasonItem(code="MONEY_REQUEST", evidence="Вложи 5000 тг")],
            explanation="Postgres E2E Test", confidence=0.91, model_version="postgres-gemini"
        )

        s = self.Session()
        now = datetime.now(timezone.utc)
        for i in range(5):
            s.add(MessageRecord(
                id=f"pg_msg_{i}", platform="telegram", chat_id="pg_chat", chat_name="PG Chat",
                message_id=f"pg_{i}", sender_hash="pg_sender", text="Вложи 5000 тг",
                timestamp=now + timedelta(seconds=i), status="PENDING",
            ))
        s.commit()
        s.close()

        # Two workers run with FOR UPDATE SKIP LOCKED
        def worker_loop(w_id):
            session = self.Session()
            try:
                process_pending_messages(session, limit=3, api_key="k", throttle_seconds=0, worker_id=w_id)
            finally:
                session.close()

        t1 = threading.Thread(target=worker_loop, args=("pg-w1",))
        t2 = threading.Thread(target=worker_loop, args=("pg-w2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Verify in Postgres
        verify_s = self.Session()
        recs = verify_s.query(MessageRecord).all()
        self.assertEqual(len(recs), 5)
        self.assertTrue(all(r.status == "PROCESSED" for r in recs))
        self.assertTrue(all(r.analysis is not None and r.analysis.risk_score == 85 for r in recs))
        verify_s.close()


if __name__ == "__main__":
    unittest.main()
