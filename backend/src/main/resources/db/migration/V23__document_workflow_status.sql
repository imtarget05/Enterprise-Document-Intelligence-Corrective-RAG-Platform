-- Persist the status of the document classification/extraction workflow.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS workflow_status VARCHAR(20);
