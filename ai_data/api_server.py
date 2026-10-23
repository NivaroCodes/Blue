import os
import csv
import io
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db.models import (
    init_db, MessageRecord, ReviewRecord, serialize_to_alert_dict,
    make_message_pk, parse_timestamp, utc_now,
)
from .worker import process_pending_messages
from .graph_analysis import analyze_network_graph
from .media import save_image, resolve_local_media_path, sniff_mime, MediaError

DATABASE_URL = os.getenv("DATABASE_URL")
# 1 = analyse right inside POST /api/messages (demo mode); 0 = leave it to the background worker.
INLINE_ANALYSIS = os.getenv("INLINE_ANALYSIS", "0") == "1"
SessionLocal = init_db(DATABASE_URL)

app = FastAPI(
    title="SafeNet KZ — Backend API & AI Surveillance Pipeline",
    version="1.1.0",
    description="API server implementing docs/API.md connected to PostgreSQL database and AI worker."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ReviewRequest(BaseModel):
    review_status: str = Field(..., pattern="^(NEW|REVIEWED|FALSE_POSITIVE)$")
    reviewer_note: str = Field(default="", max_length=2000)
    reviewed_by: Optional[str] = Field(default=None, description="Analyst name or ID")


class MessageCreateRequest(BaseModel):
    platform: str = Field(default="telegram", pattern="^(telegram|whatsapp)$")
    chat_id: str = Field(..., min_length=1, max_length=64)
    chat_name: str = "Общий чат"
    chat_url: Optional[str] = None
    message_id: str = Field(..., min_length=1, max_length=64, description="Message id local to the chat")
    sender_hash: str = Field(..., min_length=1, max_length=64)
    text: str = ""
    image_url: Optional[str] = Field(default=None, description="http(s) URL, /api/media/<file> or data: URL")
    image_base64: Optional[str] = Field(default=None, description="Attached image as base64 (saved to MEDIA_DIR)")
    timestamp: Optional[str] = Field(default=None, description="ISO-8601; without an offset it is treated as UTC")

    @model_validator(mode="after")
    def _text_or_image(self):
        if not self.text.strip() and not (self.image_url or self.image_base64):
            raise ValueError("Нужно передать text и/или изображение (image_url / image_base64).")
        return self


def _find_message(db: Session, alert_id: str) -> MessageRecord:
    """
    Resolves an alert id. Primary form is 'alert_<internal id>'.
    A bare chat-local message_id is accepted only if it is unambiguous across chats.
    """
    rec = db.get(MessageRecord, alert_id)
    if rec:
        return rec
    if alert_id.startswith("alert_"):
        key = alert_id[len("alert_"):]
        rec = db.get(MessageRecord, key)
        if rec:
            return rec
    else:
        key = alert_id

    matches = db.query(MessageRecord).filter(MessageRecord.message_id == key).limit(2).all()
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail=f"message_id '{key}' встречается в нескольких чатах — используйте id алерта.")
    raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")


def _find_by_source(db: Session, platform: str, chat_id: str, message_id: str) -> Optional[MessageRecord]:
    return (
        db.query(MessageRecord)
        .filter(
            MessageRecord.platform == platform,
            MessageRecord.chat_id == chat_id,
            MessageRecord.message_id == message_id,
        )
        .first()
    )


def _ingest(db: Session, req: MessageCreateRequest) -> MessageRecord:
    """Idempotent insert keyed by (platform, chat_id, message_id)."""
    pk = make_message_pk(req.platform, req.chat_id, req.message_id)
    existing = db.get(MessageRecord, pk) or _find_by_source(db, req.platform, req.chat_id, req.message_id)
    if existing:
        return existing

    try:
        ts = parse_timestamp(req.timestamp)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Некорректный timestamp: '{req.timestamp}' (ожидается ISO-8601).")

    image_url = req.image_url
    if req.image_base64:
        try:
            image_url = save_image(pk, req.image_base64)
        except MediaError as e:
            raise HTTPException(status_code=422, detail=str(e))

    rec = MessageRecord(
        id=pk,
        platform=req.platform,
        chat_id=req.chat_id,
        chat_name=req.chat_name,
        chat_url=req.chat_url,
        message_id=req.message_id,
        sender_hash=req.sender_hash,
        text=req.text,
        image_url=image_url,
        timestamp=ts,
        status="PENDING",
    )
    db.add(rec)
    try:
        db.commit()
    except IntegrityError:
        # Two identical messages arrived concurrently — the other request inserted it first.
        db.rollback()
        return db.get(MessageRecord, pk) or _find_by_source(db, req.platform, req.chat_id, req.message_id)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during ingestion: {e}")
    return rec


