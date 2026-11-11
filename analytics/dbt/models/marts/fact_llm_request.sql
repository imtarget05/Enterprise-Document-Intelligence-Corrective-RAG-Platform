select * from {{ ref('stg_events') }} where event_type='llm_request'
