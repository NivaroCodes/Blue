import os
import sys
import time
from datetime import datetime, timezone
from fastapi.testclient import TestClient

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
load_dotenv()

from ai_data.api_server import app, init_db
import ai_data.api_server as api_server
from ai_data.worker import process_pending_messages
from ai_data.db.models import MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord

def run_isolated_e2e():
    db_url = os.getenv("DATABASE_URL")
    api_key = os.getenv("GEMINI_API_KEY")
    expected_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    print(f"Starting Isolated E2E Verification on PostgreSQL: {db_url.split('@')[-1]}")
    print(f"Target model: {expected_model}")

    SessionLocal = init_db(db_url)
    db = SessionLocal()

    # Clean test tables
    db.query(EntityRecord).delete()
    db.query(ReviewRecord).delete()
    db.query(AnalysisRecord).delete()
    db.query(MessageRecord).delete()
    db.commit()

    # Step 1: Configure api_server for asynchronous worker queue mode
    api_server.INLINE_ANALYSIS = False
    client = TestClient(app)

    # Step 2: POST /api/messages with a synthetic message
    payload = {
        "platform": "telegram",
        "chat_id": "test_e2e_chat_01",
        "chat_name": "Test Group KZ",
        "message_id": "msg_e2e_001",
        "sender_hash": "e2e_sender_synthetic",
        "text": "Срочно вложи 30 000 тг и забери 300 000 за неделю! Перевод на личную карту Kaspi. Только 3 места осталось!",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    t0 = time.monotonic()
    post_resp = client.post("/api/messages", json=payload)
    print(f"1. POST /api/messages -> Status Code {post_resp.status_code}")
    assert post_resp.status_code == 200, f"Expected 200, got {post_resp.status_code}: {post_resp.text}"
    msg_data = post_resp.json()
    assert msg_data["status"] == "PENDING", f"Expected PENDING status, got {msg_data['status']}"
    print(f"   Created message ID: {msg_data['id']}, status: {msg_data['status']}")

    # Step 3: Run worker batch processing with real Gemini 3.5 Flash Lite + Risk Engine
    print("2. Running worker process_pending_messages() with real Gemini 3.5 Flash Lite...")
    processed_count = process_pending_messages(db, limit=5, worker_id="e2e_test_worker", api_key=api_key)
    print(f"   Worker processed {processed_count} message(s)")
    assert processed_count == 1, f"Expected 1 processed message, got {processed_count}"

    # Step 4: Verify PostgreSQL state
    raw_msg_id = msg_data["id"].replace("alert_", "")
    rec = db.query(MessageRecord).filter(MessageRecord.id == raw_msg_id).first()
    assert rec is not None, "Message record not found in PostgreSQL"
    assert rec.status == "PROCESSED", f"Expected PROCESSED status, got {rec.status}"
    assert rec.analysis is not None, "AnalysisRecord not created"
    assert rec.analysis.risk_level == "HIGH", f"Expected HIGH risk level, got {rec.analysis.risk_level}"
    assert rec.analysis.model_version == expected_model, f"Expected model_version {expected_model}, got {rec.analysis.model_version}"
    print(f"3. PostgreSQL State Verified:")
    print(f"   Status: {rec.status}")
    print(f"   Risk Score: {rec.analysis.risk_score}")
    print(f"   Risk Level: {rec.analysis.risk_level}")
    print(f"   Model Version: {rec.analysis.model_version}")
    print(f"   Confidence: {rec.analysis.confidence}")
    print(f"   Reasons JSON: {rec.analysis.reasons_json}")

    # Step 5: GET /api/alerts
    get_resp = client.get("/api/alerts")
    print(f"4. GET /api/alerts -> Status Code {get_resp.status_code}")
    assert get_resp.status_code == 200, f"Expected 200, got {get_resp.status_code}: {get_resp.text}"
    alerts_data = get_resp.json()
    assert isinstance(alerts_data, list) and len(alerts_data) >= 1, "Alerts list should not be empty"
    alert = alerts_data[0]
    assert alert["id"] == f"alert_{rec.id}", f"Alert ID mismatch: {alert['id']}"
    assert alert["risk_level"] == "HIGH", f"Alert risk level mismatch: {alert['risk_level']}"
    assert alert["model_version"] == expected_model, f"Alert model_version mismatch: {alert['model_version']}"
    print(f"   Alert retrieved successfully:")
    print(f"   ID: {alert['id']}")
    print(f"   Score: {alert['risk_score']}")
    print(f"   Level: {alert['risk_level']}")
    print(f"   Review status: {alert['review_status']}")
    print(f"   Model: {alert['model_version']}")

    # Step 6: POST /api/alerts/{id}/review
    post_review_resp = client.post(
        f"/api/alerts/{alert['id']}/review",
        json={"review_status": "REVIEWED", "reviewer_note": "Confirmed synthetic Ponzi scheme by analyst."}
    )
    print(f"5. POST /api/alerts/{alert['id']}/review -> Status Code {post_review_resp.status_code}")
    assert post_review_resp.status_code == 200, f"Expected 200, got {post_review_resp.status_code}: {post_review_resp.text}"
    updated_alert = post_review_resp.json()
    assert updated_alert["review_status"] == "REVIEWED", f"Expected REVIEWED, got {updated_alert['review_status']}"
    assert updated_alert["reviewer_note"] == "Confirmed synthetic Ponzi scheme by analyst."
    print("   Review updated and verified in database!")

    elapsed = round(time.monotonic() - t0, 2)
    print(f"\nISOLATED E2E VERIFICATION COMPLETED SUCCESSFULLY in {elapsed}s!")
    db.close()
    return True

if __name__ == "__main__":
    success = run_isolated_e2e()
    if not success:
        sys.exit(1)
