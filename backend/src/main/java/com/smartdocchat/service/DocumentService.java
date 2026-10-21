package com.smartdocchat.service;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.dto.DocumentDTO;
import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.LegalChunk;
import com.smartdocchat.entity.Role;
import com.smartdocchat.entity.SourceType;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.DocumentIngestedEvent;
import com.smartdocchat.event.DocumentPurgedEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.repository.DocumentRepository;
import com.smartdocchat.repository.LegalChunkRepository;
import com.smartdocchat.util.DocumentParser;
import com.smartdocchat.util.LegalDateExtractor;
import com.smartdocchat.util.LegalStructureParser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.CachePut;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.CharsetDecoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
@Slf4j
public class DocumentService {
    private final DocumentRepository documentRepository;
    private final DocumentParser documentParser;
    private final StorageService storageService;
    private final LegalStructureParser legalStructureParser;
    private final LegalChunkRepository legalChunkRepository;
    private final com.smartdocchat.util.LegalQueryNormalizer legalQueryNormalizer;
    private final com.smartdocchat.util.LegalDateExtractor legalDateExtractor;
    private final DocumentWorkflowClient documentWorkflowClient;
    private final com.smartdocchat.config.IngestionConfig ingestionConfig;
    private final DocumentVersionService documentVersionService;
    private final DocumentJobService documentJobService;
    private final DocumentEventPublisher eventPublisher;

    /** Matches an explicit "Số: NN/YYYY/AAA" document-number line only. */
    private static final Pattern DOCUMENT_NUMBER =
            Pattern.compile("(?im)^\\s*Số\\s*:\\s*(\\S+/\\d{4}/\\S+)");

    private static final Set<String> ALLOWED_EXTENSIONS = Set.of("pdf", "docx", "doc", "docs", "txt");

    public Document uploadDocument(MultipartFile file, String ownerUsername) throws IOException {
        String originalFileName = sanitizeFileName(file.getOriginalFilename());
        String fileExtension = getFileExtension(originalFileName);
        validateUpload(file, fileExtension);

        // Idempotent ingestion (Blueprint #17): identical content uploaded
        // twice by the same owner must not create duplicate metadata.
        String contentHash = sha256Hex(file.getBytes());
        Optional<Document> existing =
                documentRepository.findByOwnerUsernameAndContentHash(ownerUsername, contentHash);
        if (existing.isPresent()) {
            log.info("Duplicate upload '{}' ignored for {} — existing document id {} returned",
                    originalFileName, ownerUsername, existing.get().getId());
            return existing.get();
        }

        String fileName = UUID.randomUUID() + "." + fileExtension;

        // Store file on disk
        String storagePath = storageService.upload(fileName, file);

        // Parse and chunk locally
        File savedFile = storageService.download(storagePath);
        String extractedText = documentParser.extractText(savedFile, fileExtension);
        List<String> chunks = documentParser.chunkText(
                extractedText, ingestionConfig.getChunkSize(), ingestionConfig.getChunkOverlap());

        log.info("Document '{}' extracted with {} chunks", originalFileName, chunks.size());

        // Serialize chunks as JSON
        String chunksJson = new com.fasterxml.jackson.databind.ObjectMapper()
                .writeValueAsString(chunks);

        // Save document metadata + chunks to database.
        // Provenance defaults to USER — never silently OFFICIAL.
        Document document = Document.builder()
                .fileName(originalFileName)
                .filePath(storagePath)
                .ownerUsername(ownerUsername)
                .fileType(fileExtension)
                .fileSize(file.getSize())
                .chunkCount(chunks.size())
                .chunks(chunksJson)
                .sourceType(SourceType.USER)
                .contentHash(contentHash)
                .build();

        // Legal structure detection: when article markers exist, persist
        // addressable evidence units alongside the generic chunks (which are
        // kept for backward compatibility with the legacy retrieval path).
        List<LegalStructureParser.StructuredUnit> legalUnits =
                legalStructureParser.parse(extractedText);
        if (!legalUnits.isEmpty()) {
            Matcher numberMatch = DOCUMENT_NUMBER.matcher(extractedText);
            if (numberMatch.find()) {
                document.setDocumentNumber(numberMatch.group(1));
            }
            // Legal dates (Decision 16A): only explicit labelled lines; never
            // inferred from arbitrary body text; missing stays null.
            LegalDateExtractor.LegalDateMetadata dates = legalDateExtractor.extract(extractedText);
            document.setIssueDate(dates.issueDate());
            document.setEffectiveDate(dates.effectiveDate());
        }
        // Durable async workflow (ADR-004): enqueue a persisted job instead of
        // fire-and-forget CompletableFuture. DocumentJobService claims the job,
        // calls llm-router, retries with exponential backoff and dead-letters
        // after max attempts — surviving restarts and router outages.
        Document saved;
        try {
            saved = documentRepository.save(document);
        } catch (org.springframework.dao.DataIntegrityViolationException lostRace) {
            // Lost the insert race: a concurrent upload of identical content
            // won (partial unique index uq_documents_owner_content_hash, V17).
            // The upload stays idempotent — return the winning row and clean
            // up the storage blob this request uploaded before the insert.
            Document winner = documentRepository
                    .findByOwnerUsernameAndContentHash(ownerUsername, contentHash)
                    .orElseThrow(() -> lostRace);
            log.info("Concurrent duplicate upload '{}' for {} — existing document id {} returned",
                    originalFileName, ownerUsername, winner.getId());
            try {
                storageService.delete(document.getFilePath());
            } catch (Exception cleanupFailure) {
                log.warn("Could not delete orphaned blob '{}' after lost dedup race",
                        document.getFilePath(), cleanupFailure);
            }
            return winner;
        }

        // Document versioning (V10): record version 1 for the initial upload.
        documentVersionService.createVersion(saved, ownerUsername, "Initial upload");

        if (!legalUnits.isEmpty()) {
            int ordinal = 0;
            for (LegalStructureParser.StructuredUnit unit : legalUnits) {
                legalChunkRepository.save(LegalChunk.builder()
                        .documentId(saved.getId())
                        .ordinal(ordinal++)
                        .content(unit.text())
                        .chapterNumber(unit.chapter())
                        .articleNumber(unit.article())
                        .clauseNumber(unit.clause())
                        .pointLabel(unit.point())
                        .build());
            }
            log.info("Document '{}' ingested as structured legal text: {} evidence units",
                    originalFileName, legalUnits.size());
        }

        // Phase 2 wiring (#7): the document workflow (classify → extract → map →
        // match) runs through the durable ingestion queue (ADR-004) so it never
        // blocks the upload response, survives restarts and retries on failure.
        documentJobService.enqueueWorkflowJob(saved, originalFileName);

        // Emit document ingested event (non-blocking)
        emitDocumentIngestedEvent(saved);

        return saved;
    }

