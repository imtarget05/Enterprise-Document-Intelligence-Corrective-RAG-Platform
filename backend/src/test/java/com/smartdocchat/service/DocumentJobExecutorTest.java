package com.smartdocchat.service;

import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentIngestionJob;
import com.smartdocchat.entity.DocumentIngestionJob.JobStatus;
import com.smartdocchat.repository.DocumentIngestionJobRepository;
import com.smartdocchat.repository.DocumentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Pageable;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * ADR-004 — job executor: SKIP LOCKED claim semantics, retry with exponential
 * backoff, durable dead-letter transition, idempotent work execution.
 */
@ExtendWith(MockitoExtension.class)
class DocumentJobExecutorTest {

    @Mock private DocumentIngestionJobRepository jobRepository;
    @Mock private DocumentRepository documentRepository;
    @Mock private DocumentWorkflowClient documentWorkflowClient;
    @Mock private DocumentEventPublisher eventPublisher;

    private DocumentJobExecutor executor;

    @BeforeEach
    void setUp() {
        executor = new DocumentJobExecutor(jobRepository, documentRepository, documentWorkflowClient, eventPublisher);
    }

    private DocumentIngestionJob job(long id, long docId, JobStatus status, int attempts) {
        return DocumentIngestionJob.builder()
                .id(id).documentId(docId).jobType("WORKFLOW").status(status)
                .attempts(attempts).maxAttempts(3)
                .nextRunAt(LocalDateTime.now()).build();
    }

    private Document document(String chunks) {
        return Document.builder().id(10L).fileName("report.txt").ownerUsername("alice")
                .fileType("txt").chunks(chunks).build();
    }

    @Test
    void claimBatchFlipsPendingJobsToRunningAndReturnsIds() {
        DocumentIngestionJob j1 = job(1L, 10L, JobStatus.PENDING, 0);
        DocumentIngestionJob j2 = job(2L, 11L, JobStatus.PENDING, 0);
        when(jobRepository.findClaimable(any(Pageable.class))).thenReturn(List.of(j1, j2));

        List<Long> ids = executor.claimBatch(10);

        assertEquals(List.of(1L, 2L), ids);
        assertEquals(JobStatus.RUNNING, j1.getStatus());
        assertEquals(JobStatus.RUNNING, j2.getStatus());
    }

    @Test
    void executeJobCompletesAndStoresWorkflowResult() {
        DocumentIngestionJob running = job(1L, 10L, JobStatus.RUNNING, 1);
        Document doc = document("[\"chunk one\",\"chunk two\"]");
        when(jobRepository.findById(1L)).thenReturn(Optional.of(running));
        when(documentRepository.findById(10L)).thenReturn(Optional.of(doc));
        when(documentWorkflowClient.runWorkflow(eq("chunk one chunk two"), eq("report.txt")))
                .thenReturn("{\"classification\":\"invoice\"}");

        executor.executeJob(1L);

        assertEquals(JobStatus.COMPLETED, running.getStatus());
        assertNull(running.getLastError());
        assertEquals("{\"classification\":\"invoice\"}", doc.getWorkflowResult());
    }

    @Test
    void executeJobRequeuesWithBackoffOnTransientFailure() {
        DocumentIngestionJob running = job(1L, 10L, JobStatus.RUNNING, 0);
        Document doc = document(null);
        when(jobRepository.findById(1L)).thenReturn(Optional.of(running));
        when(documentRepository.findById(10L)).thenReturn(Optional.of(doc));
        when(documentWorkflowClient.runWorkflow(isNull(), eq("report.txt"))).thenReturn(null);

        LocalDateTime before = LocalDateTime.now();
        executor.executeJob(1L);

        assertEquals(JobStatus.PENDING, running.getStatus(), "attempt 1 of 3 must return to PENDING");
        assertEquals(1, running.getAttempts());
        assertNotNull(running.getLastError());
        assertTrue(running.getNextRunAt().isAfter(before.plusSeconds(25)),
                "first retry must be scheduled ~30s out (exponential backoff)");
    }

    @Test
    void executeJobDeadLettersAfterMaxAttempts() {
        DocumentIngestionJob running = job(1L, 10L, JobStatus.RUNNING, 2);
        Document doc = document(null);
        when(jobRepository.findById(1L)).thenReturn(Optional.of(running));
        when(documentRepository.findById(10L)).thenReturn(Optional.of(doc));
        when(documentWorkflowClient.runWorkflow(isNull(), eq("report.txt"))).thenReturn(null);

        executor.executeJob(1L);

        assertEquals(JobStatus.DEAD, running.getStatus(), "attempt 3 of 3 must dead-letter");
        assertEquals(3, running.getAttempts());
    }

    @Test
    void missingDocumentIsRecordedAsJobFailure() {
        DocumentIngestionJob running = job(1L, 10L, JobStatus.RUNNING, 0);
        when(jobRepository.findById(1L)).thenReturn(Optional.of(running));
        when(documentRepository.findById(10L)).thenReturn(Optional.empty());

        executor.executeJob(1L);

        assertEquals(JobStatus.PENDING, running.getStatus());
        assertTrue(running.getLastError().contains("no longer exists"));
    }

    @Test
    void alreadyProcessedDocumentIsAnIdempotentNoOp() {
        DocumentIngestionJob running = job(1L, 10L, JobStatus.RUNNING, 1);
        Document doc = document(null);
        doc.setWorkflowResult("{\"done\":true}");
        when(jobRepository.findById(1L)).thenReturn(Optional.of(running));
        when(documentRepository.findById(10L)).thenReturn(Optional.of(doc));

        executor.executeJob(1L);

        assertEquals(JobStatus.COMPLETED, running.getStatus());
        verify(documentWorkflowClient, never()).runWorkflow(any(), anyString());
    }

    @Test
    void unknownJobIdIsIgnoredWithoutWork() {
        when(jobRepository.findById(1L)).thenReturn(Optional.empty());

        executor.executeJob(1L);

        verify(documentWorkflowClient, never()).runWorkflow(any(), anyString());
    }
}
