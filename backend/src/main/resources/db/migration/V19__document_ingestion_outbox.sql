CREATE TABLE document_outbox (
    id VARCHAR(36) PRIMARY KEY,
    document_id BIGINT NOT NULL,
    document_version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status VARCHAR(255) NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP,
    last_error VARCHAR(1000),
    UNIQUE (document_id, document_version)
);
CREATE INDEX idx_document_outbox_pending ON document_outbox(status, next_attempt_at);
ALTER TABLE documents ADD COLUMN last_ingested_version INTEGER;
ALTER TABLE documents ADD COLUMN last_ingestion_event_id VARCHAR(36);
