import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import httpx
from fastapi.testclient import TestClient

from ai_data.tests.test_db_helper import get_clean_test_session, get_test_session_factory, clean_test_database, TEST_DB_URL
from ai_data.db.models import (
    validate_postgres_url,
    init_db,
    MessageRecord,
    AnalysisRecord,
    ReviewRecord,
    EntityRecord,
    make_message_pk,
)
from ai_data.config import GEMINI_MODEL
from ai_data.normalizer import detect_language, detect_obfuscation, find_exact_substring
from ai_data.heuristics import analyze_with_heuristics
from ai_data.entity_extractor import extract_entities
from ai_data.context import get_sender_context, build_context_block
from ai_data.llm_client import call_gemini_api, AIAnalysisError, _parse_and_validate_llm_json
from ai_data.analyzer import analyze_message, synthesize_risk
from ai_data.models import RiskLevelEnum, ReasonItem, AnalysisResult
from ai_data.worker import process_pending_messages
import ai_data.api_server as api_server


class TestStageAConfigurationAndPostgres(unittest.TestCase):
    """
    Stage A: Configuration and PostgreSQL Validation.
    """

    def test_missing_database_url_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            validate_postgres_url("")
        self.assertIn("DATABASE_URL is not set", str(ctx.exception))
        self.assertIn("PostgreSQL", str(ctx.exception))

    def test_sqlite_url_is_strictly_forbidden(self):
        with self.assertRaises(ValueError) as ctx:
            validate_postgres_url("sqlite:///safenet.db")
        self.assertIn("SQLite is not allowed", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            validate_postgres_url("sqlite:///:memory:")
        self.assertIn("SafeNet KZ requires PostgreSQL", str(ctx.exception))

    def test_valid_postgres_url_accepted(self):
        url = "postgresql+psycopg2://postgres:postgres@localhost:5432/safenet"
        self.assertEqual(validate_postgres_url(url), url)

    def test_schema_and_migrations_idempotent_on_postgres(self):
        # Re-initializing on PostgreSQL should succeed without schema corruption
        factory = init_db(TEST_DB_URL)
        session = factory()
        # Verify query succeeds
        cnt = session.query(MessageRecord).count()
        self.assertIsInstance(cnt, int)
        session.close()


class TestStageBAlgorithmRulesAndContext(unittest.TestCase):
    """
    Stage B: Multi-lingual Rules, Obfuscation, Entities, False Positive Suppression.
    """

    def test_kazakh_pyramid_indicators(self):
        kz_text = "Ертең 20 000 теңге ал! Табысқа кепілдік береміз, досыңды шақыр — сыйақы аласың. Kaspi арқылы жеке картаға аудар."
        res = analyze_with_heuristics(kz_text)
        self.assertEqual(res.risk_level, RiskLevelEnum.HIGH)
        codes = [r.code for r in res.reasons]
        self.assertIn("UNREALISTIC_RETURN", codes)
        self.assertIn("GUARANTEED_PROFIT", codes)
        self.assertIn("REFERRAL", codes)
        self.assertIn("PERSONAL_TRANSFER", codes)
        for r in res.reasons:
            self.assertIn(r.evidence, kz_text)

    def test_russian_pyramid_indicators(self):
        ru_text = "Вложи 5 000 тг прямо сейчас — удвой баланс за 24 часа! Доход гарантирован 100%. Приведи двоих друзей."
        res = analyze_with_heuristics(ru_text)
        self.assertEqual(res.risk_level, RiskLevelEnum.HIGH)
        codes = [r.code for r in res.reasons]
        self.assertIn("UNREALISTIC_RETURN", codes)
        self.assertIn("MONEY_REQUEST", codes)
        self.assertIn("GUARANTEED_PROFIT", codes)
        self.assertIn("REFERRAL", codes)

    def test_obfuscation_detection(self):
        # Leetspeak inside word
        self.assertTrue(detect_obfuscation("вл0жи 5000 тг"))
        self.assertTrue(detect_obfuscation("з@р@б0ток на дому"))
        # Homoglyphs mixed script inside word
        self.assertTrue(detect_obfuscation("Kаspі перевод"))  # mixed latin/cyrillic in Kaspi
        # Character separators
        self.assertTrue(detect_obfuscation("в.л.о.ж.и деньги"))
        # Normal text should NOT be marked obfuscated
        self.assertFalse(detect_obfuscation("Обычное сообщение о погоде"))
        self.assertFalse(detect_obfuscation("24 часа в сутках"))

    def test_legitimate_investment_discussion_suppressed(self):
        # Educational / legitimate context with disclaimers must be suppressed to LOW
        safe_text = "Бесплатная лекция по инвестициям и финансовой грамотности. Взносы не нужны, прибыль не гарантируем."
        res = analyze_with_heuristics(safe_text)
        self.assertEqual(res.risk_level, RiskLevelEnum.LOW)
        self.assertLessEqual(res.risk_score, 25)

    def test_entity_extraction_and_safe_masking(self):
        text = "Реквизиты куратора: Kaspi +7 777 123-45-67, карта 4400 1234 5678 9876, канал @safenet_channel"
        ents = extract_entities(text)
        ent_map = {e["type"]: e for e in ents}
        self.assertIn("PHONE", ent_map)
        self.assertEqual(ent_map["PHONE"]["value"], "+77771234567")

        self.assertIn("CARD", ent_map)
        self.assertEqual(ent_map["CARD"]["display"], "4400 **** **** 9876")
        self.assertTrue(ent_map["CARD"]["value"].startswith("card:"))

        self.assertIn("TELEGRAM_USER", ent_map)
        self.assertEqual(ent_map["TELEGRAM_USER"]["display"], "@safenet_channel")

    def test_anti_self_amplification_of_unreviewed_verdicts(self):
        session = get_clean_test_session()
        # Add 3 unreviewed AUTO_HIGH messages from same sender
        for i in range(3):
            m = MessageRecord(
                id=f"auto_msg_{i}", platform="telegram", chat_id="chat_test", chat_name="Chat",
                message_id=f"m_{i}", sender_hash="auto_spammer", text=f"Текст {i}",
                timestamp=datetime.now(timezone.utc), status="PROCESSED"
            )
            session.add(m)
            an = AnalysisRecord(
                id=f"an_{i}", message_id=m.id, risk_score=85, risk_level="HIGH",
                reasons_json="[]", explanation="", confidence=0.9
            )
            session.add(an)
            rev = ReviewRecord(id=f"rev_{i}", analysis_id=an.id, review_status="NEW")
            session.add(rev)
        session.commit()

        ctx = get_sender_context(session, "auto_spammer")
        self.assertEqual(ctx["sender_confirmed_high_count"], 0)
        self.assertEqual(ctx["sender_high_risk_count"], 3)

        block = build_context_block(session, MessageRecord(sender_hash="auto_spammer", chat_id="chat_test", text="проверка"))
        # Unconfirmed history MUST NOT state that analyst confirmed it
        self.assertNotIn("ПОДТВЕРЖДЕНО АНАЛИТИКОМ", block)
        session.close()


class TestStageCGeminiIntegrationAndSecurity(unittest.TestCase):
    """
    Stage C: Google Gemini Integration, API Security, Error Handling.
    """

    @patch("httpx.Client.post")
    def test_gemini_request_uses_header_and_single_model(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"risk_score": 85, "risk_level": "HIGH", "reasons": [{"code": "MONEY_REQUEST", "evidence": "вложи 5000"}], "explanation": "Схема", "confidence": 0.95}'
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        res = call_gemini_api(
            text="срочно вложи 5000 тг",
            api_key="secret-api-key",
            model="gemini-3.8-flash"
        )
        self.assertEqual(res.risk_level, RiskLevelEnum.HIGH)

        # Inspect call arguments
        args, kwargs = mock_post.call_args
        called_url = args[0]
        # API key must NOT be in the query URL
        self.assertNotIn("secret-api-key", called_url)
        self.assertIn("models/gemini-3.8-flash:generateContent", called_url)
        # API key must be in x-goog-api-key header
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "secret-api-key")

    @patch("httpx.Client.post")
    def test_gemini_stops_on_429_without_switching_models(self, mock_post):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "Rate limit exceeded"
        resp_429.headers = {"Retry-After": "120"}
        resp_429.json.return_value = {"error": {"message": "RequestsPerDay exhausted"}}
        mock_post.side_effect = [resp_429]

        from ai_data.llm_client import AIQuotaError
        with self.assertRaises(AIQuotaError) as ctx:
            call_gemini_api(text="только сегодня акция", api_key="secret-key", model="gemini-3.8-flash")
        self.assertTrue(ctx.exception.daily)
        self.assertEqual(ctx.exception.retry_after_seconds, 120)
        self.assertEqual(mock_post.call_count, 1)
        for call_item in mock_post.call_args_list:
            self.assertIn("gemini-3.8-flash", call_item[0][0])

    def test_unsupported_provider_raises_clear_error(self):
        with self.assertRaises(AIAnalysisError) as ctx:
            analyze_message("тест", api_key="key", provider="openai")
        self.assertIn("Неподдерживаемый AI-провайдер: 'openai'", str(ctx.exception))
        self.assertIn("Google Gemini", str(ctx.exception))

    def test_missing_gemini_key_raises_error_without_leaks(self):
        with self.assertRaises(AIAnalysisError) as ctx:
            analyze_message("тест", api_key="")
        self.assertIn("GEMINI_API_KEY is not configured", str(ctx.exception))


