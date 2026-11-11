package com.smartdocchat.entity;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "document_outbox", uniqueConstraints = @UniqueConstraint(columnNames = {"document_id", "document_version"}))
@Getter @Setter @NoArgsConstructor
public class DocumentOutbox {
    @Id private String id;
    @Column(name="document_id", nullable=false) private Long documentId;
    @Column(name="document_version", nullable=false) private Integer documentVersion;
    @Column(nullable=false, columnDefinition="TEXT") private String payload;
    @Column(nullable=false) private String status = "PENDING";
    @Column(nullable=false) private int attempts;
    @Column(name="next_attempt_at", nullable=false) private LocalDateTime nextAttemptAt = LocalDateTime.now();
    @Column(name="published_at") private LocalDateTime publishedAt;
    @Column(name="last_error", length=1000) private String lastError;
}
