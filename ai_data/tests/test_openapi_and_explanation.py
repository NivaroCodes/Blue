import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_data.api_server import app, SessionLocal
from ai_data.models import (
    Alert,
    StatsResponse,
    MessageIngestResponse,
    ReasonItem,
    RiskLevelEnum,
    AnalysisResult,
    compute_calibrated_confidence,
)
from ai_data.analyzer import sanitize_explanation, analyze_message
from ai_data.heuristics import _generate_explanation
from ai_data.heuristics import analyze_with_heuristics
from ai_data.llm_client import _parse_and_validate_llm_json
from ai_data.db.models import MessageRecord, AnalysisRecord, serialize_to_alert_dict, utc_now
from ai_data.tests.test_db_helper import get_clean_test_session


class TestOpenAPISchemas(unittest.TestCase):
    def test_openapi_schemas_are_fully_typed(self):
        schema = app.openapi()
        paths = schema.get("paths", {})

        # Ensure all key surveillance endpoints are registered and documented
        expected_endpoints = [
            ("get", "/api/alerts"),
            ("get", "/api/alerts/{alert_id}"),
            ("get", "/api/stats"),
            ("get", "/api/network-graph"),
            ("post", "/api/alerts/{alert_id}/review"),
            ("post", "/api/messages"),
            ("post", "/api/analyze-image"),
            ("get", "/api/export"),
        ]

        for method, path in expected_endpoints:
            self.assertIn(path, paths, f"Path {path} missing in OpenAPI schema")
            self.assertIn(method, paths[path], f"Method {method.upper()} {path} missing in OpenAPI schema")

            op = paths[path][method]
            resp_200 = op.get("responses", {}).get("200", {})
            self.assertIn("content", resp_200, f"{method.upper()} {path} response 200 has no content definition")
            self.assertIn("application/json", resp_200["content"], f"{method.upper()} {path} has no application/json schema")

            json_schema = resp_200["content"]["application/json"].get("schema", {})
            self.assertTrue(
                bool(json_schema),
                f"{method.upper()} {path} response schema is empty ({json_schema})"
            )
            # Schema must not be a bare empty dict or primitive string for structured endpoints
            if path in ("/api/alerts", "/api/alerts/{alert_id}", "/api/stats", "/api/messages", "/api/analyze-image"):
                self.assertTrue(
                    "$ref" in json_schema or "items" in json_schema or "anyOf" in json_schema or "type" in json_schema,
                    f"{method.upper()} {path} schema must reference a typed model, got {json_schema}"
                )

        # Ensure components define our key domain schemas
        schemas = schema.get("components", {}).get("schemas", {})
        for required_schema in ["Alert", "StatsResponse", "MessageIngestResponse", "StatsByLevel"]:
            self.assertIn(required_schema, schemas, f"Component schema '{required_schema}' missing from OpenAPI components")


