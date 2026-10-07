# DR Runbook — Smart Document Chatbot

## Backup (daily 02:00 UTC)

```bash
0 2 * * * /app/scripts/backup.sh /backups >> /var/log/backup.log 2>&1
```

- Postgres: `pg_dump NEON_DATABASE_URL | gzip > pg_YYYYMMDD.sql.gz` (PITR enabled on Neon)
- Qdrant: `POST /collections/{documents,supply_chain}/snapshots` (retain 7 days)
- R2: versioning enabled, lifecycle 30d

Artifacts: `/backups/pg_*.sql.gz` + Qdrant snapshots on `qdrant:6333/snapshots`

## Restore

```bash
./scripts/restore.sh backups/pg_20250101_020000.sql.gz
# Qdrant: curl -X POST http://qdrant:6333/collections/documents/snapshots/recover -H "api-key: $QDRANT_API_KEY" --data-binary @snapshot
```

Verify: `psql $NEON_DATABASE_URL -c "select count(*) from documents;"` + `curl $QDRANT_HOST:6333/collections/documents`

## RTO/RPO

- RTO 1h, RPO 24h (daily backup). For RPO 1h, enable Neon logical replication or wal-g.

## Incident

1. Detect via `BackendDown` / `SloBurnFast` alert (PagerDuty/Slack).
2. Check `render.yaml` health: `curl https://smartdoc-backend-2hhz.onrender.com/api/actuator/health`
3. If DB down: promote Neon read-replica or restore from latest `pg_*.sql.gz`.
4. If Qdrant down: recover from snapshot, re-index from Postgres `document_chunks`.
5. Verify `docs/render-smoke-test.md` curl checks.
6. Postmortem within 48h.

## Drill

Quarterly: restore to staging, run `eval/golden_dataset.json` 50 cases, assert retrieval 100% and LLM Judge avg >0.75.

## Multi-region (future)

Neon cross-region read-replica + Qdrant Cloud multi-region (Singapore + Frankfurt). Render region pin to `singapore` now, migrate to `frankfurt` replica when needed. See `render.yaml` env `QDRANT_HOST` override.
