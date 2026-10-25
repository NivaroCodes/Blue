from ai_data.telegram_connector import (
    is_user_allowed,
    parse_telegram_update,
    sender_hash,
    valid_webhook_secret,
)


def update(message, update_id=1):
    return {"update_id": update_id, "message": message}


def private_message(text, message_id=10, date=1792911600, reply=None):
    message = {
        "message_id": message_id,
        "date": date,
        "chat": {"id": 123456, "type": "private"},
        "from": {"id": 654321, "is_bot": False, "first_name": "Demo"},
        "text": text,
    }
    if reply is not None:
        message["reply_to_message"] = reply
    return message


def test_ordinary_private_message_is_not_returned_for_processing():
    parsed = parse_telegram_update(update(private_message("Проверь эту инвестицию")))
    assert parsed["action"] == "unsubmitted"
    assert "text" not in parsed


def test_analyze_command_text_is_explicit_submission():
    parsed = parse_telegram_update(update(private_message("/analyze Гарантируем 20% прибыли каждую неделю")))
    assert parsed["action"] == "analyze"
    assert parsed["text"] == "Гарантируем 20% прибыли каждую неделю"
    assert parsed["source_message_id"] == "10"
    assert parsed["timestamp"].endswith("+00:00")


def test_analyze_reply_extracts_replied_message_not_command():
    replied = {
        "message_id": 7,
        "date": 1792911500,
        "text": "Вложи 50000, получай гарантированную прибыль",
    }
    parsed = parse_telegram_update(update(private_message("/analyze", reply=replied)))
    assert parsed["action"] == "analyze"
    assert parsed["text"] == replied["text"]
    assert parsed["source_message_id"] == "7"


def test_analyze_can_use_caption():
    replied = {"message_id": 8, "date": 1792911500, "caption": "Доход 15% каждую неделю"}
    parsed = parse_telegram_update(update(private_message("/analyze", reply=replied)))
    assert parsed["action"] == "analyze"
    assert parsed["text"] == replied["caption"]


def test_group_updates_are_ignored():
    message = private_message("/analyze текст")
    message["chat"] = {"id": -100123, "type": "supergroup"}
    assert parse_telegram_update(update(message)) == {"action": "ignore"}


def test_channel_updates_and_service_updates_are_ignored():
    assert parse_telegram_update({"update_id": 1, "channel_post": {"text": "text"}})["action"] == "ignore"
    assert parse_telegram_update({"update_id": 2, "message": {"text": "x"}})["action"] == "ignore"


def test_empty_analyze_reply_requires_text():
    assert parse_telegram_update(update(private_message("/analyze")))["action"] == "analyze_missing"


def test_oversized_submission_is_rejected_without_returning_text():
    parsed = parse_telegram_update(update(private_message("/analyze " + ("x" * 10_001))))
    assert parsed["action"] == "too_long"
    assert "text" not in parsed


def test_supported_commands_are_detected():
    commands = [
        ("/start", "start"), ("/help", "help"), ("/consent", "consent"),
        ("/agree", "agree"), ("/revoke", "revoke"), ("/stop", "stop"),
        ("/delete_my_data", "delete_my_data"),
    ]
    for command, expected in commands:
        assert parse_telegram_update(update(private_message(command)))["action"] == expected


def test_sender_hash_is_stable_and_secret_scoped():
    first = sender_hash(123, "secret-a")
    assert first == sender_hash("123", "secret-a")
    assert first != sender_hash(123, "secret-b")
    assert len(first) == 64


def test_sender_hash_requires_secret():
    try:
        sender_hash(123, "")
        assert False, "Expected missing secret to be rejected"
    except ValueError:
        pass


def test_telegram_allowlist_allows_only_configured_numeric_ids():
    assert is_user_allowed(123, "123, 456")
    assert is_user_allowed(456, "123, 456")
    assert not is_user_allowed(789, "123, 456")
    assert not is_user_allowed(123, "")
    assert not is_user_allowed(123, None)
    assert not is_user_allowed("abc", "abc, 123")


def test_telegram_allowlist_fails_closed_when_env_empty():
    import os
    from unittest.mock import patch
    with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USER_IDS": ""}):
        assert not is_user_allowed(123)
        assert not is_user_allowed(456)
    with patch.dict(os.environ, {}, clear=True):
        assert not is_user_allowed(123)


def test_webhook_secret_validation():
    assert valid_webhook_secret("secret_123", "secret_123")
    assert not valid_webhook_secret("secret_123", "wrong")
    assert not valid_webhook_secret("secret_123", None)
    assert not valid_webhook_secret("", "secret_123")


def test_analyze_command_preserves_multiline_text():
    submitted = "/analyze Первая строка\nВторая строка"
    parsed = parse_telegram_update(update(private_message(submitted)))
    assert parsed["action"] == "analyze"
    assert parsed["text"] == "Первая строка\nВторая строка"