    /**
     * Replace a document's content in place (document versioning, V10): the
     * previous state is archived as an immutable snapshot, the live row keeps
     * its id (history/citations stay stable) and version_number is advanced.
     * RBAC is enforced by the caller (DocumentController) before this runs.
     */
    @CachePut(value = CacheNames.DOCUMENTS, key = "#result.id")
    public Document replaceDocument(Document current, MultipartFile file, String actorUsername) throws IOException {
        String originalFileName = sanitizeFileName(file.getOriginalFilename());
        String fileExtension = getFileExtension(originalFileName);
        validateUpload(file, fileExtension);

        // Re-uploading identical content is a no-op, not a new version.
        String newHash = sha256Hex(file.getBytes());
        if (newHash.equals(current.getContentHash())) {
            log.info("Replacement upload '{}' identical to version {} of document {} — ignored",
                    originalFileName, current.getVersionNumber(), current.getId());
            return current;
        }

        // Replacing with content that already exists as a sibling document
        // would violate uq_documents_owner_content_hash (V17) — reject before
        // any side effect (version archival, storage upload) happens.
        documentRepository.findByOwnerUsernameAndContentHash(current.getOwnerUsername(), newHash)
                .filter(other -> !other.getId().equals(current.getId()))
                .ifPresent(other -> {
                    throw new IllegalArgumentException(
                            "Content is identical to existing document #" + other.getId()
                                    + " — replacing this document would create a duplicate.");
                });

        // Archive current version before replacing
        documentVersionService.createVersion(current, actorUsername, "Document updated");

        String storagePath = storageService.upload(UUID.randomUUID() + "." + fileExtension, file);
        File savedFile = storageService.download(storagePath);
        String extractedText = documentParser.extractText(savedFile, fileExtension);
        List<String> chunks = documentParser.chunkText(
                extractedText, ingestionConfig.getChunkSize(), ingestionConfig.getChunkOverlap());
        String chunksJson = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(chunks);

        current.setFileName(originalFileName);
        current.setFilePath(storagePath);
        current.setFileType(fileExtension);
        current.setFileSize(file.getSize());
        current.setChunkCount(chunks.size());
        current.setChunks(chunksJson);
        current.setContentHash(newHash);

        // Re-extract legal metadata from the new content (never carried over).
        current.setDocumentNumber(null);
        current.setIssueDate(null);
        current.setEffectiveDate(null);
        Matcher numberMatch = DOCUMENT_NUMBER.matcher(extractedText);
        if (numberMatch.find()) {
            current.setDocumentNumber(numberMatch.group(1));
        }
        LegalDateExtractor.LegalDateMetadata dates = legalDateExtractor.extract(extractedText);
        current.setIssueDate(dates.issueDate());
        current.setEffectiveDate(dates.effectiveDate());

        // Rebuild structured legal units from the new content.
        legalChunkRepository.deleteByDocumentId(current.getId());
        List<LegalStructureParser.StructuredUnit> legalUnits = legalStructureParser.parse(extractedText);
        if (!legalUnits.isEmpty()) {
            int ordinal = 0;
            for (LegalStructureParser.StructuredUnit unit : legalUnits) {
                legalChunkRepository.save(LegalChunk.builder()
                        .documentId(current.getId())
                        .ordinal(ordinal++)
                        .content(unit.text())
                        .chapterNumber(unit.chapter())
                        .articleNumber(unit.article())
                        .clauseNumber(unit.clause())
                        .pointLabel(unit.point())
                        .build());
            }
        }

        // Advance version number
        current.setVersionNumber(current.getVersionNumber() != null ? current.getVersionNumber() + 1 : 2);

        Document saved = documentRepository.save(current);
        log.info("Document {} replaced → version {} with {} chunks",
                saved.getId(), saved.getVersionNumber(), chunks.size());

        // Emit document ingested event for replacement (non-blocking)
        emitDocumentIngestedEvent(saved);

        return saved;
    }

