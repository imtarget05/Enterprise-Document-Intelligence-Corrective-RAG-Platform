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
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Service
@Slf4j
public class ChatService {

    private final MessageHandler messageHandler;
    private final HistoryService historyService;
    private final CragConfig cragConfig;
    private final RetrievalService retrievalService;
    private final QueryReformulator queryReformulator;
    private final WebSearchService webSearchService;
    private final PromptInjectionDetector promptInjectionDetector;
    private final PromptInjectionProperties promptInjectionProperties;
    private final RagMetrics ragMetrics;
    private final DocumentService documentService;
    private final LangfuseService langfuse;
    private final AgentClient agentClient;
    private final LegalQueryNormalizer normalizer;
    private final ChatDedupService dedupService;
    private final ChatDlqService dlqService;
    private final SseStreamManager sseStreamManager;

    @Autowired
    public ChatService(MessageHandler messageHandler, HistoryService historyService,
                       CragConfig cragConfig, RetrievalService retrievalService,
                       QueryReformulator queryReformulator, WebSearchService webSearchService,
                       PromptInjectionDetector promptInjectionDetector,
                       PromptInjectionProperties promptInjectionProperties,
                       RagMetrics ragMetrics, DocumentService documentService,
                       LangfuseService langfuse, AgentClient agentClient,
                       LegalQueryNormalizer normalizer,
                       ChatDedupService dedupService,
                       ChatDlqService dlqService,
                       SseStreamManager sseStreamManager) {
        this.messageHandler = messageHandler;
        this.historyService = historyService;
        this.cragConfig = cragConfig;
        this.retrievalService = retrievalService;
        this.queryReformulator = queryReformulator;
        this.webSearchService = webSearchService;
        this.promptInjectionDetector = promptInjectionDetector;
        this.promptInjectionProperties = promptInjectionProperties;
        this.ragMetrics = ragMetrics;
        this.documentService = documentService;
        this.langfuse = langfuse;
        this.agentClient = agentClient;
        this.normalizer = normalizer;
        this.dedupService = dedupService;
        this.dlqService = dlqService;
        this.sseStreamManager = sseStreamManager;
    }

    // Constructor with sseThreads for testing / backwards compatibility
    public ChatService(MessageHandler messageHandler, HistoryService historyService,
                       CragConfig cragConfig, RetrievalService retrievalService,
                       QueryReformulator queryReformulator, WebSearchService webSearchService,
                       PromptInjectionDetector promptInjectionDetector,
                       PromptInjectionProperties promptInjectionProperties,
                       RagMetrics ragMetrics, DocumentService documentService,
                       LangfuseService langfuse, AgentClient agentClient,
                       LegalQueryNormalizer normalizer,
                       int sseThreads) {
        this(messageHandler, historyService, cragConfig, retrievalService, queryReformulator,
                webSearchService, promptInjectionDetector, promptInjectionProperties,
                ragMetrics, documentService, langfuse, agentClient, normalizer,
                new ChatDedupService(), new ChatDlqService(), new SseStreamManager(sseThreads));
    }

    // Package-private constructor for testing (defaults sseThreads to 0)
    ChatService(MessageHandler messageHandler, HistoryService historyService,
                CragConfig cragConfig, RetrievalService retrievalService,
                QueryReformulator queryReformulator, WebSearchService webSearchService,
                PromptInjectionDetector promptInjectionDetector,
                PromptInjectionProperties promptInjectionProperties,
                RagMetrics ragMetrics, DocumentService documentService,
                LangfuseService langfuse, AgentClient agentClient,
                LegalQueryNormalizer normalizer) {
        this(messageHandler, historyService, cragConfig, retrievalService, queryReformulator,
                webSearchService, promptInjectionDetector, promptInjectionProperties,
                ragMetrics, documentService, langfuse, agentClient, normalizer, 0);
    }

    public Map<String, String> getDlqSnapshot() {
        return dlqService.getDlqSnapshot();
    }

    /**
     * Replay one DLQ entry through the existing SSE streaming path (which
     * reuses {@code sseStreamManager}'s executor). Returns false when the key
     * does not exist.
     */
    public boolean replayDlq(String key) {
        return dlqService.replay(key, entry -> processQueryStream(entry.ownerUsername(),
                com.smartdocchat.dto.ChatRequest.builder()
                        .sessionId(entry.sessionId())
                        .message(entry.query())
                        .mode("rag")
                        .build()));
    }

