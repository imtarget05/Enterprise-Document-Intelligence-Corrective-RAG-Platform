package com.smartdocchat.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ChatResponse {
    private Long id;
    private String sessionId;
    private String userMessage;
    private String aiResponse;
    private String sourceChunks;
    private Long documentId;

    /** CRAG confidence label: "high" (>=0.70), "medium" (>=0.6), "low". */
    private String confidence;
    /** CRAG retrieval confidence score in [0,1]. */
    private Double confidenceScore;
    /** CRAG strategy used: "direct" | "corrective" | "web_search" | "general_knowledge". */
    private String ragStrategy;
    /** Structured citations: documentId, content, score, sourceType. */
    private List<Map<String, Object>> sources;
    /** True when the agent paused an action awaiting human approval (HITL). */
    private Boolean hitlPending;
    /** Approval request id for /api/agent/approvals/{id} (null unless hitlPending). */
    private String hitlApprovalId;
}