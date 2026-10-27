"""A public Auth user can only read canonical synthetic seed records."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from ai_data import api_server as api, auth
from ai_data.db.models import AnalysisRecord, MessageRecord, make_message_pk
from ai_data.tests.test_db_helper import get_clean_test_session, get_test_session_factory


@pytest.fixture
def client(monkeypatch):
    with get_clean_test_session():
        pass
    factory = get_test_session_factory()
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.setenv("INGEST_API_TOKEN", "synthetic-service-token")
    monkeypatch.setattr(auth, "verify_dashboard_token", lambda token: {
        "sub": auth.PUBLIC_DEMO_USER_ID if token == "demo" else "synthetic-analyst-id",
        "role": "authenticated", "email": "info@gmail.com" if token == "demo" else "analyst@example.invalid",
    })

    def override_db():
        with factory() as session:
            yield session

    api.app.dependency_overrides[api.get_db] = override_db
    with TestClient(api.app) as http:
        yield http, factory
    api.app.dependency_overrides.clear()


def add_message(factory, *, chat_id, message_id, text, sender_hash):
    pk = make_message_pk("telegram", chat_id, message_id)
    with factory() as db:
        db.add(MessageRecord(
            id=pk, platform="telegram", chat_id=chat_id, chat_name="Synthetic fixture",
            message_id=message_id, sender_hash=sender_hash, text=text,
            timestamp=datetime.now(timezone.utc), status="PROCESSED",
            image_url=f"/api/media/{pk}.png",
        ))
        db.add(AnalysisRecord(
            id=f"analysis-{pk}", message_id=pk, risk_score=65, risk_level="HIGH",
            reasons_json="[]", explanation="Synthetic fixture analysis", confidence=0.8,
            model_version="test-double",
        ))
        db.commit()
    return f"alert_{pk}"


def test_demo_is_read_only_and_cannot_see_live_or_spoofed_rows(client):
    http, factory = client
    synthetic = add_message(
        factory, chat_id="blue_demo_synthetic_v1", message_id="synthetic-v1-001",
        text="[SYNTHETIC / ВЫМЫШЛЕННЫЕ ДАННЫЕ] Вымышленный пример",
        sender_hash="synthetic-person-01",
    )
    live = add_message(
        factory, chat_id="real-chat", message_id="real-1", text="Private working message",
        sender_hash="private-sender",
    )
    spoof = add_message(
        factory, chat_id="other-chat", message_id="synthetic-v1-002",
        text="[SYNTHETIC / ВЫМЫШЛЕННЫЕ ДАННЫЕ] Wrong source",
        sender_hash="synthetic-person-02",
    )
    demo = {"Authorization": "Bearer demo"}
    staff = {"Authorization": "Bearer staff"}

    assert http.get("/api/alerts?visibility=all").status_code == 401
    assert {row["id"] for row in http.get("/api/alerts?visibility=all", headers=demo).json()} == {synthetic}
    assert len(http.get("/api/alerts?visibility=all", headers=staff).json()) == 3
    assert http.get(f"/api/alerts/{synthetic}", headers=demo).status_code == 200
    assert http.get(f"/api/alerts/{live}", headers=demo).status_code == 404
    assert http.get(f"/api/alerts/{spoof}", headers=demo).status_code == 404
    assert http.get("/api/stats", headers=demo).json()["total_messages"] == 1
    assert len(http.get("/api/export", headers=demo).json()) == 1
    assert http.get("/api/network-graph", headers=demo).status_code == 403
    assert http.get(f"/api/media/{live.removeprefix('alert_')}.png", headers=demo).status_code == 404

    assert http.post(f"/api/alerts/{synthetic}/review", headers=demo, json={"review_status": "REVIEWED"}).status_code == 403
    assert http.post(f"/api/alerts/{live}/review", headers=demo, json={"review_status": "REVIEWED"}).status_code == 403
    assert http.post(f"/api/alerts/{synthetic}/visibility", headers=demo, json={"off_topic": True}).status_code == 403
    assert http.post("/api/messages", headers=demo, json={
        "chat_id": "public", "message_id": "new", "sender_hash": "demo", "text": "Synthetic",
    }).status_code == 401
    with factory() as db:
        assert db.get(MessageRecord, synthetic.removeprefix("alert_")).status == "PROCESSED"
        assert db.get(MessageRecord, live.removeprefix("alert_")).status == "PROCESSED"


def test_demo_identity_matches_verified_id_or_email_without_affecting_service_role():
    assert auth.is_public_demo_user({"sub": auth.PUBLIC_DEMO_USER_ID, "role": "authenticated"})
    assert auth.is_public_demo_user({"sub": "other", "email": "INFO@gmail.com", "role": "authenticated"})
    assert not auth.is_public_demo_user({"sub": "other", "email": "analyst@example.invalid", "role": "authenticated"})
    assert not auth.is_public_demo_user({"sub": auth.PUBLIC_DEMO_USER_ID, "role": "service_role"})
