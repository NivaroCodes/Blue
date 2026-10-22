-- SafeNet KZ: Database Schema (SQLite / PostgreSQL compatible)
-- Stop-Pyramid Monitoring System

-- 1. Table: messages
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL CHECK(platform IN ('telegram', 'whatsapp')),
    chat_id TEXT NOT NULL,
    chat_name TEXT NOT NULL DEFAULT 'Общий чат',
    message_id TEXT NOT NULL,
    sender_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'ERROR')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);

-- 2. Table: analyses
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
    risk_score INTEGER CHECK(risk_score >= 0 AND risk_score <= 100),
    risk_level TEXT CHECK(risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    explanation TEXT NOT NULL DEFAULT '',
    confidence REAL CHECK(confidence >= 0.0 AND confidence <= 1.0),
    model_version TEXT NOT NULL DEFAULT 'safenet-analyzer-v1.0',
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analyses_risk_level ON analyses(risk_level);
CREATE INDEX IF NOT EXISTS idx_analyses_risk_score ON analyses(risk_score);

-- 3. Table: reviews
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL UNIQUE REFERENCES analyses(id) ON DELETE CASCADE,
    review_status TEXT NOT NULL DEFAULT 'NEW' CHECK(review_status IN ('NEW', 'REVIEWED', 'FALSE_POSITIVE')),
    reviewer_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(review_status);

-- 4. Table: entities (for tracking repeated domains, cards, phone numbers, crypto addresses)
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('PHONE', 'CARD', 'CRYPTO', 'URL', 'TELEGRAM_HANDLE')),
    normalized_value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(normalized_value);
