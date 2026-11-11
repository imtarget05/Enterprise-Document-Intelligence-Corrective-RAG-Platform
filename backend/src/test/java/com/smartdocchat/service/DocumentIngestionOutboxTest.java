package com.smartdocchat.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartdocchat.entity.*;
import com.smartdocchat.repository.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.*;
import org.springframework.transaction.annotation.*;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import java.util.concurrent.CompletableFuture;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

@DataJpaTest(properties={"spring.flyway.enabled=false", "spring.jpa.hibernate.ddl-auto=create-drop", "spring.jpa.database-platform=org.hibernate.dialect.H2Dialect", "spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.H2Dialect"})
@Import({DocumentIngestionOutbox.class, DocumentVersionService.class, DocumentIngestionOutboxTest.JsonConfig.class})
@Transactional(propagation=Propagation.NOT_SUPPORTED)
class DocumentIngestionOutboxTest {
    @org.springframework.boot.test.context.TestConfiguration static class JsonConfig {
        @Bean ObjectMapper mapper() { return new ObjectMapper().findAndRegisterModules(); }
    }
    @Autowired DocumentIngestionOutbox service;
    @Autowired DocumentRepository documents;
    @Autowired DocumentOutboxRepository outbox;
    @Autowired PlatformTransactionManager manager;
    @Autowired DocumentVersionService versions;
    @Autowired DocumentVersionRepository versionRows;
    @Autowired LegalChunkRepository chunks;
    @MockBean DocumentEventPublisher publisher;

    Document document(String name) {
        return Document.builder().fileName(name).filePath("/"+name).fileType("txt")
                .fileSize(10L).contentHash("hash-"+name).chunkCount(1).ownerUsername("alice").chunks("[\"real parsed text\"]").build();
    }

    @Test void rollbackLeavesNeitherDocumentNorEvent() {
        long docCount=documents.count(), eventCount=outbox.count();
        assertThrows(IllegalStateException.class, () -> new TransactionTemplate(manager).execute(status -> {
            service.saveAndEnqueue(document("rollback.txt"));
            throw new IllegalStateException("injected transaction failure");
        }));
        assertEquals(docCount, documents.count());
        assertEquals(eventCount, outbox.count());
    }

    @Test void brokerFailureRemainsPendingAndAckMakesReplayANoOp() {
        Document doc=service.saveAndEnqueue(document("broker.txt"));
        DocumentOutbox row=outbox.findAll().stream().filter(o -> o.getDocumentId().equals(doc.getId())).findFirst().orElseThrow();
        when(publisher.publishAsync(any())).thenReturn(CompletableFuture.failedFuture(new RuntimeException("broker down")));
        service.publishOne(row.getId());
        row=outbox.findById(row.getId()).orElseThrow();
        assertEquals("PENDING", row.getStatus()); assertEquals(1,row.getAttempts()); assertNull(row.getPublishedAt());
        row.setNextAttemptAt(java.time.LocalDateTime.now().minusSeconds(1)); outbox.saveAndFlush(row);
        when(publisher.publishAsync(any())).thenReturn(CompletableFuture.completedFuture(null));
        service.publishOne(row.getId()); service.publishOne(row.getId());
        assertEquals("PUBLISHED",outbox.findById(row.getId()).orElseThrow().getStatus());
        verify(publisher,times(2)).publishAsync(any());
    }
    @Test void metadataFailureRollsBackDocumentHistoryLegalUnitsAndOutbox() {
        long docs=documents.count(), histories=versionRows.count(), units=chunks.count(), events=outbox.count();
        assertThrows(IllegalStateException.class, () -> service.saveAndEnqueue(document("metadata-fails.txt"), doc -> {
            versions.createVersion(doc,"alice","initial");
            chunks.saveAndFlush(LegalChunk.builder().documentId(doc.getId()).ordinal(0).content("clause").build());
            throw new IllegalStateException("injected metadata failure");
        }));
        assertEquals(docs, documents.count()); assertEquals(histories, versionRows.count());
        assertEquals(units, chunks.count()); assertEquals(events, outbox.count());
    }

    @Test void replacementFailurePreservesPreviousDocumentAndLegalUnits() {
        Document original=service.saveAndEnqueue(document("original.txt"), doc ->
                chunks.saveAndFlush(LegalChunk.builder().documentId(doc.getId()).ordinal(0).content("original clause").build()));
        original.setFileName("replacement.txt"); original.setVersionNumber(2);
        assertThrows(IllegalStateException.class, () -> service.saveAndEnqueue(original, doc -> {
            chunks.deleteByDocumentId(doc.getId());
            versions.createVersion(doc,"alice","replacement");
            throw new IllegalStateException("injected replacement failure");
        }));
        Document restored=documents.findById(original.getId()).orElseThrow();
        assertEquals("original.txt",restored.getFileName()); assertEquals(1,restored.getVersionNumber());
        assertEquals("original clause", chunks.findByDocumentIdOrderByOrdinalAsc(original.getId()).get(0).getContent());
        assertEquals(1, outbox.findAll().stream().filter(row -> row.getDocumentId().equals(original.getId())).count());
    }

}
