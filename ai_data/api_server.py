import os
import csv
import io
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db.models import init_db, MessageRecord, AnalysisRecord, ReviewRecord, serialize_to_alert_dict
from .worker import process_pending_messages
from .graph_analysis import analyze_network_graph

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///safenet.db")
SessionLocal = init_db(DATABASE_URL)

app = FastAPI(
    title="SafeNet KZ — Backend API & AI Surveillance Pipeline",
    version="1.0.0",
    description="API server implementing docs/API.md connected to SQLite database and AI worker."
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
    chat_id: str
    chat_name: str = "Общий чат"
    chat_url: Optional[str] = None
    message_id: str
    sender_hash: str
    text: str
    image_url: Optional[str] = None
    timestamp: Optional[str] = None


@app.get("/api/alerts")
def get_alerts(level: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Returns full snapshot of alerts from the database.
    """
    query = db.query(MessageRecord).order_by(MessageRecord.timestamp.desc())
    records = query.all()
    alerts = [serialize_to_alert_dict(rec) for rec in records]

    if level:
        alerts = [a for a in alerts if a.get("risk_level") == level]

    return alerts


@app.get("/api/alerts/{alert_id}")
def get_alert_detail(alert_id: str, db: Session = Depends(get_db)):
    """
    Returns single alert details by alert_id.
    """
    # alert_id usually has 'alert_' prefix or is message_id directly
    msg_id = alert_id.replace("alert_", "")
    rec = db.query(MessageRecord).filter((MessageRecord.id == msg_id) | (MessageRecord.message_id == msg_id)).first()
    if not rec:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    return serialize_to_alert_dict(rec)


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """
    Computes real-time message and alert statistics from the database.
    """
    all_messages = db.query(MessageRecord).all()
    total = len(all_messages)
    pending = sum(1 for m in all_messages if m.status == "PENDING")
    processing = sum(1 for m in all_messages if m.status == "PROCESSING")
    errors = sum(1 for m in all_messages if m.status == "ERROR")

    by_level = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for m in all_messages:
        if m.status == "PROCESSED" and m.analysis and m.analysis.risk_level:
            lvl = m.analysis.risk_level
            if lvl in by_level:
                by_level[lvl] += 1

    return {
        "total_messages": total,
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
    """
    msg_id = alert_id.replace("alert_", "")
    rec = db.query(MessageRecord).filter((MessageRecord.id == msg_id) | (MessageRecord.message_id == msg_id)).first()
    if not rec:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")

    if not rec.analysis:
        raise HTTPException(status_code=400, detail="Cannot review an alert without completed AI analysis.")

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

    db.commit()
    db.refresh(rec)
    return serialize_to_alert_dict(rec)


@app.post("/api/messages")
def ingest_message(req: MessageCreateRequest, db: Session = Depends(get_db)):
    """
    Ingests raw message, saves to DB with status PENDING, and triggers AI processing.
    """
    existing = db.query(MessageRecord).filter(MessageRecord.id == req.message_id).first()
    if existing:
        return {"message_id": existing.id, "status": existing.status}

    ts = datetime.now(timezone.utc)
    if req.timestamp:
        try:
            ts = datetime.fromisoformat(req.timestamp.replace("Z", "+00:00"))
        except Exception:
            pass

    rec = MessageRecord(
        id=req.message_id,
        platform=req.platform,
        chat_id=req.chat_id,
        chat_name=req.chat_name,
        chat_url=req.chat_url,
        message_id=req.message_id,
        sender_hash=req.sender_hash,
        text=req.text,
        image_url=req.image_url,
        timestamp=ts,
        status="PENDING"
    )
    db.add(rec)
    db.commit()

    # Trigger AI worker to process pending messages immediately
    process_pending_messages(db, limit=1)

    db.refresh(rec)
    return {"message_id": rec.id, "status": rec.status}


class ImageAnalyzeRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 encoded JPEG or PNG image")
    text_caption: Optional[str] = Field(default="", description="Optional message caption or OCR context")


@app.post("/api/analyze-image")
def analyze_image_endpoint(req: ImageAnalyzeRequest):
    """
    Multimodal AI endpoint: Analyzes payment screenshots, fake bank receipts,
    or fraudulent promotional graphics using Gemini Vision (Hackathon Criterion 3).
    """
    from .analyzer import analyze_message
    from .llm_client import AIAnalysisError

    try:
        result = analyze_message(
            req.text_caption or "Проанализируй приложенный скриншот на признаки финансовой пирамиды или поддельного чека.",
            image_base64=req.image_base64
        )
        return result.model_dump()
    except AIAnalysisError as e:
        raise HTTPException(status_code=502, detail=f"AI Vision analysis error: {e}")


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
        writer.writerow(["id", "platform", "chat_name", "chat_url", "sender_hash", "status", "risk_score", "risk_level", "reasons", "explanation", "timestamp"])
        for a in alerts:
            reasons_str = "; ".join(f"{r.get('code')}: {r.get('evidence')}" for r in a.get("reasons", []))
            writer.writerow([
                a.get("id"),
                a.get("platform"),
                a.get("chat_name"),
                a.get("chat_url") or "",
                a.get("sender_hash"),
                a.get("status"),
                a.get("risk_score") or "",
                a.get("risk_level") or "",
                reasons_str,
                a.get("explanation") or "",
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
