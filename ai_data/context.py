"""
Context enrichment module — collects sender reputation and chat risk profile
from the database and builds a context block for the AI prompt.
"""
import json
import logging
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from .db.models import MessageRecord, AnalysisRecord

logger = logging.getLogger(__name__)


def get_sender_context(session: Session, sender_hash: str, current_text: str = "", exclude_msg_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds sender reputation from previous messages in the database.
    Tracks:
    - total messages sent
    - how many distinct chats this sender posts to (broadcast bot indicator)
    - exact/similar duplicate text count (spam wave indicator)
    - history of HIGH and MEDIUM risk messages
    - average risk score
    """
    query = (
        session.query(MessageRecord)
        .filter(MessageRecord.sender_hash == sender_hash, MessageRecord.status == "PROCESSED")
    )
    if exclude_msg_id:
        query = query.filter(MessageRecord.id != exclude_msg_id)

    past_messages: List[MessageRecord] = query.all()

    if not past_messages:
        return {
            "sender_total_messages": 0,
            "sender_unique_chats": 0,
            "sender_duplicate_count": 0,
            "sender_high_risk_count": 0,
            "sender_medium_risk_count": 0,
            "sender_avg_risk_score": 0.0,
        }

    high = 0
    medium = 0
    scores = []
    unique_chats = set()
    duplicate_count = 0
    clean_curr = " ".join(current_text.lower().split()) if current_text else ""

    for m in past_messages:
        unique_chats.add(m.chat_id)
        if clean_curr and " ".join(m.text.lower().split()) == clean_curr:
            duplicate_count += 1

        if m.analysis:
            if m.analysis.risk_level == "HIGH":
                high += 1
            elif m.analysis.risk_level == "MEDIUM":
                medium += 1
            if m.analysis.risk_score is not None:
                scores.append(m.analysis.risk_score)

    return {
        "sender_total_messages": len(past_messages),
        "sender_unique_chats": len(unique_chats),
        "sender_duplicate_count": duplicate_count,
        "sender_high_risk_count": high,
        "sender_medium_risk_count": medium,
        "sender_avg_risk_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
    }


def get_chat_context(session: Session, chat_id: str, exclude_msg_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds chat/group risk profile from all processed messages in this chat.
    Tracks:
    - total messages in group
    - count of HIGH risk scams found in group
    - scam ratio in group
    - number of distinct flagged senders
    """
    query = (
        session.query(MessageRecord)
        .filter(MessageRecord.chat_id == chat_id, MessageRecord.status == "PROCESSED")
    )
    if exclude_msg_id:
        query = query.filter(MessageRecord.id != exclude_msg_id)

    past_messages: List[MessageRecord] = query.all()

    if not past_messages:
        return {
            "chat_total_messages": 0,
            "chat_high_risk_count": 0,
            "chat_medium_risk_count": 0,
            "chat_scam_ratio": 0.0,
            "chat_unique_flagged_senders": 0,
        }

    high = 0
    medium = 0
    unique_senders_flagged = set()
    for m in past_messages:
        if m.analysis:
            if m.analysis.risk_level == "HIGH":
                high += 1
                unique_senders_flagged.add(m.sender_hash)
            elif m.analysis.risk_level == "MEDIUM":
                medium += 1

    total = len(past_messages)
    scam_ratio = round((high + 0.5 * medium) / total, 2) if total > 0 else 0.0

    return {
        "chat_total_messages": total,
        "chat_high_risk_count": high,
        "chat_medium_risk_count": medium,
        "chat_scam_ratio": scam_ratio,
        "chat_unique_flagged_senders": len(unique_senders_flagged),
    }


def build_context_block(session: Session, msg: MessageRecord) -> str:
    """
    Builds a context string for the AI prompt with sender reputation and chat risk profile.
    Returns empty string if no historical data exists.
    """
    sender_ctx = get_sender_context(session, msg.sender_hash, current_text=msg.text, exclude_msg_id=msg.id)
    chat_ctx = get_chat_context(session, msg.chat_id, exclude_msg_id=msg.id)

    parts = []

    # 1. Sender reputation analysis
    if sender_ctx["sender_total_messages"] > 0:
        sender_line = (
            f"ИСТОРИЯ ОТПРАВИТЕЛЯ [{msg.sender_hash}]:\n"
            f"- Всего предыдущих сообщений в БД: {sender_ctx['sender_total_messages']}\n"
            f"- Из них получили HIGH-риск (пирамида): {sender_ctx['sender_high_risk_count']}\n"
            f"- Из них получили MEDIUM-риск: {sender_ctx['sender_medium_risk_count']}\n"
            f"- Рассылает сообщения по {sender_ctx['sender_unique_chats']} разным чатам/группам\n"
            f"- Средний risk_score отправителя: {sender_ctx['sender_avg_risk_score']}"
        )
        if sender_ctx["sender_duplicate_count"] > 0:
            sender_line += f"\n- Отправил ТОЧНО ТАКОЕ ЖЕ сообщение уже {sender_ctx['sender_duplicate_count']} раз(а) ранее (паттерн спам-бота)."
        parts.append(sender_line)

        # Triggers for repeated sender
        if sender_ctx["sender_duplicate_count"] >= 2:
            parts.append(
                "[!] ВНИМАНИЕ ИИ: Данный отправитель ПОВТОРНО (3+ раз) распространяет идентичный текст. "
                "Это подтверждённый признак спам-бота или серийного скамера. "
                "ОБЯЗАТЕЛЬНО повысь risk_score на +15..+25 пунктов и укажи в explanation признак серийной спам-рассылки."
            )
        elif sender_ctx["sender_high_risk_count"] >= 2:
            parts.append(
                "[!] ВНИМАНИЕ ИИ: Этот отправитель уже 2+ раза был классифицирован как HIGH-риск. "
                "Повторяющийся автор мошеннических схем. "
                "ОБЯЗАТЕЛЬНО учти репутацию автора: повышай risk_score на +15 пунктов."
            )
        elif sender_ctx["sender_unique_chats"] >= 3:
            parts.append(
                "[!] ВНИМАНИЕ ИИ: Отправитель ведёт кросс-постинг минимум в 3 разных чата/группы. Паттерн массового посева."
            )

    # 2. Chat / group risk profile
    if chat_ctx["chat_total_messages"] > 0:
        chat_line = (
            f"ИСТОРИЯ ГРУППЫ/ИСТОЧНИКА [{msg.chat_name} (id: {msg.chat_id})]:\n"
            f"- Всего обработано сообщений из этого чата: {chat_ctx['chat_total_messages']}\n"
            f"- Выявлено подтверждённых HIGH-риск пирамид: {chat_ctx['chat_high_risk_count']}\n"
            f"- Выявлено MEDIUM-риск подозрительных: {chat_ctx['chat_medium_risk_count']}\n"
            f"- Уникальных спамеров/скамеров в чате: {chat_ctx['chat_unique_flagged_senders']}\n"
            f"- Доля мошеннической активности: {int(chat_ctx['chat_scam_ratio'] * 100)}%"
        )
        parts.append(chat_line)

        if chat_ctx["chat_high_risk_count"] >= 3 or chat_ctx["chat_scam_ratio"] >= 0.35:
            parts.append(
                "[!] ВНИМАНИЕ ИИ: Этот чат идентифицирован как ВЫСОКОРИСКОВОЕ СООБЩЕСТВО (скам-хаб). "
                "Здесь систематически продвигаются нелегальные финансовые схемы. "
                "Любые финансовые предложения в таком источнике требуют повышенной бдительности: "
                "если сообщение содержит хотя бы один сомнительный признак, относи его к HIGH/MEDIUM риску (+10 к score)."
            )

    if not parts:
        return ""

    return "\n\n========== КОНТЕКСТ ИЗ БАЗЫ ДАННЫХ ==========\n" + "\n\n".join(parts) + "\n=============================================="
