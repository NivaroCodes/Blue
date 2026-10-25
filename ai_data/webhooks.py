"""Normalization helpers for Telegram and GREEN-API webhook payloads."""

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Optional


class WebhookPayloadError(ValueError):
    pass


def sender_hash(sender_id: Any, secret: str) -> str:
    if not secret:
        raise WebhookPayloadError("sender hash secret is not configured")
    if sender_id is None or str(sender_id) == "":
        raise WebhookPayloadError("sender id is missing")
    return hmac.new(secret.encode(), str(sender_id).encode(), hashlib.sha256).hexdigest()


def _timestamp(unix_time: Any) -> str:
    try:
        return datetime.fromtimestamp(int(unix_time), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise WebhookPayloadError("invalid event timestamp") from exc


def normalize_telegram_message(message: dict[str, Any], hash_secret: str) -> Optional[dict[str, Any]]:
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is None or message_id is None:
        raise WebhookPayloadError("Telegram message lacks chat or message id")
    if sender.get("is_bot"):
        return None

    photos = message.get("photo") or []
    caption = message.get("caption") or ""
    text = message.get("text") or caption
    if not text.strip() and not photos:
        return None

    username = chat.get("username")
    chat_url = f"https://t.me/{username}" if username else None
    return {
        "platform": "telegram",
        "chat_id": str(chat_id),
        "chat_name": str(chat.get("title") or chat.get("first_name") or chat_id),
        "chat_url": chat_url,
        "message_id": str(message_id),
        "sender_hash": sender_hash(sender.get("id", chat_id), hash_secret),
        "text": text,
        "timestamp": _timestamp(message.get("date")),
        "telegram_photo_file_id": photos[-1].get("file_id") if photos else None,
    }


def normalize_green_message(payload: dict[str, Any], hash_secret: str) -> Optional[dict[str, Any]]:
    if payload.get("typeWebhook") != "incomingMessageReceived":
        return None
    sender_data = payload.get("senderData") or {}
    message_data = payload.get("messageData") or {}
    type_message = message_data.get("typeMessage")
    if type_message not in {"textMessage", "imageMessage"}:
        return None

    file_data = message_data.get("fileMessageData") or {}
    text_data = message_data.get("textMessageData") or {}
    text = text_data.get("textMessage") or file_data.get("caption") or ""
    is_image = type_message == "imageMessage"
    if not text.strip() and not (is_image and payload.get("idMessage")):
        return None

    chat_id = sender_data.get("chatId")
    message_id = payload.get("idMessage")
    sender_id = sender_data.get("sender") or sender_data.get("senderId")
    if not chat_id or not message_id or not sender_id:
        raise WebhookPayloadError("GREEN-API event lacks required identifiers")

    return {
        "platform": "whatsapp",
        "chat_id": str(chat_id),
        "chat_name": str(sender_data.get("chatName") or chat_id),
        "chat_url": None,
        "message_id": str(message_id),
        "sender_hash": sender_hash(sender_id, hash_secret),
        "text": text,
        "timestamp": _timestamp(payload.get("timestamp")),
        "green_image_message_id": str(message_id) if is_image else None,
    }


def constant_time_token_match(header_value: Optional[str], expected_token: str) -> bool:
    if not expected_token or not header_value:
        return False
    supplied = header_value.strip()
    scheme, separator, token = supplied.partition(" ")
    if separator and scheme.lower() in {"bearer", "basic"}:
        supplied = token.strip()
    return hmac.compare_digest(supplied, expected_token)