@app.get("/api/alerts")
def get_alerts(level: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Returns full snapshot of alerts from the database.
    """
    records = db.query(MessageRecord).order_by(MessageRecord.timestamp.desc()).all()
    alerts = [serialize_to_alert_dict(rec) for rec in records]

    if level:
        alerts = [a for a in alerts if a.get("risk_level") == level]

    return alerts


@app.get("/api/alerts/{alert_id}")
def get_alert_detail(alert_id: str, db: Session = Depends(get_db)):
    """
    Returns single alert details by alert_id.
    """
    return serialize_to_alert_dict(_find_message(db, alert_id))


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """
    Computes real-time message and alert statistics from the database.
    """
    all_messages = db.query(MessageRecord).all()
    since = utc_now() - timedelta(hours=24)

    pending = 0
    processing = 0
    errors = 0
    by_level = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for m in all_messages:
        if m.status == "PENDING":
            pending += 1
        elif m.status == "PROCESSING":
            processing += 1
        elif m.status == "PROCESSED" and m.analysis and m.analysis.risk_level in by_level and m.analysis.risk_score is not None:
            by_level[m.analysis.risk_level] += 1
        else:
            errors += 1

    return {
        "total_messages": len(all_messages),
        "last_24h": sum(1 for m in all_messages if m.timestamp and m.timestamp >= since),
        "pending": pending,
        "processing": processing,
        "errors": errors,
        "by_level": by_level,
    }


@app.get("/api/network-graph")
def get_network_graph(db: Session = Depends(get_db)):
    """
    Returns graph and link analysis: bot clusters, cross-chat syndicates,
    and high-risk community clusters.
    """
    return analyze_network_graph(db)


@app.post("/api/alerts/{alert_id}/review")
def update_review(alert_id: str, req: ReviewRequest, db: Session = Depends(get_db)):
    """
    Saves reviewer decision (NEW / REVIEWED / FALSE_POSITIVE) and reviewer_note in database.
    REVIEWED = analyst confirms the verdict (only confirmed verdicts escalate future risk scores);
    FALSE_POSITIVE = verdict rejected (excluded from sender/chat reputation).
    """
    rec = _find_message(db, alert_id)
    if rec.status != "PROCESSED" or not rec.analysis:
        raise HTTPException(status_code=400, detail="Cannot review an alert that is not in PROCESSED status.")

    review = rec.analysis.review
    if not review:
        review = ReviewRecord(
            id=f"rev_{rec.id}",
            analysis_id=rec.analysis.id,
            review_status=req.review_status,
            reviewer_note=req.reviewer_note,
            reviewed_by=req.reviewed_by
        )
        db.add(review)
    else:
        review.review_status = req.review_status
        review.reviewer_note = req.reviewer_note
        if req.reviewed_by:
            review.reviewed_by = req.reviewed_by

    try:
        db.commit()
        db.refresh(rec)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error saving review: {e}")
    return serialize_to_alert_dict(rec)


@app.post("/api/messages")
def ingest_message(req: MessageCreateRequest, db: Session = Depends(get_db)):
    """
    Ingests raw message (text and/or image), saves to DB with status PENDING.
    Deduplication key: (platform, chat_id, message_id).
    With INLINE_ANALYSIS=1 the message is analysed immediately (atomic claim — never double-processed
    even if the background worker runs at the same time).
    """
    rec = _ingest(db, req)
    if INLINE_ANALYSIS and rec.status == "PENDING":
        process_pending_messages(db, limit=1, only_ids=[rec.id], throttle_seconds=0)
        db.refresh(rec)
    return {"id": f"alert_{rec.id}", "message_id": rec.message_id, "status": rec.status}


class ImageAnalyzeRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 encoded JPEG/PNG/WEBP image (raw or data: URL)")
    text_caption: Optional[str] = Field(default="", description="Optional message caption")
    # Optional source metadata; defaults describe a manual upload by an analyst.
    platform: str = Field(default="telegram", pattern="^(telegram|whatsapp)$")
    chat_id: str = "manual_upload"
    chat_name: str = "Ручная загрузка скриншотов"
    chat_url: Optional[str] = None
    message_id: Optional[str] = None
    sender_hash: str = "analyst_upload"
    timestamp: Optional[str] = None


@app.post("/api/analyze-image")
def analyze_image_endpoint(req: ImageAnalyzeRequest, db: Session = Depends(get_db)):
    """
    Multimodal AI endpoint: analyses payment screenshots, fake bank receipts or promo graphics.
    The upload is stored as a regular message + alert (visible in /api/alerts, stats, graph, export).
    """
    msg_req = MessageCreateRequest(
        platform=req.platform,
        chat_id=req.chat_id,
        chat_name=req.chat_name,
        chat_url=req.chat_url,
        message_id=req.message_id or f"img_{uuid.uuid4().hex[:16]}",
        sender_hash=req.sender_hash,
        text=req.text_caption or "",
        image_base64=req.image_base64,
        timestamp=req.timestamp,
    )
    rec = _ingest(db, msg_req)
    if rec.status == "PENDING":
        process_pending_messages(db, limit=1, only_ids=[rec.id], throttle_seconds=0)
        db.refresh(rec)
    return serialize_to_alert_dict(rec)


@app.get("/api/media/{filename}")
def get_media_file(filename: str):
    """Serves persisted screenshot images from MEDIA_DIR."""
    try:
        path = resolve_local_media_path(filename)
        data = path.read_bytes()
        mime = sniff_mime(data)
    except MediaError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=data, media_type=mime)


@app.get("/api/export")
def export_alerts(format: str = "json", db: Session = Depends(get_db)):
    """
    Exports surveillance dataset as JSON or CSV for regulatory / forensic reporting (АФМ / АРРФР).
    """
    records = db.query(MessageRecord).order_by(MessageRecord.timestamp.desc()).all()
    alerts = [serialize_to_alert_dict(rec) for rec in records]

    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "platform", "chat_name", "chat_url", "sender_hash", "status", "risk_score", "risk_level", "reasons", "explanation", "review_status", "timestamp"])
        for a in alerts:
            reasons_str = "; ".join(f"{r.get('code')}: {r.get('evidence')}" for r in a.get("reasons", []))
            writer.writerow([
                a.get("id"),
                a.get("platform"),
                a.get("chat_name"),
                a.get("chat_url") or "",
                a.get("sender_hash"),
                a.get("status"),
                a.get("risk_score") if a.get("risk_score") is not None else "",
                a.get("risk_level") or "",
                reasons_str,
                a.get("explanation") or "",
                a.get("review_status"),
                a.get("timestamp")
            ])
        return Response(
            content=output.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=safenet_alerts_export.csv"}
        )

    return alerts


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ai_data.api_server:app", host="127.0.0.1", port=8000, reload=True)
