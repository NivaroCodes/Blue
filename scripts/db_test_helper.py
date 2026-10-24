import os
import sys
import json
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from ai_data.db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord, make_message_pk, serialize_to_alert_dict
from ai_data.worker import process_pending_messages

from ai_data.tests.test_db_helper import assert_is_test_database, clean_test_database

def get_session():
    db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/safenet_test"
    assert_is_test_database(db_url)
    SessionLocal = init_db(db_url)
    return SessionLocal()

def clean_db():
    db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/safenet_test"
    s = get_session()
    clean_test_database(s, db_url)
    s.close()
    print("DB_CLEANED")

def seed_pending(text="Срочно вложи 40 000 тг и получи 400 000 за неделю! Перевод на личную карту Kaspi: +7 701 111-22-33."):
    s = get_session()
    pk = make_message_pk("telegram", "live_chat_01", f"msg_{int(datetime.now().timestamp())}")
    rec = MessageRecord(
        id=pk,
        platform="telegram",
        chat_id="live_chat_01",
        chat_name="Live Test Group KZ",
        message_id=f"msg_{int(datetime.now().timestamp())}",
        sender_hash="sender_live_e2e",
        text=text,
        timestamp=datetime.now(timezone.utc),
        status="PENDING",
    )
    s.add(rec)
    s.commit()
    alert_id = f"alert_{rec.id}"
    s.close()
    print(f"SEEDED_PENDING:{alert_id}:{pk}")
    return alert_id

def process_one():
    s = get_session()
    api_key = os.getenv("GEMINI_API_KEY")
    count = process_pending_messages(s, limit=1, worker_id="live_test_worker", api_key=api_key)
    s.close()
    print(f"PROCESSED_COUNT:{count}")

def print_alert(alert_id):
    s = get_session()
    key = alert_id.replace("alert_", "")
    rec = s.get(MessageRecord, key)
    if not rec:
        rec = s.query(MessageRecord).filter(MessageRecord.id == alert_id).first()
    if rec:
        d = serialize_to_alert_dict(rec)
        print(json.dumps(d, ensure_ascii=False))
    else:
        print("NOT_FOUND")
    s.close()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "clean":
        clean_db()
    elif cmd == "seed":
        seed_pending()
    elif cmd == "process":
        process_one()
    elif cmd == "get" and len(sys.argv) > 2:
        print_alert(sys.argv[2])
    else:
        print("Unknown command")
