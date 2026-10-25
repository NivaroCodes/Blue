import base64
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_data.context import build_context_block, get_chat_context, get_sender_context, is_scam_hub
from ai_data.db.models import (
    AnalysisRecord,
    EntityRecord,
    MessageRecord,
    ReviewRecord,
    format_timestamp,
    init_db,
    make_message_pk,
    parse_timestamp,
    serialize_to_alert_dict,
    utc_now,
)
from ai_data.tests.test_db_helper import get_clean_test_session, get_test_session_factory, clean_test_database
from ai_data.entity_extractor import extract_entities
from ai_data.graph_analysis import analyze_network_graph
from ai_data.llm_client import _parse_and_validate_llm_json
from ai_data.models import AnalysisResult, ReasonItem, RiskLevelEnum
from ai_data.worker import claim_message, process_pending_messages, recover_stale_claims
import ai_data.api_server as api_server
import ai_data.media as media_mod

# Valid 1x1 PNG image bytes
TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
TINY_PNG_B64 = base64.b64encode(TINY_PNG_BYTES).decode("ascii")


class TestCardLinkingNoCollision(unittest.TestCase):
    """Issue 1: Different bank cards sharing first/last 4 digits must never merge in the graph."""

    def test_different_cards_same_edges_do_not_collide(self):
        ents_a = extract_entities("Перевод на Kaspi 4400 1111 2222 1234")
        ents_b = extract_entities("Перевод на Kaspi 4400 9999 8888 1234")
        self.assertEqual(len(ents_a), 1)
        self.assertEqual(len(ents_b), 1)

        # Both display the same privacy-masked string, yet have distinct comparison keys
        self.assertEqual(ents_a[0]["display"], "4400 **** **** 1234")
        self.assertEqual(ents_b[0]["display"], "4400 **** **** 1234")
        self.assertNotEqual(ents_a[0]["value"], ents_b[0]["value"])
        self.assertNotIn("1111", ents_a[0]["value"])  # raw middle digits not stored in plaintext

        session = get_clean_test_session()

        for idx, (sender, card_ent) in enumerate([("author_1", ents_a[0]), ("author_2", ents_b[0])]):
            m = MessageRecord(
                id=f"card_m_{idx}",
                platform="telegram",
                chat_id=f"chat_{idx}",
                chat_name="Chat",
                message_id=f"m_{idx}",
                sender_hash=sender,
                text="Перевод",
                timestamp=datetime.now(timezone.utc),
                status="PROCESSED",
            )
            session.add(m)
            session.add(EntityRecord(
                id=f"card_e_{idx}",
                message_id=m.id,
                entity_type="CARD",
                normalized_value=card_ent["value"],
                display_value=card_ent["display"],
            ))
        session.commit()

        graph = analyze_network_graph(session)
        self.assertEqual(graph["syndicates"], [], "Разные карты с одинаковыми краями не должны образовывать синдикат")
        entity_nodes = [n for n in graph["nodes"] if n["type"] == "entity"]
        self.assertEqual(len(entity_nodes), 2)

    def test_identical_full_card_links_senders_with_masked_label(self):
        ents_1 = extract_entities("Карта: 4400 1111 2222 1234")
        ents_2 = extract_entities("Карта: 4400-1111-2222-1234")
        self.assertEqual(ents_1[0]["value"], ents_2[0]["value"])

        session = get_clean_test_session()

        for idx, (sender, card_ent) in enumerate([("bot_1", ents_1[0]), ("bot_2", ents_2[0])]):
            m = MessageRecord(
                id=f"same_m_{idx}",
                platform="telegram",
                chat_id="chat_1",
                chat_name="Chat",
                message_id=f"sm_{idx}",
                sender_hash=sender,
                text="Карта",
                timestamp=datetime.now(timezone.utc),
                status="PROCESSED",
            )
            session.add(m)
            session.add(EntityRecord(
                id=f"same_e_{idx}",
                message_id=m.id,
                entity_type="CARD",
                normalized_value=card_ent["value"],
                display_value=card_ent["display"],
            ))
        session.commit()

        graph = analyze_network_graph(session)
        self.assertEqual(len(graph["syndicates"]), 1)
        self.assertEqual(graph["syndicates"][0]["shared_entity"], "4400 **** **** 1234")
        self.assertCountEqual(graph["syndicates"][0]["senders"], ["bot_1", "bot_2"])


