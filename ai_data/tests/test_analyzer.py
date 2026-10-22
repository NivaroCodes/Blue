import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from ai_data.models import (
    RiskLevelEnum,
    AnalysisResult,
    ReasonItem,
)
from ai_data.llm_client import _parse_and_validate_llm_json, AIAnalysisError
from ai_data.analyzer import analyze_message
from ai_data.context import get_sender_context, get_chat_context, build_context_block
from ai_data.db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord, serialize_to_alert_dict
from ai_data.worker import process_pending_messages


class TestLLMParsing(unittest.TestCase):

    def test_valid_json_with_exact_evidence(self):
        text = "Вложи 5 000 ₸ сегодня — получи 10 000 ₸ уже завтра! Доход гарантирован."
        raw = '{"risk_score":92,"risk_level":"HIGH","reasons":[{"code":"UNREALISTIC_RETURN","evidence":"получи 10 000 ₸ уже завтра"},{"code":"MONEY_REQUEST","evidence":"Вложи 5 000 ₸"}],"explanation":"Обнаружено обещание быстрой доходности.","confidence":0.95}'
        result = _parse_and_validate_llm_json(raw, text, "test")
        self.assertEqual(result.risk_level, RiskLevelEnum.HIGH)
        self.assertEqual(len(result.reasons), 2)
        for r in result.reasons:
            self.assertIn(r.evidence, text)

    def test_hallucinated_evidence_is_dropped(self):
        text = "Привет, как дела?"
        raw = '{"risk_score":80,"risk_level":"HIGH","reasons":[{"code":"MONEY_REQUEST","evidence":"Вложи 100000 тг"}],"explanation":"Скам","confidence":0.9}'
        result = _parse_and_validate_llm_json(raw, text, "test")
        # Evidence not found → dropped → no reasons → score forced LOW
        self.assertEqual(len(result.reasons), 0)
        self.assertEqual(result.risk_level, RiskLevelEnum.LOW)

    def test_unknown_code_is_dropped(self):
        text = "Вложи 5000 тг"
        raw = '{"risk_score":70,"risk_level":"HIGH","reasons":[{"code":"FAKE_CODE","evidence":"Вложи 5000 тг"}],"explanation":"test","confidence":0.8}'
        result = _parse_and_validate_llm_json(raw, text, "test")
        self.assertEqual(len(result.reasons), 0)  # unknown code dropped
        self.assertEqual(result.risk_level, RiskLevelEnum.LOW)  # no valid reasons → forced LOW

    def test_score_level_consistency(self):
        text = "Тест"
        raw = '{"risk_score":15,"risk_level":"HIGH","reasons":[],"explanation":"test","confidence":0.5}'
        result = _parse_and_validate_llm_json(raw, text, "test")
        self.assertEqual(result.risk_level, RiskLevelEnum.LOW)  # 15 → LOW, not HIGH

    def test_obfuscated_substring_extraction(self):
        # Scammer used 0 instead of o and dots: 'в.л.0.ж.и 5000 тг'
        text = "Срочно в.л.0.ж.и 5000 тг — удвой!"
        raw = '{"risk_score":90,"risk_level":"HIGH","reasons":[{"code":"MONEY_REQUEST","evidence":"вложи 5000 тг"}],"explanation":"test","confidence":0.9}'
        result = _parse_and_validate_llm_json(raw, text, "test")
        self.assertEqual(len(result.reasons), 1)
        self.assertIn(result.reasons[0].evidence, text)
        self.assertEqual(result.reasons[0].evidence, "в.л.0.ж.и 5000 тг")

    def test_disguised_scam_reason_parsing(self):
        # Fake job & food aid advance fee disguised scams
        job_text = "Работа на дому: ставить лайки товарам. Внесите залог 5 000 тг куратору."
        raw = '{"risk_score":85,"risk_level":"HIGH","reasons":[{"code":"MONEY_REQUEST","evidence":"Внесите залог 5 000 тг"}],"explanation":"Task scam","confidence":0.9}'
        result = _parse_and_validate_llm_json(raw, job_text, "test")
        self.assertEqual(len(result.reasons), 1)
        self.assertEqual(result.reasons[0].evidence, "Внесите залог 5 000 тг")


