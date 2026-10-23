"""
AI background worker.

Concurrency model (safe for several workers + the API's inline processing at the same time):
1. CLAIM    — a message is taken with a single conditional UPDATE
              `SET status='PROCESSING', claimed_by=<me> WHERE id=:id AND status='PENDING'`.
              The database guarantees only one caller gets rowcount == 1; everyone else skips it.
2. ANALYSE  — LLM call (text + image if the message has image_url).
3. FINALISE — results are written and the status is switched with
              `... WHERE id=:id AND status='PROCESSING' AND claimed_by=<me>`.
              If ownership was lost (e.g. the claim expired and another worker took over),
              the transaction is rolled back, so a message is never written twice.
4. RECOVER  — PROCESSING claims older than CLAIM_TIMEOUT are returned to PENDING
              (or ERROR after MAX_ATTEMPTS), so a crashed worker never leaves messages stuck.
"""
import json
import logging
import os
import re
import socket
import time
import uuid
from datetime import timedelta
from typing import Optional, List, Iterable

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, EntityRecord, utc_now
from .analyzer import analyze_message
from .context import build_context_block
from .entity_extractor import extract_entities
from .llm_client import AIAnalysisError
from .media import load_image, MediaError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ai_worker")

CLAIM_TIMEOUT = timedelta(minutes=int(os.getenv("CLAIM_TIMEOUT_MINUTES", "10")))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))


def _sanitize_error(error_msg: str) -> str:
    """Strips API keys, tokens, and query secrets from error messages before storing or logging."""
    redacted = re.sub(r"(key|api_key|token|password|secret)=[^\s&\"']+", r"\1=[REDACTED]", error_msg)
    return redacted[:2000]


