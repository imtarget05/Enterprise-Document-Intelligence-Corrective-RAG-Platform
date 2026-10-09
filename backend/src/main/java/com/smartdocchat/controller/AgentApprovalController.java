package com.smartdocchat.controller;

import com.smartdocchat.service.AgentClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.security.Principal;
import java.util.Map;

/**
 * Human-in-the-Loop approval queue, proxied to the agent service
 * ({@code /v1/agent/approvals}).
 *
 * Only ADMIN and ENGINEER roles may list or decide approvals. The approver
 * recorded upstream is always the authenticated principal — a
 * client-supplied approver value is never trusted (anti-spoofing).
 */
@RestController
@RequestMapping("/agent/approvals")
@RequiredArgsConstructor
@Slf4j
public class AgentApprovalController {

    private final AgentClient agentClient;

    @GetMapping
    @PreAuthorize("hasAnyRole('ADMIN','ENGINEER')")
    public ResponseEntity<?> listApprovals() {
        try {
            return ResponseEntity.ok(agentClient.listApprovals());
        } catch (AgentClient.AgentUpstreamException e) {
            return upstreamError(e);
        } catch (Exception e) {
            return agentDown(e);
        }
    }

    @GetMapping("/{requestId}")
    @PreAuthorize("hasAnyRole('ADMIN','ENGINEER')")
    public ResponseEntity<?> getApproval(@PathVariable String requestId) {
        try {
            return ResponseEntity.ok(agentClient.getApproval(requestId));
        } catch (AgentClient.AgentUpstreamException e) {
            return upstreamError(e);
        } catch (Exception e) {
            return agentDown(e);
        }
    }

    @PostMapping("/{requestId}/approve")
    @PreAuthorize("hasAnyRole('ADMIN','ENGINEER')")
    public ResponseEntity<?> approve(@PathVariable String requestId,
                                     @RequestBody(required = false) Map<String, Object> body,
                                     Principal principal) {
        String note = body != null ? (String) body.get("note") : null;
        String approver = principal != null ? principal.getName() : "unknown";
        log.info("HITL approve requestId={} approver={}", requestId, approver);
        try {
            return ResponseEntity.ok(agentClient.approveAction(requestId, approver, note));
        } catch (AgentClient.AgentUpstreamException e) {
            return upstreamError(e);
        } catch (Exception e) {
            return agentDown(e);
        }
    }

    @PostMapping("/{requestId}/reject")
    @PreAuthorize("hasAnyRole('ADMIN','ENGINEER')")
    public ResponseEntity<?> reject(@PathVariable String requestId,
                                    @RequestBody(required = false) Map<String, Object> body,
                                    Principal principal) {
        String note = body != null ? (String) body.get("note") : null;
        String approver = principal != null ? principal.getName() : "unknown";
        log.info("HITL reject requestId={} approver={}", requestId, approver);
        try {
            return ResponseEntity.ok(agentClient.rejectAction(requestId, approver, note));
        } catch (AgentClient.AgentUpstreamException e) {
            return upstreamError(e);
        } catch (Exception e) {
            return agentDown(e);
        }
    }

    private ResponseEntity<Map<String, String>> upstreamError(AgentClient.AgentUpstreamException e) {
        // Preserve upstream semantics: 404 unknown/expired, 503 store down.
        return ResponseEntity.status(e.getStatusCode())
                .body(Map.of("error", e.getMessage() != null ? e.getMessage() : "agent error"));
    }

    private ResponseEntity<Map<String, String>> agentDown(Exception e) {
        log.warn("Agent service unavailable for approvals: {}", e.getMessage());
        return ResponseEntity.status(502)
                .body(Map.of("error", "agent unavailable: " + e.getMessage()));
    }
}
