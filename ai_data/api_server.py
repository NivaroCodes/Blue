import os
import csv
import io
import uuid
import hmac
import base64
import logging
from urllib.parse import urlparse
from datetime import timedelta
from typing import Optional, List, Dict, Any, Union, Literal
from .models import Alert, StatsResponse, MessageIngestResponse

import httpx
from fastapi import FastAPI, HTTPException, Depends, Request, Header, BackgroundTasks
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text as sqlalchemy_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db.models import (
    init_db, MessageRecord, ReviewRecord, serialize_to_alert_dict,
    make_message_pk, parse_timestamp, utc_now,
)
from .worker import process_pending_messages
from .graph_analysis import analyze_network_graph
from .media import save_image, read_stored_image, MediaError, MediaStorageError
from .auth import require_dashboard_auth, is_public_demo_user
from .demo_access import is_demo_record
from .webhooks import (
    WebhookPayloadError, constant_time_token_match,
    normalize_green_message, normalize_telegram_message,
)

logger = logging.getLogger("safenet_api")

DATABASE_URL = os.getenv("DATABASE_URL")
# 1 = analyse right inside POST /api/messages (demo mode); 0 = leave it to the background worker.
INLINE_ANALYSIS = os.getenv("INLINE_ANALYSIS", "0") == "1"
SessionLocal = init_db(DATABASE_URL)

app = FastAPI(
    title="SafeNet KZ — Backend API & AI Surveillance Pipeline",
    version="1.1.0",
    description="API server implementing docs/API.md connected to PostgreSQL database and AI worker."
)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

cors_env = os.getenv("CORS_ORIGINS", "")
if cors_env.strip():
    cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()]
else:
    cors_origins = DEFAULT_CORS_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health_check():
    """Readiness check: verifies API and PostgreSQL connectivity."""
    try:
        with SessionLocal() as db:
            db.execute(sqlalchemy_text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable.") from None
    return {"status": "ok"}


def _require_ingest_authorization(request: Request) -> None:
    """
    Guards message ingestion endpoints with Bearer token authentication.
    Fails closed in deployed production environments if not configured.
    """
    expected = os.getenv("INGEST_API_TOKEN", "").strip()
    if not expected:
        # Recognize Fly automatically, even if PRODUCTION was accidentally omitted.
        is_deployed = bool(os.getenv("FLY_APP_NAME") or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PRODUCTION", "").lower() in ("true", "1"))
        if is_deployed:
            raise HTTPException(status_code=503, detail="Ingestion authentication is not configured.")
        return

    auth_header = request.headers.get("Authorization", "").strip()
    scheme, separator, provided = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not separator or not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="A valid Bearer token is required.")

def _message_hash_secret() -> str:
    """Prefer the dedicated shared key; support the Telegram-specific key already used on Fly."""
    return os.getenv("SENDER_HASH_SECRET", "").strip() or os.getenv("TELEGRAM_HASH_SECRET", "").strip()


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


class VisibilityRequest(BaseModel):
    off_topic: bool


class MessageCreateRequest(BaseModel):
    platform: str = Field(default="telegram", pattern="^(telegram|whatsapp)$")
    chat_id: str = Field(..., min_length=1, max_length=64)
    chat_name: str = "Общий чат"
    chat_url: Optional[str] = None
    message_id: str = Field(..., min_length=1, max_length=64, description="Message id local to the chat")
    sender_hash: str = Field(..., min_length=1, max_length=64)
    text: str = ""
    image_url: Optional[str] = Field(default=None, description="http(s) URL, /api/media/<file> or data: URL")
    image_base64: Optional[str] = Field(default=None, description="Attached image as base64 (saved to configured media storage)")
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
        except MediaStorageError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except MediaError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

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


def _process_webhook_message(message_id: str) -> None:
    """Process webhook ingests after acknowledging the provider's delivery."""
    db = SessionLocal()
    try:
        process_pending_messages(db, limit=1, only_ids=[message_id], throttle_seconds=0)
    finally:
        db.close()


async def _download_bounded(
    client: httpx.AsyncClient,
    url: str,
    max_bytes: int = 8 * 1024 * 1024,
    allowed_hosts: tuple[str, ...] = (),
) -> bytes:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or not any(hostname == host or hostname.endswith("." + host) for host in allowed_hosts)
    ):
        raise HTTPException(status_code=502, detail="Provider returned an unsupported media URL.")
    chunks = []
    size = 0
    async with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail="Image exceeds the configured size limit.")
            chunks.append(chunk)
    return b"".join(chunks)