    /** Outcome of a Corrective RAG pass over the classic chat endpoints. */
    private record CragResult(
            List<RetrievalService.RetrievalResult> results,
            List<String> webSnippets,
            double confidenceScore,
            String strategy
    ) {
        CragResult() {
            this(Collections.emptyList(), Collections.emptyList(), 0.0, "direct");
        }

        /** Context fed to the prompt: chunks for retrieval, snippets for web search. */
        List<String> contextChunks() {
            return "web_search".equals(strategy)
                    ? webSnippets
                    : results.stream().map(RetrievalService.RetrievalResult::chunk).toList();
        }
    }

    // ------------------------------------------------------------------
    // Classic (sync) chat
    // ------------------------------------------------------------------

    public ChatResponse processQuery(String ownerUsername, ChatRequest request) {
        long started = System.currentTimeMillis();
        String userMessage = request.getMessage();
        ChatResponse response;

        if (isBlockedInjection(userMessage)) {
            ragMetrics.recordInjectionBlocked();
            ChatMessage blocked = saveResponse(ownerUsername, request, userMessage,
                    messageHandler.buildInjectionBlockedResponse(), null);
            response = toResponse(ownerUsername, blocked, emptyCrag("blocked"));
            ragMetrics.recordLatency(System.currentTimeMillis() - started);
            return response;
        }

        // All questions default to Agent mode unless explicitly requested as "rag"
        boolean agentMode = !"rag".equalsIgnoreCase(request.getMode());
        if (agentMode && dedupService.isDuplicateRequest(ownerUsername, request)) {
            // dedup: treat as already processed, fall through to RAG
            agentMode = false;
        }
        if (agentMode) {
            String traceId = langfuse.startTrace("agentic_request", ownerUsername,
                    Map.of("query", userMessage));
            try {
                AgentClient.AgentResponse agentResp = agentClient.invokeAgent(
                        ownerUsername, request.getSessionId(), userMessage, traceId);
                if (agentResp == null) {
                    throw new IllegalStateException("Agent returned null response");
                }
                langfuse.updateTrace(Map.of("agentAnswer", agentResp.answer()), null);
                ChatMessage saved = saveResponse(ownerUsername, request, userMessage,
                        agentResp.answer(), null);
                response = toResponse(ownerUsername, saved, emptyCrag("agentic"));
                // HITL: surface a paused action so the frontend can render the
                // approval card (approve/reject via /api/agent/approvals).
                response.setHitlPending(agentResp.hitlPending());
                response.setHitlApprovalId(agentResp.approvalId());
                ragMetrics.recordRequest("agentic", "high");
                ragMetrics.recordAnswer("agentic", false);
                ragMetrics.recordLatency(System.currentTimeMillis() - started);
                return response;
            } catch (Exception e) {
                log.warn("Agentic path failed, falling back to RAG: {}", e.getMessage());
                langfuse.flush();
            } finally {
                langfuse.flush();
            }
        }

        try {
            CragResult crag = runCrag(ownerUsername, request.getDocumentId(), userMessage, request.isWebSearch());

            String aiResponse;
            if ("no_evidence".equals(crag.strategy())) {
                aiResponse = messageHandler.buildAbstentionResponse();
            } else {
                String llmRaw = messageHandler.callLLM(buildPromptForStrategy(userMessage, crag));
                if (isUnavailableOrFailed(llmRaw)) {
                    log.info("LLM unavailable or failed; falling back to extractive grounded legal synthesis for: {}", userMessage);
                    aiResponse = synthesizeExtractiveLegalAnswer(userMessage, crag);
                } else {
                    aiResponse = strategyPrefix(crag) + llmRaw;
                }
            }
            ChatMessage saved = saveResponse(ownerUsername, request, userMessage, aiResponse, buildSourceChunks(crag));
            response = toResponse(ownerUsername, saved, crag);

            if ("no_evidence".equals(crag.strategy())) {
                ragMetrics.recordAbstention();
            }
            String confidenceLabel;
            double confidenceScore;
            if ("no_evidence".equals(crag.strategy())) {
                confidenceLabel = "low";
                confidenceScore = 0.0;
            } else {
                confidenceLabel = confidenceLabel(crag.confidenceScore());
                confidenceScore = crag.confidenceScore();
            }
            ragMetrics.recordRequest(crag.strategy(), confidenceLabel);
            ragMetrics.recordAnswer(crag.strategy(), buildSourceChunks(crag) != null);
        } catch (RuntimeException e) {
            // CRAG orchestration failure (retrieval down, reformulator bug, web
            // search exception, etc.) must NEVER escape as 5xx. Return a safe
            // abstention labelled "error" so the frontend can show a clear
            // "không thể trả lời" instead of a generic failure, and we keep
            // an audit trail via ragMetrics + log.
            log.error("CRAG path failed, serving safe abstention: {}", e.getMessage(), e);
            String abstain = messageHandler.buildAbstentionResponse();
            ChatMessage saved = saveResponse(ownerUsername, request, userMessage, abstain, null);
            response = toResponse(ownerUsername, saved, emptyCrag("error"));
            ragMetrics.recordAbstention();
        }

        ragMetrics.recordLatency(System.currentTimeMillis() - started);
        return response;
    }