class TestReputationNoSelfAmplification(unittest.TestCase):
    """Issue 2: Auto-HIGH verdicts must not self-amplify; analyst decisions and sample size respected."""

    def test_auto_high_does_not_escalate_and_single_message_not_scam_hub(self):
        session = get_clean_test_session()


        # 1 processed message in chat with unreviewed HIGH (status NEW)
        m1 = MessageRecord(
            id="m1", platform="telegram", chat_id="new_chat", chat_name="New Chat",
            message_id="1", sender_hash="user_x", text="Подозрительный пост 1",
            timestamp=datetime.now(timezone.utc), status="PROCESSED",
        )
        m2 = MessageRecord(
            id="m2", platform="telegram", chat_id="other_chat", chat_name="Other",
            message_id="1", sender_hash="user_x", text="Подозрительный пост 2",
            timestamp=datetime.now(timezone.utc), status="PROCESSED",
        )
        session.add_all([m1, m2])
        for idx, mid in enumerate(["m1", "m2"]):
            an = AnalysisRecord(id=f"a_{mid}", message_id=mid, risk_score=85, risk_level="HIGH",
                                reasons_json="[]", explanation="auto", confidence=0.8)
            rev = ReviewRecord(id=f"r_{mid}", analysis_id=an.id, review_status="NEW")
            session.add_all([an, rev])
        session.commit()

        chat_ctx = get_chat_context(session, "new_chat")
        self.assertEqual(chat_ctx["chat_total_messages"], 1)
        self.assertFalse(is_scam_hub(chat_ctx), "1 сообщение в чате не может делать чат скам-хабом")

        m3 = MessageRecord(
            id="m3", platform="telegram", chat_id="new_chat", chat_name="New Chat",
            message_id="2", sender_hash="user_x", text="Обычный вопрос",
            timestamp=datetime.now(timezone.utc), status="PENDING",
        )
        session.add(m3)
        session.commit()

        block = build_context_block(session, m3)
        self.assertNotIn("ПОДТВЕРЖДЕНО АНАЛИТИКОМ", block)
        self.assertNotIn("ПОДТВЕРЖДЁННЫЙ СКАМ-ХАБ", block)
        self.assertNotIn("Выявлено подтверждённых HIGH-риск пирамид", block)
        self.assertIn("НЕ проверена человеком", block)

    def test_false_positive_excluded_and_reviewed_escalates(self):
        session = get_clean_test_session()


        for i in range(5):
            m = MessageRecord(
                id=f"fp_{i}", platform="telegram", chat_id="hub_chat", chat_name="Hub",
                message_id=str(i), sender_hash="scammer_1" if i < 3 else f"u_{i}",
                text="Скам", timestamp=datetime.now(timezone.utc), status="PROCESSED",
            )
            an = AnalysisRecord(id=f"afp_{i}", message_id=m.id, risk_score=90, risk_level="HIGH",
                                reasons_json="[]", explanation="", confidence=0.9)
            # Mark all 3 of scammer_1's alerts as FALSE_POSITIVE!
            status = "FALSE_POSITIVE" if i < 3 else "REVIEWED"
            rev = ReviewRecord(id=f"rfp_{i}", analysis_id=an.id, review_status=status)
            session.add_all([m, an, rev])
        session.commit()

        s_ctx = get_sender_context(session, "scammer_1")
        self.assertEqual(s_ctx["sender_high_risk_count"], 0)
        self.assertEqual(s_ctx["sender_confirmed_high_count"], 0)
        self.assertEqual(s_ctx["sender_false_positive_count"], 3)

        # Chat has 5 messages total and 2 REVIEWED HIGHs (2/5 = 0.40 >= 0.35) -> confirmed scam hub
        c_ctx = get_chat_context(session, "hub_chat")
        self.assertEqual(c_ctx["chat_confirmed_high_count"], 2)
        self.assertEqual(c_ctx["chat_false_positive_count"], 3)
        self.assertTrue(is_scam_hub(c_ctx))


class TestTimezoneSerialization(unittest.TestCase):
    """Issue 3: UTC stored in SQLite must convert to +05:00 (+5h wall clock), not merely append '+05:00'."""

    def test_utc_roundtrip_to_kz_offset_no_five_hour_shift(self):
        session = get_clean_test_session()


        utc_dt = datetime(2026, 10, 23, 14, 0, 0, tzinfo=timezone.utc)
        m = MessageRecord(
            id="tz_1", platform="telegram", chat_id="c1", chat_name="C",
            message_id="1", sender_hash="s1", text="test",
            timestamp=utc_dt, status="PENDING",
        )
        session.add(m)
        session.commit()
        session.expire_all()

        loaded = session.get(MessageRecord, "tz_1")
        alert = serialize_to_alert_dict(loaded)
        self.assertEqual(alert["timestamp"], "2026-10-23T19:00:00+05:00")
        parsed_back = datetime.fromisoformat(alert["timestamp"])
        self.assertEqual(parsed_back, utc_dt)

    def test_parse_timestamp_normalizes_offsets_for_24h_filter(self):
        t_utc = parse_timestamp("2026-10-23T14:00:00Z")
        t_kz = parse_timestamp("2026-10-23T19:00:00+05:00")
        self.assertEqual(t_utc, t_kz)
        self.assertEqual(format_timestamp(t_utc), "2026-10-23T19:00:00+05:00")


