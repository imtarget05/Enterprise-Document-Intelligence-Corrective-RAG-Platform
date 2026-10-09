package com.smartdocchat.controller;

import com.smartdocchat.service.AgentClient;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * Unit tests for the agent invoke proxy.
 *
 * Locks the path contract (controller mapping "/agent" + servlet
 * context-path "/api" = external "/api/agent/invoke", as documented in
 * docs/architecture.md and used by eval/agent_eval.py proxy mode) and the
 * HITL field passthrough for paused actions.
 */
@ExtendWith(MockitoExtension.class)
class AgentControllerTest {

    @Mock private AgentClient agentClient;

    @Test
    void invokeReturnsAnswerWithHitlFields() {
        AgentController controller = new AgentController(agentClient);
        when(agentClient.invokeAgent(eq("alice"), eq("s1"), eq("send email"), anyString()))
                .thenReturn(new AgentClient.AgentResponse("⏸ approval needed", "action",
                        List.of(), 0.5, "trace-1", true, "hitl-abc"));

        ResponseEntity<Map<String, Object>> result = controller.invokeAgent(
                "alice", Map.of("message", "send email", "session_id", "s1"));

        assertEquals(200, result.getStatusCodeValue());
        Map<String, Object> body = result.getBody();
        assertEquals("⏸ approval needed", body.get("answer"));
        assertEquals("trace-1", body.get("trace_id"));
        assertEquals("action", body.get("agent_type"));
        assertEquals(true, body.get("hitl_pending"));
        assertEquals("hitl-abc", body.get("hitl_approval_id"));
    }

    @Test
    void invokeDefaultsHitlFieldsWhenNoApproval() {
        AgentController controller = new AgentController(agentClient);
        when(agentClient.invokeAgent(eq("anonymous"), eq("api-session"), eq("hello"), anyString()))
                .thenReturn(new AgentClient.AgentResponse("hi", "rag",
                        List.of(), 0.9, "trace-2", false, null));

        ResponseEntity<Map<String, Object>> result = controller.invokeAgent(
                null, Map.of("message", "hello"));

        assertEquals(200, result.getStatusCodeValue());
        assertEquals(false, result.getBody().get("hitl_pending"));
        assertEquals("", result.getBody().get("hitl_approval_id"));
    }

    @Test
    void invokeRejectsBlankMessage() {
        AgentController controller = new AgentController(agentClient);

        ResponseEntity<Map<String, Object>> result = controller.invokeAgent(
                "alice", Map.of("message", "  "));

        assertEquals(400, result.getStatusCodeValue());
    }

    @Test
    void invokeMapsAgentDownTo502() {
        AgentController controller = new AgentController(agentClient);
        when(agentClient.invokeAgent(eq("alice"), eq("s1"), eq("hi"), anyString()))
                .thenThrow(new RuntimeException("agent unavailable: conn refused"));

        ResponseEntity<Map<String, Object>> result = controller.invokeAgent(
                "alice", Map.of("message", "hi", "session_id", "s1"));

        assertEquals(502, result.getStatusCodeValue());
    }
}