    public SseEmitter processQueryStream(String ownerUsername, ChatRequest request) {
        SseEmitter emitter = new SseEmitter(180_000L);

        sseStreamManager.execute(() -> {
            try {
                String userMessage = request.getMessage();
                if (isBlockedInjection(userMessage)) {
                    ragMetrics.recordInjectionBlocked();
                    ChatMessage blocked = saveResponse(ownerUsername, request, userMessage,
                            messageHandler.buildInjectionBlockedResponse(), null);
                    Map<String, Object> meta = new LinkedHashMap<>();
                    meta.put("ragStrategy", "blocked");
                    meta.put("confidence", "low");
                    meta.put("confidenceScore", 0.0);
                    emitter.send(SseEmitter.event().name("metadata").data(meta));
                    emitter.send(SseEmitter.event().name("complete").data(toResponse(ownerUsername, blocked, emptyCrag("blocked"))));
                    emitter.complete();
                    return;
                }

                // All questions default to Agent mode unless explicitly requested as "rag"
                boolean agentMode = !"rag".equalsIgnoreCase(request.getMode());
                if (agentMode && dedupService.isDuplicateRequest(ownerUsername, request)) {
                    agentMode = false;
                }

                if (agentMode) {
                    emitter.send(SseEmitter.event().name("status").data("Đang gọi Agent để tìm kiếm thông tin..."));
                    String traceId = langfuse.startTrace("agentic_request", ownerUsername,
                            Map.of("query", userMessage));
                    try {
                        AgentClient.AgentResponse agentResp = agentClient.invokeAgent(
                                ownerUsername, request.getSessionId(), userMessage, traceId);
                        if (agentResp == null) {
                            throw new IllegalStateException("Agent returned null response");
                        }
                        ragMetrics.recordRequest("agentic", "high");
                        langfuse.updateTrace(Map.of("agentAnswer", agentResp.answer()), null);

                        Map<String, Object> agentMeta = new LinkedHashMap<>();
                        agentMeta.put("ragStrategy", "agentic");
                        agentMeta.put("agentType", agentResp.agentType() != null ? agentResp.agentType() : "rag");
                        agentMeta.put("confidence", "high");
                        agentMeta.put("confidenceScore", agentResp.confidence() != null ? agentResp.confidence() : 0.8);
                        agentMeta.put("sources", agentResp.sources());
                        agentMeta.put("sourceChunks", "");
                        agentMeta.put("documentId", request.getDocumentId());
                        agentMeta.put("hitlPending", agentResp.hitlPending());
                        agentMeta.put("hitlApprovalId", agentResp.approvalId());
                        emitter.send(SseEmitter.event().name("metadata").data(agentMeta));
                        emitter.send(SseEmitter.event().name("chunk").data(agentResp.answer()));

                        ChatMessage saved = saveResponse(ownerUsername, request, userMessage,
                                agentResp.answer(), null);
                        ChatResponse done = toResponse(ownerUsername, saved, emptyCrag("agentic"));
                        done.setHitlPending(agentResp.hitlPending());
                        done.setHitlApprovalId(agentResp.approvalId());
                        emitter.send(SseEmitter.event().name("complete").data(done));
                        emitter.complete();
                        return;
                    } catch (Exception e) {
                        log.warn("Agentic stream failed, falling back to RAG: {}", e.getMessage());
                        langfuse.flush();
                        // fall through to CRAG path below
                    }
                }

                CragResult crag;
                try {
                    emitter.send(SseEmitter.event().name("status").data("Đang tìm kiếm tài liệu (RAG)..."));
                    crag = runCrag(ownerUsername, request.getDocumentId(), userMessage, request.isWebSearch());
                } catch (RuntimeException e) {
                    log.error("CRAG stream path failed, serving safe abstention: {}", e.getMessage(), e);
                    ragMetrics.recordAbstention();
                    String abstain = messageHandler.buildAbstentionResponse();
                    Map<String, Object> errMeta = new LinkedHashMap<>();
                    errMeta.put("ragStrategy", "error");
                    errMeta.put("confidence", "low");
                    errMeta.put("confidenceScore", 0.0);
                    try {
                        emitter.send(SseEmitter.event().name("metadata").data(errMeta));
                        emitter.send(SseEmitter.event().name("chunk").data(abstain));
                    } catch (IOException ignored) {
                        // client may already be gone; we still try to complete cleanly
                    }
                    ChatMessage saved = saveResponse(ownerUsername, request, userMessage, abstain, null);
                    try {
                        emitter.send(SseEmitter.event().name("complete").data(toResponse(ownerUsername, saved, emptyCrag("error"))));
                    } catch (IOException ignored) {
                        // ignore
                    }
                    emitter.complete();
                    return;
                }

                // Bug 1 fix: force low confidence when strategy is no_evidence
                String metaConfidenceLabel;
                double metaConfidenceScore;
                if ("no_evidence".equals(crag.strategy())) {
                    metaConfidenceLabel = "low";
                    metaConfidenceScore = 0.0;
                } else {
                    metaConfidenceLabel = confidenceLabel(crag.confidenceScore());
                    metaConfidenceScore = round(crag.confidenceScore());
                }

                // Send metadata (sources + strategy) up front, before the token stream.
                Map<String, Object> metaEvent = new LinkedHashMap<>();
                metaEvent.put("sourceChunks", buildSourceChunks(crag));
                // Structured citations for Decision 14 (frontend evidence UI).
                metaEvent.put("sources",
                        buildSources(ownerUsername, request.getDocumentId(), crag));
                metaEvent.put("documentId", request.getDocumentId());
                metaEvent.put("confidenceScore", metaConfidenceScore);
                metaEvent.put("confidence", metaConfidenceLabel);
                metaEvent.put("ragStrategy", crag.strategy());
                emitter.send(SseEmitter.event().name("metadata").data(metaEvent));

                // Unanswerable question: stream the safe abstention response, no LLM call.
                if ("no_evidence".equals(crag.strategy())) {
                    ragMetrics.recordAbstention();
                    ragMetrics.recordRequest(crag.strategy(), "low");
                    ragMetrics.recordAnswer(crag.strategy(), false);
                    String abstention = messageHandler.buildAbstentionResponse();
                    emitter.send(SseEmitter.event().name("chunk").data(abstention));
                    ChatMessage saved = saveResponse(ownerUsername, request, userMessage, abstention,
                            buildSourceChunks(crag));
                    emitter.send(SseEmitter.event().name("complete").data(toResponse(ownerUsername, saved, crag)));
                    emitter.complete();
                    return;
                }

                String prefix = strategyPrefix(crag);
                String prompt = buildPromptForStrategy(userMessage, crag);
                StringBuilder aiResponseBuilder = new StringBuilder();

                if (!prefix.isEmpty()) {
                    aiResponseBuilder.append(prefix);
                    emitter.send(SseEmitter.event().name("chunk").data(prefix));
                }

                try {
                    messageHandler.streamLLM(prompt, token -> {
                        aiResponseBuilder.append(token);
                        try {
                            emitter.send(SseEmitter.event().name("chunk").data(token));
                        } catch (IOException e) {
                            throw new IllegalStateException("SSE client disconnected during stream", e);
                        }
                    });
                } catch (Exception streamEx) {
                    log.warn("LLM stream unavailable ({}), falling back to extractive grounded legal synthesis", streamEx.getMessage());
                    String extracted = synthesizeExtractiveLegalAnswer(userMessage, crag);
                    aiResponseBuilder.append(extracted);
                    try {
                        emitter.send(SseEmitter.event().name("chunk").data(extracted));
                    } catch (IOException ignored) {}
                }

                ragMetrics.recordRequest(crag.strategy(), confidenceLabel(crag.confidenceScore()));
                ragMetrics.recordAnswer(crag.strategy(), buildSourceChunks(crag) != null);

                ChatMessage saved = saveResponse(ownerUsername, request, userMessage,
                        aiResponseBuilder.toString(), buildSourceChunks(crag));

                emitter.send(SseEmitter.event().name("complete").data(toResponse(ownerUsername, saved, crag)));
                emitter.complete();

            } catch (Exception e) {
                log.error("Error in streaming task: {}", e.getMessage(), e);
                // DLQ stub — retain failed SSE for manual replay/debugging
                try {
                    String userMessage = request.getMessage();
                    dlqService.recordDlq(ownerUsername, request.getSessionId(), userMessage, e.getMessage());
                } catch (Exception ignored) {}
                try {
                    emitter.send(SseEmitter.event().name("error").data(e.getMessage()));
                    emitter.completeWithError(e);
                } catch (Exception ex) {
                    // Ignored
                }
            }
        });

        return emitter;
    }

