package com.smartdocchat.service;

import com.smartdocchat.metrics.RagMetrics;
import com.smartdocchat.observability.LangfuseService;
import com.smartdocchat.util.LlmConfig;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Thin client for the Ollama-compatible LLM router, guarded by a resilience4j
 * circuit breaker ("llmService").
 *
 * Transport failures and 5xx responses are recorded as breaker failures so a
 * struggling provider is hit at most a handful of times before calls fail fast
 * with the standard "temporarily unavailable" placeholder. Client-side bugs
 * (unexpected response bodies) are reported through the dedicated placeholder
 * without tripping the breaker's failure rate.
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class LlmClient {

    public static final String UNAVAILABLE_RESPONSE =
            "Sorry, the language model is temporarily unavailable. Please try again.";
    public static final String NO_RESPONSE_PLACEHOLDER =
            "Sorry, I could not generate a response. Please try again.";

    /** Raised when the router answers 2xx with an unusable body. */
    static class UnexpectedResponseException extends RuntimeException {
        UnexpectedResponseException(String message) {
            super(message);
        }
    }

    private final RestTemplate restTemplate;
    private final LlmConfig llmConfig;
    private final RagMetrics ragMetrics;
    private final LangfuseService langfuse;

    @Value("${security.internal-token:}")
    private String internalToken;

    @Value("${cost.per-1k-tokens:{}}")
    private String costPer1kJson;

    @SuppressWarnings("unchecked")
    @CircuitBreaker(name = "llmService", fallbackMethod = "chatFallback")
    public String chat(String systemPrompt, String userPrompt) {
        String genId = langfuse.startGeneration("generate_answer", llmConfig.getChatModel(),
                Map.of("messages", List.of(
                        Map.of("role", "system", "content", systemPrompt),
                        Map.of("role", "user", "content", userPrompt))));
        long genStart = System.currentTimeMillis();
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (internalToken != null && !internalToken.isBlank()) {
            headers.set("X-Internal-Token", internalToken);
        }
        // Propagate the CRAG trace id to the llm-router so Python spans attach
        // to the same Langfuse trace (Phase 2 glue).
        langfuse.routerTraceHeaders().forEach(headers::set);

        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("model", llmConfig.getChatModel());
        requestBody.put("messages", List.of(
                Map.of("role", "system", "content", systemPrompt),
                Map.of("role", "user", "content", userPrompt)));
        requestBody.put("options",
                Map.of("temperature", llmConfig.getTemperature(), "top_p", llmConfig.getTopP(),
                        "num_predict", llmConfig.getMaxOutputTokens()));
        requestBody.put("stream", false);
        // This client serves document-grounded chat. Passing the task explicitly
        // prevents source text such as an "error code" from selecting the coder model.
        requestBody.put("routing", Map.of("task_type", "qa"));

        log.info("Calling local LLM model: {}", llmConfig.getChatModel());
        ResponseEntity<Map> response = restTemplate.exchange(
                llmConfig.getChatUrl(),
                HttpMethod.POST,
                new HttpEntity<>(requestBody, headers),
                Map.class
        );

        if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
            Object message = response.getBody().get("message");
            if (message instanceof Map<?, ?> m && m.get("content") != null) {
                recordTokenUsage(response.getBody());
                long genMs = System.currentTimeMillis() - genStart;
                langfuse.endGeneration(genId, String.valueOf(m.get("content")), null);
                return String.valueOf(m.get("content"));
            }
        }
        ragMetrics.recordLlmError();
        langfuse.endGeneration(genId, "LLM returned unexpected response structure", null);
        throw new UnexpectedResponseException("LLM API returned unexpected response structure");
    }

    /** Fail fast while the circuit is open. */
    String chatFallback(String systemPrompt, String userPrompt,
                        io.github.resilience4j.circuitbreaker.CallNotPermittedException e) {
        log.warn("LLM circuit breaker open — failing fast: {}", e.getMessage());
        langfuse.updateTrace(Map.of("llmError", "circuit_open"), null);
        return UNAVAILABLE_RESPONSE;
    }

    /** Translate recorded failures back into the caller-facing placeholders. */
    String chatFallback(String systemPrompt, String userPrompt, Exception e) {
        if (e instanceof HttpServerErrorException || e instanceof ResourceAccessException) {
            log.error("LLM API unreachable: {}", e.getMessage());
            langfuse.updateTrace(Map.of("llmError", "unreachable"), null);
            return UNAVAILABLE_RESPONSE;
        }
        log.error("Error calling LLM API: {}", e.getMessage());
        langfuse.updateTrace(Map.of("llmError", "generation_failed"), null);
        return NO_RESPONSE_PLACEHOLDER;
    }

    /** Records reported token usage + cost. Supports Ollama (prompt_eval_count/eval_count) and OpenAI usage. */
    private void recordTokenUsage(Map<String, Object> body) {
        long promptTokens = toLong(body.get("prompt_eval_count"));
        long completionTokens = toLong(body.get("eval_count"));
        // OpenAI / Cloudflare format: usage: {prompt_tokens, completion_tokens}
        Object usage = body.get("usage");
        if (usage instanceof Map<?, ?> um) {
            promptTokens = Math.max(promptTokens, toLong(um.get("prompt_tokens")));
            completionTokens = Math.max(completionTokens, toLong(um.get("completion_tokens")));
            if (promptTokens == 0) promptTokens = toLong(um.get("promptTokens"));
            if (completionTokens == 0) completionTokens = toLong(um.get("completionTokens"));
        }
        // legacy single field
        if (completionTokens == 0) completionTokens = toLong(body.get("completion_tokens"));
        if (promptTokens == 0) promptTokens = toLong(body.get("prompt_tokens"));

        if (promptTokens > 0 || completionTokens > 0) {
            double cost = calculateCost(promptTokens, completionTokens);
            ragMetrics.recordTokensWithCost(promptTokens, completionTokens, cost);
            Map<String, Object> meta = new HashMap<>();
            meta.put("promptTokens", promptTokens);
            meta.put("completionTokens", completionTokens);
            meta.put("totalTokens", promptTokens + completionTokens);
            if (cost > 0) meta.put("costUsd", cost);
            langfuse.updateTrace(meta, null);
        } else if (completionTokens > 0 || promptTokens > 0) {
            // fallback already handled
        } else {
            // fallback: try eval_count only for backward compat
            if (completionTokens > 0) {
                ragMetrics.recordTokens(completionTokens);
                langfuse.updateTrace(Map.of("outputTokens", completionTokens), null);
            }
        }
    }

    private long toLong(Object v) {
        if (v instanceof Number n) return n.longValue();
        if (v instanceof String s) {
            try { return Long.parseLong(s); } catch (NumberFormatException ignored) {}
        }
        return 0L;
    }

    private double calculateCost(long prompt, long completion) {
        if (costPer1kJson == null || costPer1kJson.isBlank() || costPer1kJson.equals("{}")) return 0.0;
        try {
            String model = llmConfig.getChatModel();
            // simple JSON parse without jackson to avoid overhead: look for "model":price
            // costPer1kJson is {"@cf/meta/llama-3.3-70b-instruct-fp8-fast":0.0003, ...}
            com.fasterxml.jackson.databind.ObjectMapper om = new com.fasterxml.jackson.databind.ObjectMapper();
            @SuppressWarnings("unchecked")
            Map<String, Object> map = om.readValue(costPer1kJson, Map.class);
            Object priceObj = map.get(model);
            if (priceObj == null) {
                // try generic fallback key "*" or "default"
                priceObj = map.getOrDefault("*", map.get("default"));
            }
            double pricePer1k = priceObj instanceof Number ? ((Number) priceObj).doubleValue() : 0.0;
            if (pricePer1k == 0.0) return 0.0;
            return (prompt + completion) / 1000.0 * pricePer1k;
        } catch (Exception e) {
            log.debug("Failed to parse costPer1kJson: {}", e.getMessage());
            return 0.0;
        }
    }
}
