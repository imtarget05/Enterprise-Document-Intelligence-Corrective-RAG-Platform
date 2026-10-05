package com.smartdocchat.service;

import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentIngestionJob;
import com.smartdocchat.entity.DocumentIngestionJob.JobStatus;
import com.smartdocchat.repository.DocumentIngestionJobRepository;
import com.smartdocchat.repository.DocumentRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Executes durable ingestion jobs (ADR-004). Split from {@link DocumentJobService}
 * so claim/execute run through the Spring transaction proxy (no self-invocation):
 *
 * - claimBatch(): short transaction, SELECT ... FOR UPDATE SKIP LOCKED — safe
 *   when the backend scales to multiple instances.
 * - executeJob(): separate transaction per job — a crash mid-execution leaves
 *   the row RUNNING and the stale-lease requeue hands it back to the queue.
 * - Failures retry with exponential backoff (30s → 2m → 8m); after max
 *   attempts the job becomes DEAD (durable dead-letter state, replayable).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentJobExecutor {

    private static final long[] BACKOFF_SECONDS = {30, 120, 480};

    private final DocumentIngestionJobRepository jobRepository;
    private final DocumentRepository documentRepository;
    private final DocumentWorkflowClient documentWorkflowClient;

    /**
     * Claim a batch of due jobs (PENDING → RUNNING) and execute them one by one.
     * Called by the poller in DocumentJobService.
     */
    public void processBatch(int batchSize) {
        List<Long> claimedIds = claimBatch(batchSize);
        for (Long jobId : claimedIds) {
            executeJob(jobId);
        }
    }

    /** Short claim transaction — SKIP LOCKED makes concurrent pollers safe. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public List<Long> claimBatch(int limit) {
        Pageable pageable = PageRequest.of(0, Math.max(1, limit), Sort.by("id"));
        List<DocumentIngestionJob> jobs = jobRepository.findClaimable(pageable);
        jobs.forEach(job -> job.setStatus(JobStatus.RUNNING));
        return jobs.stream().map(DocumentIngestionJob::getId).toList();
    }

    /** One job per transaction: work → COMPLETED, failure → backoff/DEAD. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void executeJob(Long jobId) {
        DocumentIngestionJob job = jobRepository.findById(jobId).orElse(null);
        if (job == null || job.getStatus() != JobStatus.RUNNING) {
            return; // deleted or requeued concurrently — never double-execute
        }
        try {
            org.slf4j.MDC.put("jobId", String.valueOf(job.getId()));
            org.slf4j.MDC.put("documentId", String.valueOf(job.getDocumentId()));
            runWorkflow(job);
            job.setStatus(JobStatus.COMPLETED);
            job.setLastError(null);
            log.info("Ingestion job {} COMPLETED for document {}", job.getId(), job.getDocumentId());
        } catch (Exception e) {
            int attempt = job.getAttempts() + 1;
            job.setAttempts(attempt);
            String message = e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
            job.setLastError(message.length() > 1000 ? message.substring(0, 1000) : message);
            if (attempt >= job.getMaxAttempts()) {
                job.setStatus(JobStatus.DEAD);
                log.error("Ingestion job {} DEAD after {} attempts for document {}: {}",
                        job.getId(), attempt, job.getDocumentId(), job.getLastError());
            } else {
                long backoff = BACKOFF_SECONDS[Math.min(attempt - 1, BACKOFF_SECONDS.length - 1)];
                job.setStatus(JobStatus.PENDING);
                job.setNextRunAt(LocalDateTime.now().plusSeconds(backoff));
                log.warn("Ingestion job {} attempt {}/{} failed for document {} — retry in {}s: {}",
                        job.getId(), attempt, job.getMaxAttempts(), job.getDocumentId(), backoff, job.getLastError());
            }
        } finally {
            org.slf4j.MDC.remove("jobId");
            org.slf4j.MDC.remove("documentId");
        }
    }

    /**
     * The unit of work: run the llm-router document workflow over the durable
     * Document row. Throws on failure so retry machinery engages. Idempotent —
     * a document that already carries a workflow result is a no-op.
     */
    private void runWorkflow(DocumentIngestionJob job) {
        Document document = documentRepository.findById(job.getDocumentId()).orElse(null);
        if (document == null) {
            throw new IllegalStateException("Document " + job.getDocumentId() + " no longer exists");
        }
        if (document.getWorkflowResult() != null) {
            log.info("Document {} already has workflow result — job {} no-op", job.getDocumentId(), job.getId());
            return;
        }
        String extractedText = document.getChunks() != null ? stripChunkJson(document.getChunks()) : null;
        String result = documentWorkflowClient.runWorkflow(extractedText, document.getFileName());
        if (result == null) {
            throw new IllegalStateException("llm-router workflow unavailable or rejected the request");
        }
        document.setWorkflowResult(result);
        log.debug("Document {} async workflow completed (job {})", job.getDocumentId(), job.getId());
    }

    /** chunks JSON "[\"a\",\"b\"]" → "a b" (job stores only the document id). */
    private String stripChunkJson(String chunksJson) {
        return chunksJson.replace('[', ' ').replace(']', ' ')
                .replace("\",\"", " ").replace("\"", "").trim();
    }
}