    // ------------------------------------------------------------------
    // Guards (prompt injection) & persistence helpers
    // ------------------------------------------------------------------

    /** True when the user message must be rejected before any retrieval/LLM call. */
    private boolean isBlockedInjection(String userMessage) {
        return promptInjectionProperties.isEnabled()
                && promptInjectionDetector.analyze(userMessage) == PromptInjectionDetector.Severity.HIGH;
    }

    private ChatMessage saveResponse(String ownerUsername, ChatRequest request, String userMessage,
                                     String aiResponse, String sourceChunks) {
        return historyService.save(ChatMessage.builder()
                .sessionId(request.getSessionId())
                .ownerUsername(ownerUsername)
                .documentId(request.getDocumentId())
                .userMessage(userMessage)
                .aiResponse(aiResponse)
                .sourceChunks(sourceChunks)
                .build());
    }

    /** Empty CRAG result for guarded responses (blocked / no evidence). */
    private CragResult emptyCrag(String strategy) {
        return new CragResult(List.of(), List.of(), 0.0, strategy);
    }

    /**
     * Null-tolerant Map.of for Langfuse trace/span metadata: unlike Map.of,
     * this accepts null values (e.g. documentId when no document selected).
     * Expects key/value pairs: traceMeta("a", 1, "b", "x").
     */
    private static Map<String, Object> traceMeta(Object... keyValuePairs) {
        Map<String, Object> metadata = new HashMap<>();
        for (int i = 0; i < keyValuePairs.length; i += 2) {
            metadata.put((String) keyValuePairs[i], keyValuePairs[i + 1]);
        }
        return metadata;
    }