def make_worker_id() -> str:
    return f"{socket.gethostname()[:30]}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def claim_message(session: Session, msg_id: str, worker_id: str) -> bool:
    """Atomically moves one message PENDING -> PROCESSING. Returns True only for the winner."""
    result = session.execute(
        update(MessageRecord)
        .where(MessageRecord.id == msg_id, MessageRecord.status == "PENDING")
        .values(
            status="PROCESSING",
            claimed_by=worker_id,
            claimed_at=utc_now(),
            attempts=MessageRecord.attempts + 1,
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return result.rowcount == 1


def _set_status_if_owner(session: Session, msg_id: str, worker_id: str, status: str, error: Optional[str] = None) -> bool:
    result = session.execute(
        update(MessageRecord)
        .where(
            MessageRecord.id == msg_id,
            MessageRecord.status == "PROCESSING",
            MessageRecord.claimed_by == worker_id,
        )
        .values(status=status, last_error=error)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def recover_stale_claims(session: Session) -> int:
    """Returns abandoned PROCESSING messages to the queue (or to ERROR after MAX_ATTEMPTS)."""
    cutoff = utc_now() - CLAIM_TIMEOUT
    stale_filter = (
        MessageRecord.status == "PROCESSING",
        MessageRecord.claimed_at.isnot(None),
        MessageRecord.claimed_at < cutoff,
    )
    failed = session.execute(
        update(MessageRecord)
        .where(*stale_filter, MessageRecord.attempts >= MAX_ATTEMPTS)
        .values(status="ERROR", last_error="Превышено число попыток обработки (воркер не завершил задачу).")
        .execution_options(synchronize_session=False)
    ).rowcount
    requeued = session.execute(
        update(MessageRecord)
        .where(*stale_filter, MessageRecord.attempts < MAX_ATTEMPTS)
        .values(status="PENDING", claimed_by=None, claimed_at=None)
        .execution_options(synchronize_session=False)
    ).rowcount
    session.commit()
    if failed or requeued:
        logger.warning(f"Recovered stale claims: requeued={requeued}, failed={failed}")
    return requeued + failed


def _analyse_and_store(session: Session, msg: MessageRecord, worker_id: str, api_key: Optional[str]) -> bool:
    """Runs the AI on one claimed message and persists the result. Returns True on success."""
    text = msg.text or ""

    # 1. Image (optional). If it cannot be loaded, fall back to text-only analysis.
    image = None
    if msg.image_url:
        try:
            image = load_image(msg.image_url)
        except MediaError as e:
            logger.warning(f"  Image for {msg.id} unavailable ({e}); analysing text only.")
            if not text.strip():
                raise AIAnalysisError(f"Сообщение без текста, а изображение недоступно: {e}")

    # 2. Context from database: sender reputation + chat risk profile
    context_block = build_context_block(session, msg)
    if context_block:
        logger.info(f"  Context enrichment applied for {msg.id}")

    # 3. AI analysis
    analysis = analyze_message(
        text,
        api_key=api_key,
        context_block=context_block,
        image_base64=image[0] if image else None,
        image_mime=image[1] if image else "image/jpeg",
    )

    reasons_payload = json.dumps(
        [
            {"code": r.code, "evidence": r.evidence, **({"source": r.source} if r.source != "text" else {})}
            for r in analysis.reasons
        ],
        ensure_ascii=False,
    )
    now = utc_now()
    existing_analysis = (
        session.query(AnalysisRecord)
        .filter(AnalysisRecord.message_id == msg.id)
        .first()
    )
    if existing_analysis:
        existing_analysis.risk_score = analysis.risk_score
        existing_analysis.risk_level = analysis.risk_level.value
        existing_analysis.reasons_json = reasons_payload
        existing_analysis.explanation = analysis.explanation
        existing_analysis.confidence = analysis.confidence
        existing_analysis.model_version = analysis.model_version
        existing_analysis.image_analyzed = 1 if image else 0
        existing_analysis.image_text = analysis.image_text if image else None
        existing_analysis.analyzed_at = now
        analysis_record = existing_analysis
    else:
        analysis_record = AnalysisRecord(
            id=f"analysis_{msg.id}",
            message_id=msg.id,
            risk_score=analysis.risk_score,
            risk_level=analysis.risk_level.value,
            reasons_json=reasons_payload,
            explanation=analysis.explanation,
            confidence=analysis.confidence,
            model_version=analysis.model_version,
            image_analyzed=1 if image else 0,
            image_text=analysis.image_text if image else None,
            analyzed_at=now,
        )
        session.add(analysis_record)

    existing_review = (
        session.query(ReviewRecord)
        .filter(ReviewRecord.analysis_id == analysis_record.id)
        .first()
    )
    if not existing_review:
        review_record = ReviewRecord(
            id=f"rev_{msg.id}",
            analysis_id=analysis_record.id,
            review_status="NEW",
            reviewer_note="",
            created_at=now,
            updated_at=now,
        )
        session.add(review_record)

    # 4. Entities (phones, cards, Telegram handles) from the text, image OCR, and image-sourced evidence
    session.query(EntityRecord).filter(EntityRecord.message_id == msg.id).delete(synchronize_session=False)
    extra_parts = []
    if image:
        if analysis.image_text:
            extra_parts.append(analysis.image_text)
        extra_parts.extend(r.evidence for r in analysis.reasons if r.source == "image")
    entity_source = "\n".join([text] + extra_parts)
    for idx, ent in enumerate(extract_entities(entity_source)):
        session.add(EntityRecord(
            id=f"ent_{msg.id}_{idx}",
            message_id=msg.id,
            entity_type=ent["type"],
            normalized_value=ent["value"],
            display_value=ent.get("display"),
            created_at=now,
        ))

    # 5. Finalise only if we still own the claim
    if not _set_status_if_owner(session, msg.id, worker_id, "PROCESSED"):
        session.rollback()
        logger.warning(f"  Lost ownership of {msg.id}; result discarded (processed by another worker).")
        return False
    session.commit()
    session.expire(msg)
    logger.info(
        f"  Result: score={analysis.risk_score}, level={analysis.risk_level.value}, "
        f"reasons={len(analysis.reasons)}, image={'yes' if image else 'no'}"
    )
    return True


def process_pending_messages(
    session: Session,
    limit: int = 10,
    api_key: Optional[str] = None,
    only_ids: Optional[Iterable[str]] = None,
    throttle_seconds: float = 1.5,
    worker_id: Optional[str] = None,
) -> int:
    """
    Claims up to `limit` PENDING messages (optionally restricted to `only_ids`), enriches them with
    sender/chat context, sends them to the AI and saves the results.
    Safe to call concurrently from several processes.
    """
    worker_id = worker_id or make_worker_id()

    is_postgres = session.bind is not None and session.bind.dialect.name == "postgresql"
    candidate_ids: List[str] = []
    already_claimed_ids = set()

    if is_postgres:
        try:
            # Atomic batch claim on PostgreSQL using SELECT ... FOR UPDATE SKIP LOCKED
            pq = (
                session.query(MessageRecord)
                .filter(MessageRecord.status == "PENDING")
                .order_by(MessageRecord.timestamp.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
            if only_ids is not None:
                pq = pq.filter(MessageRecord.id.in_(list(only_ids)))
            claimed_recs = pq.all()
            now = utc_now()
            for rec in claimed_recs:
                rec.status = "PROCESSING"
                rec.claimed_by = worker_id
                rec.claimed_at = now
                rec.attempts = (rec.attempts or 0) + 1
                rec.last_error = None
                candidate_ids.append(rec.id)
                already_claimed_ids.add(rec.id)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error during PostgreSQL FOR UPDATE SKIP LOCKED claim: {_sanitize_error(str(e))}")
            candidate_ids = []

    if not candidate_ids and not is_postgres:
        query = session.query(MessageRecord.id).filter(MessageRecord.status == "PENDING")
        if only_ids is not None:
            ids = list(only_ids)
            if not ids:
                return 0
            query = query.filter(MessageRecord.id.in_(ids))
        # Over-fetch candidates: some may be claimed by a concurrent worker in the meantime.
        candidate_ids = [
            row[0] for row in query.order_by(MessageRecord.timestamp.asc()).limit(max(limit * 3, limit)).all()
        ]

    if not candidate_ids:
        return 0

    processed_count = 0
    claimed = 0
    for msg_id in candidate_ids:
        if claimed >= limit:
            break
        if msg_id not in already_claimed_ids:
            if not claim_message(session, msg_id, worker_id):
                continue  # someone else got it
        claimed += 1
        if claimed > 1 and throttle_seconds and api_key != "":
            time.sleep(throttle_seconds)  # rate-limit between LLM calls, not after the last one

        msg = session.get(MessageRecord, msg_id)
        logger.info(f"Processing message {msg.id} (sender={msg.sender_hash}, chat={msg.chat_id})...")
        try:
            if _analyse_and_store(session, msg, worker_id, api_key):
                processed_count += 1
        except IntegrityError as e:
            session.rollback()
            logger.warning(f"Result for {msg_id} already stored by another worker: {e.orig}")
        except Exception as e:
            session.rollback()
            kind = "AI failed" if isinstance(e, AIAnalysisError) else "Unexpected error"
            sanitized_err = _sanitize_error(str(e))
            logger.error(f"{kind} for message {msg_id}: {sanitized_err}")
            _set_status_if_owner(session, msg_id, worker_id, "ERROR", error=sanitized_err)
            session.commit()

    return processed_count


def run_worker_loop(database_url: Optional[str] = None, poll_interval: float = 3.0, api_key: Optional[str] = None):
    """
    Continuous background worker loop that watches the database for PENDING messages.
    Several instances may run in parallel.
    """
    db_url = database_url or os.getenv("DATABASE_URL", "sqlite:///safenet.db")
    SessionLocal = init_db(db_url)
    worker_id = make_worker_id()
    logger.info(f"Starting AI Background Worker {worker_id} connected to {db_url}...")

    while True:
        session = SessionLocal()
        try:
            recover_stale_claims(session)
            count = process_pending_messages(session, limit=5, api_key=api_key, worker_id=worker_id)
            if count == 0:
                time.sleep(poll_interval)
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            time.sleep(poll_interval)
        finally:
            session.close()


if __name__ == "__main__":
    run_worker_loop()
