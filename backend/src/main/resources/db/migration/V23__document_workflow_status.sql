-- Match Document.workflowStatus so a clean database passes Hibernate validation.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS workflow_status VARCHAR(20);
