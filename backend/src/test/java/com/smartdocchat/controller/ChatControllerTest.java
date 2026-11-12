package com.smartdocchat.controller;

import com.smartdocchat.dto.ChatRequest;
import com.smartdocchat.dto.ChatResponse;
import com.smartdocchat.entity.ChatMessage;
import com.smartdocchat.service.ChatService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.security.Principal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatControllerTest {

    @Mock private ChatService chatService;

    private ChatController controller;

    private Principal principal() {
        Principal principal = mock(Principal.class);
        when(principal.getName()).thenReturn("alice");
        return principal;
    }

    private ChatRequest request() {
        return ChatRequest.builder().sessionId("s1").documentId(1L).message("hello").build();
    }

    private ChatMessage message() {
        return ChatMessage.builder()
                .id(1L).sessionId("s1").userMessage("hello").aiResponse("hi").sourceChunks("[]").documentId(1L)
                .build();
    }

    @Test
    void askReturnsProcessedResponse() {
        controller = new ChatController(chatService);
        ChatResponse response = ChatResponse.builder().id(1L).sessionId("s1").aiResponse("hi").build();
        when(chatService.processQuery("alice", request())).thenReturn(response);

        ResponseEntity<ChatResponse> result = controller.askQuestion(request(), principal());

        assertEquals(200, result.getStatusCode().value());
        assertEquals("hi", result.getBody().getAiResponse());
    }

    @Test
    void askReturns500OnServiceFailure() {
        controller = new ChatController(chatService);
        when(chatService.processQuery(eq("alice"), any())).thenThrow(new RuntimeException("llm down"));

        ResponseEntity<ChatResponse> result = controller.askQuestion(request(), principal());

        assertEquals(500, result.getStatusCode().value());
    }

    @Test
    void askStreamReturnsEmitterOrErrorEmitter() {
        controller = new ChatController(chatService);
        when(chatService.processQueryStream(eq("alice"), any()))
                .thenReturn(new SseEmitter())
                .thenThrow(new RuntimeException("stream error"));

        SseEmitter ok = controller.askQuestionStream(request(), principal());
        assertNotNull(ok);

        SseEmitter err = controller.askQuestionStream(request(), principal());
        assertThrows(IllegalStateException.class, () -> {
            err.send("x");
        });
    }

    @Test
    void historyEndpointsMapMessages() {
        controller = new ChatController(chatService);
        when(chatService.getChatHistory("alice", "s1")).thenReturn(List.of(message()));
        when(chatService.getChatHistory("alice", "s1", 1L)).thenReturn(List.of(message()));

        assertEquals(1, controller.getChatHistory("s1", principal()).getBody().size());
        assertEquals("hello", controller.getChatHistory("s1", 1L, principal()).getBody().get(0).getUserMessage());
    }

    @Test
    void clearHistoryAndSessions() {
        controller = new ChatController(chatService);
        when(chatService.getUniqueSessions("alice"))
                .thenReturn(List.of(Map.of("sessionId", "s1", "lastMessage", "hi")));

        assertEquals("Chat history cleared", controller.clearChatHistory("s1", principal()).getBody());
        assertEquals(1, controller.getSessions(principal()).getBody().size());
    }
}