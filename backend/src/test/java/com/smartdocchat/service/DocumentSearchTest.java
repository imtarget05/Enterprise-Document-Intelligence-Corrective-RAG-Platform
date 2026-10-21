package com.smartdocchat.service;

import com.smartdocchat.dto.DocumentDTO;
import com.smartdocchat.entity.Document;
import com.smartdocchat.repository.DocumentRepository;
import com.smartdocchat.repository.LegalChunkRepository;
import com.smartdocchat.util.DocumentParser;
import com.smartdocchat.util.LegalQueryNormalizer;
import com.smartdocchat.util.LegalStructureParser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

/** Decision 15: legal document search with Vietnamese normalisation + owner isolation. */
@ExtendWith(MockitoExtension.class)
class DocumentSearchTest {

    @Mock private DocumentRepository documentRepository;
    @Mock private DocumentParser documentParser;
    @Mock private com.smartdocchat.service.DocumentVersionService documentVersionService;
    @Mock private StorageService storageService;
    @Mock private LegalStructureParser legalStructureParser;
    @Mock private LegalChunkRepository legalChunkRepository;
    @Mock private com.smartdocchat.util.LegalDateExtractor legalDateExtractor;
    @Mock private com.smartdocchat.service.DocumentWorkflowClient documentWorkflowClient;
    @Mock private com.smartdocchat.service.DocumentJobService documentJobService;
    @Mock private DocumentEventPublisher eventPublisher;

    private DocumentService documentService;

    @BeforeEach
    void setUp() {
        documentService = new DocumentService(documentRepository, documentParser, storageService,
                legalStructureParser, legalChunkRepository, new LegalQueryNormalizer(), legalDateExtractor, documentWorkflowClient,
                new com.smartdocchat.config.IngestionConfig(), documentVersionService, documentJobService, eventPublisher);
    }

    private Document doc(long id, String fileName, String title, String number) {
        return Document.builder()
                .id(id).fileName(fileName).ownerUsername("alice")
                .title(title).documentNumber(number).build();
    }

    @Test
    void findsByTitleIgnoringDiacriticsAndCase() {
        when(documentRepository.findByOwnerUsernameOrderByCreatedAtDesc("alice"))
                .thenReturn(List.of(doc(1L, "upload.pdf", "Bộ luật Lao động", null)));
        List<DocumentDTO> results = documentService.searchDocuments("alice", "bo luat lao dong");
        assertEquals(1, results.size());
        assertEquals("Bộ luật Lao động", results.get(0).getTitle());
    }

    @Test
    void findsByDocumentNumber() {
        when(documentRepository.findByOwnerUsernameOrderByCreatedAtDesc("alice"))
                .thenReturn(List.of(doc(1L, "bll.pdf", "Bộ luật Test", "01/2026/TEST")));
        assertTrue(documentService.searchDocuments("alice", "01/2026/TEST").size() == 1);
        assertTrue(documentService.searchDocuments("alice", "Điều 4 văn bản 01/2026/TEST").size() == 1);
    }

    @Test
    void expandsKnownAbbreviations() {
        when(documentRepository.findByOwnerUsernameOrderByCreatedAtDesc("alice"))
                .thenReturn(List.of(doc(1L, "contract.pdf", "Quyền của người lao động", null)));
        assertTrue(documentService.searchDocuments("alice", "NLĐ").size() == 1);
    }

    @Test
    void ownerIsolation_userBNeverSeesUserADocuments() {
        // Repository itself is owner-scoped; simulate B's (empty) result set.
        when(documentRepository.findByOwnerUsernameOrderByCreatedAtDesc("bob")).thenReturn(List.of());
        assertTrue(documentService.searchDocuments("bob", "Bộ luật Lao động").isEmpty());
    }

    @Test
    void irrelevantQueryReturnsEmpty() {
        when(documentRepository.findByOwnerUsernameOrderByCreatedAtDesc("alice"))
                .thenReturn(List.of(doc(1L, "law.pdf", "Bộ luật Lao động", null)));
        assertTrue(documentService.searchDocuments("alice", "công thức nấu phở bò").isEmpty());
    }
}