class TestExplanationQualityAndConfidence(unittest.TestCase):
    def test_sanitize_explanation_removes_tautologies(self):
        tautology = "В сообщении присутствуют классические признаки классической финансовой пирамиды."
        clean = sanitize_explanation(tautology, "HIGH")
        self.assertNotIn("классические признаки классической", clean.lower())
        self.assertIn("признаки финансовой пирамиды", clean.lower())

    def test_sanitize_explanation_softens_categorical_accusations(self):
        accusation = "Автор является мошенником, доказано уголовное мошенничество. Немедленная блокировка."
        clean = sanitize_explanation(accusation, "HIGH")
        self.assertNotIn("является мошенником", clean.lower())
        self.assertNotIn("уголовное мошенничество", clean.lower())
        self.assertNotIn("немедленная блокировка", clean.lower())
        self.assertIn("аналитик", clean.lower())

    def test_sanitize_explanation_replaces_punitive_commands_with_verification(self):
        punitive = "Рекомендуется полная блокировка отправителя в группе и арест счёта."
        clean = sanitize_explanation(punitive, "HIGH")
        self.assertNotIn("полная блокировка", clean.lower())
        self.assertNotIn("арест счёта", clean.lower())
        self.assertTrue("верификаци" in clean.lower() or "проверк" in clean.lower() or "аудит" in clean.lower())

    def test_sanitize_explanation_fallbacks(self):
        empty_high = sanitize_explanation("", "HIGH")
        self.assertTrue(len(empty_high) > 20)
        self.assertIn("АРРФР", empty_high)

        empty_low = sanitize_explanation("   ", "LOW")
        self.assertTrue(len(empty_low) > 20)
        self.assertIn("нейтральный", empty_low)

    def test_confidence_bounded_and_uncalibrated_in_llm_parser(self):
        raw_json_1 = (
            '{"risk_score": 90, "risk_level": "HIGH", '
            '"reasons": [{"code": "MONEY_REQUEST", "evidence": "Вложи 5000 тг"}], '
            '"explanation": "Выявлен сбор средств.", "confidence": 1.0}'
        )
        res = _parse_and_validate_llm_json(raw_json_1, "Вложи 5000 тг", "gemini-3.5-flash-lite")
        self.assertLessEqual(res.confidence, 0.95, "Confidence must never exceed 0.95")
        self.assertGreaterEqual(res.confidence, 0.0)

    def test_confidence_bounded_in_heuristics(self):
        h_res = analyze_with_heuristics("Вложи 5000 тг, получи 100000 тг завтра! Зови друзей")
        self.assertLessEqual(h_res.confidence, 0.95, "Heuristic confidence must never exceed 0.95")
        self.assertGreaterEqual(h_res.confidence, 0.0)

    def test_confidence_bounded_in_analyzer_fusion(self):
        fake_gemini = AnalysisResult(
            risk_score=95,
            risk_level=RiskLevelEnum.HIGH,
            reasons=[
                ReasonItem(code="MONEY_REQUEST", evidence="Вложи 5000 тг"),
                ReasonItem(code="UNREALISTIC_RETURN", evidence="100% за сутки"),
            ],
            explanation="В тексте присутствуют классические признаки классической финансовой пирамиды.",
            confidence=1.0,
            model_version="gemini-3.5-flash-lite",
        )
        with patch("ai_data.analyzer.call_gemini_api", return_value=fake_gemini):
            res = analyze_message("Вложи 5000 тг, обещаем 100% за сутки на карту Kaspi!", api_key="fake_key")
            self.assertIsNotNone(res)
            self.assertLessEqual(res.confidence, 0.95, "Fused confidence must be capped at 0.95")
            self.assertNotIn("классические признаки классической", res.explanation.lower())

    def test_confidence_semantics_for_high_with_multiple_confirmed_signals(self):
        """
        HIGH tier with 2+ corroborated signals (unrealistic return + money request)
        yields high signal clarity confidence in [0.85, 0.95].
        """
        fake_gemini_high = AnalysisResult(
            risk_score=90,
            risk_level=RiskLevelEnum.HIGH,
            reasons=[
                ReasonItem(code="UNREALISTIC_RETURN", evidence="получи 100000 тг уже завтра"),
                ReasonItem(code="MONEY_REQUEST", evidence="Вложи 5000 тг"),
            ],
            explanation="В тексте зафиксированы явные индикаторы финансовой пирамиды: обещание сверхдоходности и сбор взносов.",
            confidence=0.92,
            model_version="gemini-3.5-flash-lite",
        )
        with patch("ai_data.analyzer.call_gemini_api", return_value=fake_gemini_high):
            text = "Вложи 5000 тг и получи 100000 тг уже завтра! Перевод на карту Kaspi."
            res = analyze_message(text, api_key="fake_key")
            self.assertEqual(res.risk_level, RiskLevelEnum.HIGH)
            self.assertGreaterEqual(len(res.reasons), 2)
            self.assertGreaterEqual(res.confidence, 0.85)
            self.assertLessEqual(res.confidence, 0.95)

    def test_confidence_semantics_for_medium_with_ambiguous_signals(self):
        """
        MEDIUM tier represents an inherent grey zone (isolated signals, course with fee, unclear mechanics).
        Confidence is calibrated to a moderate band [0.45, 0.65], reflecting uncertainty that requires human review.
        """
        fake_gemini_medium = AnalysisResult(
            risk_score=45,
            risk_level=RiskLevelEnum.MEDIUM,
            reasons=[
                ReasonItem(code="MONEY_REQUEST", evidence="Стоимость курса 15000 тг"),
            ],
            explanation="Выявлены признаки платного обучения. Признаков пирамиды нет, но требуется ручная проверка условий.",
            confidence=0.55,
            model_version="gemini-3.5-flash-lite",
        )
        with patch("ai_data.analyzer.call_gemini_api", return_value=fake_gemini_medium):
            text = "Обучение основам инвестиций. Стоимость курса 15000 тг. Запись в лс."
            res = analyze_message(text, api_key="fake_key")
            self.assertEqual(res.risk_level, RiskLevelEnum.MEDIUM)
            self.assertGreaterEqual(res.confidence, 0.45)
            self.assertLessEqual(res.confidence, 0.65)

    def test_confidence_semantics_for_low_without_signals(self):
        """
        LOW tier with complete, informative everyday context (>=15 chars, >=3 words)
        yields confidence in [0.75, 0.85] because context is sufficient to reliably rule out scam signals.
        """
        fake_gemini_low = AnalysisResult(
            risk_score=5,
            risk_level=RiskLevelEnum.LOW,
            reasons=[],
            explanation="Материал носит нейтральный характер, признаков финансовых пирамид не выявлено.",
            confidence=0.80,
            model_version="gemini-3.5-flash-lite",
        )
        with patch("ai_data.analyzer.call_gemini_api", return_value=fake_gemini_low):
            text = "Привет всем! Напоминаю, что завтра в 10:00 у нас лекция по высшей математике в 304 аудитории. Не забудьте тетради."
            res = analyze_message(text, api_key="fake_key")
            self.assertEqual(res.risk_level, RiskLevelEnum.LOW)
            self.assertEqual(len(res.reasons), 0)
            self.assertGreaterEqual(res.confidence, 0.75)
            self.assertLessEqual(res.confidence, 0.85)

    def test_confidence_semantics_for_low_with_insufficient_sparse_data(self):
        """
        LOW tier with sparse or fragmentary text (<15 chars, <3 words, e.g. 'ок' or 'привет')
        yields reduced confidence in [0.30, 0.45], explicitly indicating data insufficiency.
        """
        fake_gemini_sparse = AnalysisResult(
            risk_score=0,
            risk_level=RiskLevelEnum.LOW,
            reasons=[],
            explanation="Сообщение слишком краткое, признаки не выявлены.",
            confidence=0.35,
            model_version="gemini-3.5-flash-lite",
        )
        with patch("ai_data.analyzer.call_gemini_api", return_value=fake_gemini_sparse):
            text = "ок"
            res = analyze_message(text, api_key="fake_key")
            self.assertEqual(res.risk_level, RiskLevelEnum.LOW)
            self.assertGreaterEqual(res.confidence, 0.30)
            self.assertLessEqual(res.confidence, 0.45)


    def test_calibrated_confidence_matrix(self):
        # 1. HIGH with multiple (>= 2) reasons -> [0.85, 0.95]
        conf_high_multi = compute_calibrated_confidence(RiskLevelEnum.HIGH, reasons_count=2, text="Длинный текст с признаками")
        self.assertGreaterEqual(conf_high_multi, 0.85)
        self.assertLessEqual(conf_high_multi, 0.95)

        # 2. HIGH with single isolated reason -> [0.70, 0.80]
        conf_high_single = compute_calibrated_confidence(RiskLevelEnum.HIGH, reasons_count=1, text="Длинный текст с признаками")
        self.assertGreaterEqual(conf_high_single, 0.70)
        self.assertLessEqual(conf_high_single, 0.80)

        # 3. MEDIUM -> [0.45, 0.65]
        conf_med = compute_calibrated_confidence(RiskLevelEnum.MEDIUM, reasons_count=1, text="Платный курс по инвестициям")
        self.assertGreaterEqual(conf_med, 0.45)
        self.assertLessEqual(conf_med, 0.65)

        # 4. LOW normal informative context -> [0.70, 0.85]
        conf_low_norm = compute_calibrated_confidence(RiskLevelEnum.LOW, reasons_count=0, text="Обычное длинное сообщение о встрече выпускников")
        self.assertGreaterEqual(conf_low_norm, 0.70)
        self.assertLessEqual(conf_low_norm, 0.85)

        # 5. LOW sparse / fragmentary context (<15 chars or <3 words) -> [0.30, 0.45]
        conf_low_sparse1 = compute_calibrated_confidence(RiskLevelEnum.LOW, reasons_count=0, text="привет")
        conf_low_sparse2 = compute_calibrated_confidence(RiskLevelEnum.LOW, reasons_count=0, text="ок")
        self.assertGreaterEqual(conf_low_sparse1, 0.30)
        self.assertLessEqual(conf_low_sparse1, 0.45)
        self.assertEqual(conf_low_sparse2, 0.35)

        # 6. Upper bound never exceeds 0.95 even if model returns 1.0
        conf_clamped = compute_calibrated_confidence(RiskLevelEnum.HIGH, reasons_count=5, text="любой текст", raw_model_confidence=1.0)
        self.assertLessEqual(conf_clamped, 0.95)

    def test_heuristics_non_categorical_explanations(self):
        # HIGH
        high_expl = _generate_explanation([], RiskLevelEnum.HIGH, "ru")
        self.assertIn("признаков, характерных для схем", high_expl)
        self.assertNotIn("доказано", high_expl.lower())

        # MEDIUM
        med_expl = _generate_explanation([], RiskLevelEnum.MEDIUM, "ru")
        self.assertIn("признаки риска", med_expl)

        # LOW
        low_expl = _generate_explanation([], RiskLevelEnum.LOW, "ru")
        self.assertIn("не обнаружены", low_expl)
        self.assertIn("не является гарантией абсолютной безопасности", low_expl)


