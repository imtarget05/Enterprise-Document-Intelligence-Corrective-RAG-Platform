package com.smartdocchat.service;

import com.smartdocchat.metrics.RagMetrics;
import com.smartdocchat.util.LlmConfig;
import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Exercises the circuit-breaker semantics of {@link LlmClient} against a real
 * resilience4j registry. The annotation aspect is bypassed on purpose: the
 * breaker is applied programmatically around the same method the aspect wraps,
 * which keeps this a fast unit test while asserting genuine CB transitions.
 */
@ExtendWith(MockitoExtension.class)
class LlmClientTest {

    @Mock private RestTemplate restTemplate;

    private LlmClient llmClient;
    private LlmConfig llmConfig;
    private CircuitBreaker circuitBreaker;
    private io.micrometer.core.instrument.simple.SimpleMeterRegistry meterRegistry;

    private static final String SYS = "sys";
    private static final String USER = "user";

    @BeforeEach
    void setUp() {
        llmConfig = new LlmConfig();
        llmConfig.setChatModel("test-model");
        llmConfig.setBaseUrl("http://localhost:8001");

        meterRegistry = new io.micrometer.core.instrument.simple.SimpleMeterRegistry();
        llmClient = new LlmClient(restTemplate, llmConfig,
                new RagMetrics(meterRegistry),
                new com.smartdocchat.observability.LangfuseService());
        ReflectionTestUtils.setField(llmClient, "internalToken", "");

        CircuitBreakerConfig config = CircuitBreakerConfig.custom()
                .slidingWindowSize(10)
                .minimumNumberOfCalls(5)
                .failureRateThreshold(50)
                .waitDurationInOpenState(Duration.ofMillis(1))
                .permittedNumberOfCallsInHalfOpenState(3)
                .recordExceptions(ResourceAccessException.class)
                .build();
        circuitBreaker = CircuitBreakerRegistry.of(config).circuitBreaker("llmService");
    }

    private String guardedChat() {
        return circuitBreaker.executeSupplier(() -> llmClient.chat(SYS, USER));
    }

    @Test
    void chatReturnsContentOnSuccess() {
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(Map.of(
                        "message", Map.of("content", "answer"),
                        "eval_count", 42)));

