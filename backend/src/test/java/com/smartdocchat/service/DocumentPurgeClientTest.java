package com.smartdocchat.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Phase 2 — deleting a document must reach the agent-service stores that hold a
 * copy of its content (vector store, retrieval cache, memory).
 */
@ExtendWith(MockitoExtension.class)
class DocumentPurgeClientTest {

    @Mock private RestTemplate restTemplate;

    private DocumentPurgeClient client;

    @BeforeEach
    void setUp() {
        client = new DocumentPurgeClient(restTemplate, "http://agent.test:9000", "internal-secret");
    }

    @Test
    void purgeDocumentCallsAgentPurgeEndpoint() {
        when(restTemplate.postForObject(startsWith("http://agent.test:9000/v1/agent/documents/"), any(), eq(Map.class)))
                .thenReturn(Map.of("status", "ok"));

        boolean purged = client.purgeDocument(42L, "alice", "contract.txt");

        assertTrue(purged);
        ArgumentCaptor<HttpEntity<?>> entity = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).postForObject(
                eq("http://agent.test:9000/v1/agent/documents/42/purge"),
                entity.capture(), eq(Map.class));

        HttpHeaders assertions = entity.getValue().getHeaders();
        assertEquals("application/json", assertions.getContentType().toString());
        assertEquals("internal-secret", assertions.getFirst("X-Internal-Token"));
        Map<?, ?> body = (Map<?, ?>) entity.getValue().getBody();
        assertEquals("alice", body.get("user_id"));
        assertEquals("contract.txt", body.get("document_name"));
    }

    @Test
    void purgeDocumentReportsPartialPurge() {
        // The agent returns 200 with a per-component report; "partial" means a
        // store failed and the caller must be able to see it.
        when(restTemplate.postForObject(startsWith("http://agent.test:9000"), any(), eq(Map.class)))
                .thenReturn(Map.of("status", "partial"));

        assertFalse(client.purgeDocument(42L, "alice", "contract.txt"));
    }

    @Test
    void purgeDocumentIsBestEffortWhenAgentIsDown() {
        when(restTemplate.postForObject(startsWith("http://agent.test:9000"), any(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("connection refused"));

        // The document row is already deleted: the purge must not explode.
        assertFalse(client.purgeDocument(42L, "alice", "contract.txt"));
    }

    @Test
    void purgeDocumentOmitsTokenWhenNotConfigured() {
        when(restTemplate.postForObject(startsWith("http://agent.test:9000"), any(), eq(Map.class)))
                .thenReturn(Map.of("status", "ok"));
        DocumentPurgeClient untokened =
                new DocumentPurgeClient(restTemplate, "http://agent.test:9000", "");

        assertTrue(untokened.purgeDocument(7L, "bob", "report.pdf"));

        ArgumentCaptor<HttpEntity<?>> entity = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).postForObject(
                eq("http://agent.test:9000/v1/agent/documents/7/purge"), entity.capture(), eq(Map.class));
        assertNull(entity.getValue().getHeaders().getFirst("X-Internal-Token"));
    }

    @Test
    void purgeDocumentHandlesEmptyResponseBody() {
        when(restTemplate.postForObject(startsWith("http://agent.test:9000"), any(), eq(Map.class)))
                .thenReturn(null);

        assertFalse(client.purgeDocument(42L, "alice", "contract.txt"));
    }
}
