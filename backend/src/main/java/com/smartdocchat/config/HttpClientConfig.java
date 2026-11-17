package com.smartdocchat.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.restclient.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

@Configuration
public class HttpClientConfig {

    @Bean
    public RestTemplate restTemplate(
            RestTemplateBuilder builder,
            @Value("${external-services.connect-timeout-ms:3000}") long connectTimeoutMs,
            @Value("${external-services.read-timeout-ms:60000}") long readTimeoutMs) {
        return builder
                .connectTimeout(Duration.ofMillis(connectTimeoutMs))
                .readTimeout(Duration.ofMillis(readTimeoutMs))
                .build();
    }

    @Bean
    public RestTemplate agentRestTemplate(
            RestTemplateBuilder builder,
            @Value("${external-services.connect-timeout-ms:3000}") long connectTimeoutMs,
            @Value("${agent.timeout-ms:15000}") long agentTimeoutMs,
            @Value("${security.internal-token:}") String internalToken) {
        return builder
                .connectTimeout(Duration.ofMillis(connectTimeoutMs))
                .readTimeout(Duration.ofMillis(agentTimeoutMs))
                .additionalInterceptors((request, body, execution) -> {
                    if (internalToken != null && !internalToken.isBlank()) {
                        request.getHeaders().set("X-Internal-Token", internalToken);
                    }
                    return execution.execute(request, body);
                })
                .build();
    }
}
