"""
SafeNet KZ — PostgreSQL E2E Verification Scenario with Mocked AI Model
Tests:
1. Ingest test message via POST /api/messages.
2. Verify status is PENDING.
3. Run worker to claim and process message.
4. Verify analysis result is stored in DB.
5. Retrieve results via GET /api/alerts.
6. Retrieve details via GET /api/alerts/{id}.
7. Update analyst review status via POST /api/alerts/{id}/review.
8. Reload data and verify review changes persisted.
"""
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_data.tests.test_db_helper import assert_is_test_database, clean_test_database

POSTGRES_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/safenet_test"
assert_is_test_database(POSTGRES_URL)

os.environ["DATABASE_URL"] = POSTGRES_URL
os.environ["INLINE_ANALYSIS"] = "0"

from ai_data.db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord
import ai_data.api_server as api_server
from ai_data.worker import process_pending_messages
from ai_data.models import AnalysisResult, ReasonItem, RiskLevelEnum


def run_e2e_verification():
    print("=" * 60)
    print("STARTING POSTGRESQL E2E VERIFICATION (WITH MOCKED AI MODEL)")
    print("=" * 60)

    # 0. Connect and clean test DB via unified protective cleanup
    print(f"Connecting to Database: {POSTGRES_URL}")
    Session = init_db(POSTGRES_URL)
    session = Session()
    clean_test_database(session, POSTGRES_URL)
    session.close()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    api_server.app.dependency_overrides[api_server.get_db] = override_get_db
    client = TestClient(api_server.app)

    # Step 1: Ingest test message
    print("\n[Step 1] Ingesting message via POST /api/messages ...")
    ingest_payload = {
        "platform": "telegram",
        "chat_id": "tg_e2e_channel",
        "chat_name": "Казахстан Инвест Клуб",
        "chat_url": "https://t.me/invest_kz_club",
        "message_id": "e2e_msg_999",
        "sender_hash": "sender_e2e_investor",
        "text": "Вложи 10 000 тг прямо сейчас — гарантируем 20 000 тг через 24 часа на Kaspi!",
        "timestamp": "2026-10-23T14:00:00+05:00",
    }
    ingest_resp = client.post("/api/messages", json=ingest_payload)
    print(f"Response ({ingest_resp.status_code}): {ingest_resp.json()}")
    assert ingest_resp.status_code == 200, f"Expected 200, got {ingest_resp.status_code}"
    ingest_data = ingest_resp.json()
    alert_id = ingest_data["id"]

    # Step 2: Verify status is PENDING
    print("\n[Step 2] Verifying initial status is PENDING ...")
    assert ingest_data["status"] == "PENDING", f"Expected PENDING, got {ingest_data['status']}"
    s = Session()
    db_rec = s.query(MessageRecord).filter(MessageRecord.message_id == "e2e_msg_999").first()
    assert db_rec is not None, "Message record not found in PostgreSQL"
    assert db_rec.status == "PENDING", f"DB record status is {db_rec.status}"
    assert db_rec.analysis is None, "Analysis should be None while in PENDING"
    print("Confirmed: Message successfully stored in PostgreSQL with status PENDING.")
    s.close()

    # Step 3: Run worker to process message
    print("\n[Step 3] Running Background Worker to claim and analyze message ...")
    mock_ai_result = AnalysisResult(
        risk_score=95,
        risk_level=RiskLevelEnum.HIGH,
        reasons=[
            ReasonItem(code="UNREALISTIC_RETURN", evidence="20 000 тг через 24 часа"),
            ReasonItem(code="GUARANTEED_PROFIT", evidence="гарантируем"),
            ReasonItem(code="MONEY_REQUEST", evidence="Вложи 10 000 тг"),
            ReasonItem(code="PERSONAL_TRANSFER", evidence="на Kaspi"),
        ],
        explanation="Классическая схема финансовой пирамиды с нереалистичной доходностью (100% за сутки) и гарантией прибыли.",
        confidence=0.98,
        model_version="gemini-3-flash-preview",
    )

    with patch("ai_data.analyzer.call_gemini_api", return_value=mock_ai_result):
        w_session = Session()
        processed = process_pending_messages(w_session, limit=5, api_key="test_api_key", throttle_seconds=0)
        w_session.close()

    print(f"Worker finished: processed {processed} messages.")
    assert processed == 1, f"Expected 1 processed message, got {processed}"

    # Step 4: Verify DB state
    print("\n[Step 4] Verifying analysis results persisted in PostgreSQL ...")
    s = Session()
    db_rec = s.query(MessageRecord).filter(MessageRecord.message_id == "e2e_msg_999").first()
    assert db_rec.status == "PROCESSED", f"Expected status PROCESSED, got {db_rec.status}"
    assert db_rec.analysis is not None, "AnalysisRecord missing in DB"
    assert db_rec.analysis.risk_score == 95, f"Expected score 95, got {db_rec.analysis.risk_score}"
    assert db_rec.analysis.risk_level == "HIGH", f"Expected level HIGH, got {db_rec.analysis.risk_level}"
    assert db_rec.analysis.review.review_status == "NEW", "Review should initially be NEW"
    print("Confirmed: Analysis record, score, reasons, and initial review correctly saved.")
    s.close()

    # Step 5: GET /api/alerts
    print("\n[Step 5] Calling GET /api/alerts ...")
    alerts_resp = client.get("/api/alerts")
    assert alerts_resp.status_code == 200
    alerts = alerts_resp.json()
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}"
    alert = alerts[0]
    assert alert["id"] == alert_id
    assert alert["status"] == "PROCESSED"
    assert alert["risk_score"] == 95
    assert alert["risk_level"] == "HIGH"
    assert len(alert["reasons"]) == 4
    assert alert["review_status"] == "NEW"
    print(f"Confirmed: GET /api/alerts returned fully populated alert ({alert['id']}).")

    # Step 6: GET /api/alerts/{id}
    print(f"\n[Step 6] Calling GET /api/alerts/{alert_id} ...")
    detail_resp = client.get(f"/api/alerts/{alert_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == alert_id
    assert detail["explanation"] == mock_ai_result.explanation
    print("Confirmed: GET /api/alerts/{id} detail endpoint operates as specified.")

    # Step 7: Update analyst review via POST /api/alerts/{id}/review
    print(f"\n[Step 7] Analyst submitting review via POST /api/alerts/{alert_id}/review ...")
    review_resp = client.post(f"/api/alerts/{alert_id}/review", json={
        "review_status": "REVIEWED",
        "reviewer_note": "Проверено аналитиком: реквизиты Kaspi переданы в АФМ РК.",
        "reviewed_by": "analyst_safenet_01"
    })
    assert review_resp.status_code == 200
    reviewed_alert = review_resp.json()
    assert reviewed_alert["review_status"] == "REVIEWED"
    assert reviewed_alert["reviewer_note"] == "Проверено аналитиком: реквизиты Kaspi переданы в АФМ РК."
    assert reviewed_alert["reviewed_by"] == "analyst_safenet_01"
    print("Confirmed: Review accepted by API and returned in updated alert.")

    # Step 8: Reload and verify persistence
    print(f"\n[Step 8] Reloading alert and verifying persistence ...")
    reloaded_resp = client.get(f"/api/alerts/{alert_id}")
    assert reloaded_resp.status_code == 200
    reloaded = reloaded_resp.json()
    assert reloaded["review_status"] == "REVIEWED"
    assert reloaded["reviewer_note"] == "Проверено аналитиком: реквизиты Kaspi переданы в АФМ РК."
    assert reloaded["reviewed_by"] == "analyst_safenet_01"

    # Also verify stats reflect processed state
    stats = client.get("/api/stats").json()
    assert stats["total_messages"] == 1
    assert stats["by_level"]["HIGH"] == 1
    assert stats["pending"] == 0
    assert stats["errors"] == 0
    print(f"Stats: {stats}")
    print("\nALL 8 END-TO-END STEPS COMPLETED AND VERIFIED SUCCESSFULLY ON POSTGRESQL!")
    print("=" * 60)


if __name__ == "__main__":
    run_e2e_verification()
