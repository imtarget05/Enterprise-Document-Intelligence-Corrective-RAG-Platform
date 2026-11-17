package com.smartdocchat.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.util.List;

@Data
@NoArgsConstructor(onConstructor_ = @JsonCreator)
@AllArgsConstructor
@Builder
public class ChatRequest {
    @NotBlank(message = "Session ID must not be blank")
    @Size(max = 100, message = "Session ID must be at most 100 characters")
    private String sessionId;

    @Positive(message = "Document ID must be a positive number")
    private Long documentId;

    private List<Long> documentIds;

    @NotBlank(message = "Message must not be blank")
    @Size(max = 2000, message = "Message must be at most 2000 characters")
    private String message;

    private boolean deepThinking;
    private boolean webSearch;

    /** Chat mode: "rag" (default) or "agent" (multi-agent orchestrator). */
    private String mode;
}
