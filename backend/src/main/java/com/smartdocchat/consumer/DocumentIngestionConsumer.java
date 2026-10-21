package com.smartdocchat.consumer;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentClassifiedEvent;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.DocumentIngestedEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.event.WorkflowCompletedEvent;
import com.smartdocchat.service.DocumentEventPublisher;
import com.smartdocchat.service.DocumentService;
import com.smartdocchat.service.DocumentWorkflowClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.annotation.RetryableTopic;
import org.springframework.kafka.retrytopic.DltStrategy;
import org.springframework.kafka.support.KafkaHeaders;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.retry.annotation.Backoff;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

/**
 * Consumer for document ingestion events.
 * Listens to the document-ingestion topic and triggers the document workflow.
 * On success, emits DocumentClassifiedEvent.
 * On failure, emits WorkflowCompletedEvent with FAILED status.
 * Uses @RetryableTopic with DLQ for resilience (max 3 attempts, exponential backoff).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentIngestionConsumer {

    private final DocumentService documentService;
    private final DocumentWorkflowClient documentWorkflowClient;
    private final DocumentEventPublisher eventPublisher;
    private final KafkaProperties kafkaProperties;
    private final SearchResultCache searchResultCache;

    // Configuration for retry (can be externalized via @Value if needed)
    private int maxAttempts = 3;
    private long backoffDelay = 1000L;
    private double backoffMultiplier = 2.0;

    /**
     * Handles DocumentIngestedEvent from the document-ingestion topic.
     * Triggers the document workflow via DocumentWorkflowClient.
     * On success: publishes DocumentClassifiedEvent with extracted classification data.
     * On failure: publishes WorkflowCompletedEvent with FAILED status.
     *
     * @param event the document ingested event
     * @param partition the Kafka partition (for logging)
     * @param offset the Kafka offset (for logging)
     */
    @RetryableTopic(
            attempts = "3",
            backoff = @Backoff(delay = 1000, multiplier = 2),
            dltTopicSuffix = "-dlq",
            dltStrategy = DltStrategy.FAIL_ON_ERROR,
            include = {Exception.class}
    )
    @KafkaListener(topics = "#{@kafkaProperties.topics.documentIngestion}",
            groupId = "#{@kafkaProperties.consumer.groupId}",
            containerFactory = "kafkaListenerContainerFactory")
    public void handleDocumentIngestedEvent(
            DocumentIngestedEvent event,
            @Header(KafkaHeaders.RECEIVED_PARTITION) int partition,
            @Header(KafkaHeaders.OFFSET) long offset) {

        log.info("Received DocumentIngestedEvent eventId={} documentId={} partition={} offset={}",
                event.eventId(), event.documentId(), partition, offset);

        if (event.documentId() == null) {
            log.warn("DocumentIngestedEvent has null documentId, emitting FAILED WorkflowCompletedEvent");
            emitWorkflowCompletedEvent(null, "FAILED", "Document ID is null", 0L);
            return;
        }

        long startTime = System.currentTimeMillis();
        String workflowResult = null;

        try {
            // Call the document workflow client with document text
            // Note: We pass the filename as both text and filename since the workflow
            // expects text content. The actual text extraction happens in the workflow.
            workflowResult = documentWorkflowClient.runWorkflow(event.fileName(), event.fileName());

            if (workflowResult != null && !workflowResult.isBlank()) {
                // Parse workflow result and emit DocumentClassifiedEvent
                parseAndEmitClassifiedEvent(event, workflowResult, startTime);

                // The document's searchable content changed — drop stale search results.
                invalidateSearchCache(event.documentId());
            } else {
                // Workflow returned null/empty - treat as failure
                log.warn("Document workflow returned null/empty result for documentId={}", event.documentId());
                emitWorkflowCompletedEvent(event.documentId(), "FAILED", "Workflow returned empty result", 
                        System.currentTimeMillis() - startTime);
            }

        } catch (Exception e) {
            log.error("Document workflow failed for documentId={}: {}", event.documentId(), e.getMessage(), e);
            emitWorkflowCompletedEvent(event.documentId(), "FAILED", e.getMessage(), 
                    System.currentTimeMillis() - startTime);
        }
    }

    /**
     * Parses the workflow result JSON and emits a DocumentClassifiedEvent.
     * Expected JSON format: {"documentNumber":"...","issuingBody":"...","classification":"...","confidence":0.95}
     */
    private void parseAndEmitClassifiedEvent(DocumentIngestedEvent event, String workflowResult, long startTime) {
        try {
            // Parse JSON result
            com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            com.fasterxml.jackson.databind.JsonNode resultNode = mapper.readTree(workflowResult);

            String documentNumber = resultNode.hasNonNull("documentNumber") ? resultNode.get("documentNumber").asText() : null;
            String issuingBody = resultNode.hasNonNull("issuingBody") ? resultNode.get("issuingBody").asText() : null;
            String classification = resultNode.hasNonNull("classification") ? resultNode.get("classification").asText() : null;
            Double confidence = resultNode.hasNonNull("confidence") ? resultNode.get("confidence").asDouble() : null;
            
            // Parse dates if present
            LocalDate issueDate = null;
            LocalDate effectiveDate = null;
            if (resultNode.hasNonNull("issueDate") && !resultNode.get("issueDate").isNull()) {
                issueDate = LocalDate.parse(resultNode.get("issueDate").asText());
            }
            if (resultNode.hasNonNull("effectiveDate") && !resultNode.get("effectiveDate").isNull()) {
                effectiveDate = LocalDate.parse(resultNode.get("effectiveDate").asText());
            }

            // Emit DocumentClassifiedEvent
            EventMetadata metadata = new EventMetadata(
                    event.eventId().toString(),
                    event.eventId().toString(),
                    "document-ingestion-consumer",
                    "1.0"
            );

            DocumentClassifiedEvent classifiedEvent = DocumentClassifiedEvent.create(
                    metadata,
                    event.documentId(),
                    documentNumber,
                    issuingBody,
                    issueDate,
                    effectiveDate,
                    classification,
                    confidence
            );

            eventPublisher.publishAsync(classifiedEvent);
            log.info("Emitted DocumentClassifiedEvent for documentId={} documentNumber={}", 
                    event.documentId(), documentNumber);

        } catch (Exception e) {
            log.error("Failed to parse workflow result for documentId={}: {}", event.documentId(), e.getMessage(), e);
            emitWorkflowCompletedEvent(event.documentId(), "FAILED", "Failed to parse workflow result: " + e.getMessage(),
                    System.currentTimeMillis() - startTime);
        }
    }

    /**
     * Evicts all cached search results so the newly ingested document's chunks
     * become searchable immediately. Failure to invalidate must never break
     * ingestion, so the error is logged and swallowed.
     */
    private void invalidateSearchCache(Long documentId) {
        try {
            searchResultCache.invalidateAll(CacheNames.SEARCH_RESULTS);
            log.debug("Search cache invalidated after ingestion for documentId={}", documentId);
        } catch (Exception e) {
            log.warn("Failed to invalidate search cache after ingestion for documentId={}: {}",
                    documentId, e.getMessage());
        }
    }

    /**
     * Emits a WorkflowCompletedEvent with the given status.
     */
    private void emitWorkflowCompletedEvent(Long documentId, String status, String workflowResult, long processingTimeMs) {
        EventMetadata metadata = new EventMetadata(
                UUID.randomUUID().toString(),
                UUID.randomUUID().toString(),
                "document-ingestion-consumer",
                "1.0"
        );

        WorkflowCompletedEvent workflowEvent = WorkflowCompletedEvent.create(
                metadata,
                documentId,
                workflowResult,
                status,
                processingTimeMs
        );

        eventPublisher.publishAsync(workflowEvent);
        log.info("Emitted WorkflowCompletedEvent for documentId={} status={}", documentId, status);
    }

    // Getters/setters for testing configuration
    public void setMaxAttempts(int maxAttempts) {
        this.maxAttempts = maxAttempts;
    }

    public void setBackoffDelay(long backoffDelay) {
        this.backoffDelay = backoffDelay;
    }

    public void setBackoffMultiplier(double backoffMultiplier) {
        this.backoffMultiplier = backoffMultiplier;
    }
}