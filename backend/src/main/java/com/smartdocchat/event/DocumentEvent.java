package com.smartdocchat.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;

import java.time.Instant;
import java.util.UUID;

/**
 * Sealed interface for all document domain events.
 * Uses Jackson's @JsonTypeInfo for polymorphic serialization/deserialization.
 */
@JsonTypeInfo(
        use = JsonTypeInfo.Id.NAME,
        include = JsonTypeInfo.As.EXISTING_PROPERTY,
        property = "eventType",
        visible = true
)
@JsonSubTypes({
        @JsonSubTypes.Type(value = DocumentIngestedEvent.class, name = "documentIngested"),
        @JsonSubTypes.Type(value = DocumentClassifiedEvent.class, name = "documentClassified"),
        @JsonSubTypes.Type(value = WorkflowCompletedEvent.class, name = "workflowCompleted"),
        @JsonSubTypes.Type(value = DocumentPurgedEvent.class, name = "documentPurged")
})
public sealed interface DocumentEvent
        permits DocumentIngestedEvent, DocumentClassifiedEvent, WorkflowCompletedEvent, DocumentPurgedEvent {

    @JsonProperty("eventId")
    UUID eventId();

    @JsonProperty("eventType")
    String eventType();

    @JsonProperty("timestamp")
    Instant timestamp();

    @JsonProperty("metadata")
    EventMetadata metadata();

    /**
     * Returns the event type discriminator value.
     * This is used by Jackson for polymorphic deserialization.
     */
    default String getEventType() {
        return eventType();
    }
}