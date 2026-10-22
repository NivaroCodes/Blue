import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Text,
    create_engine,
    Enum as SQLEnum
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class MessageRecord(Base):
    __tablename__ = "messages"

    id = Column(String(64), primary_key=True)
    platform = Column(String(16), nullable=False)
    chat_id = Column(String(64), nullable=False, index=True)
    chat_name = Column(String(255), nullable=False, default="Общий чат")
    chat_url = Column(String(512), nullable=True)
    message_id = Column(String(64), nullable=False)
    sender_hash = Column(String(64), nullable=False)
    text = Column(Text, nullable=False)
    image_url = Column(String(512), nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    status = Column(String(16), nullable=False, default="PENDING", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    analysis = relationship("AnalysisRecord", back_populates="message", uselist=False, cascade="all, delete-orphan")


class AnalysisRecord(Base):
    __tablename__ = "analyses"

    id = Column(String(64), primary_key=True)
    message_id = Column(String(64), ForeignKey("messages.id"), nullable=False, unique=True)
    risk_score = Column(Integer, nullable=True)
    risk_level = Column(String(16), nullable=True, index=True)
    reasons_json = Column(Text, nullable=False, default="[]")
    explanation = Column(Text, nullable=False, default="")
    confidence = Column(Float, nullable=True)
    model_version = Column(String(64), nullable=False, default="safenet-analyzer-v1.0")
    analyzed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    message = relationship("MessageRecord", back_populates="analysis")
    review = relationship("ReviewRecord", back_populates="analysis", uselist=False, cascade="all, delete-orphan")


class ReviewRecord(Base):
    __tablename__ = "reviews"

    id = Column(String(64), primary_key=True)
    analysis_id = Column(String(64), ForeignKey("analyses.id"), nullable=False, unique=True)
    review_status = Column(String(32), nullable=False, default="NEW", index=True)
    reviewer_note = Column(Text, nullable=False, default="")
    reviewed_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    analysis = relationship("AnalysisRecord", back_populates="review")


class EntityRecord(Base):
    __tablename__ = "entities"

    id = Column(String(64), primary_key=True)
    message_id = Column(String(64), ForeignKey("messages.id"), nullable=False)
    entity_type = Column(String(32), nullable=False)
    normalized_value = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db(database_url: str = "sqlite:///safenet.db"):
    """
    Initializes database tables.
    """
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def serialize_to_alert_dict(message: MessageRecord) -> Dict[str, Any]:
    """
    Serializes a MessageRecord with its analysis and review into the exact Alert JSON structure expected by the frontend.
    """
    analysis = message.analysis
    review = analysis.review if analysis else None

    reasons = []
    if analysis and analysis.reasons_json:
        try:
            reasons = json.loads(analysis.reasons_json)
        except Exception:
            reasons = []

    iso_ts = message.timestamp.isoformat() if message.timestamp else datetime.now(timezone.utc).isoformat()
    # Ensure timezone offset is included if missing
    if "+" not in iso_ts and not iso_ts.endswith("Z"):
        iso_ts += "+05:00"

    return {
        "id": f"alert_{message.message_id}",
        "platform": message.platform,
        "chat_id": message.chat_id,
        "chat_name": message.chat_name,
        "chat_url": message.chat_url,
        "message_id": message.message_id,
        "sender_hash": message.sender_hash,
        "text": message.text,
        "image_url": message.image_url,
        "timestamp": iso_ts,
        "status": message.status,
        "risk_score": analysis.risk_score if (analysis and message.status == "PROCESSED") else None,
        "risk_level": analysis.risk_level if (analysis and message.status == "PROCESSED") else None,
        "reasons": reasons if (analysis and message.status == "PROCESSED") else [],
        "explanation": analysis.explanation if (analysis and message.status == "PROCESSED") else "",
        "confidence": analysis.confidence if (analysis and message.status == "PROCESSED") else None,
        "review_status": review.review_status if review else "NEW",
        "reviewer_note": review.reviewer_note if review else "",
        "reviewed_by": review.reviewed_by if review else None,
        "model_version": analysis.model_version if analysis else "Не указана"
    }
