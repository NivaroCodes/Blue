import base64
import os

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from ai_data import api_server
from ai_data import media
from ai_data.db.models import MessageRecord, init_db


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "telegram-test-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1003991179350")
    monkeypatch.setenv("GREEN_API_WEBHOOK_TOKEN", "green-test-secret")
    monkeypatch.setenv("GREEN_API_ALLOWED_CHAT_ID", "12025550123@g.us")
    monkeypatch.setenv("SENDER_HASH_SECRET", "test-hash-secret")
    factory = init_db("sqlite:///:memory:")

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    api_server.app.dependency_overrides[api_server.get_db] = override_get_db
    monkeypatch.setattr(api_server, "_process_webhook_message", lambda _message_id: None)
    with TestClient(api_server.app) as client:
        yield client, factory
    api_server.app.dependency_overrides.clear()


def test_telegram_webhook_stores_only_allowlisted_chat(webhook_client, monkeypatch):
    client, factory = webhook_client
    monkeypatch.delenv("SENDER_HASH_SECRET")
    monkeypatch.setenv("TELEGRAM_HASH_SECRET", "test-hash-secret")
    update = {
        "update_id": 1,
        "message": {
            "message_id": 31,
            "date": 1792911600,
            "chat": {"id": -1003991179350, "title": "Blue test group", "type": "supergroup"},
            "from": {"id": 77, "first_name": "Tester", "is_bot": False},
            "text": "Вложи 5000 и получи 10000 завтра",
        },
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": "telegram-test-secret"}

    response = client.post("/webhooks/telegram", json=update, headers=headers)
    assert response.status_code == 200
    with factory() as db:
        row = db.query(MessageRecord).filter_by(platform="telegram", message_id="31").one()
        assert row.chat_id == "-1003991179350"
        assert row.chat_name == "Blue test group"
        assert row.sender_hash != "77"
        assert row.text == update["message"]["text"]

    update["message"]["chat"]["id"] = -1000000000000
    assert client.post("/webhooks/telegram", json=update, headers=headers).status_code == 204

    update["message"]["chat"]["id"] = -1003991179350
    update["message"]["chat"]["type"] = "private"
    assert client.post("/webhooks/telegram", json=update, headers=headers).status_code == 204


def test_green_api_webhook_is_deduplicated_and_checks_token(webhook_client):
    client, factory = webhook_client
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "idMessage": "green-msg-1",
        "timestamp": 1792911600,
        "senderData": {
            "chatId": "12025550123@g.us",
            "sender": "12025550000@c.us",
            "chatName": "Allowed WhatsApp group",
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {"textMessage": "Sample incoming text"},
        },
    }
    assert client.post("/webhooks/green-api", json=payload).status_code == 401
    headers = {"Authorization": "Bearer green-test-secret"}
    assert client.post("/webhooks/green-api", json=payload, headers=headers).status_code == 200
    assert client.post("/webhooks/green-api", json=payload, headers=headers).status_code == 200
    with factory() as db:
        rows = db.query(MessageRecord).filter_by(platform="whatsapp", message_id="green-msg-1").all()
        assert len(rows) == 1


def test_green_api_ignores_nonincoming_events(webhook_client):
    client, _factory = webhook_client
    payload = {"typeWebhook": "outgoingMessageReceived"}
    response = client.post(
        "/webhooks/green-api",
        json=payload,
        headers={"Authorization": "green-test-secret"},
    )
    assert response.status_code == 204


def test_green_api_ingests_link_messages(webhook_client):
    client, factory = webhook_client
    response = client.post(
        "/webhooks/green-api",
        json={
            "typeWebhook": "incomingMessageReceived",
            "idMessage": "green-link-1",
            "timestamp": 1792911600,
            "senderData": {
                "chatId": "12025550123@g.us", "sender": "12025550000@c.us", "chatName": "Allowed group",
            },
            "messageData": {
                "typeMessage": "extendedTextMessage",
                "extendedTextMessageData": {"text": "https://example.com/invite"},
            },
        },
        headers={"Authorization": "Bearer green-test-secret"},
    )
    assert response.status_code == 200
    with factory() as db:
        row = db.query(MessageRecord).filter_by(platform="whatsapp", message_id="green-link-1").one()
        assert row.text == "https://example.com/invite"


def test_dashboard_routes_require_auth_in_production_and_accept_server_token(webhook_client, monkeypatch):
    client, _factory = webhook_client
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.setenv("INGEST_API_TOKEN", "test-dashboard-token")

    assert client.get("/api/stats").status_code == 401
    response = client.get("/api/stats", headers={"Authorization": "Bearer test-dashboard-token"})
    assert response.status_code == 200