async def _telegram_image_base64(file_id: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured.")
    async with httpx.AsyncClient(timeout=20.0) as client:
        result = await client.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
        result.raise_for_status()
        data = result.json()
        file_path = (data.get("result") or {}).get("file_path")
        if not data.get("ok") or not file_path:
            raise HTTPException(status_code=502, detail="Telegram did not provide a photo file.")
        if not isinstance(file_path, str) or not file_path or file_path.startswith("/") or ".." in file_path.split("/"):
            raise HTTPException(status_code=502, detail="Telegram returned an invalid photo path.")
        raw = await _download_bounded(
            client,
            f"https://api.telegram.org/file/bot{token}/{file_path}",
            allowed_hosts=("api.telegram.org",),
        )
    return base64.b64encode(raw).decode("ascii")


async def _green_image_base64(chat_id: str, message_id: str) -> str:
    api_url = os.getenv("GREEN_API_API_URL", "").rstrip("/")
    parsed_api_url = urlparse(api_url)
    api_host = (parsed_api_url.hostname or "").lower()
    instance_id = os.getenv("GREEN_API_ID_INSTANCE", "")
    token = os.getenv("GREEN_API_TOKEN_INSTANCE", "")
    allowed_api_hosts = ("green-api.com", "greenapi.com")
    if not (
        parsed_api_url.scheme == "https"
        and any(api_host == host or api_host.endswith("." + host) for host in allowed_api_hosts)
        and instance_id.isdigit()
        and token
    ):
        raise HTTPException(status_code=503, detail="GREEN-API media download is not configured.")
    endpoint = f"{api_url}/waInstance{instance_id}/downloadFile/{token}"
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.post(endpoint, json={"chatId": chat_id, "idMessage": message_id})
        response.raise_for_status()
        download_url = response.json().get("downloadUrl")
        if not isinstance(download_url, str):
            raise HTTPException(status_code=502, detail="GREEN-API returned an invalid media URL.")
        raw = await _download_bounded(
            client,
            download_url,
            allowed_hosts=("greenapi.net", "green-api.com", "yandexcloud.net"),
        )
    return base64.b64encode(raw).decode("ascii")


def _store_webhook_message(data: dict, db: Session, background_tasks: BackgroundTasks) -> dict:
    image_base64 = data.pop("image_base64", None)
    req = MessageCreateRequest(**data, image_base64=image_base64)
    rec = _ingest(db, req)
    if rec.status == "PENDING":
        background_tasks.add_task(_process_webhook_message, rec.id)
    return {"id": f"alert_{rec.id}", "message_id": rec.message_id, "status": rec.status}


@app.post("/webhooks/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    secret_header: Optional[str] = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected_secret:
        raise HTTPException(status_code=503, detail="Telegram webhook secret is not configured.")
    if not constant_time_token_match(secret_header, expected_secret):
        raise HTTPException(status_code=401, detail="Unauthorized webhook.")

    try:
        update = await request.json()
        message = update.get("message") or update.get("channel_post")
        if not isinstance(message, dict):
            return Response(status_code=204)
        chat = message.get("chat")
        if isinstance(chat, dict) and chat.get("type") == "private":
            from .telegram_connector import telegram_webhook as private_telegram_webhook
            return await private_telegram_webhook(request)
        if not isinstance(chat, dict) or chat.get("type") not in {"group", "supergroup"}:
            return Response(status_code=204)
        allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not allowed_chat_id:
            return Response(status_code=204)
        if str(chat.get("id")) != allowed_chat_id:
            return Response(status_code=204)
        normalized = normalize_telegram_message(message, _message_hash_secret())
        if normalized is None:
            return Response(status_code=204)
        photo_id = normalized.pop("telegram_photo_file_id", None)
        if photo_id:
            normalized["image_base64"] = await _telegram_image_base64(photo_id)
        return _store_webhook_message(normalized, db, background_tasks)
    except WebhookPayloadError as exc:
        logger.warning("Rejected malformed Telegram update: %s", exc)
        return Response(status_code=204)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Telegram webhook processing failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Telegram update could not be processed.") from exc


@app.post("/webhooks/green-api")
async def green_api_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    expected_token = os.getenv("GREEN_API_WEBHOOK_TOKEN", "")
    if not expected_token:
        raise HTTPException(status_code=503, detail="GREEN-API webhook token is not configured.")
    if not constant_time_token_match(authorization, expected_token):
        raise HTTPException(status_code=401, detail="Unauthorized webhook.")
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return Response(status_code=204)
        normalized = normalize_green_message(payload, _message_hash_secret())
        if normalized is None:
            return Response(status_code=204)
        allowed_chat_id = os.getenv("GREEN_API_ALLOWED_CHAT_ID", "")
        if not allowed_chat_id:
            raise HTTPException(status_code=503, detail="WhatsApp chat allowlist is not configured.")
        if normalized["chat_id"] != allowed_chat_id:
            return Response(status_code=204)
        image_message_id = normalized.pop("green_image_message_id", None)
        if image_message_id:
            normalized["image_base64"] = await _green_image_base64(
                normalized["chat_id"], image_message_id
            )
        return _store_webhook_message(normalized, db, background_tasks)
    except WebhookPayloadError as exc:
        logger.warning("Rejected malformed GREEN-API event: %s", exc)
        return Response(status_code=204)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("GREEN-API webhook processing failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="GREEN-API event could not be processed.") from exc


@app.get("/api/alerts", response_model=List[Alert])
def get_alerts(
    level: Optional[str] = None,
    visibility: Literal["main", "off_topic", "all"] = "main",
    db: Session = Depends(get_db),
    _auth: Dict[str, Any] = Depends(require_dashboard_auth),
):
    """
    Returns full snapshot of alerts from the database.
    """
    query = db.query(MessageRecord)
    if visibility == "main":
        query = query.filter(MessageRecord.status != "OFF_TOPIC")
    elif visibility == "off_topic":
        query = query.filter(MessageRecord.status == "OFF_TOPIC")
    records = query.order_by(MessageRecord.timestamp.desc()).all()
    if is_public_demo_user(_auth):
        records = [rec for rec in records if is_demo_record(rec)]
    alerts = [serialize_to_alert_dict(rec) for rec in records]

    if level:
        alerts = [a for a in alerts if a.get("risk_level") == level]

    return alerts


@app.get("/api/alerts/{alert_id}", response_model=Alert)
def get_alert_detail(alert_id: str, db: Session = Depends(get_db), _auth: Dict[str, Any] = Depends(require_dashboard_auth)):
    """
    Returns single alert details by alert_id.
    """
    rec = _find_message(db, alert_id)
    if is_public_demo_user(_auth) and not is_demo_record(rec):
        raise HTTPException(status_code=404, detail="Alert not found.")
    return serialize_to_alert_dict(rec)


@app.get("/api/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db), _auth: Dict[str, Any] = Depends(require_dashboard_auth)):
    """
    Computes real-time message and alert statistics from the database.
    """
    all_messages = db.query(MessageRecord).all()
    if is_public_demo_user(_auth):
        all_messages = [rec for rec in all_messages if is_demo_record(rec)]
    since = utc_now() - timedelta(hours=24)

    pending = 0
    processing = 0
    errors = 0
    off_topic = 0
    by_level = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for m in all_messages:
        if m.status == "PENDING":
            pending += 1
        elif m.status == "PROCESSING":
            processing += 1
        elif m.status == "PROCESSED" and m.analysis and m.analysis.risk_level in by_level and m.analysis.risk_score is not None:
            by_level[m.analysis.risk_level] += 1
        elif m.status == "OFF_TOPIC":
            off_topic += 1
        else:
            errors += 1

    return {
        "total_messages": len(all_messages),
        "last_24h": sum(1 for m in all_messages if m.timestamp and m.timestamp >= since),
        "pending": pending,
        "processing": processing,
        "errors": errors,
        "off_topic": off_topic,
        "by_level": by_level,
    }


@app.get("/api/network-graph", response_model=Dict[str, Any])
def get_network_graph(db: Session = Depends(get_db), _auth: Dict[str, Any] = Depends(require_dashboard_auth)):
    """
    Returns graph and link analysis: bot clusters, cross-chat syndicates,
    and high-risk community clusters.
    """
    if is_public_demo_user(_auth):
        raise HTTPException(status_code=403, detail="This endpoint is unavailable to the read-only demo account.")
    return analyze_network_graph(db)


@app.post("/api/alerts/{alert_id}/review", response_model=Alert)
def update_review(alert_id: str, req: ReviewRequest, db: Session = Depends(get_db), _auth: Dict[str, Any] = Depends(require_dashboard_auth)):
    """
    Saves reviewer decision (NEW / REVIEWED / FALSE_POSITIVE) and reviewer_note in database.
    REVIEWED = analyst confirms the verdict (only confirmed verdicts escalate future risk scores);
    FALSE_POSITIVE = verdict rejected (excluded from sender/chat reputation).
    """
    if is_public_demo_user(_auth):
        raise HTTPException(status_code=403, detail="The demo account is read-only.")
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
            reviewed_by=req.reviewed_by,
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


@app.post("/api/alerts/{alert_id}/visibility", response_model=Alert)
def update_visibility(
    alert_id: str,
    req: VisibilityRequest,
    db: Session = Depends(get_db),
    _auth: Dict[str, Any] = Depends(require_dashboard_auth),
):
    """Hide or restore one analyzed message without changing its analysis or review."""
    if is_public_demo_user(_auth):
        raise HTTPException(status_code=403, detail="The demo account is read-only.")
    rec = _find_message(db, alert_id)
    if not rec.analysis or rec.analysis.risk_score is None or rec.analysis.risk_level is None:
        raise HTTPException(status_code=409, detail="Only analyzed messages can be hidden or restored.")
    if rec.status not in {"PROCESSED", "OFF_TOPIC"}:
        raise HTTPException(status_code=409, detail="The message is not ready for visibility changes.")
    rec.status = "OFF_TOPIC" if req.off_topic else "PROCESSED"
    db.commit()
    db.refresh(rec)
    return serialize_to_alert_dict(rec)


@app.post("/api/messages", response_model=MessageIngestResponse)
def ingest_message(req: MessageCreateRequest, request: Request, db: Session = Depends(get_db)):
    """
    Ingests raw message (text and/or image), saves to DB with status PENDING.
    Deduplication key: (platform, chat_id, message_id).
    With INLINE_ANALYSIS=1 the message is analysed immediately (atomic claim — never double-processed
    even if the background worker runs at the same time).
    """
    _require_ingest_authorization(request)
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


@app.post("/api/analyze-image", response_model=Alert)
def analyze_image_endpoint(req: ImageAnalyzeRequest, request: Request, db: Session = Depends(get_db)):
    """
    Multimodal AI endpoint: analyses payment screenshots, fake bank receipts or promo graphics.
    The upload is stored as a regular message + alert (visible in /api/alerts, stats, graph, export).
    """
    _require_ingest_authorization(request)
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
def get_media_file(filename: str, db: Session = Depends(get_db), _auth: Dict[str, Any] = Depends(require_dashboard_auth)):
    """Serves persisted images through the local or private R2 storage adapter."""
    if is_public_demo_user(_auth):
        records = db.query(MessageRecord).filter(MessageRecord.image_url == f"/api/media/{filename}").all()
        if not any(is_demo_record(rec) for rec in records):
            raise HTTPException(status_code=404, detail="Media not found.")
    try:
        data, mime = read_stored_image(filename)
    except MediaError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, no-store"})


@app.get("/api/export", response_model=Union[List[Alert], str])
def export_alerts(format: str = "json", db: Session = Depends(get_db), _auth: Dict[str, Any] = Depends(require_dashboard_auth)):
    """
    Exports surveillance dataset as JSON or CSV for regulatory / forensic reporting (АФМ / АРРФР).
    """
    records = db.query(MessageRecord).order_by(MessageRecord.timestamp.desc()).all()
    if is_public_demo_user(_auth):
        records = [rec for rec in records if is_demo_record(rec)]
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


# Private-chat submissions are dispatched through the shared Telegram webhook above.


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "ai_data.api_server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("UVICORN_RELOAD", "0") == "1",
    )
