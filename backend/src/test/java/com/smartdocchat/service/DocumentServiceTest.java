package com.smartdocchat.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartdocchat.entity.Document;
import com.smartdocchat.repository.DocumentRepository;
import com.smartdocchat.util.DocumentParser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DocumentServiceTest {

    @Mock private DocumentRepository documentRepository;
    @Mock private DocumentParser documentParser;
    @Mock private com.smartdocchat.service.DocumentVersionService documentVersionService;
    @Mock private StorageService storageService;
    @Mock private com.smartdocchat.util.LegalStructureParser legalStructureParser;
    @Mock private com.smartdocchat.repository.LegalChunkRepository legalChunkRepository;
    @Mock private com.smartdocchat.util.LegalQueryNormalizer legalQueryNormalizer;
    @Mock private com.smartdocchat.util.LegalDateExtractor legalDateExtractor;
    @Mock private com.smartdocchat.service.DocumentWorkflowClient documentWorkflowClient;
    @Mock private com.smartdocchat.service.DocumentJobService documentJobService;
    @Mock private DocumentEventPublisher eventPublisher;

    private DocumentService documentService;

    @BeforeEach
    void setUp() {
        documentService = new DocumentService(documentRepository, documentParser, storageService,
                legalStructureParser, legalChunkRepository, legalQueryNormalizer, legalDateExtractor, documentWorkflowClient,
                new com.smartdocchat.config.IngestionConfig(), documentVersionService, documentJobService, eventPublisher);
    }

    private Document document(long id, String chunks) {
        return Document.builder()
                .id(id)
                .fileName("report.txt")
                .filePath("uploads/report.txt")
                .ownerUsername("alice")
                .fileType("txt")
                .fileSize(100L)
                .chunkCount(2)
                .chunks(chunks)
                .build();
    }

    @Test
    void uploadsTxtDocumentAndPersists() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file", "report.txt", "text/plain", "This is a valid text document.".getBytes(StandardCharsets.UTF_8));
        when(storageService.upload(anyString(), any())).thenReturn("uploads/report.txt");
        when(storageService.download("uploads/report.txt")).thenReturn(new File("report.txt"));
        when(documentParser.extractText(any(File.class), anyString())).thenReturn("extracted text");
        when(documentParser.chunkText("extracted text", 500, 100)).thenReturn(List.of("chunk1", "chunk2"));
        when(documentRepository.save(any(Document.class))).thenAnswer(inv -> {
            Document d = inv.getArgument(0);
            d.setId(1L);
            return d;
        });

        Document saved = documentService.uploadDocument(file, "alice");

        assertEquals("report.txt", saved.getFileName());
        assertEquals("txt", saved.getFileType());
        assertEquals(2, saved.getChunkCount());
        assertTrue(saved.getFilePath().startsWith("uploads/"));
    }

    @Test
    void rejectsUnsupportedExtension() {
        MockMultipartFile file = new MockMultipartFile(
                "file", "virus.exe", "application/octet-stream", "MZ........".getBytes(StandardCharsets.UTF_8));
        assertThrows(IllegalArgumentException.class, () -> documentService.uploadDocument(file, "alice"));
    }

    @Test
    void rejectsTinyFile() {
        MockMultipartFile file = new MockMultipartFile("file", "tiny.txt", "text/plain", "ab".getBytes());
        assertThrows(IllegalArgumentException.class, () -> documentService.uploadDocument(file, "alice"));
    }

    @Test
    void rejectsTxtWithInvalidUtf8() {
        MockMultipartFile file = new MockMultipartFile(
                "file", "bad.txt", "text/plain", new byte[]{(byte) 0xC3, (byte) 0x28, (byte) 0x61});
        assertThrows(IllegalArgumentException.class, () -> documentService.uploadDocument(file, "alice"));
    }

    @Test
    void allowsPdfWithoutMagicHeader_OcrFallback() throws Exception {
        // PDFs without magic bytes are now accepted (OCR fallback will handle them)
        MockMultipartFile file = new MockMultipartFile(
                "file", "scanned.pdf", "application/pdf", "scanned content".getBytes());

        when(storageService.upload(anyString(), any())).thenReturn("uploads/scanned.pdf");
        when(storageService.download(anyString())).thenReturn(new File("scanned.pdf"));
        when(documentParser.extractText(any(File.class), anyString())).thenReturn("scanned text");
        when(documentParser.chunkText(anyString(), anyInt(), anyInt())).thenReturn(List.of("chunk"));
        when(documentRepository.save(any(Document.class))).thenAnswer(inv -> {
            Document d = inv.getArgument(0);
            d.setId(1L);
            return d;
        });

        Document saved = documentService.uploadDocument(file, "alice");
        assertEquals("pdf", saved.getFileType());
    }

    @Test
    void acceptsPdfWithMagicHeader() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file", "real.pdf", "application/pdf",
                new byte[]{0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34});
        when(storageService.upload(anyString(), any())).thenReturn("uploads/real.pdf");
        when(storageService.download(anyString())).thenReturn(new File("real.pdf"));
        when(documentParser.extractText(any(File.class), anyString())).thenReturn("pdf text");
        when(documentParser.chunkText(anyString(), anyInt(), anyInt())).thenReturn(List.of("chunk"));
        when(documentRepository.save(any(Document.class))).thenAnswer(inv -> {
            Document d = inv.getArgument(0);
            d.setId(1L);
            return d;
        });

        Document saved = documentService.uploadDocument(file, "alice");
        assertEquals("pdf", saved.getFileType());
    }

    @Test
    void acceptsDocxWithZipMagicHeader() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file", "real.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                new byte[]{0x50, 0x4B, 0x03, 0x04, 0x00, 0x00, 0x00, 0x00});
        when(storageService.upload(anyString(), any())).thenReturn("uploads/real.docx");
        when(storageService.download(anyString())).thenReturn(new File("real.docx"));
        when(documentParser.extractText(any(File.class), anyString())).thenReturn("docx text");
        when(documentParser.chunkText(anyString(), anyInt(), anyInt())).thenReturn(List.of("chunk"));
        when(documentRepository.save(any(Document.class))).thenAnswer(inv -> {
            Document d = inv.getArgument(0);
            d.setId(1L);
            return d;
        });

        Document saved = documentService.uploadDocument(file, "alice");
        assertEquals("docx", saved.getFileType());
    }

    @Test
    void defaultsToTxtExtensionWhenFileNameHasNoDot() throws Exception {
        MockMultipartFile file = new MockMultipartFile("file", "README", "text/plain", "content".getBytes());
        when(storageService.upload(anyString(), any())).thenReturn("uploads/README.txt");
        when(storageService.download(anyString())).thenReturn(new File("README.txt"));
        when(documentParser.extractText(any(File.class), anyString())).thenReturn("text");
        when(documentParser.chunkText(anyString(), anyInt(), anyInt())).thenReturn(List.of("chunk"));
        when(documentRepository.save(any(Document.class))).thenAnswer(inv -> {
            Document d = inv.getArgument(0);
            d.setId(1L);
            return d;
        });

        Document saved = documentService.uploadDocument(file, "alice");
        assertEquals("txt", saved.getFileType());
    }

    @Test
    void getAllDocumentsDelegatesToRepository() {
        when(documentRepository.findByOwnerUsernameOrderByCreatedAtDesc("alice"))
                .thenReturn(List.of(document(1L, "[]")));
        assertEquals(1, documentService.getAllDocuments("alice").size());
    }

    @Test
    void getDocumentByIdThrowsWhenNotFound() {
        when(documentRepository.findByIdAndOwnerUsername(9L, "alice")).thenReturn(Optional.empty());
        assertThrows(RuntimeException.class, () -> documentService.getDocumentById(9L, "alice"));
    }

    @Test
    void deleteDocumentDeletesStorageAndRow() {
        when(documentRepository.findByIdAndOwnerUsername(1L, "alice"))
                .thenReturn(Optional.of(document(1L, "[]")));
        documentService.deleteDocument(1L, "alice");
        verify(storageService).delete("uploads/report.txt");
        verify(documentRepository).delete(any(Document.class));
    }

    @Test
    void getDocumentChunksParsesJsonAndHandlesErrors() {
        String json = "[\"chunk one\",\"chunk two\"]";
        when(documentRepository.findByIdAndOwnerUsername(1L, "alice"))
                .thenReturn(Optional.of(document(1L, json)));
        when(documentRepository.findByIdAndOwnerUsername(2L, "alice"))
                .thenReturn(Optional.of(document(2L, "{not json")));
        when(documentRepository.findByIdAndOwnerUsername(3L, "alice"))
                .thenReturn(Optional.of(document(3L, null)));

        assertEquals(List.of("chunk one", "chunk two"), documentService.getDocumentChunks(1L, "alice"));
        assertTrue(documentService.getDocumentChunks(2L, "alice").isEmpty());
        assertTrue(documentService.getDocumentChunks(3L, "alice").isEmpty());
    }

    @Test
    void uploadEnqueuesDurableWorkflowJobInsteadOfInlineCall() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file", "report.txt", "text/plain", "Queued workflow content.".getBytes(StandardCharsets.UTF_8));
        when(storageService.upload(anyString(), any())).thenReturn("uploads/report.txt");
        when(storageService.download("uploads/report.txt")).thenReturn(new File("report.txt"));
        when(documentParser.extractText(any(File.class), anyString())).thenReturn("extracted text");
        when(documentParser.chunkText("extracted text", 500, 100)).thenReturn(List.of("chunk1"));
        when(documentRepository.save(any(Document.class))).thenAnswer(inv -> {
            Document d = inv.getArgument(0);
            d.setId(1L);
            return d;
        });

        Document saved = documentService.uploadDocument(file, "alice");

        // ADR-004: the llm-router workflow is enqueued as a durable job — the
        // backend must not call the router inline from the upload request path.
        verify(documentJobService).enqueueWorkflowJob(saved, "report.txt");
        verify(documentWorkflowClient, never()).runWorkflow(anyString(), anyString());
    }
}