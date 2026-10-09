package com.smartdocchat.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.MDC;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * Integration-style test that locks the Java -> agent service wiring.
 *
 * Guards against regression of the supply-chain agentic path (#4):
 *  - request must hit /v1/agent/invoke
 *  - body must use query/session_id/user_id (not message/owner/trace_id)
 *  - response must map agent_type/sources/confidence_score
 */
@ExtendWith(MockitoExtension.class)
class AgentClientTest {

    private RestTemplate restTemplate;
    private MockRestServiceServer mockServer;
    private AgentClient agentClient;

    @BeforeEach
    void setUp() {
        restTemplate = new RestTemplate();
        mockServer = MockRestServiceServer.bindTo(restTemplate).build();
        // agent.base-url default overridden per-test via constructor
        agentClient = new AgentClient(restTemplate, null,
                "http://localhost:9000", 15000);
    }

    @Test
    void invokeAgent_hitsV1Endpoint_andMapsFullResponse() {
        String json = "{"
                + "\"answer\":\"Đây là kế hoạch supply chain\","
                + "\"agent_type\":\"engineering\","
                + "\"sources\":[{\"id\":\"s1\"}],"
                + "\"confidence_score\":0.82"
                + "}";
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/invoke"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(jsonPath("$.query").value("dự báo nhu cầu kho"))
                .andExpect(jsonPath("$.session_id").value("sess-1"))
                .andExpect(jsonPath("$.user_id").value("owner-1"))
                .andRespond(withSuccess(json, MediaType.APPLICATION_JSON));

        AgentClient.AgentResponse resp = agentClient.invokeAgent(
                "owner-1", "sess-1", "dự báo nhu cầu kho", "trace-1");

        mockServer.verify();
        assertEquals("Đây là kế hoạch supply chain", resp.answer());
        assertEquals("engineering", resp.agentType());
        assertNotNull(resp.sources());
        assertTrue(resp.sources().size() >= 1);
        assertEquals(0.82, resp.confidence());
    }

    @Test
    void invokeAgent_agentError_throwsRuntimeException_forFallback() {
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/invoke"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withServerError());

        RuntimeException ex = assertThrows(RuntimeException.class, () ->
                agentClient.invokeAgent("owner-1", "sess-1", "po risk", "trace-1"));

        assertTrue(ex.getMessage().contains("agent unavailable"), ex.getMessage());
        mockServer.verify();
    }

    @Test
    void invokeAgent_propagatesTraceAndRequestIds() {
        MDC.put("requestId", "rid-123");
        try {
            mockServer.expect(requestTo("http://localhost:9000/v1/agent/invoke"))
                    .andExpect(method(HttpMethod.POST))
                    .andExpect(jsonPath("$.trace_id").value("trace-9"))
                    .andExpect(jsonPath("$.request_id").value("rid-123"))
                    .andExpect(header("X-Langfuse-Trace-Id", "trace-9"))
                    .andExpect(header("X-Request-Id", "rid-123"))
                    .andRespond(withSuccess("{\"answer\":\"ok\"}", MediaType.APPLICATION_JSON));

            AgentClient.AgentResponse resp = agentClient.invokeAgent(
                    "owner-1", "sess-1", "hello", "trace-9");

            mockServer.verify();
            assertEquals("ok", resp.answer());
        } finally {
            MDC.remove("requestId");
        }
    }

    @Test
    void invokeAgent_nullBody_returnsEmptyResponseWithTrace() {
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/invoke"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess("", MediaType.APPLICATION_JSON));

        AgentClient.AgentResponse resp = agentClient.invokeAgent(
                "owner-1", "sess-1", "hello", "trace-7");

        assertEquals("", resp.answer());
        assertEquals("trace-7", resp.traceId());
        assertNull(resp.confidence());
        mockServer.verify();
    }

    @Test
    void invokeAgentFallback_throwsRuntimeException_andPersistsFailureState() {
        RuntimeException ex = assertThrows(RuntimeException.class, () ->
                ReflectionTestUtils.invokeMethod(agentClient, "invokeAgentFallback",
                        "owner-1", "sess-1", "msg", "trace-1",
                        new IllegalStateException("boom")));

        assertTrue(ex.getMessage().contains("circuit open"), ex.getMessage());
    }

    // ------------------------------------------------------------------
    // HITL approvals
    // ------------------------------------------------------------------
    @Test
    void invokeAgent_mapsHitlPendingFields() {
        String json = "{"
                + "\"answer\":\"⏸ approval needed\","
                + "\"agent_type\":\"action\","
                + "\"hitl_pending\":true,"
                + "\"hitl_approval_id\":\"hitl-abc123\""
                + "}";
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/invoke"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess(json, MediaType.APPLICATION_JSON));

        AgentClient.AgentResponse resp = agentClient.invokeAgent(
                "owner-1", "sess-1", "send email", "trace-1");

        assertTrue(resp.hitlPending());
        assertEquals("hitl-abc123", resp.approvalId());
        mockServer.verify();
    }

    @Test
    void invokeAgent_defaultsHitlFieldsToFalseWhenAbsent() {
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/invoke"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess("{\"answer\":\"ok\"}", MediaType.APPLICATION_JSON));

        AgentClient.AgentResponse resp = agentClient.invokeAgent(
                "owner-1", "sess-1", "hello", "trace-1");

        assertFalse(resp.hitlPending());
        assertNull(resp.approvalId());
        mockServer.verify();
    }

    @Test
    void listApprovals_hitsEndpoint_andReturnsPayload() {
        String json = "{\"status\":\"ok\","
                + "\"pending\":[{\"request_id\":\"hitl-1\"}],\"count\":1}";
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/approvals"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess(json, MediaType.APPLICATION_JSON));

        Map<String, Object> resp = agentClient.listApprovals();

        assertEquals("ok", resp.get("status"));
        assertEquals(1, resp.get("count"));
        mockServer.verify();
    }

    @Test
    void getApproval_upstream404_throwsAgentUpstreamException() {
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/approvals/hitl-nope"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withStatus(HttpStatus.NOT_FOUND));

        AgentClient.AgentUpstreamException ex = assertThrows(
                AgentClient.AgentUpstreamException.class,
                () -> agentClient.getApproval("hitl-nope"));

        assertEquals(404, ex.getStatusCode());
        mockServer.verify();
    }

    @Test
    void approveAction_postsApproverAndNote() {
        String json = "{\"status\":\"ok\",\"decision\":\"approved\"}";
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/approvals/hitl-1/approve"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(jsonPath("$.approver").value("boss"))
                .andExpect(jsonPath("$.note").value("looks good"))
                .andRespond(withSuccess(json, MediaType.APPLICATION_JSON));

        Map<String, Object> resp = agentClient.approveAction("hitl-1", "boss", "looks good");

        assertEquals("approved", resp.get("decision"));
        mockServer.verify();
    }

    @Test
    void rejectAction_upstream503_throwsAgentUpstreamException() {
        mockServer.expect(requestTo("http://localhost:9000/v1/agent/approvals/hitl-1/reject"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));

        AgentClient.AgentUpstreamException ex = assertThrows(
                AgentClient.AgentUpstreamException.class,
                () -> agentClient.rejectAction("hitl-1", "boss", null));

        assertEquals(503, ex.getStatusCode());
        mockServer.verify();
    }
}