class TestAnalyzerRequiresAPIKey(unittest.TestCase):

    def test_no_key_raises_error(self):
        with self.assertRaises(AIAnalysisError):
            analyze_message("Тест", api_key="", provider="gemini")


class TestContextEnrichment(unittest.TestCase):

    def _make_db(self):
        Session = init_db("sqlite:///:memory:")
        return Session()

    def test_sender_reputation_grows(self):
        session = self._make_db()
        # Add 3 processed messages from same sender, 2 are HIGH
        for i in range(3):
            m = MessageRecord(id=f"m{i}", platform="telegram", chat_id="tg1", chat_name="Chat",
                              message_id=f"m{i}", sender_hash="scammer_001", text=f"text{i}",
                              timestamp=datetime.now(timezone.utc), status="PROCESSED")
            session.add(m)
            a = AnalysisRecord(id=f"a{i}", message_id=f"m{i}", risk_score=80 if i < 2 else 20,
                               risk_level="HIGH" if i < 2 else "LOW",
                               reasons_json="[]", explanation="", confidence=0.9)
            session.add(a)
        session.commit()

        ctx = get_sender_context(session, "scammer_001")
        self.assertEqual(ctx["sender_total_messages"], 3)
        self.assertEqual(ctx["sender_high_risk_count"], 2)

    def test_chat_risk_profile(self):
        session = self._make_db()
        for i in range(5):
            m = MessageRecord(id=f"c{i}", platform="telegram", chat_id="scam_group", chat_name="Bad Group",
                              message_id=f"c{i}", sender_hash=f"user_{i}", text=f"text{i}",
                              timestamp=datetime.now(timezone.utc), status="PROCESSED")
            session.add(m)
            a = AnalysisRecord(id=f"ac{i}", message_id=f"c{i}", risk_score=85,
                               risk_level="HIGH", reasons_json="[]", explanation="", confidence=0.9)
            session.add(a)
        session.commit()

        ctx = get_chat_context(session, "scam_group")
        self.assertEqual(ctx["chat_total_messages"], 5)
        self.assertEqual(ctx["chat_high_risk_count"], 5)
        self.assertEqual(ctx["chat_unique_flagged_senders"], 5)

    def test_context_block_generated(self):
        session = self._make_db()
        m1 = MessageRecord(id="old1", platform="telegram", chat_id="tg1", chat_name="Chat",
                           message_id="old1", sender_hash="repeat_sender", text="old text",
                           timestamp=datetime.now(timezone.utc), status="PROCESSED")
        session.add(m1)
        a1 = AnalysisRecord(id="aold1", message_id="old1", risk_score=90,
                            risk_level="HIGH", reasons_json="[]", explanation="", confidence=0.9)
        session.add(a1)
        session.commit()

        new_msg = MessageRecord(id="new1", platform="telegram", chat_id="tg1", chat_name="Chat",
                                message_id="new1", sender_hash="repeat_sender", text="new text",
                                timestamp=datetime.now(timezone.utc), status="PENDING")
        session.add(new_msg)
        session.commit()

        block = build_context_block(session, new_msg)
        self.assertIn("ИСТОРИЯ ОТПРАВИТЕЛЯ", block)
        self.assertIn("repeat_sender", block)


