"""
Context enrichment module — collects sender reputation and chat risk profile
from the database and builds a context block for the AI prompt.

Design rule (prevents the model from amplifying its own mistakes):
- Only verdicts CONFIRMED by an analyst (review_status = REVIEWED) may raise the next score.
- Automatic, unreviewed verdicts are shown to the model as *unverified* information only.
- Verdicts rejected by an analyst (FALSE_POSITIVE) are excluded from all risk counts.
- Factual, model-independent signals (identical text repeated, cross-posting to many chats)
  may still escalate, but only if the current message itself contains a financial red flag.
- A chat needs a minimal sample (MIN_CHAT_SAMPLE processed messages) before it can be a "scam hub".
"""
import logging
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from .db.models import MessageRecord

logger = logging.getLogger(__name__)

MIN_CHAT_SAMPLE = 5            # processed messages required before chat-level escalation
HUB_CONFIRMED_MIN = 3          # confirmed HIGH messages that make a chat a scam hub ...
HUB_CONFIRMED_RATIO = 0.35     # ... or the confirmed HIGH share of the chat sample
SENDER_CONFIRMED_MIN = 2       # confirmed HIGH messages that make a sender a repeat offender
DUPLICATE_MIN = 2              # identical earlier copies => 3rd+ copy is a broadcast


def _classify(m: MessageRecord) -> str:
    """
    Returns one of:
      CONFIRMED_HIGH / CONFIRMED_MEDIUM  — analyst reviewed and kept the verdict
      AUTO_HIGH / AUTO_MEDIUM            — model verdict, not yet reviewed
      REJECTED                           — analyst marked FALSE_POSITIVE
      LOW / NONE
    """
    a = m.analysis
    if not a or not a.risk_level:
        return "NONE"
    status = a.review.review_status if a.review else "NEW"
    if status == "FALSE_POSITIVE":
        return "REJECTED"
    if a.risk_level in ("HIGH", "MEDIUM"):
        return ("CONFIRMED_" if status == "REVIEWED" else "AUTO_") + a.risk_level
    return "LOW"


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").lower().split())


