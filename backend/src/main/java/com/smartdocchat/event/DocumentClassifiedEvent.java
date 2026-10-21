package com.smartdocchat.event;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

/**
 * Event emitted when a document is classified (e.g., legal document classification).
 */
public record DocumentClassifiedEvent(
        @JsonProperty("eventId") UUID eventId,
        @JsonProperty("eventType") String eventType,
        @JsonProperty("timestamp") Instant timestamp,
        @JsonProperty("metadata") EventMetadata metadata,

        // Business fields
        @JsonProperty("documentId") Long documentId,
        @JsonProperty("documentNumber") String documentNumber,
        @JsonProperty("issuingBody") String issuingBody,
        @JsonProperty("issueDate") LocalDate issueDate,
        @JsonProperty("effectiveDate") LocalDate effectiveDate,
        @JsonProperty("classification") String classification,
        @JsonProperty("confidence") Double confidence
) implements DocumentEvent {

    public DocumentClassifiedEvent {
        if (eventType == null || !eventType.equals("documentClassified")) {
            throw new IllegalArgumentException("eventType must be 'documentClassified'");
        }
    }

    /**
     * Factory method to create a new DocumentClassifiedEvent with generated UUID and current timestamp.
     */
    public static DocumentClassifiedEvent create(
            EventMetadata metadata,
            Long documentId,
            String documentNumber,
            String issuingBody,
            LocalDate issueDate,
            LocalDate effectiveDate,
            String classification,
            Double confidence
    ) {
        return new DocumentClassifiedEvent(
                UUID.randomUUID(),
                "documentClassified",
                Instant.now(),
                metadata,
                documentId,
                documentNumber,
                issuingBody,
                issueDate,
                effectiveDate,
                classification,
                confidence
        );
    }
}