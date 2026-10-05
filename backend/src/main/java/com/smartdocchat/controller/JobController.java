package com.smartdocchat.controller;

import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.DocumentIngestionJob;
import com.smartdocchat.repository.DocumentIngestionJobRepository;
import com.smartdocchat.repository.DocumentRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.security.Principal;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Owner-scoped endpoint to inspect ingestion job status by ID.
 */
@RestController
@RequestMapping("/jobs")
@RequiredArgsConstructor
public class JobController {

    private final DocumentIngestionJobRepository jobRepository;
    private final DocumentRepository documentRepository;

    private boolean isAdmin() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null) {
            return false;
        }
        return auth.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .anyMatch(a -> a.equals("ROLE_ADMIN"));
    }

    @GetMapping("/{id}")
    public ResponseEntity<Map<String, Object>> getJobById(@PathVariable Long id, Principal principal) {
        Optional<DocumentIngestionJob> optJob = jobRepository.findById(id);
        if (optJob.isEmpty()) {
            return ResponseEntity.notFound().build();
        }

        DocumentIngestionJob job = optJob.get();

        // Enforce owner isolation unless user has ROLE_ADMIN
        if (!isAdmin()) {
            Optional<Document> doc = documentRepository.findByIdAndOwnerUsername(job.getDocumentId(), principal.getName());
            if (doc.isEmpty()) {
                // Deny access if current user is not document owner
                return ResponseEntity.notFound().build();
            }
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", job.getId());
        body.put("documentId", job.getDocumentId());
        body.put("jobType", job.getJobType());
        body.put("status", job.getStatus().name());
        body.put("attempts", job.getAttempts());
        body.put("maxAttempts", job.getMaxAttempts());
        body.put("nextRunAt", job.getNextRunAt());
        body.put("lastError", job.getLastError());
        body.put("createdAt", job.getCreatedAt());
        body.put("updatedAt", job.getUpdatedAt());

        return ResponseEntity.ok(body);
    }
}
