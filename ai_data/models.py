from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


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


class AnalysisResult(BaseModel):
    risk_score: int = Field(..., ge=0, le=100, description="Risk score from 0 to 100")
    risk_level: RiskLevelEnum = Field(..., description="Risk category: LOW, MEDIUM, or HIGH")
    reasons: List[ReasonItem] = Field(default_factory=list, description="Identified pyramid traits with exact evidence")
    explanation: str = Field(..., description="Human-readable explanation in Russian or Kazakh")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence score")
    model_version: str = Field(default="safenet-analyzer-v1.0")
    image_text: Optional[str] = Field(default=None, description="Verbatim text transcribed from the attached image (OCR by the model)")


class Alert(BaseModel):
    """
    Combined Alert format conforming 100% to frontend docs/API.md and AlertSchema,
    with forward-compatible optional fields (chat_url, reviewed_by, image_url).
    """
    id: str
    platform: PlatformEnum
    chat_id: str
    chat_name: str
    chat_url: Optional[str] = None
    message_id: str
    sender_hash: str
    text: str
    image_url: Optional[str] = None
    timestamp: str  # ISO 8601 string with timezone offset
    status: StatusEnum = StatusEnum.PROCESSED
    risk_score: Optional[int] = Field(default=None, ge=0, le=100)
    risk_level: Optional[RiskLevelEnum] = None
    reasons: List[ReasonItem] = Field(default_factory=list)
    explanation: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    review_status: ReviewStatusEnum = ReviewStatusEnum.NEW
    reviewer_note: str = ""
    reviewed_by: Optional[str] = None
    model_version: str = "safenet-analyzer-v1.0"


class ReviewUpdateInput(BaseModel):
    review_status: ReviewStatusEnum
    reviewer_note: str = Field(default="", max_length=2000)
    reviewed_by: Optional[str] = Field(default=None, description="Analyst name or ID who reviewed this alert")