class TestWorkerPipeline(unittest.TestCase):

    def test_error_status_on_no_key(self):
        Session = init_db("sqlite:///:memory:")
        session = Session()
        m = MessageRecord(id="w1", platform="telegram", chat_id="c1", chat_name="C",
                          message_id="w1", sender_hash="h", text="test",
                          timestamp=datetime.now(timezone.utc), status="PENDING")
        session.add(m)
        session.commit()
        process_pending_messages(session, limit=1, api_key="")
        session.refresh(m)
        self.assertEqual(m.status, "ERROR")

    @patch("ai_data.analyzer.call_gemini_api")
    def test_success_pipeline(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=90, risk_level=RiskLevelEnum.HIGH,
            reasons=[ReasonItem(code="UNREALISTIC_RETURN", evidence="получи 10000 завтра")],
            explanation="Пирамида.", confidence=0.92, model_version="gemini-2.0-flash"
        )
        Session = init_db("sqlite:///:memory:")
        session = Session()
        m = MessageRecord(id="w2", platform="telegram", chat_id="c1", chat_name="C",
                          message_id="w2", sender_hash="h", text="Вложи — получи 10000 завтра",
                          timestamp=datetime.now(timezone.utc), status="PENDING")
        session.add(m)
        session.commit()
        process_pending_messages(session, limit=1, api_key="fake_key")
        session.refresh(m)
        self.assertEqual(m.status, "PROCESSED")
        self.assertEqual(m.analysis.risk_level, "HIGH")
        alert = serialize_to_alert_dict(m)
        self.assertEqual(alert["risk_score"], 90)
        self.assertEqual(alert["review_status"], "NEW")


class TestGraphAnalysis(unittest.TestCase):

    def test_graph_link_detection(self):
        from ai_data.graph_analysis import analyze_network_graph

        Session = init_db("sqlite:///:memory:")
        session = Session()

        # Sender bot posting to 2 chats
        for idx, chat in enumerate(["tg_chat_a", "tg_chat_b"]):
            m = MessageRecord(
                id=f"g_msg_{idx}",
                platform="telegram",
                chat_id=chat,
                chat_name=f"Chat {chat}",
                message_id=f"g_msg_{idx}",
                sender_hash="spammer_bot_99",
                text="Вложи деньги удвой капитал",
                timestamp=datetime.now(timezone.utc),
                status="PROCESSED"
            )
            session.add(m)
            a = AnalysisRecord(
                id=f"g_an_{idx}",
                message_id=m.id,
                risk_score=95,
                risk_level="HIGH",
                reasons_json="[]",
                explanation="Скам",
                confidence=0.9
            )
            session.add(a)

        session.commit()

        graph = analyze_network_graph(session)
        self.assertGreaterEqual(len(graph["cross_chat_senders"]), 1)
        self.assertEqual(graph["cross_chat_senders"][0]["sender_hash"], "spammer_bot_99")
        self.assertTrue(graph["cross_chat_senders"][0]["is_bot_pattern"])
        self.assertGreaterEqual(len(graph["high_risk_chats"]), 2)
        self.assertIn("nodes", graph)
        self.assertIn("links", graph)

    def test_entity_extraction_and_syndicates(self):
        from ai_data.entity_extractor import extract_entities
        from ai_data.graph_analysis import analyze_network_graph

        # 1. Direct entity extraction
        ents = extract_entities("Kaspi: +7 707 555-44-33, карта 4400 1234 5678 9999, контакт @scam_boss")
        types = [e["type"] for e in ents]
        self.assertIn("PHONE", types)
        self.assertIn("CARD", types)
        self.assertIn("TELEGRAM_USER", types)

        # 2. Syndicate detection across senders
        Session = init_db("sqlite:///:memory:")
        session = Session()

        # Two different senders posting the same phone number
        for i, s_hash in enumerate(["bot_alpha", "bot_beta"]):
            m = MessageRecord(
                id=f"syn_msg_{i}", platform="telegram", chat_id=f"chat_{i}", chat_name="Chat",
                message_id=f"syn_msg_{i}", sender_hash=s_hash,
                text="Kaspi: +7 707 999-88-77", timestamp=datetime.now(timezone.utc), status="PROCESSED"
            )
            session.add(m)
            session.commit()
            ent = EntityRecord(
                id=f"syn_ent_{i}", message_id=m.id, entity_type="PHONE",
                normalized_value="+77079998877", created_at=datetime.now(timezone.utc)
            )
            session.add(ent)
            session.commit()

        graph = analyze_network_graph(session)
        self.assertGreaterEqual(len(graph["syndicates"]), 1)
        self.assertEqual(graph["syndicates"][0]["shared_entity"], "+77079998877")
        self.assertEqual(len(graph["syndicates"][0]["senders"]), 2)


if __name__ == "__main__":
    unittest.main()
