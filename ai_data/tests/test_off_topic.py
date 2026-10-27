"""Reversible queue visibility using isolated, synthetic PostgreSQL records."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from ai_data.tests.test_db_helper import get_clean_test_session, get_test_session_factory
from ai_data.db.models import AnalysisRecord, MessageRecord, ReviewRecord
from ai_data import api_server as api


@pytest.fixture
def client(monkeypatch):
    with get_clean_test_session():
        pass
    factory = get_test_session_factory()
    monkeypatch.setenv("PRODUCTION", "1")
    monkeypatch.setenv("INGEST_API_TOKEN", "synthetic-analyst-token")

    def override_db():
        with factory() as session:
            yield session

    api.app.dependency_overrides[api.get_db] = override_db
    with TestClient(api.app) as http:
        yield http, factory
    api.app.dependency_overrides.clear()


def add_message(factory, suffix: str, text: str, score: int = 0, review: bool = False):
    with factory() as db:
        message = MessageRecord(
            id=f"synthetic-{suffix}", platform="telegram", chat_id="synthetic-chat",
            chat_name="Synthetic source", message_id=suffix, sender_hash="synthetic-sender",
            text=text, timestamp=datetime.now(timezone.utc), status="PROCESSED",
        )
        analysis = AnalysisRecord(
            id=f"analysis-synthetic-{suffix}", message_id=message.id, risk_score=score,
            risk_level="HIGH" if score >= 60 else "LOW", reasons_json="[]",
            explanation="Synthetic analysis retained", confidence=0.8, model_version="test-double",
        )
        db.add_all([message, analysis])
        if review:
            db.add(ReviewRecord(
                id=f"review-synthetic-{suffix}", analysis_id=analysis.id,
                review_status="REVIEWED", reviewer_note="Synthetic review retained",
                reviewed_by="synthetic-analyst",
            ))
        db.commit()
    return f"alert_synthetic-{suffix}"


def test_hide_and_restore_preserves_analysis_review_and_totals(client):
    http, factory = client
    target = add_message(factory, "limits-exclamation", "ЛИМИТЫ ЖЕ", review=True)
    other = add_message(factory, "financial-limits", "Лимиты переводов для вложений требуют проверки", score=80)
    auth = {"Authorization": "Bearer synthetic-analyst-token"}

    assert http.post(f"/api/alerts/{target}/visibility", json={"off_topic": True}).status_code == 401
    before = http.get("/api/stats", headers=auth).json()
    hidden = http.post(f"/api/alerts/{target}/visibility", json={"off_topic": True}, headers=auth)
    assert hidden.status_code == 200
    assert hidden.json()["status"] == "OFF_TOPIC"
    assert hidden.json()["risk_score"] == 0
    assert hidden.json()["explanation"] == "Synthetic analysis retained"
    assert hidden.json()["review_status"] == "REVIEWED"
    assert hidden.json()["reviewer_note"] == "Synthetic review retained"
    assert {a["id"] for a in http.get("/api/alerts", headers=auth).json()} == {other}
    assert {a["id"] for a in http.get("/api/alerts?visibility=off_topic", headers=auth).json()} == {target}
    assert len(http.get("/api/alerts?visibility=all", headers=auth).json()) == 2
    assert http.get(f"/api/alerts/{target}", headers=auth).json()["text"] == "ЛИМИТЫ ЖЕ"
    after = http.get("/api/stats", headers=auth).json()
    assert after["total_messages"] == before["total_messages"] == 2
    assert after["off_topic"] == 1 and after["errors"] == before["errors"] == 0
    with factory() as db:
        row = db.get(MessageRecord, "synthetic-limits-exclamation")
        assert row and row.analysis.risk_score == 0
        assert row.analysis.review.review_status == "REVIEWED"

    restored = http.post(f"/api/alerts/{target}/visibility", json={"off_topic": False}, headers=auth)
    assert restored.status_code == 200 and restored.json()["status"] == "PROCESSED"
    assert len(http.get("/api/alerts", headers=auth).json()) == 2
    assert http.get("/api/stats", headers=auth).json()["off_topic"] == 0


def test_only_explicit_records_are_hidden(client):
    http, factory = client
    exact = [
        add_message(factory, "one", "БЛЯЯЯЯТЬЯ"),
        add_message(factory, "two", "ок"),
        add_message(factory, "three", "заново"),
        add_message(factory, "four", "ЛИМИТЫ ЖЕ"),
    ]
    relevant = [
        add_message(factory, "five", "Лимиты переводов и вложений нужно проверить", score=0),
        add_message(factory, "six", "Бля, вложи 5000 тг и приведи друзей", score=85),
    ]
    auth = {"Authorization": "Bearer synthetic-analyst-token"}
    for target in exact:
        assert http.post(f"/api/alerts/{target}/visibility", json={"off_topic": True}, headers=auth).status_code == 200
    assert {a["id"] for a in http.get("/api/alerts", headers=auth).json()} == set(relevant)
    assert {a["id"] for a in http.get("/api/alerts?visibility=off_topic", headers=auth).json()} == set(exact)
    stats = http.get("/api/stats", headers=auth).json()
    assert stats["total_messages"] == 6 and stats["off_topic"] == 4
    assert stats["by_level"] == {"HIGH": 1, "MEDIUM": 0, "LOW": 1}


def test_unanalyzed_message_cannot_be_hidden(client):
    http, factory = client
    with factory() as db:
        db.add(MessageRecord(
            id="synthetic-pending", platform="telegram", chat_id="synthetic-chat",
            chat_name="Synthetic source", message_id="pending", sender_hash="synthetic-sender",
            text="Synthetic pending message", timestamp=datetime.now(timezone.utc), status="PENDING",
        ))
        db.commit()
    response = http.post(
        "/api/alerts/alert_synthetic-pending/visibility",
        json={"off_topic": True}, headers={"Authorization": "Bearer synthetic-analyst-token"},
    )
    assert response.status_code == 409
    with factory() as db:
        assert db.get(MessageRecord, "synthetic-pending").status == "PENDING"