    public List<ChatMessage> getChatHistory(String ownerUsername, String sessionId) {
        return historyService.getChatHistory(ownerUsername, sessionId);
    }

    public List<ChatMessage> getChatHistory(String ownerUsername, String sessionId, Long documentId) {
        return historyService.getChatHistory(ownerUsername, sessionId, documentId);
    }

    public void clearChatHistory(String ownerUsername, String sessionId) {
        historyService.clearChatHistory(ownerUsername, sessionId);
    }

    public List<Map<String, Object>> getUniqueSessions(String ownerUsername) {
        return historyService.getUniqueSessions(ownerUsername);
    }

    // ------------------------------------------------------------------
    // Corrective RAG (CRAG) orchestration
    // ------------------------------------------------------------------

    private CragResult runCrag(String ownerUsername, Long documentId, String query, boolean webSearchRequested) {
        // traceMeta (not Map.of) because documentId is null when the user chats
        // without selecting a document — Map.of rejects null values with NPE.
        String traceId = langfuse.startTrace("crag_request", ownerUsername,
                traceMeta("documentId", documentId, "query", query));
        long requestStart = System.currentTimeMillis();

        String retrieveSpan = langfuse.startSpan("retrieve_chunks",
                Map.of("query", query, "topK", cragConfig.getTopK()));
        List<RetrievalService.RetrievalResult> results =
                retrievalService.retrieve(ownerUsername, documentId, query, cragConfig.getTopK());
        double confidence = results.isEmpty() ? 0.0 : results.get(0).score();
        langfuse.endSpan(retrieveSpan, String.format("%d chunks, top score %.3f",
                        results.size(), confidence),
                Map.of("chunkCount", results.size(), "topScore", round(confidence),
                        "latencyMs", System.currentTimeMillis() - requestStart));

        String strategy = "direct";

        // Relevance sanity-check (anti-hallucination): a high vector score alone
        // is not proof of topical relevance. If none of the retrieved chunks
        // share any significant token with the query, the context is likely
        // unrelated and answering "directly" from it lets the LLM fabricate
        // with high confidence. Demote to the corrective loop instead.
        String judgeSpan = langfuse.startSpan("judge_relevance",
                Map.of("confidence", round(confidence), "threshold", cragConfig.getConfidenceThreshold()));
        boolean passedJudge = confidence >= cragConfig.getConfidenceThreshold()
                && hasLexicalSupport(query, results);
        langfuse.endSpan(judgeSpan, passedJudge ? "direct" : "needs_corrective",
                Map.of("passed", passedJudge, "confidence", round(confidence)));

        if (passedJudge) {
            langfuse.updateTrace(
                    traceMeta("strategy", "direct", "confidence", round(confidence),
                            "chunkCount", results.size(), "documentId", documentId),
                    Map.of("query", query));
            langfuse.flush();
            return new CragResult(results, List.of(), confidence, strategy);
        }

        // Corrective loop: reformulate (if possible) and re-retrieve.
        String reformSpan = langfuse.startSpan("query_reformulate",
                Map.of("originalQuery", query, "maxReformulations", cragConfig.getMaxReformulations()));
        List<String> variants = queryReformulator.reformulate(query, cragConfig.getMaxReformulations());
        langfuse.endSpan(reformSpan, "generated " + variants.size() + " variants",
                Map.of("variantCount", variants.size(), "variants", variants));

        Map<String, RetrievalService.RetrievalResult> merged = new LinkedHashMap<>();
        results.forEach(r -> merged.put(r.chunk(), r));
        double bestScore = confidence;
        strategy = "corrective";

        String reretSpan = langfuse.startSpan("retrieve_chunks_corrective",
                Map.of("variantCount", variants.size()));
        for (String variant : variants) {
            List<RetrievalService.RetrievalResult> vResults =
                    retrievalService.retrieve(ownerUsername, documentId, variant, cragConfig.getTopK());
            for (RetrievalService.RetrievalResult r : vResults) {
                bestScore = Math.max(bestScore, r.score());
                merged.putIfAbsent(r.chunk(), r);
            }
        }
        confidence = bestScore;
        langfuse.endSpan(reretSpan, String.format("merged %d unique chunks, best %.3f",
                        merged.size(), confidence), Map.of("mergedCount", merged.size()));

        List<RetrievalService.RetrievalResult> topMerged = keepTopK(merged.values(), cragConfig.getTopK());
        if (confidence >= cragConfig.getConfidenceThreshold()
                && hasLexicalSupport(query, topMerged)) {
            langfuse.updateTrace(
                    traceMeta("strategy", "corrective", "confidence", round(confidence),
                            "chunkCount", topMerged.size(), "documentId", documentId,
                            "reformulated", true),
                    Map.of("query", query, "variants", variants));
            langfuse.flush();
            return new CragResult(topMerged, List.of(), confidence, strategy);
        }

        // Still low -> web search (if configured/requested) else abstain
        // (safe "insufficient evidence") or general knowledge.
        boolean useWeb = webSearchRequested
                || (webSearchService.isConfigured() && cragConfig.isWebSearchEnabled());
        if (useWeb) {
            String webSpan = langfuse.startSpan("web_search", Map.of("query", query));
            Optional<List<String>> web = webSearchService.search(query);
            if (web.isPresent()) {
                langfuse.endSpan(webSpan, "web snippets retrieved",
                        Map.of("snippetCount", web.get().size(), "strategy", "web_search"));
                langfuse.updateTrace(
                        traceMeta("strategy", "web_search", "confidence", round(confidence),
                                "documentId", documentId, "webSearch", true),
                        Map.of("query", query));
                langfuse.flush();
                return new CragResult(List.of(), web.get(), confidence, "web_search");
            }
            langfuse.endSpan(webSpan, "web search returned nothing",
                    Map.of("strategy", "no_evidence"));
        }
        if (cragConfig.isAbstainEnabled()) {
            langfuse.updateTrace(
                    traceMeta("strategy", "no_evidence", "confidence", round(confidence),
                            "documentId", documentId, "abstained", true),
                    Map.of("query", query));
            langfuse.flush();
            return new CragResult(List.of(), List.of(), confidence, "no_evidence");
        }
        langfuse.updateTrace(
                traceMeta("strategy", "general_knowledge", "confidence", round(confidence),
                        "documentId", documentId),
                Map.of("query", query));
        langfuse.flush();
        return new CragResult(List.of(), List.of(), confidence, "general_knowledge");
    }

