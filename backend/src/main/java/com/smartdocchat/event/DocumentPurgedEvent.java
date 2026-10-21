package com.smartdocchat.event;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.UUID;

/**
 * Event emitted when a document is purged from the system (e.g., retention policy expiration).
 */
public record DocumentPurgedEvent(
        @JsonProperty("eventId") UUID eventId,
        @JsonProperty("eventType") String eventType,
        @JsonProperty("timestamp") Instant timestamp,
        @JsonProperty("metadata") EventMetadata metadata,

        // Business fields
        @JsonProperty("documentId") Long documentId,
        @JsonProperty("fileName") String fileName,
        @JsonProperty("purgedBy") String purgedBy,
        @JsonProperty("reason") String reason
) implements DocumentEvent {

    public DocumentPurgedEvent {
        if (eventType == null || !eventType.equals("documentPurged")) {
            throw new IllegalArgumentException("eventType must be 'documentPurged'");
        }
    }

    /**
     * Factory method to create a new DocumentPurgedEvent with generated UUID and current timestamp.
     */
    public static DocumentPurgedEvent create(
            EventMetadata metadata,
            Long documentId,
            String fileName,
            String purgedBy,
            String reason
    ) {
        return new DocumentPurgedEvent(
                UUID.randomUUID(),
                "documentPurged",
                Instant.now(),
                metadata,
                documentId,
                fileName,
                purgedBy,
                reason
        );
    }
}