import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text as sql_text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

Base = declarative_base()

# Kazakhstan uses a single UTC+5 zone (since 2024-03-01). A fixed offset avoids a tzdata dependency on Windows.
KZ_TZ = timezone(timedelta(hours=5), name="Asia/Almaty")


# ---------------------------------------------------------------------------
# Time handling
# ---------------------------------------------------------------------------
def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Returns a timezone-aware UTC datetime. Naive values are interpreted as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_timestamp(value: Optional[str]) -> datetime:
    """
    Parses an ISO-8601 timestamp from the parser.
    - '...Z' / '+00:00' / '+05:00' offsets are honoured and converted to UTC.
    - A timestamp without an offset is interpreted as UTC (Telegram/WhatsApp APIs deliver UTC).
    - If value is None, defaults to current UTC time.
    - Empty or malformed strings raise ValueError.
    """
    if value is None:
        return datetime.now(timezone.utc)
    val = value.strip()
    if not val:
        raise ValueError("Timestamp string cannot be empty.")
    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
    return to_utc(dt)


def format_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """Serializes a datetime as ISO-8601 in Kazakhstan local time with a correct +05:00 offset."""
    if dt is None:
        return None
    return to_utc(dt).astimezone(KZ_TZ).isoformat()


class UTCDateTime(TypeDecorator):
    """
    Stores datetimes as naive UTC (SQLite has no timezone support) and always returns aware UTC.
    Any aware value (e.g. +05:00) is converted to UTC *before* the offset is dropped,
    so the wall-clock hours are never silently shifted.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return to_utc(value).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def make_message_pk(platform: str, chat_id: str, message_id: str) -> str:
    """
    Telegram/WhatsApp message ids are only unique *inside one chat*.
    The internal primary key is therefore derived from (platform, chat_id, message_id).
    """
    raw = f"{platform}\x1f{chat_id}\x1f{message_id}".encode("utf-8")
    return "m_" + hashlib.sha256(raw).hexdigest()[:32]


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------
class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("platform", "chat_id", "message_id", name="uq_messages_source"),
    )

    id = Column(String(64), primary_key=True)
    platform = Column(String(16), nullable=False)
    chat_id = Column(String(64), nullable=False, index=True)
    chat_name = Column(String(255), nullable=False, default="Общий чат")
    chat_url = Column(String(512), nullable=True)
    message_id = Column(String(64), nullable=False)
    sender_hash = Column(String(64), nullable=False, index=True)
    text = Column(Text, nullable=False, default="")
    image_url = Column(String(512), nullable=True)
    timestamp = Column(UTCDateTime, nullable=False, index=True)
    status = Column(String(16), nullable=False, default="PENDING", index=True)
    claimed_at = Column(UTCDateTime, nullable=True)
    claimed_by = Column(String(64), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(UTCDateTime, default=utc_now)

    analysis = relationship("AnalysisRecord", back_populates="message", uselist=False, cascade="all, delete-orphan")
    entities = relationship("EntityRecord", back_populates="message", cascade="all, delete-orphan")


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
    image_analyzed = Column(Integer, nullable=False, default=0)
    image_text = Column(Text, nullable=True)  # verbatim OCR of the attached image (source of image evidence)
    analyzed_at = Column(UTCDateTime, default=utc_now)

    message = relationship("MessageRecord", back_populates="analysis")
    review = relationship("ReviewRecord", back_populates="analysis", uselist=False, cascade="all, delete-orphan")


class ReviewRecord(Base):
    __tablename__ = "reviews"

    id = Column(String(64), primary_key=True)
    analysis_id = Column(String(64), ForeignKey("analyses.id"), nullable=False, unique=True)
    review_status = Column(String(32), nullable=False, default="NEW", index=True)
    reviewer_note = Column(Text, nullable=False, default="")
    reviewed_by = Column(String(128), nullable=True)
    created_at = Column(UTCDateTime, default=utc_now)
    updated_at = Column(UTCDateTime, default=utc_now, onupdate=utc_now)

    analysis = relationship("AnalysisRecord", back_populates="review")


class EntityRecord(Base):
    __tablename__ = "entities"

    id = Column(String(64), primary_key=True)
    message_id = Column(String(64), ForeignKey("messages.id"), nullable=False, index=True)
    entity_type = Column(String(32), nullable=False)
    # Comparison key. For cards this is a keyed hash of the FULL number, never the masked form.
    normalized_value = Column(String(255), nullable=False, index=True)
    # Human-readable, privacy-safe representation (e.g. masked card "4400 **** **** 1234").
    display_value = Column(String(255), nullable=True)
    created_at = Column(UTCDateTime, default=utc_now)

    message = relationship("MessageRecord", back_populates="entities")


class TelegramConsentRecord(Base):
    """Current Telegram processing consent keyed by a pseudonymous HMAC."""
    __tablename__ = "telegram_consents"

    user_hash = Column(String(64), primary_key=True)
    consent_version = Column(String(32), nullable=False, default="2026-10-25-v1")
    notice_shown_at = Column(UTCDateTime, nullable=True)
    consented_at = Column(UTCDateTime, nullable=True)
    revoked_at = Column(UTCDateTime, nullable=True)
    updated_at = Column(UTCDateTime, default=utc_now, onupdate=utc_now)


# ---------------------------------------------------------------------------
# Engine / lightweight migration
# ---------------------------------------------------------------------------
_ADDED_COLUMNS = {
    "messages": {
        "claimed_at": "TIMESTAMP",
        "claimed_by": "VARCHAR(64)",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "last_error": "TEXT",
        "chat_url": "VARCHAR(512)",
        "image_url": "VARCHAR(512)",
    },
    "analyses": {"image_analyzed": "INTEGER NOT NULL DEFAULT 0", "image_text": "TEXT"},
    "entities": {"display_value": "VARCHAR(255)"},
}


def _migrate(engine) -> None:
    """Adds columns introduced after the first release to an existing database (create_all does not)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in existing:
                    conn.execute(sql_text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    logger.info("Migrated: added %s.%s", table, name)
    try:
        with engine.begin() as conn:
            conn.execute(sql_text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_source_idx "
                "ON messages(platform, chat_id, message_id)"
            ))
    except Exception as e:  # pre-existing duplicates in an old DB
        logger.warning("Could not create unique (platform, chat_id, message_id) index: %s. Re-seed the DB.", e)


