package com.smartdocchat.event;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Metadata for document events, providing traceability and versioning.
 */
public record EventMetadata(
        @JsonProperty("correlationId") String correlationId,
        @JsonProperty("causationId") String causationId,
        @JsonProperty("source") String source,
        @JsonProperty("version") String version
) {
}