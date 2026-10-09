package com.smartdocchat.controller;

import com.smartdocchat.service.AgentClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;

import java.security.Principal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for the HITL approvals proxy controller.
 *
 * Locks the governance contract: the approver recorded upstream is always
 * the authenticated principal (never client-supplied), and upstream
 * statuses (404/503) are preserved instead of collapsing to 502.
 */
@ExtendWith(MockitoExtension.class)
class AgentApprovalControllerTest {

    @Mock private AgentClient agentClient;

    private AgentApprovalController controller;

    @BeforeEach
    void setUp() {
        controller = new AgentApprovalController(agentClient);
    }

    private Principal principal() {
        Principal principal = mock(Principal.class);
        when(principal.getName()).thenReturn("boss");
        return principal;
    }

    @Test
    void listReturnsQueue() {
        Map<String, Object> queue = Map.of("status", "ok", "pending", List.of(), "count", 0);
        when(agentClient.listApprovals()).thenReturn(queue);

        ResponseEntity<?> result = controller.listApprovals();

        assertEquals(200, result.getStatusCodeValue());
        assertEquals(queue, result.getBody());
    }

    @Test
    void listMapsUpstream404() {
        when(agentClient.listApprovals())
                .thenThrow(new AgentClient.AgentUpstreamException(404, "not found"));

        ResponseEntity<?> result = controller.listApprovals();

        assertEquals(404, result.getStatusCodeValue());
    }

    @Test
    void listMapsAgentDownTo502() {
        when(agentClient.listApprovals()).thenThrow(new RuntimeException("boom"));

        ResponseEntity<?> result = controller.listApprovals();

        assertEquals(502, result.getStatusCodeValue());
    }

    @Test
    void getApprovalReturnsDetail() {
        Map<String, Object> detail = Map.of("status", "ok");
        when(agentClient.getApproval("hitl-1")).thenReturn(detail);

        ResponseEntity<?> result = controller.getApproval("hitl-1");

        assertEquals(200, result.getStatusCodeValue());
        assertEquals(detail, result.getBody());
    }

    @Test
    void approveUsesPrincipalNameAsApprover() {
        Map<String, Object> decided = Map.of("status", "ok", "decision", "approved");
        when(agentClient.approveAction(eq("hitl-1"), eq("boss"), eq("ok"))).thenReturn(decided);

        ResponseEntity<?> result = controller.approve("hitl-1", Map.of("note", "ok"), principal());

        assertEquals(200, result.getStatusCodeValue());
        verify(agentClient).approveAction("hitl-1", "boss", "ok");
    }

    @Test
    void approveWithNullBodySendsNullNote() {
        when(agentClient.approveAction(eq("hitl-1"), eq("boss"), eq(null)))
                .thenReturn(Map.of("status", "ok"));

        ResponseEntity<?> result = controller.approve("hitl-1", null, principal());

        assertEquals(200, result.getStatusCodeValue());
        verify(agentClient).approveAction("hitl-1", "boss", null);
    }

    @Test
    void approveMapsUpstream503() {
        when(agentClient.approveAction(eq("hitl-1"), any(), any()))
                .thenThrow(new AgentClient.AgentUpstreamException(503, "store down"));

        ResponseEntity<?> result = controller.approve("hitl-1", Map.of(), principal());

        assertEquals(503, result.getStatusCodeValue());
    }

    @Test
    void rejectReturnsDecision() {
        Map<String, Object> decided = Map.of("status", "ok", "decision", "rejected");
        when(agentClient.rejectAction(eq("hitl-9"), eq("boss"), eq(null))).thenReturn(decided);

        ResponseEntity<?> result = controller.reject("hitl-9", Map.of(), principal());

        assertEquals(200, result.getStatusCodeValue());
        assertEquals(decided, result.getBody());
        verify(agentClient).rejectAction("hitl-9", "boss", null);
    }
}
