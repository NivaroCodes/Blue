from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_serializer


class PlatformEnum(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class RiskLevelEnum(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class StatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    ERROR = "ERROR"


class ReviewStatusEnum(str, Enum):
    NEW = "NEW"
    REVIEWED = "REVIEWED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class ReasonCodeEnum(str, Enum):
    UNREALISTIC_RETURN = "UNREALISTIC_RETURN"
    MONEY_REQUEST = "MONEY_REQUEST"
    REFERRAL = "REFERRAL"
    URGENCY = "URGENCY"
    PERSONAL_TRANSFER = "PERSONAL_TRANSFER"
    GUARANTEED_PROFIT = "GUARANTEED_PROFIT"


REASON_LABELS = {
    ReasonCodeEnum.UNREALISTIC_RETURN.value: "Нереалистичная доходность",
    ReasonCodeEnum.MONEY_REQUEST.value: "Запрос вложений",
    ReasonCodeEnum.REFERRAL.value: "Привлечение участников",
    ReasonCodeEnum.URGENCY.value: "Давление и срочность",
    ReasonCodeEnum.PERSONAL_TRANSFER.value: "Перевод на личную карту",
    ReasonCodeEnum.GUARANTEED_PROFIT.value: "Гарантия прибыли",
}


class ReasonItem(BaseModel):
    code: str = Field(..., description="Machine-readable code corresponding to ReasonCodeEnum or custom code")
    evidence: str = Field(..., description="EXACT substring from the original text (critical for frontend highlighting)")
    source: str = Field(default="text", description="'text' = quote from message text (highlightable); 'image' = quote from OCR of the attached image")

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        d = handler(self)
        if isinstance(d, dict) and d.get("source") == "text":
            d.pop("source", None)
        return d


class MessageInput(BaseModel):
    platform: PlatformEnum = Field(default=PlatformEnum.TELEGRAM)
    chat_id: str
    chat_name: str = "Общий чат"
    chat_url: Optional[str] = Field(default=None, description="Optional link/URL to the Telegram or WhatsApp chat")
    message_id: str
    sender_hash: str
    text: str
    image_base64: Optional[str] = Field(default=None, description="Optional base64 screenshot (e.g. fake Kaspi check, payout proof)")
    image_url: Optional[str] = Field(default=None, description="Optional URL to the screenshot/media file")
    timestamp: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("timestamp", mode="before")
    def parse_timestamp(cls, v):
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        if isinstance(v, datetime):
            return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
        return v


def compute_calibrated_confidence(
    risk_level: RiskLevelEnum,
    reasons_count: int,
    text: Optional[str] = None,
    raw_model_confidence: Optional[float] = None,
    has_image: bool = False,
) -> float:
    """
    Computes an uncalibrated heuristic measure of signal clarity and context sufficiency
    for the assigned classification tier (bounded within [0.0, 0.95]).

    Semantics:
    - HIGH with multiple (>=2) corroborating signals: 0.85 - 0.95 (strong multi-signal corroboration)
    - HIGH with 1 signal: 0.70 - 0.80 (elevated risk with limited single-signal corroboration)
    - MEDIUM (inherent grey-zone uncertainty, isolated or conflicting signals): 0.45 - 0.65
    - LOW with sufficient informative context (>=15 chars, >=3 words): 0.75 - 0.85 (context is sufficient to rule out scam)
    - LOW with sparse / fragmentary input (<15 chars, <3 words): 0.30 - 0.45 (insufficient data for firm conclusion)
    """
    clean_text = (text or "").strip()
    words = clean_text.split()
    is_sparse = len(clean_text) < 15 or len(words) < 3

    if risk_level == RiskLevelEnum.HIGH:
        if reasons_count >= 2:
            base = 0.90
            if raw_model_confidence is not None:
                base = (base + float(raw_model_confidence)) / 2
            return round(min(0.95, max(0.85, base)), 2)
        else:
            base = 0.75
            if raw_model_confidence is not None:
                base = (base + float(raw_model_confidence)) / 2
            return round(min(0.80, max(0.70, base)), 2)

    elif risk_level == RiskLevelEnum.MEDIUM:
        # Inherent ambiguity of the medium tier
        base = 0.55
        if raw_model_confidence is not None:
            base = (base + float(raw_model_confidence)) / 2
        return round(min(0.65, max(0.45, base)), 2)

    else:  # LOW
        if is_sparse and not has_image:
            # Data is sparse/fragmentary — low confidence in excluding risk
            return 0.35
        base = 0.80
        if raw_model_confidence is not None:
            base = (base + float(raw_model_confidence)) / 2
        return round(min(0.85, max(0.70, base)), 2)


class AnalysisResult(BaseModel):
    risk_score: int = Field(..., ge=0, le=100, description="Risk score from 0 to 100")
    risk_level: RiskLevelEnum = Field(..., description="Risk category: LOW, MEDIUM, or HIGH")
    reasons: List[ReasonItem] = Field(default_factory=list, description="Identified pyramid traits with exact evidence")
    explanation: str = Field(..., description="Human-readable explanation in Russian or Kazakh")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Heuristic measure of signal clarity and context sufficiency (0.0-0.95)")
    model_version: str = Field(default="safenet-analyzer-v1.0")
    image_text: Optional[str] = Field(default=None, description="Verbatim text transcribed from the attached image (OCR by the model)")


class Alert(BaseModel):
    """
    Combined Alert format conforming 100% to frontend docs/API.md and AlertSchema,
    with forward-compatible optional fields (chat_url, reviewed_by, image_url).
    """
    id: str = Field(..., description="Unique alert identifier, e.g. 'alert_telegram_chat123_456'")
    platform: PlatformEnum = Field(..., description="Platform identifier: telegram or whatsapp")
    chat_id: str = Field(..., description="Chat ID")
    chat_name: str = Field(default="Общий чат", description="Human-readable chat title")
    chat_url: Optional[str] = Field(default=None, description="Direct URL or link to the chat")
    message_id: str = Field(..., description="Message ID within the chat")
    sender_hash: str = Field(..., description="Anonymized hash of sender account/phone")
    text: str = Field(default="", description="Original message text")
    image_url: Optional[str] = Field(default=None, description="URL of attached screenshot/media")
    timestamp: str = Field(..., description="ISO 8601 string with timezone offset (+05:00)")
    status: StatusEnum = Field(default=StatusEnum.PROCESSED, description="Processing status: PENDING, PROCESSING, PROCESSED, ERROR")
    risk_score: Optional[int] = Field(default=None, ge=0, le=100, description="Risk score 0-100 (null if unanalyzed or error)")
    risk_level: Optional[RiskLevelEnum] = Field(default=None, description="Risk tier: LOW, MEDIUM, HIGH (null if unanalyzed or error)")
    reasons: List[ReasonItem] = Field(default_factory=list, description="Detected financial risk indicators with exact quotes")
    explanation: str = Field(default="", description="Objective structured analytical rationale and verification recommendations")
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Heuristic measure of signal clarity and context sufficiency for the assigned risk tier (0.0–0.95; uncalibrated, not a statistical or legal probability of guilt)"
    )
    image_analyzed: Optional[bool] = Field(default=False, description="Whether an attached image was OCR-analyzed")
    image_text: Optional[str] = Field(default=None, description="OCR text extracted from image if present")
    error: Optional[str] = Field(default=None, description="Error detail if status is ERROR")
    review_status: ReviewStatusEnum = Field(default=ReviewStatusEnum.NEW, description="Analyst review state: NEW, REVIEWED, FALSE_POSITIVE")
    reviewer_note: str = Field(default="", max_length=2000, description="Analyst notes and rationale")
    reviewed_by: Optional[str] = Field(default=None, description="Analyst identity or ID")
    model_version: str = Field(default="safenet-analyzer-v1.0", description="Analyzer version or model identifier")


class ReviewUpdateInput(BaseModel):
    review_status: ReviewStatusEnum = Field(..., description="Analyst review verdict: NEW, REVIEWED, or FALSE_POSITIVE")
    reviewer_note: str = Field(default="", max_length=2000, description="Analyst rationale or notes")
    reviewed_by: Optional[str] = Field(default=None, description="Analyst name or ID who reviewed this alert")


class StatsByLevel(BaseModel):
    HIGH: int = Field(default=0, ge=0, description="Number of PROCESSED alerts with HIGH risk level")
    MEDIUM: int = Field(default=0, ge=0, description="Number of PROCESSED alerts with MEDIUM risk level")
    LOW: int = Field(default=0, ge=0, description="Number of PROCESSED alerts with LOW risk level")


class StatsResponse(BaseModel):
    total_messages: int = Field(..., ge=0, description="Total ingested messages across all statuses")
    last_24h: int = Field(..., ge=0, description="Messages ingested in the last 24 hours")
    pending: int = Field(..., ge=0, description="Messages currently waiting in the processing queue")
    processing: int = Field(..., ge=0, description="Messages currently being analyzed by AI workers")
    errors: int = Field(..., ge=0, description="Messages that failed analysis or have invalid structure")
    by_level: StatsByLevel = Field(..., description="Breakdown of successfully processed messages by risk level")


class MessageIngestResponse(BaseModel):
    id: str = Field(..., description="Internal alert identifier (e.g. alert_telegram_c1_m1)")
    message_id: str = Field(..., description="Original platform message ID")
    status: str = Field(..., description="Current message processing status (e.g. PENDING, PROCESSED)")
