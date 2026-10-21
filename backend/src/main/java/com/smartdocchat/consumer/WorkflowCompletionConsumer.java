package com.smartdocchat.consumer;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.config.KafkaProperties;
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

import java.util.UUID;

/**
 * Consumer for workflow completion events.
 * Listens to the workflow-completed topic and updates the document status/workflow result.
 * If SUCCESS: triggers search cache invalidation.
 * If FAILED: logs for alerting.
 * Uses @RetryableTopic with DLQ for resilience (max 3 attempts, exponential backoff).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class WorkflowCompletionConsumer {

    private final DocumentService documentService;
    private final DocumentEventPublisher eventPublisher;
    private final KafkaProperties kafkaProperties;
    private final SearchResultCache searchResultCache;

    // Configuration for retry (can be externalized via @Value if needed)
    private int maxAttempts = 3;
    private long backoffDelay = 1000L;
    private double backoffMultiplier = 2.0;

    /**
     * Handles WorkflowCompletedEvent from the workflow-completed topic.
     * Updates the document with workflow result and status.
     * If SUCCESS: triggers search cache invalidation.
     * If FAILED: logs for alerting.
     *
     * @param event the workflow completed event
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
    @KafkaListener(topics = "#{@kafkaProperties.topics.workflowCompleted}",
            groupId = "#{@kafkaProperties.consumer.groupId}",
            containerFactory = "kafkaListenerContainerFactory")
    public void handleWorkflowCompletedEvent(
            WorkflowCompletedEvent event,
            @Header(KafkaHeaders.RECEIVED_PARTITION) int partition,
            @Header(KafkaHeaders.OFFSET) long offset) {

        log.info("Received WorkflowCompletedEvent eventId={} documentId={} status={} partition={} offset={}",
                event.eventId(), event.documentId(), event.status(), partition, offset);

        try {
            // Update document with workflow result
            if (event.documentId() != null) {
                documentService.updateWorkflowResult(event.documentId(), event.workflowResult(), event.status());
                log.info("Updated documentId={} with workflow result status={}", event.documentId(), event.status());
            } else {
                log.warn("WorkflowCompletedEvent has null documentId, skipping document update");
            }

            // Handle SUCCESS vs FAILED
            if ("SUCCESS".equalsIgnoreCase(event.status())) {
                // The document changed — drop stale search results. Cache
                // invalidation failure must never block the workflow.
                try {
                    searchResultCache.invalidateAll(CacheNames.SEARCH_RESULTS);
                    log.info("Search cache invalidated for documentId={}", event.documentId());
                } catch (Exception e) {
                    log.warn("Failed to invalidate search cache for documentId={}: {}",
                            event.documentId(), e.getMessage());
                }
            } else if ("FAILED".equalsIgnoreCase(event.status())) {
                // Log for alerting - in production this could trigger an alert
                log.error("ALERT: Workflow FAILED for documentId={}: {}", event.documentId(), event.workflowResult());
                // TODO: Integrate with alerting system (e.g., PagerDuty, OpsGenie, email)
            }

        } catch (Exception e) {
            log.error("Failed to process WorkflowCompletedEvent for documentId={}: {}", event.documentId(), e.getMessage(), e);
            // Re-throw to trigger retry/DLQ
            throw e;
        }
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