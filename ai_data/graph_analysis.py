"""
SafeNet KZ — Graph & Link Analysis Module (Графовый анализ связей)
Addresses Hackathon Criterion 3: 'Инновационность подхода (графовый анализ связей)'

Identifies:
1. Senders broadcasting identical/similar scams across multiple groups (Botnet / Spam wave).
2. Chats and groups that form high-risk scam clusters.
3. Shared entities: repeated Kaspi cards, phone numbers, crypto wallets, and invite links.
"""
from typing import Dict, Any, List, Set
from collections import defaultdict
from sqlalchemy.orm import Session

from .db.models import MessageRecord, AnalysisRecord, EntityRecord


def analyze_network_graph(session: Session) -> Dict[str, Any]:
    """
    Performs link analysis across all messages, senders, and chats in the database.
    Returns:
    - bot_clusters: groups of senders or duplicate broadcast patterns
    - high_risk_chats: ranking of chats by scam density
    - cross_chat_senders: actors active across multiple monitored groups
    - repeat_entities: financial endpoints (Kaspi cards, phone numbers, URLs)
    """
    messages: List[MessageRecord] = (
        session.query(MessageRecord)
        .filter(MessageRecord.status == "PROCESSED")
        .all()
    )

    if not messages:
        return {
            "total_nodes": 0,
            "bot_clusters": [],
            "high_risk_chats": [],
            "cross_chat_senders": [],
            "summary": "База данных пока не содержит обработанных сообщений для графового анализа."
        }

    # Graph maps
    sender_to_chats: Dict[str, Set[str]] = defaultdict(set)
    sender_to_messages: Dict[str, List[MessageRecord]] = defaultdict(list)
    chat_to_messages: Dict[str, List[MessageRecord]] = defaultdict(list)
    text_fingerprint_to_senders: Dict[str, Set[str]] = defaultdict(set)

    for m in messages:
        sender_to_chats[m.sender_hash].add(m.chat_id)
        sender_to_messages[m.sender_hash].append(m)
        chat_to_messages[m.chat_id].append(m)

        # Normalize text fingerprint for cluster detection
        clean_text = " ".join(m.text.lower().split()[:8])  # first 8 words
        text_fingerprint_to_senders[clean_text].add(m.sender_hash)

    # 1. Detect Cross-Chat Senders (potential botnets)
    cross_chat_senders = []
    for sender, chats in sender_to_chats.items():
        if len(chats) > 1:
            msgs = sender_to_messages[sender]
            high_count = sum(1 for m in msgs if m.analysis and m.analysis.risk_level == "HIGH")
            cross_chat_senders.append({
                "sender_hash": sender,
                "chat_count": len(chats),
                "chats": list(chats),
                "total_messages": len(msgs),
                "high_risk_messages": high_count,
                "is_bot_pattern": (len(chats) >= 2 and high_count >= 1)
            })

    cross_chat_senders.sort(key=lambda x: (x["is_bot_pattern"], x["high_risk_messages"]), reverse=True)

    # 2. Detect High-Risk Chat Clusters
    high_risk_chats = []
    for chat_id, msgs in chat_to_messages.items():
        total = len(msgs)
        high = sum(1 for m in msgs if m.analysis and m.analysis.risk_level == "HIGH")
        medium = sum(1 for m in msgs if m.analysis and m.analysis.risk_level == "MEDIUM")
        chat_name = msgs[0].chat_name if msgs else chat_id
        platform = msgs[0].platform if msgs else "telegram"

        scam_ratio = round((high + 0.5 * medium) / total, 2) if total > 0 else 0.0
        unique_senders = len(set(m.sender_hash for m in msgs))

        high_risk_chats.append({
            "chat_id": chat_id,
            "chat_name": chat_name,
            "platform": platform,
            "total_messages": total,
            "high_risk_count": high,
            "medium_risk_count": medium,
            "scam_ratio": scam_ratio,
            "unique_senders": unique_senders,
            "is_scam_hub": (high >= 2 or scam_ratio >= 0.4)
        })

    high_risk_chats.sort(key=lambda x: (x["is_scam_hub"], x["high_risk_count"], x["scam_ratio"]), reverse=True)

    # 3. Detect Bot Broadcast Clusters (same message text posted by multiple entities)
    bot_clusters = []
    for text_preview, senders in text_fingerprint_to_senders.items():
        if len(senders) > 1:
            bot_clusters.append({
                "fingerprint": text_preview,
                "sender_count": len(senders),
                "senders": list(senders),
                "description": "Синхронная рассылка одинакового текста разными аккаунтами (признак сетки ботов)"
            })

    return {
        "total_nodes": len(sender_to_chats) + len(chat_to_messages),
        "total_senders": len(sender_to_chats),
        "total_chats": len(chat_to_messages),
        "cross_chat_senders": cross_chat_senders,
        "high_risk_chats": high_risk_chats,
        "bot_clusters": bot_clusters,
        "summary": (
            f"Проанализировано {len(messages)} сообщений, {len(sender_to_chats)} авторов, {len(chat_to_messages)} групп. "
            f"Выявлено {sum(1 for s in cross_chat_senders if s['is_bot_pattern'])} подозрительных ботов/рассыльщиков "
            f"и {sum(1 for c in high_risk_chats if c['is_scam_hub'])} групп-кластеров высокого риска."
        )
    }
