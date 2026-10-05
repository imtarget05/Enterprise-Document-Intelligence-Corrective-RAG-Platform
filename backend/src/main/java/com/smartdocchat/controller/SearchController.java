package com.smartdocchat.controller;

import com.smartdocchat.dto.DocumentDTO;
import com.smartdocchat.service.DocumentService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.security.Principal;
import java.util.List;
import java.util.Map;

/**
 * Top-level Search API endpoint supporting both POST /search and GET /search.
 */
@RestController
@RequestMapping("/search")
@RequiredArgsConstructor
public class SearchController {

    private final DocumentService documentService;

    @PostMapping
    public ResponseEntity<List<DocumentDTO>> search(
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

    @GetMapping
    public ResponseEntity<List<DocumentDTO>> searchGet(
            @RequestParam(value = "q", defaultValue = "") String query,
            Principal principal) {
        return ResponseEntity.ok(documentService.searchDocuments(principal.getName(), query));
    }
}