    private List<RetrievalService.RetrievalResult> keepTopK(
            java.util.Collection<RetrievalService.RetrievalResult> collection, int topK) {
        List<RetrievalService.RetrievalResult> sorted = new ArrayList<>(collection);
        sorted.sort((a, b) -> Double.compare(b.score(), a.score()));
        return sorted.size() > topK ? sorted.subList(0, topK) : sorted;
    }

    /** Common English/Vietnamese function words that carry no topical signal. */
    private static final java.util.Set<String> STOPWORDS = java.util.Set.of(
            "the", "and", "for", "with", "what", "how", "does", "did", "are", "was",
            "were", "when", "which", "that", "this", "those", "these", "from",
            "into", "about", "can", "could", "should", "would", "will", "have",
            "has", "had", "not", "but", "all", "any", "its", "his", "her", "their",
            // Vietnamese
            "cách", "hệ", "thống", "của", "và", "cho", "là", "gì", "như", "thế",
            "nào", "các", "được", "không", "trong", "một", "những", "với", "từ");

    /**
     * True when at least one retrieved chunk shares a significant token with
     * the query. Used as a cheap lexical relevance gate so that a high vector
     * similarity alone can never route an unrelated context into the
     * "direct" answer path (hallucination guard, eval case q27).
     */
    private boolean hasLexicalSupport(String query, List<RetrievalService.RetrievalResult> results) {
        java.util.Set<String> queryTokens = significantTokens(query);
        if (queryTokens.isEmpty()) {
            // Nothing verifiable in the query — keep legacy behaviour.
            return true;
        }
        for (RetrievalService.RetrievalResult r : results) {
            if (!java.util.Collections.disjoint(significantTokens(r.chunk()), queryTokens)) {
                return true;
            }
        }
        return false;
    }

