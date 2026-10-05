package com.smartdocchat.controller;

import com.smartdocchat.dto.DocumentDTO;
import com.smartdocchat.service.DocumentService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;

import java.security.Principal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SearchControllerTest {

    @Mock
    private DocumentService documentService;

    private SearchController controller;

    @BeforeEach
    void setUp() {
        controller = new SearchController(documentService);
    }

    private Principal principal(String name) {
        Principal p = mock(Principal.class);
        when(p.getName()).thenReturn(name);
        return p;
    }

    @Test
    void searchPostWithBodyQuery() {
        DocumentDTO dto = DocumentDTO.builder().id(1L).fileName("test.pdf").build();
        when(documentService.searchDocuments("alice", "invoice")).thenReturn(List.of(dto));

        ResponseEntity<List<DocumentDTO>> resp = controller.search(
                Map.of("query", "invoice"), null, principal("alice")
        );

        assertEquals(200, resp.getStatusCodeValue());
        assertEquals(1, resp.getBody().size());
        assertEquals("test.pdf", resp.getBody().get(0).getFileName());
    }

    @Test
    void searchPostWithQueryParams() {
        DocumentDTO dto = DocumentDTO.builder().id(2L).fileName("report.docx").build();
        when(documentService.searchDocuments("alice", "report")).thenReturn(List.of(dto));

        ResponseEntity<List<DocumentDTO>> resp = controller.search(
                null, "report", principal("alice")
        );

        assertEquals(200, resp.getStatusCodeValue());
        assertEquals(1, resp.getBody().size());
        assertEquals("report.docx", resp.getBody().get(0).getFileName());
    }

    @Test
    void searchGetDelegatesToDocumentService() {
        DocumentDTO dto = DocumentDTO.builder().id(3L).fileName("guide.txt").build();
        when(documentService.searchDocuments("alice", "guide")).thenReturn(List.of(dto));

        ResponseEntity<List<DocumentDTO>> resp = controller.searchGet("guide", principal("alice"));

        assertEquals(200, resp.getStatusCodeValue());
        assertEquals(1, resp.getBody().size());
    }
}
