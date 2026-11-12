package com.smartdocchat.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.restclient.RestTemplateBuilder;
import org.springframework.web.client.RestTemplate;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import org.springframework.test.web.client.MockRestServiceServer;

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
        RestTemplate rt = config.agentRestTemplate(new RestTemplateBuilder(), 3000, 15000, "test-internal-token");
        assertNotNull(rt);
        MockRestServiceServer server = MockRestServiceServer.bindTo(rt).build();
        server.expect(requestTo("http://agent/v1/agent/invoke"))
                .andExpect(header("X-Internal-Token", "test-internal-token"))
                .andRespond(withSuccess());
        rt.getForObject("http://agent/v1/agent/invoke", String.class);
        server.verify();
    }
}