    private java.util.Set<String> significantTokens(String text) {
        java.util.Set<String> tokens = new java.util.HashSet<>();
        String folded = normalizer.fold(text.toLowerCase());
        for (String raw : folded.split("[^\\p{L}]+")) {
            if (raw.length() >= 2 && !STOPWORDS.contains(raw)) {
                tokens.add(raw);
            }
        }
        return tokens;
    }

    private String buildPromptForStrategy(String query, CragResult crag) {
        return switch (crag.strategy()) {
            case "web_search" -> messageHandler.buildWebSearchPrompt(query, crag.contextChunks());
            case "general_knowledge" -> messageHandler.buildGeneralKnowledgePrompt(query);
            default -> messageHandler.buildPrompt(query, crag.contextChunks());
        };
    }

    private String strategyPrefix(CragResult crag) {
        return switch (crag.strategy()) {
            case "web_search" -> "[Web Search]\n\n";
            case "general_knowledge" -> "[General Knowledge]\n\n";
            default -> "";
        };
    }

    private String buildSourceChunks(CragResult crag) {
        List<String> context = crag.contextChunks();
        return context.isEmpty() ? null : String.join("\n---\n", context);
    }

    // ------------------------------------------------------------------
    // Response mapping
    // ------------------------------------------------------------------

