package com.smartdocchat.event;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.UUID;

/**
 * Event emitted when a document is successfully ingested into the system.
 */
public record DocumentIngestedEvent(
        @JsonProperty("eventId") UUID eventId,
        @JsonProperty("eventType") String eventType,
        @JsonProperty("timestamp") Instant timestamp,
        @JsonProperty("metadata") EventMetadata metadata,

        // Business fields
        @JsonProperty("documentId") Long documentId,
        @JsonProperty("fileName") String fileName,
        @JsonProperty("ownerUsername") String ownerUsername,
        @JsonProperty("fileType") String fileType,
        @JsonProperty("fileSize") Long fileSize,
        @JsonProperty("contentHash") String contentHash,
        @JsonProperty("sourceType") String sourceType
) implements DocumentEvent {

    public DocumentIngestedEvent {
        if (eventType == null || !eventType.equals("documentIngested")) {
            throw new IllegalArgumentException("eventType must be 'documentIngested'");
        }
    }

    /**
     * Factory method to create a new DocumentIngestedEvent with generated UUID and current timestamp.
     */
    public static DocumentIngestedEvent create(
            EventMetadata metadata,
            Long documentId,
            String fileName,
            String ownerUsername,
            String fileType,
            Long fileSize,
            String contentHash,
            String sourceType
    ) {
        return new DocumentIngestedEvent(
                UUID.randomUUID(),
                "documentIngested",
                Instant.now(),
                metadata,
                documentId,
                fileName,
                ownerUsername,
                fileType,
                fileSize,
                contentHash,
                sourceType
        );
    }
}