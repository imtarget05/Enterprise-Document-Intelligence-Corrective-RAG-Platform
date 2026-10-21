package com.smartdocchat.service;

import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentIngestionJob;
import com.smartdocchat.entity.DocumentIngestionJob.JobStatus;
import com.smartdocchat.repository.DocumentIngestionJobRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * ADR-004 — durable ingestion queue: idempotent enqueue, poller wiring and
 * admin replay of the durable dead-letter state.
 */
@ExtendWith(MockitoExtension.class)
class DocumentJobServiceTest {

    @Mock private DocumentIngestionJobRepository jobRepository;
    @Mock private DocumentJobExecutor executor;

    private DocumentJobService service;

    @BeforeEach
    void setUp() {
        service = new DocumentJobService(jobRepository, executor);
        // @Value fields are not populated in plain Mockito tests — inject
        // production defaults explicitly (batch-size=10, stale-running-minutes=5).
        org.springframework.test.util.ReflectionTestUtils.setField(service, "batchSize", 10);
        org.springframework.test.util.ReflectionTestUtils.setField(service, "staleRunningMinutes", 5L);
    }

    private Document document(long id) {
        return Document.builder().id(id).fileName("report.txt")
                .ownerUsername("alice").fileType("txt").build();
    }

    @Test
    void enqueueCreatesPendingJobForNewDocument() {
        when(jobRepository.existsByDocumentIdAndJobTypeAndStatusIn(eq(7L), eq("WORKFLOW"), anyList()))
                .thenReturn(false);
        when(jobRepository.save(any(DocumentIngestionJob.class))).thenAnswer(inv -> inv.getArgument(0));

        DocumentIngestionJob job = service.enqueueWorkflowJob(document(7L), "report.txt");

        assertNotNull(job);
        assertEquals(JobStatus.PENDING, job.getStatus());
        assertEquals(7L, job.getDocumentId());
        assertEquals("WORKFLOW", job.getJobType());
        assertEquals("report.txt", job.getPayload());
        assertNotNull(job.getNextRunAt());
    }

    @Test
    void enqueueIsIdempotentWhenActiveJobAlreadyExists() {
        when(jobRepository.existsByDocumentIdAndJobTypeAndStatusIn(eq(7L), eq("WORKFLOW"), anyList()))
                .thenReturn(true);

        assertNull(service.enqueueWorkflowJob(document(7L), "report.txt"));
        verify(jobRepository, never()).save(any(DocumentIngestionJob.class));
    }

    @Test
    void pollRecoversStaleLeasesThenProcessesBatch() {
        when(jobRepository.requeueStaleRunningJobs(5L)).thenReturn(2);
        
        // Enable polling for this test
        ReflectionTestUtils.setField(service, "pollingEnabled", true);
        
        service.poll();

        verify(executor).processBatch(10);
    }

    @Test
    void replayDeadJobResetsToPendingWithAttemptsCleared() {
        DocumentIngestionJob dead = DocumentIngestionJob.builder()
                .id(3L).documentId(7L).status(JobStatus.DEAD).attempts(3).maxAttempts(3).build();
        when(jobRepository.findById(3L)).thenReturn(Optional.of(dead));

        DocumentIngestionJob replayed = service.replayDeadJob(3L);

        assertEquals(JobStatus.PENDING, replayed.getStatus());
        assertEquals(0, replayed.getAttempts());
        assertNotNull(replayed.getNextRunAt());
    }

    @Test
    void replayRejectsJobsThatAreNotDead() {
        DocumentIngestionJob pending = DocumentIngestionJob.builder()
                .id(4L).documentId(7L).status(JobStatus.PENDING).attempts(0).maxAttempts(3).build();
        when(jobRepository.findById(4L)).thenReturn(Optional.of(pending));

        assertThrows(IllegalStateException.class, () -> service.replayDeadJob(4L));
    }

    @Test
    void replayUnknownJobThrows() {
        when(jobRepository.findById(99L)).thenReturn(Optional.empty());

        assertThrows(IllegalArgumentException.class, () -> service.replayDeadJob(99L));
    }
}