    private ChatResponse toResponse(String ownerUsername, ChatMessage message, CragResult crag) {
        // Bug 1 fix: force low confidence when strategy is no_evidence
        String label;
        double score;
        if ("no_evidence".equals(crag.strategy())) {
            label = "low";
            score = 0.0;
        } else {
            label = confidenceLabel(crag.confidenceScore());
            score = round(crag.confidenceScore());
        }
        return ChatResponse.builder()
                .id(message.getId())
                .sessionId(message.getSessionId())
                .userMessage(message.getUserMessage())
                .aiResponse(message.getAiResponse())
                .sourceChunks(message.getSourceChunks())
                .documentId(message.getDocumentId())
                .confidence(label)
                .confidenceScore(score)
                .ragStrategy(crag.strategy())
                .sources(buildSources(ownerUsername, message.getDocumentId(), crag))
                .build();
    }

    /**
     * Structured citations (Decision 13). Legal metadata is included only
     * when verifiably present; missing fields stay null rather than being
     * fabricated. Document-level metadata is attached when the document is
     * accessible to the requesting owner.
     */
    private List<Map<String, Object>> buildSources(String ownerUsername, Long documentId, CragResult crag) {
        com.smartdocchat.entity.Document doc = null;
        if (documentId != null) {
            try {
                doc = documentService.getDocumentById(documentId, ownerUsername);
            } catch (RuntimeException e) {
                log.debug("Source enrichment skipped: document {} not accessible for {}", documentId, ownerUsername);
            }
        }

        List<Map<String, Object>> sources = new ArrayList<>();
        for (RetrievalService.RetrievalResult r : crag.results()) {
            String content = r.chunk();
            if (content.length() > 300) {
                content = content.substring(0, 300);
            }
            Map<String, Object> s = new LinkedHashMap<>();
            s.put("documentId", documentId);
            s.put("content", content);
            s.put("score", round(r.score()));
            s.put("sourceType", doc != null && doc.getSourceType() != null
                    ? doc.getSourceType().name() : "document");
            s.put("chunkId", r.chunkId());
            s.put("article", r.article());
            s.put("clause", r.clause());
            s.put("point", r.point());
            s.put("documentTitle", doc != null ? doc.getTitle() : null);
            s.put("documentNumber", doc != null ? doc.getDocumentNumber() : null);
            sources.add(s);
        }
        return sources;
    }

    private boolean isUnavailableOrFailed(String response) {
        if (response == null || response.isBlank()) {
            return true;
        }
        return response.startsWith(LlmClient.UNAVAILABLE_RESPONSE)
                || response.startsWith(LlmClient.NO_RESPONSE_PLACEHOLDER)
                || response.contains("language model is temporarily unavailable")
                || response.contains("could not generate a response");
    }

    public String synthesizeExtractiveLegalAnswer(String query, CragResult crag) {
        if (crag.results() == null || crag.results().isEmpty()) {
            return messageHandler.buildAbstentionResponse();
        }
        StringBuilder sb = new StringBuilder();
        sb.append("Căn cứ vào dữ liệu văn bản quy phạm pháp luật và quy chế doanh nghiệp đã được xác thực trong hệ thống:\n\n");
        int idx = 1;
        for (RetrievalService.RetrievalResult r : crag.results()) {
            sb.append("### ").append(idx++).append(". ");
            boolean hasLegalRef = false;
            if (r.article() != null && !r.article().isBlank()) {
                sb.append("Điều ").append(r.article());
                hasLegalRef = true;
            }
            if (r.clause() != null && !r.clause().isBlank()) {
                sb.append(" (Khoản ").append(r.clause()).append(")");
                hasLegalRef = true;
            }
            if (r.point() != null && !r.point().isBlank()) {
                sb.append(" Điểm ").append(r.point());
                hasLegalRef = true;
            }
            if (!hasLegalRef) {
                sb.append("Căn cứ quy định liên quan");
            }
            sb.append(" — *Độ tin cậy: ").append(Math.round(r.score() * 100)).append("%*\n\n");

            String content = r.chunk() != null ? r.chunk().trim() : "";
            sb.append("> ").append(content.replace("\n", "\n> ")).append("\n\n");
        }
        sb.append("────────────────────────────────────────\n");
        sb.append("📋 *Nội dung được trích xuất trực tiếp từ các văn bản chính thức theo quy chế pháp lý.*");
        return sb.toString();
    }

    private String confidenceLabel(double score) {
        if (score >= 0.70) {
            return "high";
        }
        if (score >= 0.6) {
            return "medium";
        }
        return "low";
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
