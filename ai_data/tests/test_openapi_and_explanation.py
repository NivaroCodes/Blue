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
)
from ai_data.analyzer import sanitize_explanation, analyze_message
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


if __name__ == "__main__":
    unittest.main()
