package com.smartdocchat.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.restclient.RestTemplateBuilder;
import org.springframework.web.client.RestTemplate;

import static org.junit.jupiter.api.Assertions.assertNotNull;

/**
 * Covers the {@link HttpClientConfig} RestTemplate beans (Phase 1: a dedicated
 * agent RestTemplate with a shorter read timeout for the internal agent call).
 */
class HttpClientConfigTest {

    @Test
    void restTemplateBeanBuildsWithTimeouts() {
        HttpClientConfig config = new HttpClientConfig();
        RestTemplate rt = config.restTemplate(new RestTemplateBuilder(), 3000, 60000);
        assertNotNull(rt);
    }

    @Test
    void agentRestTemplateBuildsWithDedicatedTimeout() {
        HttpClientConfig config = new HttpClientConfig();
        RestTemplate rt = config.agentRestTemplate(new RestTemplateBuilder(), 3000, 15000);
        assertNotNull(rt);
    }
}