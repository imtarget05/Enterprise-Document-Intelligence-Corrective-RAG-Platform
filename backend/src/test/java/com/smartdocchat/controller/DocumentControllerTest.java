package com.smartdocchat.controller;

import com.smartdocchat.dto.DocumentDTO;
import com.smartdocchat.dto.UploadResponse;
import com.smartdocchat.entity.Document;
import com.smartdocchat.service.DocumentService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.security.Principal;
import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DocumentControllerTest {

    @Mock private DocumentService documentService;
    @Mock private com.smartdocchat.service.DocumentAccessService documentAccessService;
    @Mock private com.smartdocchat.service.AuditLogService auditLogService;
    @Mock private com.smartdocchat.service.DocumentVersionService documentVersionService;

    private DocumentController controller;

    private Principal principal() {
        Principal principal = mock(Principal.class);
        lenient().when(principal.getName()).thenReturn("alice");
        // Simulate the JWT authentication set up by JwtAuthenticationFilter so
        // the controller resolves ROLE_ENGINEER (may upload and manage own docs).
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken("alice", "n/a",
                        List.of(new SimpleGrantedAuthority("ROLE_ENGINEER"))));
        return principal;
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    private Document document() {
        return Document.builder()
                .id(1L)
                .fileName("report.txt")
                .filePath("uploads/report.txt")
                .ownerUsername("alice")
                .fileType("txt")
                .fileSize(100L)
                .createdAt(LocalDateTime.now())
                .updatedAt(LocalDateTime.now())
                .chunkCount(3)
                .build();
    }

    @Test
    void uploadRejectsEmptyFile() throws Exception {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        MultipartFile empty = new MockMultipartFile("file", "empty.txt", "text/plain", new byte[0]);

        ResponseEntity<UploadResponse> response = controller.uploadDocument(empty, principal());

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertTrue(!response.getBody().isSuccess());
        assertEquals("File is empty", response.getBody().getMessage());
    }

    @Test
    void uploadReturnsDocumentDetails() throws Exception {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        MultipartFile file = new MockMultipartFile("file", "report.txt", "text/plain", "data".getBytes());
        when(documentService.uploadDocument(any(MultipartFile.class), eq("alice"))).thenReturn(document());

        ResponseEntity<UploadResponse> response = controller.uploadDocument(file, principal());

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertTrue(response.getBody().isSuccess());
        assertEquals(1L, response.getBody().getDocumentId());
        assertEquals("report.txt", response.getBody().getFileName());
    }

    @Test
    void uploadHandlesIllegalArgumentAndIoExceptions() throws Exception {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        MultipartFile file = new MockMultipartFile("file", "bad.exe", "application/octet-stream", "x".getBytes());
        when(documentService.uploadDocument(any(MultipartFile.class), anyString()))
                .thenThrow(new IllegalArgumentException("Unsupported document type"));

        assertEquals(HttpStatus.BAD_REQUEST, controller.uploadDocument(file, principal()).getStatusCode());

        when(documentService.uploadDocument(any(MultipartFile.class), anyString()))
                .thenThrow(new IOException("disk full"));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, controller.uploadDocument(file, principal()).getStatusCode());
    }

    @Test
    void getAllDocumentsReturnsDtos() {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        when(documentService.getAllDocumentsForRole("alice", com.smartdocchat.entity.Role.ROLE_ENGINEER))
                .thenReturn(List.of(document()));

        ResponseEntity<List<DocumentDTO>> response = controller.getAllDocuments(principal());

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(1, response.getBody().size());
        assertEquals("report.txt", response.getBody().get(0).getFileName());
    }

    @Test
    void getDocumentByIdReturnsDtoOrNotFound() {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        when(documentService.getDocumentByIdForRole(1L, "alice",
                com.smartdocchat.entity.Role.ROLE_ENGINEER)).thenReturn(document());
        when(documentService.getDocumentByIdForRole(9L, "alice",
                com.smartdocchat.entity.Role.ROLE_ENGINEER)).thenThrow(new RuntimeException("not found"));

        assertEquals(HttpStatus.OK, controller.getDocumentById(1L, principal()).getStatusCode());
        assertEquals(HttpStatus.NOT_FOUND, controller.getDocumentById(9L, principal()).getStatusCode());
    }

    @Test
    void deleteDocumentReturnsOkOrNotFound() {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        when(documentService.getDocumentByIdForRole(1L, "alice",
                com.smartdocchat.entity.Role.ROLE_ENGINEER)).thenReturn(document());
        when(documentService.getDocumentByIdForRole(5L, "alice",
                com.smartdocchat.entity.Role.ROLE_ENGINEER))
                .thenThrow(new RuntimeException("not found"));
        doNothing().when(documentService).deleteDocument(anyLong(), anyString());

        assertEquals("Document deleted successfully", controller.deleteDocument(1L, principal()).getBody());
        assertEquals(HttpStatus.NOT_FOUND, controller.deleteDocument(5L, principal()).getStatusCode());
    }

    @Test
    void deleteDocumentsBatchReturnsOk() {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        when(documentService.deleteDocumentsBatch(List.of(1L, 2L), "alice", com.smartdocchat.entity.Role.ROLE_ENGINEER))
                .thenReturn(2);

        var response = controller.deleteDocumentsBatch(List.of(1L, 2L), principal());

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(2, response.getBody().get("deletedCount"));
    }

    /**
     * Phase 2: a delete must also purge the agent-service stores (vector store,
     * retrieval cache, memory) that hold a copy of the document's content.
     */
    @Test
    void deleteDocumentAlsoPurgesAgentSideArtifacts() {
        com.smartdocchat.service.DocumentPurgeClient purgeClient =
                mock(com.smartdocchat.service.DocumentPurgeClient.class);
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        controller.setDocumentPurgeClient(purgeClient);
        when(documentService.getDocumentByIdForRole(1L, "alice",
                com.smartdocchat.entity.Role.ROLE_ENGINEER)).thenReturn(document());
        doNothing().when(documentService).deleteDocument(anyLong(), anyString());

        controller.deleteDocument(1L, principal());

        verify(purgeClient).purgeDocument(1L, "alice", "report.txt");
    }

    @Test
    void deleteDocumentSurvivesAFailedAgentPurge() {
        com.smartdocchat.service.DocumentPurgeClient purgeClient =
                mock(com.smartdocchat.service.DocumentPurgeClient.class);
        doThrow(new RuntimeException("agent down"))
                .when(purgeClient).purgeDocument(anyLong(), any(), any());
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        controller.setDocumentPurgeClient(purgeClient);
        when(documentService.getDocumentByIdForRole(1L, "alice",
                com.smartdocchat.entity.Role.ROLE_ENGINEER)).thenReturn(document());
        doNothing().when(documentService).deleteDocument(anyLong(), anyString());

        // The document row is already deleted — the caller must still see success.
        var response = controller.deleteDocument(1L, principal());

        assertEquals(HttpStatus.OK, response.getStatusCode());
    }

    @Test
    void deleteDocumentsBatchAlsoPurgesAgentSideArtifacts() {
        com.smartdocchat.service.DocumentPurgeClient purgeClient =
                mock(com.smartdocchat.service.DocumentPurgeClient.class);
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        controller.setDocumentPurgeClient(purgeClient);
        when(documentService.deleteDocumentsBatch(List.of(1L, 2L), "alice", com.smartdocchat.entity.Role.ROLE_ENGINEER))
                .thenReturn(2);

        controller.deleteDocumentsBatch(List.of(1L, 2L), principal());

        verify(purgeClient).purgeDocument(1L, "alice", null);
        verify(purgeClient).purgeDocument(2L, "alice", null);
    }

    @Test
    void deleteDocumentWorksWithoutPurgeClientConfigured() {
        controller = new DocumentController(documentService, documentAccessService, auditLogService, documentVersionService);
        when(documentService.getDocumentByIdForRole(1L, "alice",
                com.smartdocchat.entity.Role.ROLE_ENGINEER)).thenReturn(document());
        doNothing().when(documentService).deleteDocument(anyLong(), anyString());

        assertEquals(HttpStatus.OK, controller.deleteDocument(1L, principal()).getStatusCode());
    }
}
