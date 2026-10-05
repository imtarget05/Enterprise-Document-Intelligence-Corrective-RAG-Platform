-- V22: Drop the video_jobs queue (video pipeline scope removed).
--
-- V19/V20 created video_jobs for the standalone video-worker. That scope was
-- deleted, so fresh databases must never see the table, while databases that
-- already applied V19/V20 get it dropped cleanly. Flyway has no down
-- migrations by design, hence this forward guarded drop.
--
-- Guarded with IF EXISTS: no-op on fresh databases. The dependent partial
-- unique index (V19) is dropped first, also guarded.

DROP INDEX IF EXISTS idx_video_jobs_active_source;

DROP TABLE IF EXISTS video_jobs;