class TestAPIReturnTypesValidation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.session = get_clean_test_session()

    def tearDown(self):
        self.session.close()

    def test_api_stats_matches_schema(self):
        resp = self.client.get("/api/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        validated = StatsResponse.model_validate(data)
        self.assertIsInstance(validated.total_messages, int)
        self.assertIsInstance(validated.by_level.HIGH, int)

    def test_api_alerts_and_detail_matches_schema(self):
        # Ingest a message
        payload = {
            "platform": "telegram",
            "chat_id": "test_schema_chat",
            "chat_name": "Test Schema Chat",
            "message_id": "schema_msg_01",
            "sender_hash": "user_schema_01",
            "text": "Тестовое нейтральное сообщение для проверки схемы API."
        }
        ingest_resp = self.client.post("/api/messages", json=payload)
        self.assertEqual(ingest_resp.status_code, 200)
        ingest_val = MessageIngestResponse.model_validate(ingest_resp.json())
        self.assertTrue(ingest_val.id.startswith("alert_"))

        # Fetch alerts
        alerts_resp = self.client.get("/api/alerts")
        self.assertEqual(alerts_resp.status_code, 200)
        alerts_list = alerts_resp.json()
        self.assertIsInstance(alerts_list, list)
        self.assertGreaterEqual(len(alerts_list), 1)

        # Validate through Alert Pydantic model
        validated_alerts = [Alert.model_validate(a) for a in alerts_list]
        self.assertTrue(any(a.id == ingest_val.id for a in validated_alerts))

        # Fetch single alert detail
        detail_resp = self.client.get(f"/api/alerts/{ingest_val.id}")
        self.assertEqual(detail_resp.status_code, 200)
        detail_val = Alert.model_validate(detail_resp.json())
        self.assertEqual(detail_val.id, ingest_val.id)
        self.assertEqual(detail_val.platform.value, "telegram")


    def test_pending_alert_has_null_confidence_and_validates(self):
        # Direct check on PENDING alert serialization
        from ai_data.db.models import MessageRecord, serialize_to_alert_dict, utc_now
        msg = MessageRecord(
            id="telegram_testnull_1",
            platform="telegram",
            chat_id="testnull",
            chat_name="Test Null Chat",
            message_id="1",
            sender_hash="sender123",
            text="Тестовое сообщение в очереди",
            timestamp=utc_now(),
            status="PENDING",
        )
        api_dict = serialize_to_alert_dict(msg)
        self.assertIsNone(api_dict["confidence"])
        self.assertIsNone(api_dict["risk_score"])
        self.assertIsNone(api_dict["risk_level"])
        self.assertEqual(api_dict["reasons"], [])

        # Validate with Alert Pydantic schema
        alert_model = Alert.model_validate(api_dict)
        self.assertIsNone(alert_model.confidence)
        self.assertIsNone(alert_model.risk_score)
        self.assertIsNone(alert_model.risk_level)


if __name__ == "__main__":
    unittest.main()
