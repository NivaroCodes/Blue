import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import Session
from .db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord
from .analyzer import analyze_message
from .context import build_context_block
from .entity_extractor import extract_entities
from .llm_client import AIAnalysisError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ai_worker")


def process_pending_messages(session: Session, limit: int = 10, api_key: Optional[str] = None) -> int:
    """
    Fetches PENDING messages from the database, enriches them with sender/chat
    context, sends to AI for analysis, and saves results back to the database.
    """
    pending_messages: List[MessageRecord] = (
        session.query(MessageRecord)
        .filter(MessageRecord.status == "PENDING")
        .order_by(MessageRecord.timestamp.asc())
        .limit(limit)
        .all()
    )

    if not pending_messages:
        return 0

    logger.info(f"Found {len(pending_messages)} PENDING message(s) to analyze with AI.")
    processed_count = 0

    for msg in pending_messages:
        logger.info(f"Processing message {msg.id} (sender={msg.sender_hash}, chat={msg.chat_id})...")
        msg.status = "PROCESSING"
        session.commit()

        try:
            # Build context from database: sender reputation + chat risk profile
            context_block = build_context_block(session, msg)
            if context_block:
                logger.info(f"  Context enrichment applied for {msg.id}")

            # AI Analysis with context
            analysis = analyze_message(msg.text, api_key=api_key, context_block=context_block)

            # Convert reasons to JSON string
            reasons_payload = json.dumps(
                [{"code": r.code, "evidence": r.evidence} for r in analysis.reasons],
                ensure_ascii=False
            )

            analysis_record = AnalysisRecord(
                id=f"analysis_{msg.id}",
                message_id=msg.id,
                risk_score=analysis.risk_score,
                risk_level=analysis.risk_level.value,
                reasons_json=reasons_payload,
                explanation=analysis.explanation,
                confidence=analysis.confidence,
                model_version=analysis.model_version,
                analyzed_at=datetime.now(timezone.utc)
            )

            review_record = ReviewRecord(
                id=f"rev_{msg.id}",
                analysis_id=analysis_record.id,
                review_status="NEW",
                reviewer_note="",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            session.add(analysis_record)
            session.add(review_record)

            # Extract financial and contact entities (phones, cards, Telegram handles)
            entities = extract_entities(msg.text)
            for idx, ent in enumerate(entities):
                ent_rec = EntityRecord(
                    id=f"ent_{msg.id}_{idx}",
                    message_id=msg.id,
                    entity_type=ent["type"],
                    normalized_value=ent["value"],
                    created_at=datetime.now(timezone.utc)
                )
                session.add(ent_rec)

            msg.status = "PROCESSED"
            session.commit()

            processed_count += 1
            logger.info(f"  Result: score={analysis.risk_score}, level={analysis.risk_level.value}, reasons={len(analysis.reasons)}")

        except AIAnalysisError as e:
            logger.error(f"AI failed for message {msg.id}: {e}")
            msg.status = "ERROR"
            session.commit()
        except Exception as e:
            logger.error(f"Unexpected error processing message {msg.id}: {e}")
            msg.status = "ERROR"
            session.commit()
        finally:
            if api_key != "":
                time.sleep(1.5)

    return processed_count


def run_worker_loop(database_url: str = "sqlite:///safenet.db", poll_interval: float = 3.0, api_key: Optional[str] = None):
    """
    Continuous background worker loop that watches the database for PENDING messages.
    """
    SessionLocal = init_db(database_url)
    logger.info(f"Starting AI Background Worker connected to {database_url}...")

    while True:
        session = SessionLocal()
        try:
            count = process_pending_messages(session, limit=5, api_key=api_key)
            if count == 0:
                time.sleep(poll_interval)
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            time.sleep(poll_interval)
        finally:
            session.close()


if __name__ == "__main__":
    run_worker_loop()
