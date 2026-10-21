package com.smartdocchat.event;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.UUID;

/**
 * Event emitted when a document workflow (classify → extract → map → match) completes.
 */
public record WorkflowCompletedEvent(
        @JsonProperty("eventId") UUID eventId,
        @JsonProperty("eventType") String eventType,
        @JsonProperty("timestamp") Instant timestamp,
        @JsonProperty("metadata") EventMetadata metadata,

        // Business fields
        @JsonProperty("documentId") Long documentId,
        @JsonProperty("workflowResult") String workflowResult,
        @JsonProperty("status") String status,
        @JsonProperty("processingTimeMs") Long processingTimeMs
) implements DocumentEvent {

    public WorkflowCompletedEvent {
        if (eventType == null || !eventType.equals("workflowCompleted")) {
            throw new IllegalArgumentException("eventType must be 'workflowCompleted'");
        }
        if (status == null || (!status.equals("SUCCESS") && !status.equals("FAILED"))) {
            throw new IllegalArgumentException("status must be 'SUCCESS' or 'FAILED'");
        }
    }

    /**
     * Factory method to create a new WorkflowCompletedEvent with generated UUID and current timestamp.
     */
    public static WorkflowCompletedEvent create(
            EventMetadata metadata,
            Long documentId,
            String workflowResult,
            String status,
            Long processingTimeMs
    ) {
        return new WorkflowCompletedEvent(
                UUID.randomUUID(),
                "workflowCompleted",
                Instant.now(),
                metadata,
                documentId,
                workflowResult,
                status,
                processingTimeMs
        );
    }
}