class TestCrossChatDeduplication(unittest.TestCase):
    """Issue 4: Identical chat-local message_id across different chats/platforms must never collide."""

    def setUp(self):
        self.Session = get_test_session_factory()
        _s = self.Session()
        clean_test_database(_s)
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

    def test_same_local_message_id_in_two_chats_and_platforms_preserved(self):
        r1 = self.client.post("/api/messages", json={
            "platform": "telegram", "chat_id": "chat_A", "chat_name": "Chat A",
            "message_id": "105", "sender_hash": "u1", "text": "Сообщение из чата А",
        })
        r2 = self.client.post("/api/messages", json={
            "platform": "telegram", "chat_id": "chat_B", "chat_name": "Chat B",
            "message_id": "105", "sender_hash": "u2", "text": "Сообщение из чата Б",
        })
        r3 = self.client.post("/api/messages", json={
            "platform": "whatsapp", "chat_id": "chat_A", "chat_name": "WA Chat A",
            "message_id": "105", "sender_hash": "u3", "text": "Сообщение из WhatsApp",
        })
        # Duplicate of r1 -> must return same alert id without adding a 4th row
        r1_dup = self.client.post("/api/messages", json={
            "platform": "telegram", "chat_id": "chat_A", "chat_name": "Chat A",
            "message_id": "105", "sender_hash": "u1", "text": "Сообщение из чата А",
        })

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r1.json()["id"], r1_dup.json()["id"])
        self.assertNotEqual(r1.json()["id"], r2.json()["id"])
        self.assertNotEqual(r1.json()["id"], r3.json()["id"])

        alerts = self.client.get("/api/alerts").json()
        self.assertEqual(len(alerts), 3)

        # Bare local message_id '105' is ambiguous across 3 chats -> 409 Conflict
        ambiguous = self.client.get("/api/alerts/105")
        self.assertEqual(ambiguous.status_code, 409)

        # Full alert id resolves unambiguously
        detail = self.client.get(f"/api/alerts/{r2.json()['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["text"], "Сообщение из чата Б")


class TestMultimodalUnifiedPipeline(unittest.TestCase):
    """Issue 5: Worker processes image_url; /api/analyze-image persists regular alerts."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self._orig_media_dir = media_mod.MEDIA_DIR
        media_mod.MEDIA_DIR = Path(self.tmp_dir.name).resolve()

        self.Session = get_test_session_factory()
        _s = self.Session()
        clean_test_database(_s)
        _s.close()

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
        media_mod.MEDIA_DIR = self._orig_media_dir
        self.tmp_dir.cleanup()

    @patch("ai_data.analyzer.call_gemini_api")
    def test_worker_loads_image_url_and_extracts_ocr_entities(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=91,
            risk_level=RiskLevelEnum.HIGH,
            reasons=[ReasonItem(code="PERSONAL_TRANSFER", evidence="Kaspi +7 707 111 22 33", source="image")],
            explanation="Поддельный чек перевода на Kaspi.",
            confidence=0.94,
            model_version="gemini-3-flash-preview",
            image_text="Чек перевода 50 000 тг. Kaspi +7 707 111 22 33",
        )

        db = self.Session()
        pk = make_message_pk("telegram", "tg_1", "img_1")
        db.add(MessageRecord(
            id=pk, platform="telegram", chat_id="tg_1", chat_name="Chat",
            message_id="img_1", sender_hash="sender_pic", text="",
            image_url=f"data:image/png;base64,{TINY_PNG_B64}",
            timestamp=datetime.now(timezone.utc), status="PENDING",
        ))
        db.commit()

        processed = process_pending_messages(db, limit=1, api_key="fake_key", throttle_seconds=0)
        self.assertEqual(processed, 1)

        # Confirm Gemini received the decoded image and MIME type
        _, kwargs = mock_gemini.call_args
        self.assertEqual(kwargs["image_base64"], TINY_PNG_B64)
        self.assertEqual(kwargs["image_mime"], "image/png")

        rec = db.get(MessageRecord, pk)
        alert = serialize_to_alert_dict(rec)
        self.assertEqual(alert["status"], "PROCESSED")
        self.assertTrue(alert["image_analyzed"])
        self.assertEqual(alert["risk_score"], 91)

        # Phone number from screenshot OCR must be stored in EntityRecord
        ents = db.query(EntityRecord).filter(EntityRecord.message_id == pk).all()
        self.assertEqual(len(ents), 1)
        self.assertEqual(ents[0].normalized_value, "+77071112233")
        db.close()

    @patch("ai_data.analyzer.call_gemini_api")
    def test_analyze_image_endpoint_persists_alert_and_serves_media(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=88,
            risk_level=RiskLevelEnum.HIGH,
            reasons=[ReasonItem(code="UNREALISTIC_RETURN", evidence="выплата 200% за сутки", source="image")],
            explanation="Рекламный баннер пирамиды.",
            confidence=0.9,
            model_version="gemini-3-flash-preview",
            image_text="Закрытый пул: выплата 200% за сутки!",
        )

        with patch("ai_data.analyzer.GEMINI_API_KEY", "fake_key"):
            resp = self.client.post("/api/analyze-image", json={
                "image_base64": TINY_PNG_B64,
                "text_caption": "Скриншот из чата",
            })

        self.assertEqual(resp.status_code, 200)
        created = resp.json()
        self.assertEqual(created["status"], "PROCESSED")
        self.assertEqual(created["risk_level"], "HIGH")
        self.assertTrue(created["image_url"].startswith("/api/media/"))

        # Must appear in regular /api/alerts and /api/stats
        alerts = self.client.get("/api/alerts").json()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["id"], created["id"])

        stats = self.client.get("/api/stats").json()
        self.assertEqual(stats["total_messages"], 1)
        self.assertEqual(stats["by_level"]["HIGH"], 1)

        # Saved media file is retrievable
        media_resp = self.client.get(created["image_url"])
        self.assertEqual(media_resp.status_code, 200)
        self.assertEqual(media_resp.headers["content-type"], "image/png")

    def test_llm_json_parser_preserves_image_evidence_when_text_empty(self):
        raw = (
            '{"risk_score":85,"risk_level":"HIGH",'
            '"image_text":"Вложи 10 000 тг получи 30 000 тг",'
            '"reasons":[{"code":"UNREALISTIC_RETURN","evidence":"получи 30 000 тг","source":"image"}],'
            '"explanation":"Скриншот пирамиды","confidence":0.9}'
        )
        res = _parse_and_validate_llm_json(raw, "", "gemini-test", has_image=True)
        self.assertEqual(res.risk_level, RiskLevelEnum.HIGH)
        self.assertEqual(len(res.reasons), 1)
        self.assertEqual(res.reasons[0].source, "image")

    @patch("ai_data.analyzer.call_gemini_api")
    def test_worker_handles_missing_image_file_with_text_fallback(self, mock_gemini):
        mock_gemini.return_value = AnalysisResult(
            risk_score=75,
            risk_level=RiskLevelEnum.MEDIUM,
            reasons=[ReasonItem(code="MONEY_REQUEST", evidence="вложите деньги", source="text")],
            explanation="Анализ только текста (изображение недоступно)",
            confidence=0.80,
            model_version="gemini-test",
        )
        db = get_clean_test_session()
        pk = "msg_missing_img_fallback"
        msg = MessageRecord(
            id=pk,
            platform="telegram",
            chat_id="chat_img",
            message_id="101",
            sender_hash="sender_img",
            text="Пожалуйста вложите деньги прямо сейчас",
            image_url="/api/media/non_existent_file.png",
            timestamp=utc_now(),
            status="PENDING",
        )
        db.add(msg)
        db.commit()

        processed = process_pending_messages(db, limit=1, api_key="fake_key", throttle_seconds=0)
        self.assertEqual(processed, 1)

        db.refresh(msg)
        alert = serialize_to_alert_dict(msg)
        self.assertEqual(alert["status"], "PROCESSED")
        # Critical security & honesty check: image_analyzed MUST be False, NOT True
        self.assertFalse(alert["image_analyzed"])
        self.assertIsNone(alert["image_text"])
        self.assertEqual(alert["risk_score"], 75)
        db.close()

    def test_worker_fails_when_image_missing_and_no_text(self):
        db = get_clean_test_session()
        pk = "msg_missing_img_no_text"
        msg = MessageRecord(
            id=pk,
            platform="telegram",
            chat_id="chat_img_2",
            message_id="102",
            sender_hash="sender_img_2",
            text="",
            image_url="/api/media/completely_missing.png",
            timestamp=utc_now(),
            status="PENDING",
        )
        db.add(msg)
        db.commit()

        processed = process_pending_messages(db, limit=1, api_key="fake_key", throttle_seconds=0)
        self.assertEqual(processed, 0)

        db.refresh(msg)
        self.assertEqual(msg.status, "ERROR")
        self.assertIn("Сообщение без текста, а изображение недоступно", msg.last_error)
        db.close()


class TestAtomicWorkerConcurrency(unittest.TestCase):
    """Issue 6: Concurrent API inline processing + background workers never double-process a message."""

    def test_concurrent_workers_never_analyze_same_message_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "concurrent.db"
            Session = get_test_session_factory()
            clean_s = Session()
            clean_test_database(clean_s)
            clean_s.close()

            seed_s = Session()
            now = datetime.now(timezone.utc)
            for i in range(12):
                seed_s.add(MessageRecord(
                    id=f"race_{i}", platform="telegram", chat_id="c1", chat_name="C",
                    message_id=str(i), sender_hash=f"u_{i}", text="Вложи 5000 тг",
                    timestamp=now + timedelta(seconds=i), status="PENDING",
                ))
            seed_s.commit()
            seed_s.close()

            call_lock = threading.Lock()
            analyzed_texts = []

            def fake_gemini(text, **kwargs):
                time.sleep(0.02)  # overlap workers so races actually happen
                with call_lock:
                    analyzed_texts.append(text)
                return AnalysisResult(
                    risk_score=80,
                    risk_level=RiskLevelEnum.HIGH,
                    reasons=[ReasonItem(code="MONEY_REQUEST", evidence="Вложи 5000 тг")],
                    explanation="Пирамида",
                    confidence=0.9,
                    model_version="test",
                )

            counts = []
            barrier = threading.Barrier(4)

            def worker_fn(idx: int):
                s = Session()
                try:
                    barrier.wait()
                    done = 0
                    retries = 10
                    while True:
                        n = process_pending_messages(
                            s, limit=3, api_key="fake_key", throttle_seconds=0, worker_id=f"w-{idx}"
                        )
                        if n == 0:
                            s.rollback()
                            if s.query(MessageRecord).filter(MessageRecord.status == "PENDING").count() > 0 and retries > 0:
                                retries -= 1
                                time.sleep(0.05)
                                continue
                            break
                        done += n
                    counts.append(done)
                finally:
                    s.close()

            with patch("ai_data.analyzer.call_gemini_api", side_effect=fake_gemini):
                threads = [threading.Thread(target=worker_fn, args=(i,)) for i in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

            self.assertEqual(sum(counts), 12)
            self.assertEqual(len(analyzed_texts), 12, "Каждое сообщение должно быть проанализировано строго 1 раз")

            check_s = Session()
            rows = check_s.query(MessageRecord).all()
            self.assertTrue(all(r.status == "PROCESSED" and r.attempts == 1 for r in rows))
            check_s.close()


    def test_stale_claim_recovery_and_max_attempts(self):
        session = get_clean_test_session()
        s = session
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        # Message 1: stuck on attempt 1 -> should return to PENDING
        s.add(MessageRecord(
            id="stuck_1", platform="telegram", chat_id="c", chat_name="C",
            message_id="1", sender_hash="u", text="t",
            timestamp=stale_time, status="PROCESSING",
            claimed_by="dead-worker", claimed_at=stale_time, attempts=1,
        ))
        # Message 2: stuck on attempt 3 (MAX_ATTEMPTS) -> should move to ERROR
        s.add(MessageRecord(
            id="stuck_2", platform="telegram", chat_id="c", chat_name="C",
            message_id="2", sender_hash="u", text="t",
            timestamp=stale_time, status="PROCESSING",
            claimed_by="dead-worker", claimed_at=stale_time, attempts=3,
        ))
        s.commit()

        recovered = recover_stale_claims(s)
        self.assertEqual(recovered, 2)
        s.expire_all()
        self.assertEqual(s.get(MessageRecord, "stuck_1").status, "PENDING")
        self.assertEqual(s.get(MessageRecord, "stuck_2").status, "ERROR")

        # Atomic claim test: first caller wins, second caller gets False
        self.assertTrue(claim_message(s, "stuck_1", "worker-A"))
        self.assertFalse(claim_message(s, "stuck_1", "worker-B"))
        s.close()


if __name__ == "__main__":
    unittest.main()
