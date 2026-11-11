package com.smartdocchat.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentOutbox;
import com.smartdocchat.event.*;
import com.smartdocchat.repository.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/** Document and event commit together. Delivery is at-least-once, never exactly-once. */
@Service @RequiredArgsConstructor @Slf4j
public class DocumentIngestionOutbox {
    private final DocumentRepository documents;
    private final DocumentOutboxRepository outbox;
    private final DocumentEventPublisher publisher;
    private final ObjectMapper mapper;

    @Transactional
    public Document saveAndEnqueue(Document document) {
        return saveAndEnqueue(document, saved -> {});
    }

    @Transactional
    public Document saveAndEnqueue(Document document, java.util.function.Consumer<Document> persistMetadata) {
        if (document.getId() != null) documents.lockForIngestion(document.getId()).orElseThrow();
        document.setWorkflowStatus("PENDING");
        Document saved = documents.saveAndFlush(document);
        persistMetadata.accept(saved);
        int version = saved.getVersionNumber() == null ? 1 : saved.getVersionNumber();
        String id = UUID.nameUUIDFromBytes(("ingestion:" + saved.getId() + ":" + version)
                .getBytes(StandardCharsets.UTF_8)).toString();
        DocumentIngestedEvent event = new DocumentIngestedEvent(UUID.fromString(id), "documentIngested",
                Instant.now(), new EventMetadata(saved.getId().toString(), null, "document-service", "1.0"),
                saved.getId(), saved.getFileName(), saved.getOwnerUsername(), saved.getFileType(),
                saved.getFileSize(), saved.getContentHash(), saved.getSourceType() == null ? "USER" : saved.getSourceType().name())
                .withDocumentVersion(version);
        DocumentOutbox row = new DocumentOutbox();
        row.setId(id); row.setDocumentId(saved.getId()); row.setDocumentVersion(version);
        try { row.setPayload(mapper.writeValueAsString(event)); }
        catch (Exception e) { throw new IllegalStateException("Cannot serialize ingestion event", e); }
        outbox.saveAndFlush(row);
        return saved;
    }

    @Transactional
    public void reconcileOne(Long documentId) {
        Document document = documents.lockForIngestion(documentId).orElse(null);
        if (document != null && document.getWorkflowResult() == null
                && !outbox.existsByDocumentIdAndDocumentVersion(documentId, document.getVersionNumber())) {
            saveAndEnqueue(document);
        }
    }

    /** The row lock serializes competing relays; crash after ack causes safe duplicate delivery. */
    @Transactional
    public void publishOne(String id) {
        DocumentOutbox row = outbox.lockById(id).orElse(null);
        if (row == null || !"PENDING".equals(row.getStatus()) || row.getNextAttemptAt().isAfter(LocalDateTime.now())) return;
        try {
            DocumentIngestedEvent event = mapper.readValue(row.getPayload(), DocumentIngestedEvent.class);
            publisher.publishAsync(event).get(15, TimeUnit.SECONDS);
            row.setStatus("PUBLISHED"); row.setPublishedAt(LocalDateTime.now()); row.setLastError(null);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt(); recordFailure(row, e);
        } catch (Exception e) { recordFailure(row, e); }
    }

    private void recordFailure(DocumentOutbox row, Exception error) {
        row.setAttempts(row.getAttempts() + 1);
        row.setNextAttemptAt(LocalDateTime.now().plusSeconds(Math.min(300, 5L << Math.min(row.getAttempts(), 5))));
        row.setLastError(error.getClass().getSimpleName());
        log.warn("Ingestion outbox {} remains pending after attempt {}", row.getId(), row.getAttempts());
    }
}