def test_manual_ingestion_requires_server_bearer(webhook_client, monkeypatch):
    client, _factory = webhook_client
    monkeypatch.setenv("INGEST_API_TOKEN", "test-ingest-token")
    payload = {
        "platform": "telegram", "chat_id": "demo", "chat_name": "Synthetic demo",
        "message_id": "synthetic-1", "sender_hash": "demo-sender", "text": "[SYNTHETIC] test",
    }
    assert client.post("/api/messages", json=payload).status_code == 401
    assert client.post("/api/messages", json=payload, headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.post("/api/messages", json=payload, headers={"Authorization": "Bearer test-ingest-token"})
    assert response.status_code == 200
    assert client.post("/api/analyze-image", json={"image_base64": "invalid"}).status_code == 401


def test_telegram_photo_uses_shared_r2_for_ingest_worker_and_private_preview(webhook_client, monkeypatch):
    client, factory = webhook_client
    image = b"\x89PNG\r\n\x1a\n" + b"test-image"
    objects = {}

    class Body:
        def read(self, size):
            return self.data[:size]

        def close(self):
            pass

    class FakeS3:
        def put_object(self, *, Bucket, Key, Body, ContentType):
            objects[(Bucket, Key)] = (Body, ContentType)

        def get_object(self, *, Bucket, Key):
            body = Body()
            body.data = objects[(Bucket, Key)][0]
            return {"Body": body}

    monkeypatch.setenv("MEDIA_STORAGE", "r2")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-key-secret")
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.setenv("INGEST_API_TOKEN", "test-dashboard-token")
    monkeypatch.setattr(media.boto3, "client", lambda *_args, **_kwargs: FakeS3())

    async def fake_download(_file_id):
        return base64.b64encode(image).decode("ascii")

    monkeypatch.setattr(api_server, "_telegram_image_base64", fake_download)
    response = client.post("/webhooks/telegram", json={
        "message": {
            "message_id": 32,
            "date": 1792911600,
            "chat": {"id": -1003991179350, "title": "Blue test group", "type": "supergroup"},
            "from": {"id": 77, "is_bot": False},
            "caption": "Фото с рекламой",
            "photo": [{"file_id": "tg-photo-32"}],
        },
    }, headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-test-secret"})
    assert response.status_code == 200
    with factory() as db:
        row = db.query(MessageRecord).filter_by(platform="telegram", message_id="32").one()
        assert row.text == "Фото с рекламой"
        assert row.image_url.startswith("/api/media/")
        assert media.load_image(row.image_url) == (base64.b64encode(image).decode("ascii"), "image/png")
        assert ("test-bucket", f"media/{row.image_url.rsplit('/', 1)[-1]}") in objects
        image_url = row.image_url

    assert client.get(image_url).status_code == 401
    preview = client.get(image_url, headers={"Authorization": "Bearer test-dashboard-token"})
    assert preview.status_code == 200
    assert preview.content == image
    assert preview.headers["content-type"] == "image/png"


def test_r2_failure_returns_retryable_webhook_error(webhook_client, monkeypatch):
    client, factory = webhook_client
    monkeypatch.setenv("MEDIA_STORAGE", "r2")
    monkeypatch.delenv("R2_BUCKET_NAME", raising=False)

    async def fake_download(_file_id):
        return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"test").decode("ascii")

    monkeypatch.setattr(api_server, "_telegram_image_base64", fake_download)
    response = client.post("/webhooks/telegram", json={
        "message": {
            "message_id": 33,
            "date": 1792911600,
            "chat": {"id": -1003991179350, "type": "supergroup"},
            "from": {"id": 77, "is_bot": False},
            "caption": "Фото",
            "photo": [{"file_id": "tg-photo-33"}],
        },
    }, headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-test-secret"})
    assert response.status_code == 503
    with factory() as db:
        assert db.query(MessageRecord).filter_by(platform="telegram", message_id="33").count() == 0


@pytest.mark.asyncio
async def test_provider_media_download_rejects_untrusted_urls_before_network_io():
    class NoNetworkClient:
        def stream(self, *_args, **_kwargs):
            raise AssertionError("network should not be used for a rejected URL")

    with pytest.raises(HTTPException) as http_error:
        await api_server._download_bounded(
            NoNetworkClient(),
            "http://127.0.0.1/latest/meta-data",
            allowed_hosts=("green-api.com",),
        )
    assert http_error.value.status_code == 502

    with pytest.raises(HTTPException) as http_error:
        await api_server._download_bounded(
            NoNetworkClient(),
            "https://attacker.example/image.jpg",
            allowed_hosts=("green-api.com",),
        )
    assert http_error.value.status_code == 502