    public List<Document> getAllDocuments(String ownerUsername) {
        return documentRepository.findByOwnerUsernameOrderByCreatedAtDesc(ownerUsername);
    }

    /**
     * RBAC-aware listing (production requirement #3): admins see every
     * document; everyone else is restricted to their own (owner isolation).
     */
    @Cacheable(value = CacheNames.DOCUMENT_METADATA, key = "#callerUsername", unless = "#result == null")
    public List<Document> getAllDocumentsForRole(String callerUsername, Role role) {
        if (role == Role.ROLE_ADMIN) {
            return documentRepository.findByOrderByCreatedAtDesc();
        }
        return getAllDocuments(callerUsername);
    }

    private List<Document> getDocumentsByOwner(String ownerUsername) {
        return documentRepository.findByOwnerUsernameOrderByCreatedAtDesc(ownerUsername);
    }

    @Cacheable(value = CacheNames.DOCUMENTS, key = "#id", unless = "#result == null")
    public Document getDocumentById(Long id, String ownerUsername) {
        return documentRepository.findByIdAndOwnerUsername(id, ownerUsername).orElseThrow(
                () -> new RuntimeException("Document not found with id: " + id)
        );
    }

    /**
     * RBAC-aware fetch (production requirement #3): admins may read any
     * document; other roles remain owner-isolated (same not-found signal).
     */
    @Cacheable(value = CacheNames.DOCUMENTS, key = "#id", unless = "#result == null")
    public Document getDocumentByIdForRole(Long id, String callerUsername, Role role) {
        if (role == Role.ROLE_ADMIN) {
            return documentRepository.findById(id).orElseThrow(
                    () -> new RuntimeException("Document not found with id: " + id)
            );
        }
        return getDocumentById(id, callerUsername);
    }

    @Transactional
    @CacheEvict(value = CacheNames.DOCUMENTS, key = "#id")
    public void deleteDocument(Long id, String ownerUsername) {
        Document document = getDocumentById(id, ownerUsername);

        // Emit document purged event before deletion (non-blocking)
        emitDocumentPurgedEvent(document, ownerUsername, "User deletion request");

        storageService.delete(document.getFilePath());
        legalChunkRepository.deleteByDocumentId(id);
        documentVersionService.deleteVersionsByDocumentId(id);
        documentRepository.delete(document);
    }