class TestStageDEndToEndPipelineOnPostgres(unittest.TestCase):
    """
    Stage D: Full Pipeline on PostgreSQL:
    POST /api/messages -> PENDING -> worker -> Gemini -> risk engine -> PostgreSQL -> GET /api/alerts -> analyst review
    """

    def setUp(self):
        self.Session = get_test_session_factory()
        s = self.Session()
        clean_test_database(s)
        s.close()

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

    @patch("ai_data.analyzer.call_gemini_api")
    def test_full_pipeline_ingestion_worker_and_analyst_review(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=94,
            risk_level=RiskLevelEnum.HIGH,
            reasons=[
                ReasonItem(code="UNREALISTIC_RETURN", evidence="удвой депозит за 24ч"),
                ReasonItem(code="MONEY_REQUEST", evidence="Вложи 10 000 тг"),
            ],
            explanation="Выявлены признаки классической схемы Понци с обещанием удвоения депозита.",
            confidence=0.96,
            model_version="gemini-3.8-flash",
        )

        # 1. INGESTION via POST /api/messages
        ingest_payload = {
            "platform": "telegram",
            "chat_id": "invest_chat_e2e",
            "chat_name": "Инвестиции Алматы",
            "message_id": "e2e_msg_999",
            "sender_hash": "sender_e2e",
            "text": "Вложи 10 000 тг — удвой депозит за 24ч! Перевод на Kaspi: +7 701 555-44-33",
            "timestamp": "2026-10-23T15:30:00Z",
        }
        resp = self.client.post("/api/messages", json=ingest_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        alert_id = data["id"]
        self.assertEqual(data["status"], "PENDING")

        # 2. Verify state in PostgreSQL before worker
        db_s = self.Session()
        msg_rec = db_s.get(MessageRecord, alert_id.replace("alert_", ""))
        self.assertIsNotNone(msg_rec)
        self.assertEqual(msg_rec.status, "PENDING")
        self.assertIsNone(msg_rec.analysis)
        db_s.close()

        # 3. WORKER EXECUTION
        worker_s = self.Session()
        processed_count = process_pending_messages(
            worker_s, limit=5, api_key="test-gemini-key", throttle_seconds=0, worker_id="e2e-worker"
        )
        self.assertEqual(processed_count, 1)
        worker_s.close()

        # 4. GET /api/alerts - Verify analysis output in API
        alerts_resp = self.client.get("/api/alerts")
        self.assertEqual(alerts_resp.status_code, 200)
        alerts = alerts_resp.json()
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["id"], alert_id)
        self.assertEqual(alert["status"], "PROCESSED")
        self.assertEqual(alert["risk_level"], "HIGH")
        self.assertEqual(alert["risk_score"], 94)
        self.assertEqual(alert["review_status"], "NEW")
        self.assertIn("удвой депозит за 24ч", [r["evidence"] for r in alert["reasons"]])

        # 5. ANALYST REVIEW: POST /api/alerts/{id}/review
        review_payload = {
            "review_status": "REVIEWED",
            "reviewer_note": "Подтверждено аналитиком: выявлены признаки пирамиды",
            "reviewed_by": "senior_analyst_01",
        }
        rev_resp = self.client.post(f"/api/alerts/{alert_id}/review", json=review_payload)
        self.assertEqual(rev_resp.status_code, 200)
        reviewed_alert = rev_resp.json()
        self.assertEqual(reviewed_alert["review_status"], "REVIEWED")
        self.assertEqual(reviewed_alert["reviewer_note"], "Подтверждено аналитиком: выявлены признаки пирамиды")
        self.assertEqual(reviewed_alert["reviewed_by"], "senior_analyst_01")

        # 6. IDEMPOTENT PERSISTENCE: Re-load from PostgreSQL and verify persistence
        verify_s = self.Session()
        final_rec = verify_s.get(MessageRecord, alert_id.replace("alert_", ""))
        self.assertEqual(final_rec.status, "PROCESSED")
        self.assertEqual(final_rec.analysis.review.review_status, "REVIEWED")
        self.assertEqual(final_rec.analysis.review.reviewer_note, "Подтверждено аналитиком: выявлены признаки пирамиды")
        self.assertEqual(final_rec.analysis.review.reviewed_by, "senior_analyst_01")

        # Verify entities persisted in PostgreSQL
        entities = verify_s.query(EntityRecord).filter(EntityRecord.message_id == final_rec.id).all()
        ent_types = [e.entity_type for e in entities]
        self.assertIn("PHONE", ent_types)
        verify_s.close()


if __name__ == "__main__":
    unittest.main()
