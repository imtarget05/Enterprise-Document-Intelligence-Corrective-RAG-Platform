package com.smartdocchat.service;

import com.smartdocchat.config.CragConfig;
import com.smartdocchat.config.PromptInjectionProperties;
import com.smartdocchat.dto.ChatRequest;
import com.smartdocchat.dto.ChatResponse;
import com.smartdocchat.entity.ChatMessage;
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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Hardening test: the CRAG orchestration path inside processQuery must never
 * let a runtime exception from retrieval/reformulator/web-search escape to the
 * controller as 5xx. When CRAG throws, ChatService should record a structured
 * "error" outcome and return a safe abstention response, just like
 * "no_evidence". This is the contract that the agentic-path exception guard
 * (lines 87-92) was designed to provide — the CRAG branch must honour it too.
 */
@ExtendWith(MockitoExtension.class)
class ChatServiceCragExceptionHardeningTest {

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
        // disable prompt-injection gate so messages go to the CRAG branch
        pip.setEnabled(false);
        chatService = new ChatService(messageHandler, historyService, cragConfig, retrievalService,
                queryReformulator, webSearchService, promptInjectionDetector, pip,
                ragMetrics, documentService, new LangfuseService(), agentClient, normalizer);
        lenient().when(historyService.save(any())).thenAnswer(inv -> inv.getArgument(0));
        lenient().when(messageHandler.buildAbstentionResponse()).thenReturn("safe abstain");
    }

    private ChatRequest req(String msg) {
        return ChatRequest.builder().sessionId("s1").documentId(1L).message(msg).build();
    }

    @Test
    void retrievalThrows_processQueryDoesNotThrow_returnsAbstention() {
        // RAG path - not a supply-chain keyword, so goes to CRAG.
        when(retrievalService.retrieve(any(), any(), anyString(), anyInt()))
                .thenThrow(new RuntimeException("qdrant down"));

        ChatResponse response = chatService.processQuery("alice", req("Thủ đô Việt Nam?"));

        assertNotNull(response, "ChatService must not throw even when retrieval fails");
        // Safe abstention should be served from the error fallback branch.
        assertEquals("safe abstain", response.getAiResponse());
        verify(messageHandler).buildAbstentionResponse();
    }

    @Test
    void retrievalThrows_responseRagStrategyIndicatesError() {
        when(retrievalService.retrieve(any(), any(), anyString(), anyInt()))
                .thenThrow(new RuntimeException("qdrant timeout"));

        ChatResponse response = chatService.processQuery("alice", req("Bồi thường thiệt hại?"));

        assertNotNull(response);
        // Frontend should be able to render a distinguishable strategy label.
        assertEquals("error", response.getRagStrategy());
        assertEquals("error", response.getAnswerOrigin());
    }

    @Test
    void streamEndpoint_swallowsRetrievalException_completes() {
        // SSE stream: a retrieval exception must be reported via "error" event
        // and the emitter must complete (not hang). We only assert the
        // contract: processQueryStream returns an emitter and does not throw.
        lenient().when(retrievalService.retrieve(any(), any(), anyString(), anyInt()))
                .thenThrow(new RuntimeException("qdrant gone"));

        var emitter = chatService.processQueryStream("alice", req("Hello world?"));
        assertNotNull(emitter);
        // We do not call emitter.send here because the async task may run on
        // any thread; the contract is that the method itself never throws.
    }
}