def get_sender_context(session: Session, sender_hash: str, current_text: str = "", exclude_msg_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds sender reputation from previous messages in the database.
    Tracks:
    - total messages sent
    - how many distinct chats this sender posts to (broadcast bot indicator)
    - exact duplicate text count (spam wave indicator), excluding copies rejected by an analyst
    - HIGH / MEDIUM history split into analyst-confirmed vs. automatic (unverified)
    - average risk score (rejected verdicts excluded)
    """
    query = (
        session.query(MessageRecord)
        .filter(MessageRecord.sender_hash == sender_hash, MessageRecord.status == "PROCESSED")
    )
    if exclude_msg_id:
        query = query.filter(MessageRecord.id != exclude_msg_id)

    past_messages: List[MessageRecord] = query.all()

    counts = {k: 0 for k in ("CONFIRMED_HIGH", "AUTO_HIGH", "CONFIRMED_MEDIUM", "AUTO_MEDIUM", "REJECTED")}
    scores = []
    unique_chats = set()
    duplicate_count = 0
    duplicate_rejected = 0
    clean_curr = _norm(current_text)

    for m in past_messages:
        unique_chats.add(m.chat_id)
        cls = _classify(m)
        if cls in counts:
            counts[cls] += 1

        if clean_curr and _norm(m.text) == clean_curr:
            if cls == "REJECTED":
                duplicate_rejected += 1
            else:
                duplicate_count += 1

        if cls != "REJECTED" and m.analysis and m.analysis.risk_score is not None:
            scores.append(m.analysis.risk_score)

    return {
        "sender_total_messages": len(past_messages),
        "sender_unique_chats": len(unique_chats),
        "sender_duplicate_count": duplicate_count,
        "sender_duplicate_rejected_count": duplicate_rejected,
        # Not rejected by an analyst (confirmed + automatic)
        "sender_high_risk_count": counts["CONFIRMED_HIGH"] + counts["AUTO_HIGH"],
        "sender_medium_risk_count": counts["CONFIRMED_MEDIUM"] + counts["AUTO_MEDIUM"],
        "sender_confirmed_high_count": counts["CONFIRMED_HIGH"],
        "sender_auto_high_count": counts["AUTO_HIGH"],
        "sender_false_positive_count": counts["REJECTED"],
        "sender_avg_risk_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
    }


def get_chat_context(session: Session, chat_id: str, exclude_msg_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds chat/group risk profile from all processed messages in this chat.
    Tracks:
    - total messages in group
    - HIGH / MEDIUM counts split into analyst-confirmed vs. automatic
    - scam ratio (all non-rejected verdicts) and confirmed scam ratio (escalation basis)
    - number of distinct flagged senders
    """
    query = (
        session.query(MessageRecord)
        .filter(MessageRecord.chat_id == chat_id, MessageRecord.status == "PROCESSED")
    )
    if exclude_msg_id:
        query = query.filter(MessageRecord.id != exclude_msg_id)

    past_messages: List[MessageRecord] = query.all()

    counts = {k: 0 for k in ("CONFIRMED_HIGH", "AUTO_HIGH", "CONFIRMED_MEDIUM", "AUTO_MEDIUM", "REJECTED")}
    flagged_senders = set()
    for m in past_messages:
        cls = _classify(m)
        if cls in counts:
            counts[cls] += 1
        if cls in ("CONFIRMED_HIGH", "AUTO_HIGH"):
            flagged_senders.add(m.sender_hash)

    total = len(past_messages)
    high = counts["CONFIRMED_HIGH"] + counts["AUTO_HIGH"]
    medium = counts["CONFIRMED_MEDIUM"] + counts["AUTO_MEDIUM"]

    return {
        "chat_total_messages": total,
        "chat_high_risk_count": high,
        "chat_medium_risk_count": medium,
        "chat_confirmed_high_count": counts["CONFIRMED_HIGH"],
        "chat_auto_high_count": counts["AUTO_HIGH"],
        "chat_false_positive_count": counts["REJECTED"],
        "chat_scam_ratio": round((high + 0.5 * medium) / total, 2) if total else 0.0,
        "chat_confirmed_scam_ratio": round(counts["CONFIRMED_HIGH"] / total, 2) if total else 0.0,
        "chat_unique_flagged_senders": len(flagged_senders),
    }


def is_scam_hub(chat_ctx: Dict[str, Any]) -> bool:
    """Chat-level escalation requires a minimal sample AND multiple analyst-confirmed HIGH verdicts."""
    if chat_ctx["chat_total_messages"] < MIN_CHAT_SAMPLE:
        return False
    if chat_ctx["chat_confirmed_high_count"] < 2:
        return False
    return (
        chat_ctx["chat_confirmed_high_count"] >= HUB_CONFIRMED_MIN
        or chat_ctx["chat_confirmed_scam_ratio"] >= HUB_CONFIRMED_RATIO
    )


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
            f"- HIGH-риск, подтверждён аналитиком: {sender_ctx['sender_confirmed_high_count']}\n"
            f"- HIGH-риск, автоматическая оценка ИИ (НЕ проверена человеком): {sender_ctx['sender_auto_high_count']}\n"
            f"- MEDIUM-риск (всего): {sender_ctx['sender_medium_risk_count']}\n"
            f"- Признано аналитиком ложным срабатыванием: {sender_ctx['sender_false_positive_count']}\n"
            f"- Рассылает сообщения по {sender_ctx['sender_unique_chats']} разным чатам/группам\n"
            f"- Средний risk_score отправителя: {sender_ctx['sender_avg_risk_score']}"
        )
        if sender_ctx["sender_duplicate_count"] > 0:
            sender_line += f"\n- Отправил ТОЧНО ТАКОЕ ЖЕ сообщение уже {sender_ctx['sender_duplicate_count']} раз(а) ранее."
        parts.append(sender_line)

        if sender_ctx["sender_duplicate_rejected_count"] > 0:
            parts.append(
                "[i] Аналитик ранее признал идентичный текст этого отправителя ЛОЖНЫМ СРАБАТЫВАНИЕМ. "
                "Не повышай оценку из-за повторов; оценивай только содержание сообщения."
            )
        elif sender_ctx["sender_duplicate_count"] >= DUPLICATE_MIN:
            parts.append(
                "[!] ФАКТ: отправитель распространяет идентичный текст 3+ раз (признак массовой рассылки). "
                "Это НЕ доказательство мошенничества само по себе. Если в самом сообщении есть хотя бы один "
                "финансовый признак из списка кодов — повысь risk_score на +15..+25 и укажи в explanation "
                "серийную рассылку. Если текст нейтральный (объявление, новость) — не повышай."
            )

        if sender_ctx["sender_confirmed_high_count"] >= SENDER_CONFIRMED_MIN:
            parts.append(
                f"[!] ПОДТВЕРЖДЕНО АНАЛИТИКОМ: {sender_ctx['sender_confirmed_high_count']} сообщения этого отправителя "
                "проверены человеком и признаны мошенническими. Если текущее сообщение содержит финансовые "
                "признаки — повысь risk_score на +15 и укажи репутацию автора в explanation."
            )
        elif sender_ctx["sender_auto_high_count"] > 0:
            parts.append(
                "[i] Прошлые HIGH-оценки этого отправителя выставлены автоматически и НЕ проверены человеком. "
                "Не повышай risk_score только на их основании — оценивай текущее сообщение по его содержанию."
            )

        if sender_ctx["sender_unique_chats"] >= 3:
            parts.append(
                "[i] ФАКТ: отправитель публикует сообщения минимум в 3 разных чатах/группах (кросс-постинг)."
            )

    # 2. Chat / group risk profile
    if chat_ctx["chat_total_messages"] > 0:
        chat_line = (
            f"ИСТОРИЯ ГРУППЫ/ИСТОЧНИКА [{msg.chat_name} (id: {msg.chat_id})]:\n"
            f"- Всего обработано сообщений из этого чата: {chat_ctx['chat_total_messages']}\n"
            f"- HIGH-риск, подтверждён аналитиком: {chat_ctx['chat_confirmed_high_count']}\n"
            f"- HIGH-риск, автоматическая оценка ИИ (НЕ проверена человеком): {chat_ctx['chat_auto_high_count']}\n"
            f"- MEDIUM-риск (всего): {chat_ctx['chat_medium_risk_count']}\n"
            f"- Признано ложным срабатыванием: {chat_ctx['chat_false_positive_count']}\n"
            f"- Уникальных авторов с HIGH-оценкой: {chat_ctx['chat_unique_flagged_senders']}"
        )
        parts.append(chat_line)

        if is_scam_hub(chat_ctx):
            parts.append(
                "[!] ПОДТВЕРЖДЁННЫЙ СКАМ-ХАБ: аналитики подтвердили систематическое продвижение мошеннических схем "
                "в этом чате. Если сообщение содержит хотя бы один сомнительный финансовый признак, "
                "относи его к HIGH/MEDIUM риску (+10 к score). Нейтральные сообщения не повышай."
            )
        elif chat_ctx["chat_total_messages"] < MIN_CHAT_SAMPLE:
            parts.append(
                f"[i] Выборка по чату мала (< {MIN_CHAT_SAMPLE} сообщений) — статистику чата не используй для повышения оценки."
            )
        elif chat_ctx["chat_auto_high_count"] > 0:
            parts.append(
                "[i] HIGH-оценки в этом чате пока автоматические и не подтверждены человеком — "
                "не повышай risk_score на их основании."
            )

    if not parts:
        return ""

    return "\n\n========== КОНТЕКСТ ИЗ БАЗЫ ДАННЫХ ==========\n" + "\n\n".join(parts) + "\n=============================================="
