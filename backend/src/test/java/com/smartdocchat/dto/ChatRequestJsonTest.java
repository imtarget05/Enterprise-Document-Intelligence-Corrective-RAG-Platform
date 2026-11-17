package com.smartdocchat.dto;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

class ChatRequestJsonTest {
    @Test
    void omittedOptionalFlagsDefaultToFalse() {
        ChatRequest request = JsonMapper.builder().build().readValue(
                "{\"sessionId\":\"smoke\",\"message\":\"Where is Paris?\",\"mode\":\"rag\"}",
                ChatRequest.class);
        assertFalse(request.isDeepThinking());
        assertFalse(request.isWebSearch());
        assertEquals("smoke", request.getSessionId());
    }
}
