package com.smartdocchat.event;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for Jackson round-trip serialization/deserialization of DocumentEvent types.
 * Verifies that @JsonTypeInfo works correctly with the sealed interface pattern.
 */
class DocumentEventSerializationTest {

    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        objectMapper.findAndRegisterModules();
        objectMapper.registerModule(new JavaTimeModule());
    }

    @Test
    void documentIngestedEventRoundTrip() throws Exception {
        EventMetadata metadata = new EventMetadata(
                "corr-123", "cause-456", "ingestion-service", "1.0");

        DocumentIngestedEvent original = new DocumentIngestedEvent(
                UUID.randomUUID(),
                "documentIngested",
                Instant.now(),
                metadata,
                123L,
                "test.pdf",
                "alice",
                "pdf",
                1024L,
                "abc123hash",
                "USER"
        );

        String json = objectMapper.writeValueAsString(original);
        DocumentEvent deserialized = objectMapper.readValue(json, DocumentEvent.class);

        assertInstanceOf(DocumentIngestedEvent.class, deserialized);
        DocumentIngestedEvent event = (DocumentIngestedEvent) deserialized;

        assertEquals(original.eventId(), event.eventId());
        assertEquals("documentIngested", event.eventType());
        assertEquals(original.timestamp(), event.timestamp());
        assertEquals(original.metadata(), event.metadata());
        assertEquals(original.documentId(), event.documentId());
        assertEquals(original.fileName(), event.fileName());
        assertEquals(original.ownerUsername(), event.ownerUsername());
        assertEquals(original.fileType(), event.fileType());
        assertEquals(original.fileSize(), event.fileSize());
        assertEquals(original.contentHash(), event.contentHash());
        assertEquals(original.sourceType(), event.sourceType());
    }

    @Test
    void documentClassifiedEventRoundTrip() throws Exception {
        EventMetadata metadata = new EventMetadata(
                "corr-123", "cause-456", "classification-service", "1.0");

        DocumentClassifiedEvent original = new DocumentClassifiedEvent(
                UUID.randomUUID(),
                "documentClassified",
                Instant.now(),
                metadata,
                123L,
                "45/2019/QH14",
                "National Assembly",
                LocalDate.of(2019, 6, 14),
                LocalDate.of(2019, 7, 1),
                "Law",
                0.95
        );

        String json = objectMapper.writeValueAsString(original);
        DocumentEvent deserialized = objectMapper.readValue(json, DocumentEvent.class);

        assertInstanceOf(DocumentClassifiedEvent.class, deserialized);
        DocumentClassifiedEvent event = (DocumentClassifiedEvent) deserialized;

        assertEquals(original.eventId(), event.eventId());
        assertEquals("documentClassified", event.eventType());
        assertEquals(original.timestamp(), event.timestamp());
        assertEquals(original.metadata(), event.metadata());
        assertEquals(original.documentId(), event.documentId());
        assertEquals(original.documentNumber(), event.documentNumber());
        assertEquals(original.issuingBody(), event.issuingBody());
        assertEquals(original.issueDate(), event.issueDate());
        assertEquals(original.effectiveDate(), event.effectiveDate());
        assertEquals(original.classification(), event.classification());
        assertEquals(original.confidence(), event.confidence());
    }

    @Test
    void workflowCompletedEventRoundTrip() throws Exception {
        EventMetadata metadata = new EventMetadata(
                "corr-123", "cause-456", "workflow-service", "1.0");

        WorkflowCompletedEvent original = new WorkflowCompletedEvent(
                UUID.randomUUID(),
                "workflowCompleted",
                Instant.now(),
                metadata,
                123L,
                "{\"result\": \"success\"}",
                "SUCCESS",
                5000L
        );

        String json = objectMapper.writeValueAsString(original);
        DocumentEvent deserialized = objectMapper.readValue(json, DocumentEvent.class);

        assertInstanceOf(WorkflowCompletedEvent.class, deserialized);
        WorkflowCompletedEvent event = (WorkflowCompletedEvent) deserialized;

        assertEquals(original.eventId(), event.eventId());
        assertEquals("workflowCompleted", event.eventType());
        assertEquals(original.timestamp(), event.timestamp());
        assertEquals(original.metadata(), event.metadata());
        assertEquals(original.documentId(), event.documentId());
        assertEquals(original.workflowResult(), event.workflowResult());
        assertEquals(original.status(), event.status());
        assertEquals(original.processingTimeMs(), event.processingTimeMs());
    }

    @Test
    void documentPurgedEventRoundTrip() throws Exception {
        EventMetadata metadata = new EventMetadata(
                "corr-123", "cause-456", "purge-service", "1.0");

        DocumentPurgedEvent original = new DocumentPurgedEvent(
                UUID.randomUUID(),
                "documentPurged",
                Instant.now(),
                metadata,
                123L,
                "test.pdf",
                "admin",
                "Retention policy expired"
        );

        String json = objectMapper.writeValueAsString(original);
        DocumentEvent deserialized = objectMapper.readValue(json, DocumentEvent.class);

        assertInstanceOf(DocumentPurgedEvent.class, deserialized);
        DocumentPurgedEvent event = (DocumentPurgedEvent) deserialized;

        assertEquals(original.eventId(), event.eventId());
        assertEquals("documentPurged", event.eventType());
        assertEquals(original.timestamp(), event.timestamp());
        assertEquals(original.metadata(), event.metadata());
        assertEquals(original.documentId(), event.documentId());
        assertEquals(original.fileName(), event.fileName());
        assertEquals(original.purgedBy(), event.purgedBy());
        assertEquals(original.reason(), event.reason());
    }

    @Test
    void polymorphicDeserializationPreservesTypeDiscriminator() throws Exception {
        // Test that the eventType field is preserved and used for polymorphic deserialization
        DocumentIngestedEvent ingested = new DocumentIngestedEvent(
                UUID.randomUUID(), "documentIngested", Instant.now(),
                new EventMetadata("c1", "c2", "s1", "1.0"),
                1L, "a.pdf", "user", "pdf", 100L, "hash", "USER"
        );

        String json = objectMapper.writeValueAsString(ingested);
        assertTrue(json.contains("\"eventType\":\"documentIngested\""));

        DocumentEvent deserialized = objectMapper.readValue(json, DocumentEvent.class);
        assertEquals("documentIngested", deserialized.getEventType());
        assertInstanceOf(DocumentIngestedEvent.class, deserialized);
    }

    @Test
    void eventMetadataRoundTrip() throws Exception {
        EventMetadata original = new EventMetadata(
                "correlation-123", "causation-456", "test-service", "2.0");

        String json = objectMapper.writeValueAsString(original);
        EventMetadata deserialized = objectMapper.readValue(json, EventMetadata.class);

        assertEquals(original.correlationId(), deserialized.correlationId());
        assertEquals(original.causationId(), deserialized.causationId());
        assertEquals(original.source(), deserialized.source());
        assertEquals(original.version(), deserialized.version());
    }
}