package com.smartdocchat.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartdocchat.util.LlmConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MessageHandlerTest {

    @Mock private RestTemplate restTemplate;
    @Mock private LlmClient llmClient;

    private LlmConfig llmConfig;
    private MessageHandler messageHandler;

    @BeforeEach
    void setUp() {
        llmConfig = new LlmConfig();
        llmConfig.setChatModel("@cf/meta/llama-3.3-70b-instruct-fp8-fast");
        llmConfig.setBaseUrl("http://localhost:8001");
        llmConfig.setMaxAttempts(2);
        llmConfig.setRetryBackoffMs(1);
        messageHandler = new MessageHandler(llmConfig, restTemplate,
                new com.smartdocchat.metrics.RagMetrics(new io.micrometer.core.instrument.simple.SimpleMeterRegistry()),
                llmClient);
    }

    @Test
    void buildPromptIncludesContextAndQuestion() {
        String prompt = messageHandler.buildPrompt("What is X?", List.of("chunk one", "chunk two"));
        assertTrue(prompt.contains("[1] chunk one"));
        assertTrue(prompt.contains("[2] chunk two"));
        assertTrue(prompt.contains("CÂU HỎI: What is X?"));
        assertFalse(prompt.contains("Cite the numbered excerpt"));
        assertFalse(prompt.contains("Never infer an exact number"));
        assertFalse(prompt.contains("Điều 7 Luật Doanh nghiệp"));
    }

    @Test
    void buildPromptHandlesEmptyContext() {
        String prompt = messageHandler.buildPrompt("What is X?", List.of());
        assertTrue(prompt.contains("(Không tìm thấy tài liệu liên quan)"));
    }

    @Test
    void buildsFallbackPromptsAndAbstention() {
        assertTrue(messageHandler.buildGeneralKnowledgePrompt("Q").contains("Không tìm thấy thông tin trong tài liệu"));
        assertTrue(messageHandler.buildWebSearchPrompt("Q", List.of("snippet")).contains("[1] snippet"));
        assertTrue(messageHandler.buildAbstentionResponse().contains("Không tìm thấy thông tin trong tài liệu"));
        assertTrue(messageHandler.buildInjectionBlockedResponse().contains("override the assistant's behavior"));
    }

    @Test
    void callLLMOnceExtractsContentFromResponse() {
        when(llmClient.chat("sys", "user")).thenReturn("hello world");

        assertEquals("hello world", messageHandler.callLLMOnce("sys", "user"));
    }

    @Test
    void callLLMRetriesUntilSuccess() {
        when(llmClient.chat(eq("sys"), eq("user")))
                .thenReturn(LlmClient.NO_RESPONSE_PLACEHOLDER)
                .thenReturn("final answer");

        assertEquals("final answer", messageHandler.callLLM("sys", "user"));
    }

    @Test
    void callLLMReturnsLastErrorAfterExhaustingRetries() {
        when(llmClient.chat(anyString(), anyString()))
                .thenReturn(LlmClient.NO_RESPONSE_PLACEHOLDER);

        String result = messageHandler.callLLM("sys", "user");
        assertTrue(result.startsWith("Sorry, I could not generate a response."));
    }

    @Test
    @SuppressWarnings("unchecked")
    void streamLLMDeliversTokensToConsumer() throws Exception {
        String ndjson = "{\"message\":{\"content\":\"Hel\"}}\n{\"message\":{\"content\":\"lo world\"}}\n";
        AtomicInteger calls = new AtomicInteger();
        when(restTemplate.execute(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(org.springframework.web.client.RequestCallback.class),
                any(org.springframework.web.client.ResponseExtractor.class)))
                .thenAnswer(inv -> {
                    calls.incrementAndGet();
                    org.springframework.web.client.ResponseExtractor<Object> extractor = inv.getArgument(3);
                    org.springframework.http.client.ClientHttpResponse mockResponse =
                            mock(org.springframework.http.client.ClientHttpResponse.class);
                    when(mockResponse.getStatusCode()).thenReturn(HttpStatus.OK);
                    when(mockResponse.getBody()).thenReturn(
                            new ByteArrayInputStream(ndjson.getBytes(StandardCharsets.UTF_8)));
                    return extractor.extractData(mockResponse);
                });

        List<String> tokens = new ArrayList<>();
        messageHandler.streamLLM("sys", "user", tokens::add);

        assertEquals(List.of("Hel", "lo world"), tokens);
        assertEquals(1, calls.get());
    }

    @Test
    @SuppressWarnings("unchecked")
    void streamLLMPropagatesTransportErrors() {
        when(restTemplate.execute(eq("http://localhost:8001/api/chat"), eq(HttpMethod.POST),
                any(org.springframework.web.client.RequestCallback.class),
                any(org.springframework.web.client.ResponseExtractor.class)))
                .thenThrow(new IllegalStateException("LLM stream request failed: 500"));

        assertThrows(IllegalStateException.class, () -> messageHandler.streamLLM("sys", "user", t -> {
        }));
    }

    private boolean callsNoOp() {
        return true;
    }
}
