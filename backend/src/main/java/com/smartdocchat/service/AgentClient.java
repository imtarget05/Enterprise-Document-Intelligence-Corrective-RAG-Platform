package com.smartdocchat.service;

import com.smartdocchat.entity.AgentState;
import com.smartdocchat.repository.AgentStateRepository;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;

/**
 * Client gọi llm-router agentic path (/v1/agent/invoke).
 *
 * Persistence: mỗi lần invoke được ghi 1 dòng vào agent_state table
 * (session, owner, trace, answer, status). Lỗi DB không ảnh hưởng
 * tới luồng agent — chỉ log warn.
 */
@Component
@Slf4j
public class AgentClient {

    private final RestTemplate restTemplate;
    private final AgentStateRepository agentStateRepository;
    private final String agentBaseUrl;
    private final int timeoutMs;

    public AgentClient(@Qualifier("agentRestTemplate") RestTemplate restTemplate,
                       @org.springframework.lang.Nullable AgentStateRepository agentStateRepository,
                       @Value("${agent.base-url:http://localhost:9000}") String agentBaseUrl,
                       @Value("${agent.timeout-ms:15000}") int timeoutMs) {
        this.restTemplate = restTemplate;
        this.agentStateRepository = agentStateRepository;
        this.agentBaseUrl = agentBaseUrl;
        this.timeoutMs = timeoutMs;
    }

    public record AgentResponse(String answer, String agentType, java.util.List<?> sources,
                                  Double confidence, String traceId,
                                  boolean hitlPending, String approvalId) {
        public AgentResponse(String answer, String traceId) {
            this(answer, null, java.util.List.of(), null, traceId, false, null);
        }
    }

    /**
     * Upstream agent-service error with its HTTP status preserved (404 unknown
     * approval, 503 approval store down...). Controllers map this to the same
     * status instead of a generic 502.
     */
    public static class AgentUpstreamException extends RuntimeException {
        private final int statusCode;

        public AgentUpstreamException(int statusCode, String message) {
            super(message);
            this.statusCode = statusCode;
        }

        public int getStatusCode() {
            return statusCode;
        }
    }

    @CircuitBreaker(name = "agentService", fallbackMethod = "invokeAgentFallback")
    @Retry(name = "agentService")
    public AgentResponse invokeAgent(String ownerUsername, String sessionId,
                                     String message, String traceId) {
        String url = agentBaseUrl + "/v1/agent/invoke";
        Map<String, Object> body = new HashMap<>();
        body.put("query", message);
        body.put("session_id", sessionId);
        body.put("user_id", ownerUsername);
        if (traceId != null) {
            body.put("trace_id", traceId);
        }
        String requestId = MDC.get("requestId");
        if (requestId != null) {
            body.put("request_id", requestId);
        }

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (traceId != null) {
            headers.set("X-Langfuse-Trace-Id", traceId);
        }
        if (requestId != null) {
            headers.set("X-Request-Id", requestId);
        }
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);

