package com.smartdocchat.consumer;

import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.service.DocumentEventPublisher;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.annotation.RetryableTopic;
import org.springframework.kafka.retrytopic.DltStrategy;
import org.springframework.kafka.support.KafkaHeaders;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.retry.annotation.Backoff;
import org.springframework.stereotype.Service;

import java.util.Map;

/**
 * Consumer for notification events.
 * Listens to the notification topic for future extensibility.
 * Currently logs notifications for debugging/monitoring.
 * Email/push integration can be added later.
 * Uses @RetryableTopic with DLQ for resilience (max 3 attempts, exponential backoff).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class NotificationConsumer {

    private final DocumentEventPublisher eventPublisher;
    private final KafkaProperties kafkaProperties;

    // Configuration for retry (can be externalized via @Value if needed)
    private int maxAttempts = 3;
    private long backoffDelay = 1000L;
    private double backoffMultiplier = 2.0;

    /**
     * Handles notification events from the notification topic.
     * Currently logs the notification for debugging/monitoring.
     * Future: integrate with email, push, SMS, Slack, etc.
     *
     * @param payload the notification payload (generic Map for flexibility)
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
    @KafkaListener(topics = "#{@kafkaProperties.topics.notification}",
            groupId = "#{@kafkaProperties.consumer.groupId}",
            containerFactory = "kafkaListenerContainerFactory")
    public void handleNotification(
            @Payload Map<String, Object> payload,
            @Header(KafkaHeaders.RECEIVED_PARTITION) int partition,
            @Header(KafkaHeaders.OFFSET) long offset) {

        log.info("Received Notification event partition={} offset={} payload={}", partition, offset, payload);

        try {
            // Extract notification details
            String notificationType = (String) payload.get("type");
            String recipient = (String) payload.get("recipient");
            String subject = (String) payload.get("subject");
            String message = (String) payload.get("message");
            String priority = (String) payload.get("priority");

            // Log the notification for now
            log.info("NOTIFICATION: type={} recipient={} subject={} priority={}",
                    notificationType, recipient, subject, priority);

            // TODO: Integrate with notification delivery systems:
            // - Email: JavaMailSender
            // - Push: Firebase Cloud Messaging / APNs
            // - SMS: Twilio / Vonage
            // - Slack: Webhook / Bot API
            // - WebSocket: Server-sent events to connected clients

            // Example future implementation:
            // if ("EMAIL".equalsIgnoreCase(notificationType)) {
            //     emailService.send(recipient, subject, message);
            // } else if ("PUSH".equalsIgnoreCase(notificationType)) {
            //     pushService.send(recipient, message);
            // }

        } catch (Exception e) {
            log.error("Failed to process notification: {}", e.getMessage(), e);
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