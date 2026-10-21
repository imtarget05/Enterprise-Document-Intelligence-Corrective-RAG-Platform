package com.smartdocchat.consumer;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentClassifiedEvent;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.event.WorkflowCompletedEvent;
import com.smartdocchat.service.DocumentEventPublisher;
import com.smartdocchat.service.DocumentService;
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
import java.util.UUID;

/**
 * Consumer for document classification events.
 * Listens to the document-classified topic and updates the document with classification metadata.
 * Then emits WorkflowCompletedEvent with SUCCESS status.
 * Uses @RetryableTopic with DLQ for resilience (max 3 attempts, exponential backoff).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentClassificationConsumer {

    private final DocumentService documentService;
    private final DocumentEventPublisher eventPublisher;
    private final KafkaProperties kafkaProperties;
    private final SearchResultCache searchResultCache;

    // Configuration for retry (can be externalized via @Value if needed)
    private int maxAttempts = 3;
    private long backoffDelay = 1000L;
    private double backoffMultiplier = 2.0;

    /**
     * Handles DocumentClassifiedEvent from the document-classified topic.
     * Updates the document with classification metadata.
     * Then emits WorkflowCompletedEvent with SUCCESS status.
     *
     * @param event the document classified event
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
    @KafkaListener(topics = "#{@kafkaProperties.topics.documentClassified}",
            groupId = "#{@kafkaProperties.consumer.groupId}",
            containerFactory = "kafkaListenerContainerFactory")
    public void handleDocumentClassifiedEvent(
            DocumentClassifiedEvent event,
            @Header(KafkaHeaders.RECEIVED_PARTITION) int partition,
            @Header(KafkaHeaders.OFFSET) long offset) {

        log.info("Received DocumentClassifiedEvent eventId={} documentId={} partition={} offset={}",
                event.eventId(), event.documentId(), partition, offset);

        long startTime = System.currentTimeMillis();

        try {
            // Update document with classification metadata
            if (event.documentId() != null) {
                documentService.updateDocumentClassification(
                        event.documentId(),
                        event.documentNumber(),
                        event.issuingBody(),
                        event.issueDate(),
                        event.effectiveDate(),
                        event.classification(),
                        event.confidence()
                );
                log.info("Updated documentId={} with classification: documentNumber={}, issuingBody={}, classification={}",
                        event.documentId(), event.documentNumber(), event.issuingBody(), event.classification());
            } else {
                log.warn("DocumentClassifiedEvent has null documentId, skipping document update");
            }

            // The document's classification changed — drop stale search results.
            invalidateSearchCache(event.documentId());

            // Emit WorkflowCompletedEvent with SUCCESS
            emitWorkflowCompletedEvent(event, "SUCCESS", startTime);

        } catch (Exception e) {
            log.error("Failed to process DocumentClassifiedEvent for documentId={}: {}", event.documentId(), e.getMessage(), e);
            // Re-throw to trigger retry/DLQ
            throw e;
        }
    }

    /**
     * Evicts all cached search results so the re-classified document is searched
     * fresh. Failure to invalidate must never break the workflow, so the error
     * is logged and swallowed.
     */
    private void invalidateSearchCache(Long documentId) {
        try {
            searchResultCache.invalidateAll(CacheNames.SEARCH_RESULTS);
            log.debug("Search cache invalidated after classification for documentId={}", documentId);
        } catch (Exception e) {
            log.warn("Failed to invalidate search cache after classification for documentId={}: {}",
                    documentId, e.getMessage());
        }
    }

    /**
     * Emits a WorkflowCompletedEvent with SUCCESS status containing the classification result.
     */
    private void emitWorkflowCompletedEvent(DocumentClassifiedEvent event, String status, long startTime) {
        EventMetadata metadata = new EventMetadata(
                event.eventId().toString(),
                event.eventId().toString(),
                "document-classification-consumer",
                "1.0"
        );

        // Build a summary of the classification result
        StringBuilder resultBuilder = new StringBuilder();
        resultBuilder.append("{");
        if (event.documentNumber() != null) {
            resultBuilder.append("\"documentNumber\":\"").append(event.documentNumber()).append("\",");
        }
        if (event.issuingBody() != null) {
            resultBuilder.append("\"issuingBody\":\"").append(event.issuingBody()).append("\",");
        }
        if (event.classification() != null) {
            resultBuilder.append("\"classification\":\"").append(event.classification()).append("\",");
        }
        if (event.confidence() != null) {
            resultBuilder.append("\"confidence\":").append(event.confidence()).append(",");
        }
        if (event.issueDate() != null) {
            resultBuilder.append("\"issueDate\":\"").append(event.issueDate()).append("\",");
        }
        if (event.effectiveDate() != null) {
            resultBuilder.append("\"effectiveDate\":\"").append(event.effectiveDate()).append("\",");
        }
        // Remove trailing comma
        if (resultBuilder.charAt(resultBuilder.length() - 1) == ',') {
            resultBuilder.setLength(resultBuilder.length() - 1);
        }
        resultBuilder.append("}");

        WorkflowCompletedEvent workflowEvent = WorkflowCompletedEvent.create(
                metadata,
                event.documentId(),
                resultBuilder.toString(),
                status,
                System.currentTimeMillis() - startTime
        );

        eventPublisher.publishAsync(workflowEvent);
        log.info("Emitted WorkflowCompletedEvent for documentId={} status={}", event.documentId(), status);
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