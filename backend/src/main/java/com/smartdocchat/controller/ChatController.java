package com.smartdocchat.controller;

import com.smartdocchat.dto.ChatRequest;
import com.smartdocchat.dto.ChatResponse;
import com.smartdocchat.entity.ChatMessage;
import com.smartdocchat.service.ChatService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.security.Principal;
import java.util.List;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/chat")
@RequiredArgsConstructor
@Slf4j
public class ChatController {
    private final ChatService chatService;

    @PostMapping({"", "/ask"})
    public ResponseEntity<ChatResponse> askQuestion(@Valid @RequestBody ChatRequest request, Principal principal) {
        try {
            return ResponseEntity.ok(chatService.processQuery(principal.getName(), request));
        } catch (Exception e) {
            log.error("Error processing chat request", e);
            return ResponseEntity.status(500).build();
        }
    }

    @PostMapping(value = {"/stream", "/ask-stream"}, produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter askQuestionStream(@Valid @RequestBody ChatRequest request, Principal principal) {
        try {
            return chatService.processQueryStream(principal.getName(), request);
        } catch (Exception e) {
            log.error("Error starting chat stream", e);
            SseEmitter errorEmitter = new SseEmitter();
            errorEmitter.completeWithError(e);
            return errorEmitter;
        }
    }

    @GetMapping("/history/{sessionId}")
    public ResponseEntity<List<ChatResponse>> getChatHistory(@PathVariable String sessionId, Principal principal) {
        List<ChatMessage> messages = chatService.getChatHistory(principal.getName(), sessionId);
        List<ChatResponse> responses = messages.stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
        return ResponseEntity.ok(responses);
    }

    @GetMapping("/history/{sessionId}/{documentId}")
    public ResponseEntity<List<ChatResponse>> getChatHistory(
            @PathVariable String sessionId,
            @PathVariable Long documentId,
            Principal principal) {
        List<ChatMessage> messages = chatService.getChatHistory(principal.getName(), sessionId, documentId);
        List<ChatResponse> responses = messages.stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
        return ResponseEntity.ok(responses);
    }

    @DeleteMapping("/history/{sessionId}")
    public ResponseEntity<String> clearChatHistory(@PathVariable String sessionId, Principal principal) {
        chatService.clearChatHistory(principal.getName(), sessionId);
        return ResponseEntity.ok("Chat history cleared");
    }

    @GetMapping("/sessions")
    public ResponseEntity<List<java.util.Map<String, Object>>> getSessions(Principal principal) {
        return ResponseEntity.ok(chatService.getUniqueSessions(principal.getName()));
    }

    private ChatResponse convertToResponse(ChatMessage message) {
        return ChatResponse.builder()
                .id(message.getId())
                .sessionId(message.getSessionId())
                .userMessage(message.getUserMessage())
                .aiResponse(message.getAiResponse())
                .sourceChunks(message.getSourceChunks())
                .documentId(message.getDocumentId())
                .build();
    }
}