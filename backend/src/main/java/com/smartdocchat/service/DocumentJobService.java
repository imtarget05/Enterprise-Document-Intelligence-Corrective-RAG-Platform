package com.smartdocchat.service;

import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentIngestionJob;
import com.smartdocchat.entity.DocumentIngestionJob.JobStatus;
import com.smartdocchat.repository.DocumentIngestionJobRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Durable document-ingestion job queue (ADR-004).
 *
 * Replaces the fire-and-forget CompletableFuture.runAsync workflow call with a
 * DB-backed queue on top of PostgreSQL:
 *
 * - enqueueWorkflowJob(): idempotent — one active job per (document, type),
 *   enforced by a partial unique index; safe against duplicate enqueues.
 * - poll(): recovers stale RUNNING leases (worker crash recovery), then hands
 *   over to {@link DocumentJobExecutor} which claims PENDING rows with
 *   SELECT ... FOR UPDATE SKIP LOCKED (safe to scale horizontally) and executes
 *   each job OUTSIDE the claim transaction.
 * - Failures retry with exponential backoff (30s → 2m → 8m); after max
 *   attempts the job becomes DEAD — the durable dead-letter state — replayable
 *   by an admin via /admin/ingestion-jobs/{id}/replay.
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentJobService {

    static final String JOB_TYPE_WORKFLOW = "WORKFLOW";

    private final DocumentIngestionJobRepository jobRepository;
    private final DocumentJobExecutor executor;

    @Value("${ingestion-jobs.batch-size:10}")
    private int batchSize;

    @Value("${ingestion-jobs.stale-running-minutes:5}")
    private long staleRunningMinutes;

    @Value("${job.polling.enabled:false}")
    private boolean pollingEnabled;

    @Value("${ingestion-jobs.poll-interval-ms:5000}")
    private long pollIntervalMs;

    @Value("${ingestion-jobs.initial-delay-ms:10000}")
    private long initialDelayMs;

    /**
     * Enqueue a document-workflow job. Idempotent: when an active job already
     * exists for the document, nothing is enqueued and null is returned.
     */
    @Transactional
    public DocumentIngestionJob enqueueWorkflowJob(Document document, String payload) {
        boolean active = jobRepository.existsByDocumentIdAndJobTypeAndStatusIn(
                document.getId(), JOB_TYPE_WORKFLOW,
                List.of(DocumentIngestionJob.JobStatus.PENDING, DocumentIngestionJob.JobStatus.RUNNING));
        if (active) {
            log.info("Workflow job already active for document {} — enqueue skipped (idempotent)",
                    document.getId());
            return null;
        }
        DocumentIngestionJob job = DocumentIngestionJob.builder()
                .documentId(document.getId())
                .jobType(JOB_TYPE_WORKFLOW)
                .payload(payload != null && payload.length() > 500 ? payload.substring(0, 500) : payload)
                .status(DocumentIngestionJob.JobStatus.PENDING)
                .nextRunAt(LocalDateTime.now())
                .build();
        DocumentIngestionJob saved = jobRepository.save(job);
        log.info("Enqueued ingestion job id={} for document {}", saved.getId(), document.getId());
        return saved;
    }

    /**
     * Poller tick: recover stale RUNNING leases (worker crash recovery), then
     * process a batch of due jobs. Claim and execute happen in separate
     * transactions inside the executor bean (proxy — self-invocation safe).
     *
     * @deprecated Replaced by Kafka event-driven consumers (DocumentIngestionConsumer,
     * DocumentClassificationConsumer, WorkflowCompletionConsumer).
     * This method is kept for backward compatibility and can be enabled via
     * {@code job.polling.enabled=true} property (default: false).
     */
    @Deprecated(since = "1.4", forRemoval = true)
    @Scheduled(fixedDelayString = "${ingestion-jobs.poll-interval-ms:5000}",
            initialDelayString = "${ingestion-jobs.initial-delay-ms:10000}")
    public void poll() {
        if (!pollingEnabled) {
            log.debug("Polling is disabled (job.polling.enabled=false). Skipping poll.");
            return;
        }
        int recovered = jobRepository.requeueStaleRunningJobs(staleRunningMinutes);
        if (recovered > 0) {
            log.warn("Requeued {} stale RUNNING ingestion jobs (worker crash recovery)", recovered);
        }
        executor.processBatch(batchSize);
    }

    /**
     * Admin replay: DEAD → PENDING with attempts reset; the poller picks it up
     * on the next tick (durable DLQ replay).
     */
    @Transactional
    public DocumentIngestionJob replayDeadJob(Long jobId) {
        DocumentIngestionJob job = jobRepository.findById(jobId)
                .orElseThrow(() -> new IllegalArgumentException("Job " + jobId + " not found"));
        if (job.getStatus() != DocumentIngestionJob.JobStatus.DEAD) {
            throw new IllegalStateException(
                    "Only DEAD jobs can be replayed (job " + jobId + " is " + job.getStatus() + ")");
        }
        job.setStatus(DocumentIngestionJob.JobStatus.PENDING);
        job.setAttempts(0);
        job.setNextRunAt(LocalDateTime.now());
        log.info("Ingestion job {} replayed by admin → PENDING", jobId);
        return job;
    }

    public Page<DocumentIngestionJob> listByStatus(DocumentIngestionJob.JobStatus status, int page, int size) {
        int safeSize = Math.min(Math.max(size, 1), 200);
        Pageable pageable = PageRequest.of(Math.max(page, 0), safeSize,
                Sort.by(Sort.Direction.DESC, "updatedAt"));
        return jobRepository.findByStatus(status, pageable);
    }
}

