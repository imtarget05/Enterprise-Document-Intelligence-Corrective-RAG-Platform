package com.smartdocchat.service;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

/** Sends owner-checked Spring document chunks to the Python agent index. */
@Component
public class DocumentIndexClient {
    private final RestTemplate agentRestTemplate;
    private final String agentBaseUrl;

    public DocumentIndexClient(@Qualifier("agentRestTemplate") RestTemplate agentRestTemplate,
                               @Value("${agent.base-url:http://localhost:9000}") String agentBaseUrl) {
        this.agentRestTemplate = agentRestTemplate;
        this.agentBaseUrl = agentBaseUrl;
    }

    public Map<String, Object> index(Long documentId, String owner, String name, List<String> chunks) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        @SuppressWarnings("unchecked")
        Map<String, Object> result = agentRestTemplate.postForObject(
                agentBaseUrl + "/v1/agent/documents/" + documentId + "/index",
                new HttpEntity<>(Map.of("user_id", owner, "document_name", name,
                        "chunks", chunks), headers), Map.class);
        return result;
    }
}
