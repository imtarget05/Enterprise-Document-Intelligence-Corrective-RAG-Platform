package com.smartdocchat.service;

import com.smartdocchat.config.CragConfig;
import com.smartdocchat.config.PromptInjectionProperties;
import com.smartdocchat.dto.ChatRequest;
import com.smartdocchat.dto.ChatResponse;
import com.smartdocchat.metrics.RagMetrics;
import com.smartdocchat.observability.LangfuseService;
import com.smartdocchat.security.PromptInjectionDetector;
import com.smartdocchat.util.LegalQueryNormalizer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Hardening test: the generic agentic path must degrade gracefully. When
 * the agent client throws (down/unreachable), ChatService MUST fall back to the
 * RAG path and NEVER propagate the exception to the caller.
 */
@ExtendWith(MockitoExtension.class)
class ChatServiceFallbackHardeningTest {

    @Mock private MessageHandler messageHandler;
    @Mock private HistoryService historyService;
    @Mock private RetrievalService retrievalService;
    @Mock private QueryReformulator queryReformulator;
    @Mock private WebSearchService webSearchService;
    @Mock private PromptInjectionDetector promptInjectionDetector;
    @Mock private RagMetrics ragMetrics;
    @Mock private DocumentService documentService;
    @Mock private AgentClient agentClient;
    private LegalQueryNormalizer normalizer = new LegalQueryNormalizer();

    private ChatService chatService;

    @BeforeEach
    void setUp() {
        CragConfig cragConfig = new CragConfig();
        PromptInjectionProperties pip = new PromptInjectionProperties();
        chatService = new ChatService(messageHandler, historyService, cragConfig, retrievalService,
                queryReformulator, webSearchService, promptInjectionDetector, pip,
                ragMetrics, documentService, new LangfuseService(), agentClient, normalizer);
        // default stubs so the RAG fallback path does not itself throw
        lenient().when(historyService.save(any())).thenAnswer(inv -> inv.getArgument(0));
        lenient().when(retrievalService.retrieve(any(), any(), anyString(), anyInt())).thenReturn(List.of());
        lenient().when(queryReformulator.reformulate(anyString(), anyInt())).thenReturn(List.of());
        lenient().when(webSearchService.isConfigured()).thenReturn(false);
        lenient().when(messageHandler.buildAbstentionResponse())
                .thenReturn("no evidence");
    }

    private ChatRequest req(String msg) {
        return ChatRequest.builder().sessionId("s1").documentId(1L).message(msg).build();
    }

    @Test
    void agentDown_fallsBackToRagWithoutThrowing() {
        // any non-"rag" message goes through the generic agent path first
        String supplyMsg = "dự báo nhu cầu tồn kho supplier risk lead time";
        when(agentClient.invokeAgent(any(), any(), any(), any(), any()))
                .thenThrow(new RuntimeException("agent unavailable"));

        ChatResponse response = chatService.processQuery("alice", req(supplyMsg));

        assertNotNull(response, "response must not be null even when agent is down");
        verify(agentClient).invokeAgent(any(), any(), any(), any(), any());
        // RAG fallback should have been attempted (abstention since no context)
        verify(messageHandler).buildAbstentionResponse();
    }

    @Test
    void agentReturnsNull_fallsBackSafely() {
        String supplyMsg = "dự báo nhu cầu tồn kho supplier risk lead time";
        when(agentClient.invokeAgent(any(), any(), any(), any(), any())).thenReturn(null);

        ChatResponse response = chatService.processQuery("alice", req(supplyMsg));

        assertNotNull(response);
        verify(agentClient).invokeAgent(any(), any(), any(), any(), any());
    }
}
