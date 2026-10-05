package com.smartdocchat.controller;

import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentIngestionJob;
import com.smartdocchat.repository.DocumentIngestionJobRepository;
import com.smartdocchat.repository.DocumentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;

import java.security.Principal;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class JobControllerTest {

    @Mock
    private DocumentIngestionJobRepository jobRepository;

    @Mock
    private DocumentRepository documentRepository;

    private JobController controller;

    @BeforeEach
    void setUp() {
        controller = new JobController(jobRepository, documentRepository);
    }

    private Principal principal(String name) {
        Principal p = mock(Principal.class);
        org.mockito.Mockito.lenient().when(p.getName()).thenReturn(name);
        return p;
    }

    @Test
    void getJobByIdReturns404WhenJobNotFound() {
        when(jobRepository.findById(999L)).thenReturn(Optional.empty());

        ResponseEntity<Map<String, Object>> resp = controller.getJobById(999L, principal("alice"));
        assertEquals(404, resp.getStatusCodeValue());
    }

    @Test
    void getJobByIdReturns404WhenUserNotOwner() {
        DocumentIngestionJob job = DocumentIngestionJob.builder()
                .id(1L)
                .documentId(10L)
                .jobType("WORKFLOW")
                .status(DocumentIngestionJob.JobStatus.PENDING)
                .build();
        when(jobRepository.findById(1L)).thenReturn(Optional.of(job));
        when(documentRepository.findByIdAndOwnerUsername(10L, "bob")).thenReturn(Optional.empty());

        ResponseEntity<Map<String, Object>> resp = controller.getJobById(1L, principal("bob"));
        assertEquals(404, resp.getStatusCodeValue());
    }

    @Test
    void getJobByIdReturnsJobWhenUserIsOwner() {
        DocumentIngestionJob job = DocumentIngestionJob.builder()
                .id(1L)
                .documentId(10L)
                .jobType("WORKFLOW")
                .status(DocumentIngestionJob.JobStatus.RUNNING)
                .attempts(1)
                .maxAttempts(3)
                .build();
        Document doc = Document.builder().id(10L).ownerUsername("alice").build();

        when(jobRepository.findById(1L)).thenReturn(Optional.of(job));
        when(documentRepository.findByIdAndOwnerUsername(10L, "alice")).thenReturn(Optional.of(doc));

        ResponseEntity<Map<String, Object>> resp = controller.getJobById(1L, principal("alice"));
        assertEquals(200, resp.getStatusCodeValue());
        assertEquals(1L, resp.getBody().get("id"));
        assertEquals("RUNNING", resp.getBody().get("status"));
    }
}