        AgentResponse result;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = restTemplate.postForObject(url, entity, Map.class);
            if (resp != null) {
                String answer = (String) resp.get("answer");
                String agentType = (String) resp.getOrDefault("agent_type", "rag");
                Object sourcesObj = resp.getOrDefault("sources", java.util.List.of());
                java.util.List<?> sources = sourcesObj instanceof java.util.List<?>
                        ? (java.util.List<?>) sourcesObj : java.util.List.of();
                Object confidenceObj = resp.get("confidence_score");
                Double confidence = confidenceObj instanceof Number
                        ? ((Number) confidenceObj).doubleValue() : null;
                String respTraceId = (String) resp.getOrDefault("trace_id", traceId);
                boolean hitlPending = Boolean.TRUE.equals(resp.get("hitl_pending"));
                String approvalId = (String) resp.get("hitl_approval_id");
                result = new AgentResponse(answer != null ? answer : "", agentType, sources,
                        confidence, respTraceId, hitlPending, approvalId);
            } else {
                result = new AgentResponse("", traceId);
            }
        } catch (Exception e) {
            log.warn("Agent invoke failed url={} traceId={} err={}", url, traceId, e.getMessage());
            persistState(ownerUsername, sessionId, traceId, null, "failed", e.getMessage());
            throw new RuntimeException("agent unavailable: " + e.getMessage(), e);
        }
        persistState(ownerUsername, sessionId, traceId, result.answer(), "done", null);
        return result;
    }

    @SuppressWarnings("unused")
    private AgentResponse invokeAgentFallback(String ownerUsername, String sessionId,
                                              String message, String traceId, Exception ex) {
        log.warn("Agent circuit breaker fallback traceId={} err={}", traceId, ex.getMessage());
        persistState(ownerUsername, sessionId, traceId, null, "failed", "circuit_open: " + ex.getMessage());
        throw new RuntimeException("agent unavailable (circuit open): " + ex.getMessage(), ex);
    }

    // ------------------------------------------------------------------
    // HITL approvals — proxy to the agent service governance queue.
    // GETs are retryable; approve/reject are NOT retried (non-idempotent:
    // approve re-executes the paused action, so a retried POST could run it
    // twice after a server-side success + lost response).
    // ------------------------------------------------------------------
    @CircuitBreaker(name = "agentService", fallbackMethod = "approvalsFallback")
    @Retry(name = "agentService")
    public Map<String, Object> listApprovals() {
        String url = agentBaseUrl + "/v1/agent/approvals";
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = restTemplate.getForObject(url, Map.class);
            return resp != null ? resp
                    : Map.of("status", "ok", "pending", java.util.List.of(), "count", 0);
        } catch (HttpStatusCodeException e) {
            throw new AgentUpstreamException(e.getStatusCode().value(), e.getResponseBodyAsString());
        } catch (Exception e) {
            log.warn("Agent listApprovals failed url={} err={}", url, e.getMessage());
            throw new RuntimeException("agent unavailable: " + e.getMessage(), e);
        }
    }

    @CircuitBreaker(name = "agentService", fallbackMethod = "approvalDetailFallback")
    @Retry(name = "agentService")
    public Map<String, Object> getApproval(String requestId) {
        String url = agentBaseUrl + "/v1/agent/approvals/" + requestId;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = restTemplate.getForObject(url, Map.class);
            if (resp == null) {
                throw new AgentUpstreamException(404, "Approval request not found: " + requestId);
            }
            return resp;
        } catch (HttpStatusCodeException e) {
            throw new AgentUpstreamException(e.getStatusCode().value(), e.getResponseBodyAsString());
        } catch (AgentUpstreamException e) {
            throw e;
        } catch (Exception e) {
            log.warn("Agent getApproval failed url={} err={}", url, e.getMessage());
            throw new RuntimeException("agent unavailable: " + e.getMessage(), e);
        }
    }

    @CircuitBreaker(name = "agentService", fallbackMethod = "decideFallback")
    public Map<String, Object> approveAction(String requestId, String approver, String note) {
        return decideAction(requestId, approver, note, "approve");
    }

    @CircuitBreaker(name = "agentService", fallbackMethod = "decideFallback")
    public Map<String, Object> rejectAction(String requestId, String approver, String note) {
        return decideAction(requestId, approver, note, "reject");
    }

    private Map<String, Object> decideAction(String requestId, String approver,
                                             String note, String decision) {
        String url = agentBaseUrl + "/v1/agent/approvals/" + requestId + "/" + decision;
        Map<String, Object> body = new HashMap<>();
        body.put("approver", approver);
        if (note != null) {
            body.put("note", note);
        }
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> resp = restTemplate.postForObject(url, new HttpEntity<>(body, headers), Map.class);
            if (resp == null) {
                throw new AgentUpstreamException(502, "Empty response from agent service");
            }
            return resp;
        } catch (HttpStatusCodeException e) {
            throw new AgentUpstreamException(e.getStatusCode().value(), e.getResponseBodyAsString());
        } catch (AgentUpstreamException e) {
            throw e;
        } catch (Exception e) {
            log.warn("Agent {} failed url={} err={}", decision, url, e.getMessage());
            throw new RuntimeException("agent unavailable: " + e.getMessage(), e);
        }
    }

    @SuppressWarnings("unused")
    private Map<String, Object> approvalsFallback(Exception ex) {
        throw new RuntimeException("agent unavailable (circuit open): " + ex.getMessage(), ex);
    }

    @SuppressWarnings("unused")
    private Map<String, Object> approvalDetailFallback(String requestId, Exception ex) {
        throw new RuntimeException("agent unavailable (circuit open): " + ex.getMessage(), ex);
    }

    @SuppressWarnings("unused")
    private Map<String, Object> decideFallback(String requestId, String approver,
                                               String note, Exception ex) {
        throw new RuntimeException("agent unavailable (circuit open): " + ex.getMessage(), ex);
    }

    private void persistState(String owner, String sessionId, String traceId,
                              String answer, String status, String error) {
        if (agentStateRepository == null) {
            return;
        }
        try {
            AgentState state = AgentState.builder()
                    .sessionId(sessionId)
                    .ownerUsername(owner)
                    .traceId(traceId)
                    .currentStep("invoke")
                    .finalAnswer(answer != null ? answer : (error != null ? "ERROR: " + error : null))
                    .status(status)
                    .build();
            agentStateRepository.save(state);
        } catch (Exception dbEx) {
            log.warn("Failed to persist agent state session={} err={}", sessionId, dbEx.getMessage());
        }
    }
}
