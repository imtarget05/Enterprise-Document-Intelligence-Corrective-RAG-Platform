package com.smartdocchat.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.concurrent.Callable;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class RetrievalServiceTest {

    @Mock private DocumentService documentService;
    @Mock private com.smartdocchat.repository.LegalChunkRepository legalChunkRepository;
    @Mock private com.smartdocchat.cache.SearchResultCache searchResultCache;

    private RetrievalService retrievalService;

    @BeforeEach
    void setUp() {
        retrievalService = new RetrievalService(documentService, legalChunkRepository, 
                new com.smartdocchat.util.LegalQueryNormalizer(), searchResultCache);
        // Delegate to actual retrieval logic for testing
        when(searchResultCache.getOrCompute(anyString(), anyString(), any(Callable.class)))
                .thenAnswer(invocation -> invocation.getArgument(2, Callable.class).call());
    }

    @Test
    void returnsEmptyForNullDocumentOrNonPositiveTopK() {
        assertTrue(retrievalService.retrieve("alice", null, "query", 5).isEmpty());
        assertTrue(retrievalService.retrieve("alice", 1L, "query", 0).isEmpty());
    }

    @Test
    void returnsEmptyWhenNoChunksOrQueryHasNoWords() {
        when(documentService.getDocumentChunks(1L, "alice")).thenReturn(List.of());
        assertTrue(retrievalService.retrieve("alice", 1L, "query", 5).isEmpty());

        when(documentService.getDocumentChunks(2L, "alice"))
                .thenReturn(List.of("some meaningful chunk here"));
        assertTrue(retrievalService.retrieve("alice", 2L, "hi", 5).isEmpty());
    }

    @Test
    void scoresChunksAndReturnsTopKAboveZero() {
        when(documentService.getDocumentChunks(1L, "alice"))
                .thenReturn(List.of("insurance policy renewal process described here",
                        "completely unrelated talk about weather today"));
        when(documentService.getDocumentChunks(2L, "alice")).thenReturn(
                java.util.Arrays.asList("alpha beta gamma delta", "alpha alpha alpha", null, "  "));

        List<RetrievalService.RetrievalResult> top =
                retrievalService.retrieve("alice", 1L, "insurance renewal", 3);

        assertEquals(1, top.size());
        assertTrue(top.get(0).score() > 0.0);
        assertTrue(top.get(0).chunk().contains("insurance policy renewal"));

        List<RetrievalService.RetrievalResult> top2 =
                retrievalService.retrieve("alice", 2L, "alpha beta gamma delta", 10);

        assertEquals(2, top2.size());
        assertTrue(top2.get(0).score() >= top2.get(1).score());
    }

    @Test
    void skipsNullAndBlankChunksWithoutFailing() {
        when(documentService.getDocumentChunks(1L, "alice"))
                .thenReturn(java.util.Arrays.asList("word one", null, " ", "word two"));
        assertEquals(2, retrievalService.retrieve("alice", 1L, "word one two", 10).size());
    }

    @Test
    void retrievesVietnameseChunkForVietnameseQuestion() {
        when(documentService.getDocumentChunks(1L, "alice"))
                .thenReturn(List.of(
                        "Hệ thống sử dụng Spring Boot 3.2 làm framework backend chính, "
                                + "kết hợp FastAPI cho dịch vụ agent.",
                        "Vector database Qdrant lưu trữ embeddings của tài liệu."));
        when(documentService.getDocumentById(1L, "alice"))
                .thenReturn(new com.smartdocchat.entity.Document());

        List<RetrievalService.RetrievalResult> results =
                retrievalService.retrieve("alice", 1L,
                        "Hệ thống sử dụng framework backend nào?", 5);

        assertFalse(results.isEmpty(), "Phải tìm được chunk chứa đáp án tiếng Việt");
        assertTrue(results.get(0).chunk().contains("Spring Boot"),
                "Chunk đứng đầu phải chứa đáp án");
    }

    @Test
    void vietnameseCompoundBigramsBoostCorrectChunk() {
        when(documentService.getDocumentChunks(1L, "alice"))
                .thenReturn(List.of(
                        "Xử lý concurrent users bằng connection pool Hikari giới hạn kết nối PostgreSQL "
                                + "và thread pool với timeout cho mọi call.",
                        "Backup định kỳ PostgreSQL bằng pg_dump hàng ngày."));
        when(documentService.getDocumentById(1L, "alice"))
                .thenReturn(new com.smartdocchat.entity.Document());

        List<RetrievalService.RetrievalResult> results =
                retrievalService.retrieve("alice", 1L,
                        "Cách hệ thống xử lý concurrent users?", 5);

        assertFalse(results.isEmpty(), "Bigram 'concurrent users' phải match được chunk");
        assertTrue(results.get(0).chunk().contains("connection pool"));
    }
}