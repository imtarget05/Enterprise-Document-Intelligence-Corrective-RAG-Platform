select distinct tenant_id,entity_id as document_id from {{ ref('stg_events') }} where event_type='ingestion'
