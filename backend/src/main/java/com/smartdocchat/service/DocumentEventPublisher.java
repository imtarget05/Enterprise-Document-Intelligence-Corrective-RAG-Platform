package com.smartdocchat.service;

import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.DocumentIngestedEvent;
import com.smartdocchat.event.DocumentPurgedEvent;
import com.smartdocchat.event.WorkflowCompletedEvent;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Service;

import java.util.concurrent.CompletableFuture;

/**
 * Publishes document domain events to Kafka topics.
 * Topic routing is based on the event type.
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentEventPublisher {

    private final KafkaTemplate<String, Object> kafkaTemplate;
    private final KafkaProperties kafkaProperties;

    /**
     * Publishes an event to the appropriate Kafka topic based on event type.
     * Fire-and-forget with error logging callback.
     *
     * @param event the document event to publish
     */
    public void publish(DocumentEvent event) {
        String topic = resolveTopic(event);
        String key = event.eventId().toString();

        CompletableFuture<SendResult<String, Object>> future =
                kafkaTemplate.send(topic, key, event);

        future.whenComplete((result, ex) -> {
            if (ex != null) {
                log.error("Failed to publish event {} to topic {}: {}",
                        event.eventId(), topic, ex.getMessage(), ex);
            } else {
                log.debug("Published event {} to topic {} partition {} offset {}",
                        event.eventId(), topic, result.getRecordMetadata().partition(),
                        result.getRecordMetadata().offset());
            }
        });
    }

    /**
     * Publishes an event asynchronously and returns a CompletableFuture for callers
     * that need confirmation of send completion.
     *
     * @param event the document event to publish
     * @return CompletableFuture that completes when the send succeeds or fails
     */
    public CompletableFuture<SendResult<String, Object>> publishAsync(DocumentEvent event) {
        String topic = resolveTopic(event);
        String key = event.eventId().toString();

        return kafkaTemplate.send(topic, key, event);
    }

    /**
     * Resolves the Kafka topic based on the event type.
     *
     * @param event the document event
     * @return the topic name
     */
    private String resolveTopic(DocumentEvent event) {
        if (event instanceof DocumentIngestedEvent) {
            return kafkaProperties.getTopics().getDocumentIngestion();
        } else if (event instanceof DocumentPurgedEvent) {
            return kafkaProperties.getTopics().getDocumentPurged();
        } else if (event instanceof WorkflowCompletedEvent) {
            return kafkaProperties.getTopics().getWorkflowCompleted();
        } else {
            // Default fallback for DocumentClassifiedEvent and any future event types
            return kafkaProperties.getTopics().getDocumentClassified();
        }
    }
}