"""Privacy-conscious Telegram submission connector for Blue.

Private chats only. Ordinary messages are not persisted or analyzed. A user must
see the processing notice, explicitly agree, and submit each item with /analyze.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from .db.models import MessageRecord, TelegramConsentRecord, utc_now

logger = logging.getLogger("blue.telegram")
router = APIRouter(tags=["telegram"])
CONSENT_VERSION = "2026-10-25-v1"
NOTICE_VALIDITY = timedelta(hours=24)
MAX_SUBMISSION_CHARS = 10_000
COMMAND_RE = re.compile(r"^/([a-z_]+)(?:@[A-Za-z0-9_]+)?(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def sender_hash(user_id: int | str, secret: str) -> str:
    """Stable pseudonymous Telegram user ID; never persist the raw ID."""
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("TELEGRAM_HASH_SECRET must be configured.")
    payload = b"blue:telegram-user:" + str(user_id).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def is_user_allowed(user_id: int | str, configured_ids: str | None = None) -> bool:
    """Fail closed unless the user ID is explicitly listed for the MVP test bot."""
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "") if configured_ids is None else configured_ids
    allowed = {item.strip() for item in raw.split(",") if item.strip().isdigit()}
    return str(user_id).isdigit() and str(user_id) in allowed


def valid_webhook_secret(expected: str, received: str | None) -> bool:
    return bool(expected and received and hmac.compare_digest(expected, received))


def _iso_timestamp(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _message_text(message: Mapping[str, Any]) -> str:
    for key in ("text", "caption"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def parse_telegram_update(update: Mapping[str, Any]) -> dict[str, Any]:
    """Parse an update; arbitrary text is excluded unless /analyze is used."""
    if not isinstance(update, Mapping):
        return {"action": "ignore"}
    message = update.get("message")
    if not isinstance(message, Mapping):
        return {"action": "ignore"}

    chat = message.get("chat")
    user = message.get("from")
    if not isinstance(chat, Mapping) or chat.get("type") != "private":
        return {"action": "ignore"}
    if not isinstance(user, Mapping) or user.get("is_bot") is True or user.get("id") is None:
        return {"action": "ignore"}
    if chat.get("id") is None or message.get("message_id") is None:
        return {"action": "ignore"}

    raw_text = message.get("text")
    raw_text = raw_text if isinstance(raw_text, str) else ""
    match = COMMAND_RE.match(raw_text.strip())
    command = match.group(1).lower() if match else None
    tail = (match.group(2) or "").strip() if match else ""
    meta = {
        # Request-local only; persistent storage uses a keyed pseudonym.
        "user_id": str(user["id"]),
        "telegram_chat_id": str(chat["id"]),
        "telegram_message_id": str(message["message_id"]),
    }

    if command in {"start", "help", "privacy", "consent", "agree", "revoke", "stop", "delete_my_data"}:
        return {"action": command, **meta}
    if command == "analyze":
        replied = message.get("reply_to_message") if not tail else None
        source = replied if isinstance(replied, Mapping) else message
        # Do not mistake the literal command `/analyze` for user-submitted content.
        text = tail if tail else (_message_text(source) if isinstance(replied, Mapping) else "")
        if not text:
            return {"action": "analyze_missing", **meta}
        if len(text) > MAX_SUBMISSION_CHARS:
            return {"action": "too_long", **meta}
        source_message_id = source.get("message_id", message.get("message_id"))
        timestamp = _iso_timestamp(source.get("date")) or _iso_timestamp(message.get("date"))
        return {
            "action": "analyze",
            **meta,
            "source_message_id": str(source_message_id),
            "text": text,
            "timestamp": timestamp,
        }
    if not match:
        # Do not return raw ordinary message text.
        return {"action": "unsubmitted", **meta}
    return {"action": "unknown", **meta}


async def _telegram_api(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")
    # Telegram embeds the token in the URL. Never log URLs or HTTP exception bodies.
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError("Telegram Bot API returned a non-success response.")
    return data


async def _send_message(chat_id: str, text: str) -> bool:
    try:
        await _telegram_api("sendMessage", {"chat_id": chat_id, "text": text})
        return True
    except Exception as exc:
        logger.warning("Telegram sendMessage failed (%s).", type(exc).__name__)
        return False


def _hash_secret() -> str:
    return os.getenv("TELEGRAM_HASH_SECRET", "").strip()


def _consent_notice() -> str:
    return (
        "Уведомление о данных Blue\n\n"
        "Если вы явно отправите сообщение на анализ, Blue сохранит его текст и технические "
        "метаданные в своей базе максимум на 30 дней, передаст текст внешнему AI-сервису "
        "Google Gemini для анализа, "
        "а исходный текст и результат могут отображаться в dashboard Blue. В текущем MVP "
        "доступ к dashboard/API ещё может не быть ограничен учётными записями, поэтому до "
        "подтверждения защиты используйте только синтетические или обезличенные материалы и "
        "не отправляйте личные, платёжные или конфиденциальные сведения. "
        "Blue не сканирует ваши чаты автоматически. Для каждого материала нужно отдельно "
        "отправить /analyze. Данные, сохранённые в Blue, можно удалить командой /delete_my_data; "
        "будущую обработку можно остановить командой /revoke. Это удаляет записи Blue, но не "
        "удаляет сообщения из Telegram или копии, которые могли существовать у других участников.\n\n"
        "Если вы согласны с обработкой по этому описанию, отправьте /agree в течение 24 часов. "
        "Не передавайте чужие персональные или конфиденциальные сведения без надлежащего основания."
    )


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not SECRET_RE.fullmatch(expected):
        raise HTTPException(status_code=503, detail="Telegram webhook is not configured.")
    received = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not valid_webhook_secret(expected, received):
        raise HTTPException(status_code=403, detail="Invalid webhook secret.")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON.")
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="Expected an Update object.")

    parsed = parse_telegram_update(update)
    action = parsed["action"]
    if action == "ignore":
        return {"ok": True, "action": "ignored"}

    telegram_chat_id = parsed["telegram_chat_id"]
    if not is_user_allowed(parsed.get("user_id", "")):
        # Only echo the user's own ID for onboarding. Never persist or log it.
        await _send_message(
            telegram_chat_id,
            f"Blue сейчас доступен только тестовой команде. Ваш Telegram ID: {parsed.get('user_id', '')}. "
            "Передайте этот ID администратору проекта для добавления в список тестировщиков.",
        )
        return {"ok": True, "action": "not_allowlisted"}

    if action in {"start", "help"}:
        await _send_message(
            telegram_chat_id,
            "Blue помогает проверять признаки финансовых пирамид в добровольно отправленных материалах. "
            "Я не читаю ваши группы автоматически. Сначала отправьте /consent, прочитайте уведомление, "
            "затем /agree. Для анализа используйте /analyze текст или ответьте /analyze на пересланное "
            "текстовое сообщение. Команды: /revoke — остановить будущий анализ; "
            "/delete_my_data — удалить записи, отправленные в Blue.",
        )
        return {"ok": True, "action": action}

    secret = _hash_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Telegram processing is not configured.")
    identity = sender_hash(parsed["user_id"], secret)

    # Imported lazily to avoid a module-level cycle: api_server includes this router.
    from .api_server import SessionLocal, MessageCreateRequest, _ingest

    db: Session = SessionLocal()
    try:
        if action in {"consent", "privacy"}:
            row = db.get(TelegramConsentRecord, identity)
            if row is None:
                row = TelegramConsentRecord(
                    user_hash=identity,
                    consent_version=CONSENT_VERSION,
                    notice_shown_at=None,
                    consented_at=None,
                    revoked_at=None,
                )
                db.add(row)
            delivered = await _send_message(telegram_chat_id, _consent_notice())
            if delivered:
                row.notice_shown_at = utc_now()
                row.consent_version = CONSENT_VERSION
                db.commit()
            else:
                db.rollback()
            return {"ok": True, "action": "notice_sent" if delivered else "notice_delivery_failed"}

        if action == "agree":
            row = db.get(TelegramConsentRecord, identity)
            now = utc_now()
            notice_recent = (
                row is not None
                and row.notice_shown_at is not None
                and now - row.notice_shown_at <= NOTICE_VALIDITY
                and row.notice_shown_at <= now
            )
            if not notice_recent:
                await _send_message(
                    telegram_chat_id,
                    "Сначала отправьте /consent, прочитайте уведомление и затем отправьте /agree.",
                )
                return {"ok": True, "action": "notice_required"}
            row.consent_version = CONSENT_VERSION
            row.consented_at = now
            row.revoked_at = None
            db.commit()
            await _send_message(
                telegram_chat_id,
                "Согласие записано. Каждый материал анализируется только после отдельной команды "
                "/analyze. Отозвать согласие: /revoke. Удалить записи Blue: /delete_my_data.",
            )
            return {"ok": True, "action": "consent_recorded"}

        if action in {"revoke", "stop"}:
            row = db.get(TelegramConsentRecord, identity)
            if row is not None:
                row.revoked_at = utc_now()
                db.commit()
            await _send_message(
                telegram_chat_id,
                "Согласие отозвано. Новые сообщения не будут передаваться на анализ. "
                "Для удаления ранее отправленных записей Blue используйте /delete_my_data.",
            )
            return {"ok": True, "action": "consent_revoked"}

        if action == "delete_my_data":
            records = db.query(MessageRecord).filter(MessageRecord.sender_hash == identity).all()
            deleted_count = len(records)
            for record in records:
                db.delete(record)
            consent = db.get(TelegramConsentRecord, identity)
            if consent is not None:
                db.delete(consent)
            db.commit()
            await _send_message(
                telegram_chat_id,
                f"Удалены записи Blue, отправленные вами через Telegram: {deleted_count}. "
                "Это не удаляет сообщения из самого Telegram или копии у других участников.",
            )
            return {"ok": True, "action": "user_data_deleted", "deleted": deleted_count}

        if action == "unsubmitted":
            await _send_message(
                telegram_chat_id,
                "Сообщение не анализировалось и не было сохранено. Сначала /consent, затем /agree. "
                "Чтобы проанализировать конкретный материал, отправьте /analyze текст либо ответьте "
                "/analyze на пересланное текстовое сообщение.",
            )
            return {"ok": True, "action": "not_submitted"}

        if action == "analyze_missing":
            await _send_message(
                telegram_chat_id,
                "Текст не найден. MVP поддерживает текст и подписи. Ответьте /analyze на пересланное "
                "текстовое сообщение или отправьте /analyze текст.",
            )
            return {"ok": True, "action": "analyze_missing"}

        if action == "too_long":
            await _send_message(telegram_chat_id, "Превышен лимит 10 000 символов. Разделите материал.")
            return {"ok": True, "action": "too_long"}

        if action == "unknown":
            await _send_message(telegram_chat_id, "Неизвестная команда. Используйте /help.")
            return {"ok": True, "action": "unknown_command"}

        if action != "analyze":
            return {"ok": True, "action": "ignored"}

        consent = db.get(TelegramConsentRecord, identity)
        now = utc_now()
        if (
            consent is None
            or consent.consented_at is None
            or consent.revoked_at is not None
            or consent.consented_at > now
        ):
            await _send_message(
                telegram_chat_id,
                "Сначала выполните /consent, прочитайте уведомление и подтвердите через /agree. "
                "Это сообщение не передавалось на анализ.",
            )
            return {"ok": True, "action": "consent_required"}

        source_message_id = parsed["source_message_id"]
        safe_message_id = f"tg_{identity[:24]}_{source_message_id}"[:64]
        consent.updated_at = now
        db.commit()
        req = MessageCreateRequest(
            platform="telegram",
            chat_id=f"tg_{identity[:60]}",
            chat_name="Telegram voluntary submission",
            message_id=safe_message_id,
            sender_hash=identity,
            text=parsed["text"],
            timestamp=parsed.get("timestamp"),
        )
        record = _ingest(db, req)
        await _send_message(
            telegram_chat_id,
            f"Материал отправлен в Blue. Статус: {record.status}. "
            "Анализ выполняется в фоне; результат появится в dashboard.",
        )
        return {"ok": True, "action": "submitted", "status": record.status}
    finally:
        db.close()


async def _configure_webhook() -> None:
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    parsed = urlparse(webhook_url)
    if parsed.scheme != "https" or not parsed.netloc or not parsed.path.endswith("/webhooks/telegram"):
        raise SystemExit("TELEGRAM_WEBHOOK_URL must be a public HTTPS URL ending in /webhooks/telegram.")
    if not SECRET_RE.fullmatch(secret):
        raise SystemExit("TELEGRAM_WEBHOOK_SECRET must contain 1-256 URL-safe characters.")
    await _telegram_api(
        "setWebhook",
        {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message"],
            "drop_pending_updates": False,
        },
    )
    print("Telegram webhook configured.")


async def _show_webhook_info() -> None:
    data = await _telegram_api("getWebhookInfo", {})
    result = data.get("result", {}) if isinstance(data, dict) else {}
    print({
        "url_configured": bool(result.get("url")),
        "pending_update_count": result.get("pending_update_count"),
        "last_error_date": result.get("last_error_date"),
        "has_last_error": bool(result.get("last_error_message")),
    })


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if command == "set-webhook":
            asyncio.run(_configure_webhook())
        elif command == "webhook-info":
            asyncio.run(_show_webhook_info())
        else:
            raise SystemExit("Use: python -m ai_data.telegram_connector set-webhook|webhook-info")
    except SystemExit:
        raise
    except Exception as exc:
        # Do not print httpx exceptions: request URLs include the bot token.
        raise SystemExit(
            f"Telegram Bot API operation failed ({type(exc).__name__}); details suppressed to protect the bot token."
        ) from None