def validate_postgres_url(database_url: Optional[str]) -> str:
    """
    Validates that a PostgreSQL database URL is configured.
    SQLite is explicitly forbidden in runtime.
    """
    if not database_url or not database_url.strip():
        raise ValueError(
            "DATABASE_URL is not set. SafeNet KZ requires PostgreSQL. "
            "Set DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname in environment or .env."
        )
    url = database_url.strip()
    url_lower = url.lower()
    if not (url_lower.startswith("postgresql://") or url_lower.startswith("postgresql+") or url_lower.startswith("postgres://")):
        raise ValueError(
            f"Invalid DATABASE_URL scheme '{database_url}'. SafeNet KZ requires PostgreSQL. "
            "Expected format: postgresql+psycopg2://user:password@host:5432/dbname. SQLite is not allowed."
        )
    # SQLAlchemy 2.0 requires postgresql:// instead of the legacy postgres:// scheme
    if url_lower.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def init_db(database_url: Optional[str] = None):
    """
    Initializes PostgreSQL database tables and returns a session factory.
    SQLite is strictly disallowed in runtime.
    """
    raw_url = database_url or os.getenv("DATABASE_URL")
    url = validate_postgres_url(raw_url)

    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

    Base.metadata.create_all(engine)
    _migrate(engine)
    return sessionmaker(bind=engine)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize_to_alert_dict(message: MessageRecord) -> Dict[str, Any]:
    """
    Serializes a MessageRecord with its analysis and review into the exact Alert JSON structure expected by the frontend.
    """
    analysis = message.analysis
    review = analysis.review if analysis else None
    done = bool(
        analysis
        and message.status == "PROCESSED"
        and analysis.risk_score is not None
        and analysis.risk_level is not None
    )
    effective_status = message.status if (message.status != "PROCESSED" or done) else "ERROR"

    reasons = []
    if analysis and analysis.reasons_json:
        try:
            reasons = json.loads(analysis.reasons_json)
        except Exception:
            reasons = []

    return {
        # Internal id is unique across platforms/chats; message_id alone is not.
        "id": f"alert_{message.id}",
        "platform": message.platform,
        "chat_id": message.chat_id,
        "chat_name": message.chat_name,
        "chat_url": message.chat_url,
        "message_id": message.message_id,
        "sender_hash": message.sender_hash,
        "text": message.text,
        "image_url": message.image_url,
        "timestamp": format_timestamp(message.timestamp) or format_timestamp(utc_now()),
        "status": effective_status,
        "risk_score": analysis.risk_score if done else None,
        "risk_level": analysis.risk_level if done else None,
        "reasons": reasons if done else [],
        "explanation": analysis.explanation if done else "",
        "confidence": analysis.confidence if done else None,
        "image_analyzed": bool(analysis.image_analyzed) if done else False,
        "image_text": analysis.image_text if done else None,
        "error": message.last_error if message.status == "ERROR" else None,
        "review_status": review.review_status if review else "NEW",
        "reviewer_note": review.reviewer_note if review else "",
        "reviewed_by": review.reviewed_by if review else None,
        "model_version": analysis.model_version if analysis else "Не указана",
    }
