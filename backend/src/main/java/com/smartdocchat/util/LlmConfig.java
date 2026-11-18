package com.smartdocchat.util;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Enterprise-grade LLM infrastructure configuration.
 * Decouples the application code from specific LLM providers (e.g. Ollama).
 */
@Component
@ConfigurationProperties(prefix = "llm")
@Data
public class LlmConfig {
    private String baseUrl = "http://localhost:8001";
    private String chatModel = "@cf/meta/llama-3.3-70b-instruct-fp8-fast";
    private String embeddingModel = "@cf/baai/bge-base-en-v1.5";
    private double temperature = 0.3;
    private double topP = 0.95;
    private int maxOutputTokens = 2048;
    
    // Retry configurations
    private int maxAttempts = 3;
    private long retryBackoffMs = 250;

    public String getChatUrl() {
        return stripTrailingSlash(baseUrl) + "/api/chat";
    }

    public String getEmbeddingUrl() {
        return stripTrailingSlash(baseUrl) + "/api/embeddings";
    }

    private String stripTrailingSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
