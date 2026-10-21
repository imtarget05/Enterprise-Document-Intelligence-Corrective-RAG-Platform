package com.smartdocchat.consumer;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentPurgedEvent;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.annotation.RetryableTopic;
import org.springframework.kafka.retrytopic.DltStrategy;
import org.springframework.kafka.support.KafkaHeaders;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.retry.annotation.Backoff;
import org.springframework.stereotype.Service;

/**
 * Consumer for document-purged events.
 * A purged document's chunks are gone, so any cached search results that
 * referenced them must be evicted (write-through cache invalidation).
 * Uses @RetryableTopic with DLQ for resilience (max 3 attempts, exponential backoff).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentPurgedConsumer {

    private final SearchResultCache searchResultCache;
    private final KafkaProperties kafkaProperties;

    // Configuration for retry (can be externalized via @Value if needed)
    private int maxAttempts = 3;
    private long backoffDelay = 1000L;
    private double backoffMultiplier = 2.0;

    /**
     * Handles DocumentPurgedEvent from the document-purged topic by evicting the
     * search results cache.
     *
     * @param event the document purged event
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
    @KafkaListener(topics = "#{@kafkaProperties.topics.documentPurged}",
            groupId = "#{@kafkaProperties.consumer.groupId}",
            containerFactory = "kafkaListenerContainerFactory")
    public void handleDocumentPurgedEvent(
            DocumentPurgedEvent event,
            @Header(KafkaHeaders.RECEIVED_PARTITION) int partition,
            @Header(KafkaHeaders.OFFSET) long offset) {

        log.info("Received DocumentPurgedEvent eventId={} documentId={} partition={} offset={}",
                event.eventId(), event.documentId(), partition, offset);

        try {
            searchResultCache.invalidateAll(CacheNames.SEARCH_RESULTS);
            log.info("Search cache invalidated after purge for documentId={}", event.documentId());
        } catch (Exception e) {
            log.error("Failed to invalidate search cache for purged documentId={}: {}",
                    event.documentId(), e.getMessage(), e);
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