    @Transactional
    @CacheEvict(value = {CacheNames.DOCUMENTS, CacheNames.DOCUMENT_METADATA}, allEntries = true)
    public int deleteDocumentsBatch(List<Long> ids, String callerUsername, Role role) {
        if (ids == null || ids.isEmpty()) {
            return 0;
        }
        int count = 0;
        for (Long id : ids) {
            try {
                Document doc = getDocumentByIdForRole(id, callerUsername, role);

                // Emit document purged event before deletion (non-blocking)
                emitDocumentPurgedEvent(doc, callerUsername, "Batch deletion");

                storageService.delete(doc.getFilePath());
                legalChunkRepository.deleteByDocumentId(id);
                documentVersionService.deleteVersionsByDocumentId(id);
                documentRepository.delete(doc);
                count++;
            } catch (Exception e) {
                log.warn("Failed to delete document id {} in batch: {}", id, e.getMessage());
            }
        }
        return count;
    }

    public Document saveDocument(Document document) {
        return documentRepository.save(document);
    }

    @SuppressWarnings("unchecked")
    public List<String> getDocumentChunks(Long documentId, String ownerUsername) {
        Document doc = getDocumentById(documentId, ownerUsername);
        if (doc.getChunks() == null || doc.getChunks().isBlank()) {
            return Collections.emptyList();
        }
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper()
                    .readValue(doc.getChunks(), List.class);
        } catch (Exception e) {
            log.error("Error parsing chunks for document {}", documentId, e);
            return Collections.emptyList();
        }
    }

    /**
     * Returns the structured legal evidence units for a document, enforcing
     * owner isolation. Empty when the document was ingested without legal
     * structure (legacy/generic chunking only).
     */
    public List<LegalChunk> getLegalChunks(Long documentId, String ownerUsername) {
        getDocumentById(documentId, ownerUsername); // owner isolation check
        return legalChunkRepository.findByDocumentIdOrderByOrdinalAsc(documentId);
    }

    /** RBAC-aware variant: admins may inspect any document's legal chunks. */
    public List<LegalChunk> getLegalChunksForRole(Long documentId, String callerUsername, Role role) {
        getDocumentByIdForRole(documentId, callerUsername, role); // RBAC + owner isolation check
        return legalChunkRepository.findByDocumentIdOrderByOrdinalAsc(documentId);
    }

    /**
     * Legal document search (Decision 15): matches the query against file
     * name, legal title and document number using Vietnamese-aware
     * normalisation (case-fold + diacritic-fold + abbreviation expansion).
     * Only the requesting owner's documents are ever considered.
     */
    public List<DocumentDTO> searchDocuments(String ownerUsername, String query) {
        Set<String> terms = legalQueryNormalizer.matchTerms(query);
        String foldedQuery = legalQueryNormalizer.foldContent(query);
        String rawNumber = extractDocumentNumber(query);

        return getDocumentsByOwner(ownerUsername).stream()
                .map(doc -> {
                    String haystack = legalQueryNormalizer.foldContent(
                            nullSafe(doc.getFileName()) + " " + nullSafe(doc.getTitle()) + " "
                                    + nullSafe(doc.getDocumentNumber()));
                    boolean match = false;
                    if (!rawNumber.isEmpty() && doc.getDocumentNumber() != null
                            && legalQueryNormalizer.foldContent(doc.getDocumentNumber()).contains(rawNumber)) {
                        match = true;
                    }
                    if (!match && !terms.isEmpty()) {
                        long hits = terms.stream().filter(t -> containsWord(haystack, t)).count();
                        if (terms.size() == 1) {
                            match = hits >= 1;
                        } else {
                            match = hits >= 2 && hits / (double) terms.size() >= 0.4;
                        }
                    }
                    if (!match && !foldedQuery.isBlank() && containsWord(haystack, foldedQuery)) {
                        match = true;
                    }
                    return match ? toDTO(doc) : null;
                })
                .filter(Objects::nonNull)
                .toList();
    }

    private static final Pattern NUMBER_TOKEN = Pattern.compile("\\d{1,4}/\\d{4}/[A-Za-z\\-]+");

    private String extractDocumentNumber(String query) {
        Matcher m = NUMBER_TOKEN.matcher(query == null ? "" : query);
        return m.find() ? legalQueryNormalizer.foldContent(m.group()) : "";
    }

    private String nullSafe(String s) {
        return s == null ? "" : s;
    }

    /**
     * Word-boundary-aware contains: a term only matches when surrounded by
     * non-letter characters (mirrors RetrievalService.indexOfWord). Prevents
     * short folded terms ("bo", "pho") matching inside unrelated longer words.
     */
    private static boolean containsWord(String text, String term) {
        return indexOfWord(text, term, 0) >= 0;
    }

    private static int indexOfWord(String text, String term, int from) {
        if (text == null || term == null || term.isEmpty()) {
            return -1;
        }
        int idx = text.indexOf(term, from);
        while (idx >= 0) {
            boolean leftOk = idx == 0 || !Character.isLetter(text.charAt(idx - 1));
            int end = idx + term.length();
            boolean rightOk = end >= text.length() || !Character.isLetter(text.charAt(end));
            if (leftOk && rightOk) {
                return idx;
            }
            idx = text.indexOf(term, idx + 1);
        }
        return -1;
    }

    private DocumentDTO toDTO(Document d) {
        return DocumentDTO.builder()
                .id(d.getId())
                .fileName(d.getFileName())
                .fileType(d.getFileType())
                .fileSize(d.getFileSize())
                .createdAt(d.getCreatedAt())
                .updatedAt(d.getUpdatedAt())
                .chunkCount(d.getChunkCount())
                .title(d.getTitle())
                .documentNumber(d.getDocumentNumber())
                .issuingBody(d.getIssuingBody())
                .issueDate(d.getIssueDate())
                .effectiveDate(d.getEffectiveDate())
                .sourceType(d.getSourceType() != null ? d.getSourceType().name() : null)
                .versionNumber(d.getVersionNumber())
                .versionCount(documentVersionService.getVersionCount(d.getId()))
                .build();
    }

    /** SHA-256 hex digest used for idempotent ingestion (Blueprint #17). */
    private String sha256Hex(byte[] content) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            StringBuilder sb = new StringBuilder();
            for (byte b : digest.digest(content)) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            // SHA-256 is mandatory on every supported JVM — unreachable.
            throw new IllegalStateException("SHA-256 algorithm unavailable", e);
        }
    }

    private String getFileExtension(String fileName) {
        if (fileName != null && fileName.contains(".")) {
            return fileName.substring(fileName.lastIndexOf(".") + 1).toLowerCase();
        }
        return "txt";
    }

    private String sanitizeFileName(String fileName) {
        if (fileName == null || fileName.isBlank()) {
            return "document.txt";
        }
        String name = fileName.replaceAll("[\\r\\n]", "_");
        int lastSlash = Math.max(name.lastIndexOf('/'), name.lastIndexOf('\\'));
        return lastSlash >= 0 ? name.substring(lastSlash + 1) : name;
    }

    private void validateUpload(MultipartFile file, String extension) throws IOException {
        if (!ALLOWED_EXTENSIONS.contains(extension)) {
            throw new IllegalArgumentException("Unsupported document type. Allowed types: PDF, DOCX, TXT");
        }

        byte[] header = new byte[8];
        try (InputStream in = file.getInputStream()) {
            int bytesRead = in.read(header);
            if (bytesRead < 4) {
                throw new IllegalArgumentException("File is too small to be a valid document.");
            }
        }

        switch (extension) {
            case "pdf" -> {
                if (header[0] != 0x25 || header[1] != 0x50 || header[2] != 0x44 || header[3] != 0x46) {
                    log.warn("PDF magic bytes missing for '{}' — treating as scanned/image PDF, will attempt OCR fallback",
                            file.getOriginalFilename());
                    // Allow upload; DocumentParser will attempt OCR fallback
                }
            }
            case "docx", "docs" -> {
                if (header[0] != 0x50 || header[1] != 0x4B || header[2] != 0x03 || header[3] != 0x04) {
                    throw new IllegalArgumentException("File content does not match a valid DOCX (ZIP) archive.");
                }
            }
            case "doc" -> {
                boolean isZip = header[0] == 0x50 && header[1] == 0x4B;
                boolean isOle = (header[0] & 0xFF) == 0xD0 && (header[1] & 0xFF) == 0xCF;
                if (!isZip && !isOle) {
                    log.warn("Non-standard DOC header for '{}', proceeding with best-effort parsing", file.getOriginalFilename());
                }
            }
            case "txt" -> {
                byte[] sample = file.getBytes();
                try {
                    CharsetDecoder decoder = StandardCharsets.UTF_8.newDecoder();
                    decoder.decode(java.nio.ByteBuffer.wrap(sample));
                } catch (java.nio.charset.CharacterCodingException e) {
                    throw new IllegalArgumentException("TXT file contains invalid UTF-8 characters.");
                }
            }
            default -> throw new IllegalArgumentException("Unsupported extension: " + extension);
        }
    }

    /**
     * Emits a DocumentIngestedEvent for the given document.
     * Non-blocking - uses publishAsync to avoid slowing down the response.
     */
    private void emitDocumentIngestedEvent(Document document) {
        EventMetadata metadata = new EventMetadata(
                document.getId().toString(),
                null,
                "document-service",
                "1.0"
        );
        DocumentIngestedEvent event = DocumentIngestedEvent.create(
                metadata,
                document.getId(),
                document.getFileName(),
                document.getOwnerUsername(),
                document.getFileType(),
                document.getFileSize(),
                document.getContentHash(),
                document.getSourceType() != null ? document.getSourceType().name() : "USER"
        );
        eventPublisher.publishAsync(event);
    }

    /**
     * Emits a DocumentPurgedEvent for the given document.
     * Non-blocking - uses publishAsync to avoid slowing down the response.
     */
    private void emitDocumentPurgedEvent(Document document, String purgedBy, String reason) {
        EventMetadata metadata = new EventMetadata(
                document.getId().toString(),
                null,
                "document-service",
                "1.0"
        );
        DocumentPurgedEvent event = DocumentPurgedEvent.create(
                metadata,
                document.getId(),
                document.getFileName(),
                purgedBy,
                reason
        );
        eventPublisher.publishAsync(event);
    }

    /**
     * Updates a document with classification metadata from the workflow.
     * Called by DocumentClassificationConsumer when a DocumentClassifiedEvent is received.
     *
     * @param documentId the document ID
     * @param documentNumber the document number (e.g., "123/2024/ND-CP")
     * @param issuingBody the issuing body (e.g., "Government")
     * @param issueDate the issue date
     * @param effectiveDate the effective date
     * @param classification the classification type (e.g., "Decree", "Circular")
     * @param confidence the confidence score (0.0 to 1.0)
     */
    @Transactional
    @CacheEvict(value = CacheNames.DOCUMENTS, key = "#documentId")
    public void updateDocumentClassification(Long documentId,
                                              String documentNumber,
                                              String issuingBody,
                                              java.time.LocalDate issueDate,
                                              java.time.LocalDate effectiveDate,
                                              String classification,
                                              Double confidence) {
        Document document = documentRepository.findById(documentId)
                .orElseThrow(() -> new IllegalArgumentException("Document not found: " + documentId));

        if (documentNumber != null) {
            document.setDocumentNumber(documentNumber);
        }
        if (issuingBody != null) {
            document.setIssuingBody(issuingBody);
        }
        if (issueDate != null) {
            document.setIssueDate(issueDate);
        }
        if (effectiveDate != null) {
            document.setEffectiveDate(effectiveDate);
        }
        // Store classification and confidence in a metadata field or extended attributes
        // For now, we'll store classification in the title field if not set, or add a dedicated field later
        if (classification != null && (document.getTitle() == null || document.getTitle().isBlank())) {
            document.setTitle(classification);
        }
        // Confidence could be stored in a new field or metadata JSON - for now log it
        if (confidence != null) {
            log.info("Document {} classification confidence: {}", documentId, confidence);
        }

        documentRepository.save(document);
        log.info("Updated document {} with classification metadata", documentId);
    }

    /**
     * Updates a document with the workflow result and status.
     * Called by WorkflowCompletionConsumer when a WorkflowCompletedEvent is received.
     *
     * @param documentId the document ID
     * @param workflowResult the workflow result JSON string
     * @param status the workflow status (SUCCESS or FAILED)
     */
    @Transactional
    @CacheEvict(value = CacheNames.DOCUMENTS, key = "#documentId")
    public void updateWorkflowResult(Long documentId, String workflowResult, String status) {
        Document document = documentRepository.findById(documentId)
                .orElseThrow(() -> new IllegalArgumentException("Document not found: " + documentId));

        document.setWorkflowResult(workflowResult);
        document.setWorkflowStatus(status);
        documentRepository.save(document);
        log.info("Updated document {} with workflow result status={}", documentId, status);
    }

    /**
     * Invalidates the search cache for a document.
     * Called by WorkflowCompletionConsumer when workflow completes successfully.
     * This ensures subsequent searches reflect the updated document.
     *
     * @param documentId the document ID
     */
    public void invalidateSearchCache(Long documentId) {
        // In a production system, this would invalidate Redis cache, Elasticsearch, etc.
        // For now, this is a no-op placeholder that can be extended.
        log.debug("Search cache invalidation requested for document {}", documentId);
        // TODO: Implement actual cache invalidation (e.g., Redis, Caffeine, Elasticsearch)
    }
}
