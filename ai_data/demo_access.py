"""Narrow, explicit provenance check for the public read-only demo account."""

import re

from .db.models import MessageRecord, make_message_pk

DEMO_CHAT_ID = "blue_demo_synthetic_v1"
DEMO_TEXT_PREFIX = "[SYNTHETIC / ВЫМЫШЛЕННЫЕ ДАННЫЕ] "


def is_demo_record(message: MessageRecord) -> bool:
    match = re.fullmatch(r"synthetic-v1-(\d{3})", message.message_id or "")
    return bool(
        match
        and 1 <= int(match.group(1)) <= 36
        and message.platform == "telegram"
        and message.chat_id == DEMO_CHAT_ID
        and message.id == make_message_pk("telegram", DEMO_CHAT_ID, message.message_id)
        and (message.text or "").startswith(DEMO_TEXT_PREFIX)
        and (message.sender_hash or "").startswith("synthetic-person-")
    )
