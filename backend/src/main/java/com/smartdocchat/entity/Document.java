package com.smartdocchat.entity;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.time.LocalDateTime;

@Entity
@Table(name = "documents")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Document {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String fileName;

    @Column(nullable = false)
    private String filePath;

    @Column(name = "owner_username", nullable = false)
    private String ownerUsername;

    @Column(nullable = false)
    private String fileType;

    @Column(name = "file_size")
    private Long fileSize;

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Column(name = "chunk_count")
    private Integer chunkCount;

    @Column(columnDefinition = "TEXT")
    private String chunks;

    // ------------------------------------------------------------------
    // Legal metadata (Decision 13). Nullable: only set when verifiable
    // from the document text or explicitly provided. Never fabricated.
    // ------------------------------------------------------------------

    @Column
    private String title;

    /** Văn bản số hiệu, e.g. "45/2019/QH14". */
    @Column(name = "document_number")
    private String documentNumber;

    @Column(name = "issuing_body")
    private String issuingBody;

    @Column(name = "issue_date")
    private java.time.LocalDate issueDate;

    @Column(name = "effective_date")
    private java.time.LocalDate effectiveDate;

    /**
     * Provenance of the document. Defaults to USER on upload; never
     * silently set to OFFICIAL.
     */
    @Enumerated(EnumType.STRING)
    @Column(name = "source_type", nullable = false)
    @Builder.Default
    private SourceType sourceType = SourceType.USER;

    /**
     * Live version number (document versioning, V10). Bumped on every
     * replacement upload; historical states live in document_versions.
     */
    @Column(name = "version_number", nullable = false)
    @Builder.Default
    private Integer versionNumber = 1;

    /**
     * SHA-256 hex digest of the uploaded file content (Blueprint #17,
     * idempotent ingestion). Null for legacy rows ingested before this
     * field existed.
     */
    @Column(name = "content_hash")
    private String contentHash;

    /**
     * Kết quả document workflow (Phase 2: classify → extract → map → match PO↔Invoice)
     * từ llm-router /document/workflow. Lưu dạng JSON. Null cho tới khi workflow chạy xong.
     */
    @Column(name = "workflow_result", columnDefinition = "TEXT")
    private String workflowResult;

    /**
     * Trạng thái workflow: PENDING, SUCCESS, FAILED.
     * Được cập nhật khi workflow hoàn tất.
     */
    @Column(name = "workflow_status", length = 20)
    private String workflowStatus;

    @PrePersist
    public void prePersist() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }

    @PreUpdate
    public void preUpdate() {
        updatedAt = LocalDateTime.now();
    }
}