        assertEquals("answer", guardedChat());
        ArgumentCaptor<HttpEntity> requestCaptor = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                requestCaptor.capture(), eq(Map.class));
        Map<?, ?> body = (Map<?, ?>) requestCaptor.getValue().getBody();
        assertEquals(Map.of("task_type", "qa"), body.get("routing"));
    }

    @Test
    void transportFailuresOpenTheCircuitAndSubsequentCallsFailFast() {
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenThrow(new ResourceAccessException("connection refused"));

        for (int i = 0; i < 5; i++) {
            assertEquals(LlmClient.UNAVAILABLE_RESPONSE,
                    llmClient.chatFallback(SYS, USER, assertThrows(ResourceAccessException.class, this::guardedChat)));
        }
        assertEquals(CircuitBreaker.State.OPEN, circuitBreaker.getState());

        // Open circuit: the provider is no longer contacted at all.
        assertThrows(CallNotPermittedException.class, this::guardedChat);
        verify(restTemplate, times(5)).exchange(eq("http://localhost:8001/api/chat"),
                eq(HttpMethod.POST), any(HttpEntity.class), eq(Map.class));
    }

    @Test
    void clientErrorsDoNotTripTheCircuit() {
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(Map.of()));

        for (int i = 0; i < 8; i++) {
            assertEquals(LlmClient.NO_RESPONSE_PLACEHOLDER,
                    llmClient.chatFallback(SYS, USER,
                            assertThrows(LlmClient.UnexpectedResponseException.class, this::guardedChat)));
        }
        assertEquals(CircuitBreaker.State.CLOSED, circuitBreaker.getState());
    }

    @Test
    void halfOpenSuccessesCloseTheCircuitAgain() {
        java.util.concurrent.atomic.AtomicInteger attempts = new java.util.concurrent.atomic.AtomicInteger();
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenAnswer(inv -> {
                    if (attempts.incrementAndGet() <= 5) {
                        throw new ResourceAccessException("down");
                    }
                    return ResponseEntity.ok(Map.of("message", Map.of("content", "back")));
                });

        // Trip the breaker (minimumNumberOfCalls=5).
        for (int i = 0; i < 5; i++) {
            try {
                guardedChat();
            } catch (ResourceAccessException | CallNotPermittedException expected) {
                // until the breaker opens / half-opens
            }
        }
        assertEquals(CircuitBreaker.State.OPEN, circuitBreaker.getState());

        // waitDurationInOpenState=1ms → after it elapses the next call moves
        // the breaker to HALF_OPEN; a successful trial lets traffic through.
        try {
            Thread.sleep(5);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
        assertEquals("back", guardedChat());
        assertEquals("back", guardedChat());
    }

    @Test
    void fallbackMapsExceptionsToCallerFacingPlaceholders() {
        assertEquals(LlmClient.UNAVAILABLE_RESPONSE, llmClient.chatFallback(
                SYS, USER, new ResourceAccessException("timeout")));
        assertEquals(LlmClient.NO_RESPONSE_PLACEHOLDER, llmClient.chatFallback(
                SYS, USER, new LlmClient.UnexpectedResponseException("bad body")));
    }

    @Test
    @SuppressWarnings("unchecked")
    void chatSendsTopPSamplingInOptions() {
        llmConfig.setMaxOutputTokens(256);
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(Map.of("message", Map.of("content", "answer"))));

        assertEquals("answer", guardedChat());

        ArgumentCaptor<HttpEntity<Map<String, Object>>> captor =
                ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                captor.capture(), eq(Map.class));
        Map<String, Object> body = captor.getValue().getBody();
        Map<String, Object> options = (Map<String, Object>) body.get("options");
        assertEquals(0.95, ((Number) options.get("top_p")).doubleValue());
        assertEquals(0.3, ((Number) options.get("temperature")).doubleValue());
        assertEquals(256, ((Number) options.get("num_predict")).intValue());
    }

    @Test
    void tokenUsageWithOllamaCountsRecordsTokensAndCost() {
        ReflectionTestUtils.setField(llmClient, "costPer1kJson",
                "{\"test-model\":0.0003}");
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(Map.of(
                        "message", Map.of("content", "answer"),
                        "prompt_eval_count", 150,
                        "eval_count", 50)));

        assertEquals("answer", guardedChat());

        assertEquals(200.0, meterRegistry.get("chat.tokens").summary().totalAmount());
        assertEquals(150.0, meterRegistry.get("chat.tokens.total")
                .tag("direction", "prompt").counter().count());
        assertEquals(50.0, meterRegistry.get("chat.tokens.total")
                .tag("direction", "completion").counter().count());
        // (150+50)/1000 * 0.0003 = 0.00006
        assertEquals(0.00006, meterRegistry.get("chat.cost.total").counter().count(), 1e-12);
    }

    @Test
    void tokenUsageFromUsageMapFormatIsRecorded() {
        ReflectionTestUtils.setField(llmClient, "costPer1kJson", "{}");
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(Map.of(
                        "message", Map.of("content", "answer"),
                        "usage", Map.of("prompt_tokens", 100, "completion_tokens", 25))));

        assertEquals("answer", guardedChat());

        assertEquals(125.0, meterRegistry.get("chat.tokens").summary().totalAmount());
    }

    @Test
    void tokenUsageWithStringCountsAndBlankCostJsonRecordsTokensOnly() {
        ReflectionTestUtils.setField(llmClient, "costPer1kJson", "{}");
        when(restTemplate.exchange(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(HttpEntity.class), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(Map.of(
                        "message", Map.of("content", "answer"),
                        "prompt_eval_count", "40",
                        "eval_count", "60")));

        assertEquals("answer", guardedChat());

        assertEquals(100.0, meterRegistry.get("chat.tokens").summary().totalAmount());
        // blank/empty cost JSON → no cost metric recorded
        assertNull(meterRegistry.find("chat.cost.total").counter());
    }
}
