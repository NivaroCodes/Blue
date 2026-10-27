"""Server-side data scope and text masking for the public read-only account."""

import re
from typing import Any

from .db.models import MessageRecord

DEMO_CHAT_ID = "blue_demo_synthetic_v1"
PUBLIC_REDACTION = re.compile(
    r"(?iu)(?<![а-яёa-z])(?:бля\w*|пизд\w*|ху[йеяюи]\w*|ёб\w*|еб[а-яё]\w*|сук[аиу]\w*|fuck\w*|shit\w*)(?![а-яёa-z])"
)


def is_public_working_record(message: MessageRecord) -> bool:
    """Keep the public view on working messages that belong in the main queue."""
    return message.chat_id != DEMO_CHAT_ID and message.status != "OFF_TOPIC"


def redact_public_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Mask offensive words in API output without changing stored evidence."""
    result = alert.copy()
    for field in ("text", "chat_name", "explanation", "image_text", "reviewer_note", "reviewed_by", "error"):
        if isinstance(result.get(field), str):
            result[field] = PUBLIC_REDACTION.sub("***", result[field])
    result["reasons"] = [
        {
            **reason,
            "evidence": PUBLIC_REDACTION.sub("***", reason["evidence"])
            if isinstance(reason.get("evidence"), str) else reason.get("evidence"),
        }
        for reason in alert.get("reasons", [])
    ]
    return result
