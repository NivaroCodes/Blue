"""
Verification script: Demonstrates Safe Reputation & Chat Risk Escalation:
1. Unreviewed automatic HIGH verdicts do NOT self-amplify; FALSE_POSITIVE verdicts are excluded.
2. A single HIGH message in a chat (1/1) never labels the chat a scam hub.
3. Analyst-confirmed (REVIEWED) HIGH verdicts + minimal sample (>= 5 messages) properly escalate risk.
"""
import sys, os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone, timedelta
from ai_data.db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord
from ai_data.context import get_sender_context, get_chat_context, build_context_block, is_scam_hub


def test_reputation_and_chat_escalation():
    import os
    from ai_data.tests.test_db_helper import assert_is_test_database, clean_test_database
    db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/safenet_test")
    assert_is_test_database(db_url)
    Session = init_db(db_url)
    s_clean = Session()
    clean_test_database(s_clean, db_url)
    s_clean.close()
    session = Session()

    print("=" * 60)
    print("TEST 1: Anti-self-amplification & Analyst confirmation")
    print("=" * 60)

    # 1a. Two unreviewed AUTO_HIGH messages from 'bot_pyramid_spammer'
    for idx, chat in enumerate(["chat_invest_almaty", "chat_crypto_astana"], start=1):
        m = MessageRecord(
            id=f"sim_msg_0{idx}",
            platform="telegram",
            chat_id=chat,
            chat_name=f"Chat {idx}",
            message_id=f"sim_msg_0{idx}",
            sender_hash="bot_pyramid_spammer",
            text=f"Вариант текста #{idx}: вложи 5000 тг — удвой до вечера!",
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=60 // idx),
            status="PROCESSED",
        )
        session.add(m)
        an = AnalysisRecord(
            id=f"sim_an_0{idx}",
            message_id=m.id,
            risk_score=80,
            risk_level="HIGH",
            reasons_json='[{"code": "UNREALISTIC_RETURN", "evidence": "удвой до вечера"}]',
            explanation="Признаки финансовой пирамиды.",
            confidence=0.9,
        )
        session.add(an)
        rev = ReviewRecord(
            id=f"sim_rev_0{idx}",
            analysis_id=an.id,
            review_status="NEW",  # NOT yet confirmed by a human analyst!
            reviewer_note="",
        )
        session.add(rev)
    session.commit()

    m3 = MessageRecord(
        id="sim_msg_03",
        platform="whatsapp",
        chat_id="chat_wa_shymkent",
        chat_name="Табыс Шымкент",
        message_id="sim_msg_03",
        sender_hash="bot_pyramid_spammer",
        text="Новый текст от того же автора",
        timestamp=datetime.now(timezone.utc),
        status="PENDING",
    )
    session.add(m3)
    session.commit()

    unverified_block = build_context_block(session, m3)
    assert "НЕ проверены человеком" in unverified_block, "Auto-HIGH должен быть явно помечен как непроверенный"
    assert "ПОДТВЕРЖДЕНО АНАЛИТИКОМ" not in unverified_block, "Без REVIEWED нельзя требовать повышения оценки"

    # 1b. Now an analyst confirms both past alerts as REVIEWED
    for rev in session.query(ReviewRecord).all():
        rev.review_status = "REVIEWED"
    session.commit()

    confirmed_ctx = get_sender_context(session, "bot_pyramid_spammer", current_text=m3.text, exclude_msg_id=m3.id)
    confirmed_block = build_context_block(session, m3)
    print(confirmed_block)
    assert confirmed_ctx["sender_confirmed_high_count"] == 2
    assert "ПОДТВЕРЖДЕНО АНАЛИТИКОМ" in confirmed_block
    print("\n-> ТЕСТ 1 ПРОЙДЕН: авто-HIGH не усиливает сам себя, а подтверждённый REVIEWED усиливает!\n")

    print("=" * 60)
    print("TEST 2: Scam hub requires >= 5 messages AND analyst confirmation")
    print("=" * 60)

    # Single message in a brand-new chat must NEVER make it a scam hub
    single_ctx = get_chat_context(session, "chat_invest_almaty")
    assert single_ctx["chat_total_messages"] == 1
    assert not is_scam_hub(single_ctx), "1 HIGH в 1 сообщении не должен считаться скам-хабом!"

    # Add 5 processed messages to 'toxic_group_kz', 4 confirmed HIGH by analyst + 1 FALSE_POSITIVE
    for i in range(5):
        msg = MessageRecord(
            id=f"toxic_msg_{i}",
            platform="telegram",
            chat_id="toxic_group_kz",
            chat_name="Быстрый Доход 1000%",
            message_id=f"toxic_msg_{i}",
            sender_hash=f"scam_user_{i}",
            text=f"Схема #{i}: депозит 10000 тг -> 50000 тг через 2 дня!",
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=10 * i),
            status="PROCESSED",
        )
        session.add(msg)
        an = AnalysisRecord(
            id=f"toxic_an_{i}",
            message_id=msg.id,
            risk_score=90,
            risk_level="HIGH",
            reasons_json="[]",
            explanation="Скам",
            confidence=0.9,
        )
        session.add(an)
        rev = ReviewRecord(
            id=f"toxic_rev_{i}",
            analysis_id=an.id,
            review_status="FALSE_POSITIVE" if i == 4 else "REVIEWED",
            reviewer_note="",
        )
        session.add(rev)
    session.commit()

    new_in_toxic = MessageRecord(
        id="toxic_msg_new",
        platform="telegram",
        chat_id="toxic_group_kz",
        chat_name="Быстрый Доход 1000%",
        message_id="toxic_msg_new",
        sender_hash="newbie_user_44",
        text="Есть интересный проект, кто хочет попробовать?",
        timestamp=datetime.now(timezone.utc),
        status="PENDING",
    )
    session.add(new_in_toxic)
    session.commit()

    chat_ctx = get_chat_context(session, "toxic_group_kz", exclude_msg_id=new_in_toxic.id)
    chat_block = build_context_block(session, new_in_toxic)
    print(chat_block)

    assert chat_ctx["chat_total_messages"] == 5
    assert chat_ctx["chat_confirmed_high_count"] == 4
    assert chat_ctx["chat_false_positive_count"] == 1
    assert is_scam_hub(chat_ctx)
    assert "ПОДТВЕРЖДЁННЫЙ СКАМ-ХАБ" in chat_block
    print("\n-> ТЕСТ 2 ПРОЙДЕН: FALSE_POSITIVE исключён, скам-хаб требует выборку >= 5 и подтверждение аналитика!\n")


if __name__ == "__main__":
    test_reputation_and_chat_escalation()
