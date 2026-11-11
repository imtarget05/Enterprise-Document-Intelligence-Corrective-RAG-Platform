select distinct tenant_id,model from {{ ref('stg_events') }} where model is not null
