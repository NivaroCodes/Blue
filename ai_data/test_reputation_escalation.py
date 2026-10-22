"""
Verification script: Demonstrates Dynamic Risk Escalation based on Database Context:
1. Sender Reputation Escalation: Repeat sender/bot gets boosted risk score and explicit warning in explanation.
2. Chat Cluster Escalation: Chat with high density of scam messages triggers elevated vigilance for new messages.
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from datetime import datetime, timezone, timedelta
from ai_data.db.models import init_db, MessageRecord, AnalysisRecord
from ai_data.context import get_sender_context, get_chat_context, build_context_block


def test_reputation_and_chat_escalation():
    Session = init_db("sqlite:///:memory:")
    session = Session()

    print("=" * 60)
    print("TEST 1: Sender reputation escalation (bot / serial spammer)")
    print("=" * 60)

    # Author 'bot_pyramid_spammer' posts message 1 in Chat A (processed as HIGH)
    m1 = MessageRecord(
        id="sim_msg_01",
        platform="telegram",
        chat_id="chat_invest_almaty",
        chat_name="Инвест Клуб Алматы",
        message_id="sim_msg_01",
        sender_hash="bot_pyramid_spammer",
        text="Вложи 5000 тг — удвой до вечера! Kaspi перевод.",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=60),
        status="PROCESSED"
    )
    session.add(m1)
    a1 = AnalysisRecord(
        id="sim_an_01",
        message_id=m1.id,
        risk_score=75,
        risk_level="HIGH",
        reasons_json='[{"code": "UNREALISTIC_RETURN", "evidence": "удвой до вечера"}]',
        explanation="Признаки финансовой пирамиды.",
        confidence=0.9
    )
    session.add(a1)
    session.commit()

    # Author 'bot_pyramid_spammer' posts message 2 in Chat B (processed as HIGH)
    m2 = MessageRecord(
        id="sim_msg_02",
        platform="telegram",
        chat_id="chat_crypto_astana",
        chat_name="Крипто Астана",
        message_id="sim_msg_02",
        sender_hash="bot_pyramid_spammer",
        text="Вложи 5000 тг — удвой до вечера! Kaspi перевод.",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=30),
        status="PROCESSED"
    )
    session.add(m2)
    a2 = AnalysisRecord(
        id="sim_an_02",
        message_id=m2.id,
        risk_score=85,
        risk_level="HIGH",
        reasons_json='[{"code": "UNREALISTIC_RETURN", "evidence": "удвой до вечера"}]',
        explanation="Повторный скам.",
        confidence=0.92
    )
    session.add(a2)
    session.commit()

    # Incoming message 3 from same author in Chat C (PENDING)
    m3 = MessageRecord(
        id="sim_msg_03",
        platform="whatsapp",
        chat_id="chat_wa_shymkent",
        chat_name="Табыс Шымкент",
        message_id="sim_msg_03",
        sender_hash="bot_pyramid_spammer",
        text="Вложи 5000 тг — удвой до вечера! Kaspi перевод.",
        timestamp=datetime.now(timezone.utc),
        status="PENDING"
    )
    session.add(m3)
    session.commit()

    # Check context generated for Message 3
    sender_ctx = get_sender_context(session, "bot_pyramid_spammer", current_text=m3.text, exclude_msg_id=m3.id)
    context_block = build_context_block(session, m3)

    print(f"Отправитель: {m3.sender_hash}")
    print(f"- Предыдущих сообщений в БД: {sender_ctx['sender_total_messages']}")
    print(f"- Из них признаны HIGH-риском: {sender_ctx['sender_high_risk_count']}")
    print(f"- Охват уникальных чатов: {sender_ctx['sender_unique_chats']}")
    print(f"- Повторов идентичного текста: {sender_ctx['sender_duplicate_count']}")
    print("\nСформированный блок контекста для ИИ:")
    print(context_block)

    assert sender_ctx['sender_high_risk_count'] == 2, "Должно быть 2 HIGH риска в истории"
    assert sender_ctx['sender_unique_chats'] == 2, "Должен охватывать 2 разных чата"
    assert sender_ctx['sender_duplicate_count'] == 2, "Должно быть 2 дубликата текста"
    assert "ВНИМАНИЕ ИИ: Данный отправитель ПОВТОРНО" in context_block, "Блок контекста обязан содержать предупреждение о спам-боте"
    print("\n-> ТЕСТ 1 УСПЕШНО ПРОЙДЕН! Репутация спамера корректно накапливается и передаётся в промпт ИИ.\n")

    print("=" * 60)
    print("TEST 2: Escalation for toxic chat / scam hub")
    print("=" * 60)

    # Add 4 HIGH-risk messages from different users into 'toxic_group_kz'
    for i in range(4):
        msg = MessageRecord(
            id=f"toxic_msg_{i}",
            platform="telegram",
            chat_id="toxic_group_kz",
            chat_name="Быстрый Доход 1000%",
            message_id=f"toxic_msg_{i}",
            sender_hash=f"scam_user_{i}",
            text=f"Схема #{i}: депозит 10000 тг -> 50000 тг через 2 дня!",
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=10 * i),
            status="PROCESSED"
        )
        session.add(msg)
        an = AnalysisRecord(
            id=f"toxic_an_{i}",
            message_id=msg.id,
            risk_score=90,
            risk_level="HIGH",
            reasons_json="[]",
            explanation="Скам",
            confidence=0.9
        )
        session.add(an)
    session.commit()

    # Now a new, borderline message arrives in 'toxic_group_kz'
    new_in_toxic = MessageRecord(
        id="toxic_msg_new",
        platform="telegram",
        chat_id="toxic_group_kz",
        chat_name="Быстрый Доход 1000%",
        message_id="toxic_msg_new",
        sender_hash="newbie_user_44",
        text="Есть интересный проект, кто хочет попробовать?",
        timestamp=datetime.now(timezone.utc),
        status="PENDING"
    )
    session.add(new_in_toxic)
    session.commit()

    chat_ctx = get_chat_context(session, "toxic_group_kz", exclude_msg_id=new_in_toxic.id)
    chat_block = build_context_block(session, new_in_toxic)

    print(f"Группа: {new_in_toxic.chat_name} ({new_in_toxic.chat_id})")
    print(f"- Всего сообщений в группе: {chat_ctx['chat_total_messages']}")
    print(f"- Выявлено подтверждённых пирамид: {chat_ctx['chat_high_risk_count']}")
    print(f"- Доля мошеннической активности: {int(chat_ctx['chat_scam_ratio'] * 100)}%")
    print("\nСформированный блок контекста для ИИ:")
    print(chat_block)

    assert chat_ctx['chat_high_risk_count'] == 4, "Должно быть 4 HIGH риска в чате"
    assert chat_ctx['chat_scam_ratio'] == 1.0, "Доля скама должна быть 100%"
    assert "ВНИМАНИЕ ИИ: Этот чат идентифицирован как ВЫСОКОРИСКОВОЕ СООБЩЕСТВО" in chat_block, "Блок контекста обязан маркировать группу как скам-хаб"
    print("\n-> ТЕСТ 2 УСПЕШНО ПРОЙДЕН! Группа со множеством скамов идентифицирована как скам-хаб, ИИ получает требование повышенной бдительности.\n")


if __name__ == "__main__":
    test_reputation_and_chat_escalation()
