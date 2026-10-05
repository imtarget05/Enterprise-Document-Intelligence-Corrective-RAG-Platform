package com.smartdocchat.controller;

import com.smartdocchat.dto.DocumentDTO;
import com.smartdocchat.dto.UploadResponse;
import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentVersion;
import com.smartdocchat.entity.Role;
import com.smartdocchat.service.AuditLogService;
import com.smartdocchat.service.DocumentAccessService;
import com.smartdocchat.service.DocumentService;
import com.smartdocchat.service.DocumentVersionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.security.Principal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.slf4j.MDC;

@RestController
@RequestMapping("/documents")
@RequiredArgsConstructor
@Slf4j
public class DocumentController {
    private final DocumentService documentService;
    private final DocumentAccessService documentAccessService;
    private final AuditLogService auditLogService;
    private final DocumentVersionService documentVersionService;
    private com.smartdocchat.repository.DocumentIngestionJobRepository jobRepository;

    @org.springframework.beans.factory.annotation.Autowired
    public void setJobRepository(com.smartdocchat.repository.DocumentIngestionJobRepository jobRepository) {
        this.jobRepository = jobRepository;
    }

    private Role currentRole() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null) {
            return Role.ROLE_USER;
        }
        return auth.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .filter(a -> a.startsWith("ROLE_"))
                .findFirst()
                .map(Role::valueOf)
                .orElse(Role.ROLE_USER);
    }

    private void audit(String action, String username, String resourceType, String resourceId, String detail) {
        auditLogService.record(username != null ? username : "system", action, resourceType, resourceId, null, detail);
    }

    private void auditDocumentAccess(String action, Long id, String owner, boolean granted) {
        try {
            MDC.put("auditAction", action);
            MDC.put("documentId", String.valueOf(id));
            MDC.put("owner", owner != null ? owner : "anonymous");
            MDC.put("granted", String.valueOf(granted));
            log.info("document access");
        } finally {
            MDC.remove("auditAction");
            MDC.remove("documentId");
            MDC.remove("owner");
            MDC.remove("granted");
        }
    }

    @GetMapping("/{id}/legal-chunks")
    public ResponseEntity<?> getLegalChunks(@PathVariable Long id, Principal principal) {
        String username = principal.getName();
        try {
            Document document = documentService.getDocumentByIdForRole(id, username, currentRole());
            List<com.smartdocchat.entity.LegalChunk> chunks =
                    documentService.getLegalChunksForRole(id, username, currentRole());
            auditDocumentAccess("document.read", id, username, true);
            Map<String, Object> body = new java.util.LinkedHashMap<>();
            body.put("documentId", id);
            body.put("fileName", document.getFileName());
            body.put("title", document.getTitle());
            body.put("documentNumber", document.getDocumentNumber());
            body.put("issuingBody", document.getIssuingBody());
            body.put("issueDate", document.getIssueDate());
            body.put("effectiveDate", document.getEffectiveDate());
            body.put("sourceType", document.getSourceType() != null
                    ? document.getSourceType().name() : "USER");
            body.put("chunks", chunks.stream().map(c -> {
                Map<String, Object> m = new java.util.LinkedHashMap<>();
                m.put("id", c.getId());
                m.put("ordinal", c.getOrdinal());
                m.put("article", c.getArticleNumber());
                m.put("clause", c.getClauseNumber());
                m.put("point", c.getPointLabel());
                m.put("content", c.getContent());
                return m;
            }).collect(Collectors.toList()));
            return ResponseEntity.ok(body);
        } catch (RuntimeException e) {
            auditDocumentAccess("document.read", id, principal.getName(), false);
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(java.util.Map.of("message", "Document not found"));
        }
    }

    @PostMapping({"", "/upload"})
    public ResponseEntity<UploadResponse> uploadDocument(
            @RequestParam("file") MultipartFile file, Principal principal) {
        try {
            if (file.isEmpty()) {
                return ResponseEntity.badRequest().body(
                        UploadResponse.builder()
                                .success(false)
                                .message("File is empty")
                                .build()
                );
            }

            documentAccessService.checkUpload(currentRole());

            Document document = documentService.uploadDocument(file, principal.getName());
            audit("document.upload", principal.getName(), "document",
                    String.valueOf(document.getId()), "fileName=" + document.getFileName());

            Long jobId = null;
            if (jobRepository != null && document.getId() != null) {
                jobId = jobRepository.findFirstByDocumentIdOrderByIdDesc(document.getId())
                        .map(com.smartdocchat.entity.DocumentIngestionJob::getId)
                        .orElse(null);
            }

            return ResponseEntity.ok(
                    UploadResponse.builder()
                            .success(true)
                            .message("Document uploaded successfully")
                            .documentId(document.getId())
                            .fileName(document.getFileName())
                            .jobId(jobId)
                            .build()
            );
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(
                    UploadResponse.builder().success(false).message(e.getMessage()).build()
            );
        } catch (IOException e) {
            log.error("Error uploading document", e);
            audit("document.upload.failed", principal.getName(), "document", null, e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(
                    UploadResponse.builder()
                            .success(false)
                            .message("Unable to process the uploaded document")
                            .build()
            );
        }
    }

    @GetMapping
    public ResponseEntity<List<DocumentDTO>> getAllDocuments(Principal principal) {
        List<Document> documents =
                documentService.getAllDocumentsForRole(principal.getName(), currentRole());
        Map<Long, Long> versionCounts = documentVersionService.getAllVersionCounts();
        List<DocumentDTO> dtos = documents.stream()
                .map(doc -> convertToDTO(doc, versionCounts != null ? versionCounts.get(doc.getId()) : null))
                .collect(Collectors.toList());
        return ResponseEntity.ok(dtos);
    }

    @GetMapping("/search")
    public ResponseEntity<List<DocumentDTO>> searchDocuments(@RequestParam("q") String query, Principal principal) {
        return ResponseEntity.ok(documentService.searchDocuments(principal.getName(), query));
    }

    @PostMapping("/search")
    public ResponseEntity<List<DocumentDTO>> searchDocumentsPost(
            @RequestBody(required = false) Map<String, String> body,
            @RequestParam(value = "q", required = false) String queryParam,
            Principal principal) {
        String query = body != null ? (body.get("query") != null ? body.get("query") : body.get("q")) : null;
        if (query == null || query.isBlank()) {
            query = queryParam;
        }
        if (query == null) {
            query = "";
        }
        return ResponseEntity.ok(documentService.searchDocuments(principal.getName(), query));
    }

    @GetMapping("/{id}")
    public ResponseEntity<DocumentDTO> getDocumentById(@PathVariable Long id, Principal principal) {
        try {
            Document document =
                    documentService.getDocumentByIdForRole(id, principal.getName(), currentRole());
            auditDocumentAccess("document.read", id, principal.getName(), true);
            audit("document.read", principal.getName(), "document", String.valueOf(id), "granted=true");
            return ResponseEntity.ok(convertToDTO(document));
        } catch (RuntimeException e) {
            auditDocumentAccess("document.read", id, principal.getName(), false);
            audit("document.read.denied", principal.getName(), "document", String.valueOf(id), "granted=false");
            return ResponseEntity.notFound().build();
        }
    }

    @DeleteMapping("/batch")
    public ResponseEntity<Map<String, Object>> deleteDocumentsBatch(
            @RequestBody List<Long> ids,
            Principal principal) {
        if (ids == null || ids.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "No document IDs provided"));
        }
        int deletedCount = documentService.deleteDocumentsBatch(ids, principal.getName(), currentRole());
        audit("document.batch_delete", principal.getName(), "document",
                ids.toString(), "count=" + deletedCount);
        return ResponseEntity.ok(Map.of(
                "success", true,
                "deletedCount", deletedCount,
                "message", "Deleted " + deletedCount + " documents successfully"
        ));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<String> deleteDocument(@PathVariable Long id, Principal principal) {
        try {
            Document document =
                    documentService.getDocumentByIdForRole(id, principal.getName(), currentRole());
            documentAccessService.checkDelete(currentRole(), document.getOwnerUsername(), principal.getName());
            documentService.deleteDocument(id, principal.getName());
            audit("document.delete", principal.getName(), "document", String.valueOf(id), "granted=true");
            return ResponseEntity.ok("Document deleted successfully");
        } catch (RuntimeException e) {
            audit("document.delete.denied", principal.getName(), "document", String.valueOf(id), "granted=false");
            return ResponseEntity.notFound().build();
        }
    }

    @PatchMapping("/{id}")
    public ResponseEntity<DocumentDTO> updateDocumentMetadata(
            @PathVariable Long id,
            @RequestBody Map<String, String> payload,
            Principal principal) {
        Document document = documentService.getDocumentByIdForRole(id, principal.getName(), currentRole());
        documentAccessService.checkReplace(currentRole(), document.getOwnerUsername(), principal.getName());
        if (payload.containsKey("title")) {
            document.setTitle(payload.get("title"));
        }
        if (payload.containsKey("documentNumber")) {
            document.setDocumentNumber(payload.get("documentNumber"));
        }
        Document saved = documentService.saveDocument(document);
        return ResponseEntity.ok(convertToDTO(saved));
    }

    @PutMapping(value = "/{id}", consumes = "application/json")
    public ResponseEntity<DocumentDTO> updateDocumentMetadataPut(
            @PathVariable Long id,
            @RequestBody Map<String, String> payload,
            Principal principal) {
        return updateDocumentMetadata(id, payload, principal);
    }

    @PutMapping(value = "/{id}", consumes = "multipart/form-data")
    public ResponseEntity<?> replaceDocument(@PathVariable Long id,
                                             @RequestParam("file") MultipartFile file,
                                             Principal principal) {
        try {
            Document document =
                    documentService.getDocumentByIdForRole(id, principal.getName(), currentRole());
            documentAccessService.checkReplace(currentRole(), document.getOwnerUsername(), principal.getName());
            Document replaced = documentService.replaceDocument(document, file, principal.getName());
            audit("document.replace", principal.getName(), "document", String.valueOf(id),
                    "version=" + replaced.getVersionNumber());
            return ResponseEntity.ok(convertToDTO(replaced));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(java.util.Map.of("message", e.getMessage()));
        } catch (IOException e) {
            log.error("Error replacing document", e);
            audit("document.replace.failed", principal.getName(), "document", String.valueOf(id), e.getMessage());
            return ResponseEntity.internalServerError()
                    .body(java.util.Map.of("message", "Unable to replace the document"));
        } catch (RuntimeException e) {
            audit("document.replace.denied", principal.getName(), "document", String.valueOf(id), "granted=false");
            return ResponseEntity.notFound().build();
        }
    }

    @GetMapping("/{id}/versions")
    public ResponseEntity<?> getDocumentVersions(@PathVariable Long id, Principal principal) {
        try {
            documentService.getDocumentByIdForRole(id, principal.getName(), currentRole());
            List<DocumentVersion> versions = documentVersionService.getVersions(id);
            return ResponseEntity.ok(versions);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", e.getMessage()));
        }
    }

    @GetMapping("/{id}/versions/{versionNumber}")
    public ResponseEntity<?> getDocumentVersion(
            @PathVariable Long id,
            @PathVariable Integer versionNumber,
            Principal principal) {
        try {
            documentService.getDocumentByIdForRole(id, principal.getName(), currentRole());
            DocumentVersion version = documentVersionService.getVersion(id, versionNumber);
            return ResponseEntity.ok(version);
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", e.getMessage()));
        }
    }

    private DocumentDTO convertToDTO(Document document) {
        return convertToDTO(document, documentVersionService.getVersionCount(document.getId()));
    }

    private DocumentDTO convertToDTO(Document document, Long versionCount) {
        return DocumentDTO.builder()
                .id(document.getId())
                .fileName(document.getFileName())
                .fileType(document.getFileType())
                .fileSize(document.getFileSize())
                .createdAt(document.getCreatedAt())
                .updatedAt(document.getUpdatedAt())
                .chunkCount(document.getChunkCount())
                .title(document.getTitle())
                .documentNumber(document.getDocumentNumber())
                .issuingBody(document.getIssuingBody())
                .issueDate(document.getIssueDate())
                .effectiveDate(document.getEffectiveDate())
                .sourceType(document.getSourceType() != null
                        ? document.getSourceType().name() : null)
                .versionNumber(document.getVersionNumber())
                .versionCount(versionCount != null ? versionCount : 1L)
                .workflowResult(document.getWorkflowResult())
                .build();
    }
}
