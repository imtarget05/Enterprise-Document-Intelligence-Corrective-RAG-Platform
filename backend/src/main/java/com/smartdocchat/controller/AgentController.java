package com.smartdocchat.controller;

import com.smartdocchat.service.AgentClient;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/agent")
@RequiredArgsConstructor
public class AgentController {

    private final AgentClient agentClient;

    @PostMapping("/invoke")
    public ResponseEntity<Map<String, Object>> invokeAgent(
            @RequestHeader(value = "X-User", required = false) String ownerUsername,
            @RequestBody Map<String, Object> request) {
        String message = (String) request.get("message");
        String traceId = (String) request.get("trace_id");
        String sessionId = (String) request.getOrDefault("session_id", "api-session");
        if (message == null || message.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "message is required"));
        }
        try {
            AgentClient.AgentResponse resp = agentClient.invokeAgent(
                    ownerUsername != null ? ownerUsername : "anonymous",
                    sessionId,
                    message,
                    traceId != null ? traceId : UUID.randomUUID().toString()
            );
            String effectiveTraceId = resp.traceId() != null ? resp.traceId()
                    : (traceId != null ? traceId : "");
            return ResponseEntity.ok(Map.of(
                    "answer", resp.answer(),
                    "trace_id", effectiveTraceId,
                    "agent_type", resp.agentType() != null ? resp.agentType() : "rag",
                    "hitl_pending", resp.hitlPending(),
                    "hitl_approval_id", resp.approvalId() != null ? resp.approvalId() : ""
            ));
        } catch (Exception e) {
            return ResponseEntity.status(502).body(Map.of("error", "agent unavailable: " + e.getMessage()));
        }
    }
}
