package com.smartdocchat.service;

import com.smartdocchat.entity.Document;
import com.smartdocchat.entity.Role;
import com.smartdocchat.repository.DocumentRepository;
import com.smartdocchat.util.DocumentParser;
import com.smartdocchat.util.LegalDateExtractor;
import com.smartdocchat.util.LegalQueryNormalizer;
import com.smartdocchat.util.LegalStructureParser;
import com.smartdocchat.repository.LegalChunkRepository;
import com.smartdocchat.config.IngestionConfig;
import org.junit.jupiter.api.Test;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.concurrent.ConcurrentMapCacheManager;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** A Spring cache proxy must never return an admin/owner-warmed document to another principal. */
class DocumentServiceOwnerCacheIsolationTest {

    @Configuration
    @EnableCaching
    static class CacheProxyFixture {
        @Bean CacheManager cacheManager() { return new ConcurrentMapCacheManager("documents", "documentMetadata"); }
        @Bean DocumentRepository repository() { return mock(DocumentRepository.class); }
        @Bean DocumentService documentService(DocumentRepository repository) {
            return new DocumentService(repository, mock(DocumentParser.class), mock(StorageService.class),
                    mock(LegalStructureParser.class), mock(LegalChunkRepository.class),
                    mock(LegalQueryNormalizer.class), mock(LegalDateExtractor.class),
                    mock(DocumentWorkflowClient.class), new IngestionConfig(),
                    mock(DocumentVersionService.class), mock(DocumentJobService.class),
                    mock(DocumentEventPublisher.class));
        }
    }

    @Test
    void adminAndOwnerWarmReadsCannotLeakToAnotherPrincipal() {
        try (var context = new AnnotationConfigApplicationContext(CacheProxyFixture.class)) {
            var service = context.getBean(DocumentService.class);
            var repository = context.getBean(DocumentRepository.class);
            var aliceDoc = Document.builder().id(42L).ownerUsername("alice").build();
            when(repository.findById(42L)).thenReturn(Optional.of(aliceDoc));
            when(repository.findByIdAndOwnerUsername(42L, "alice")).thenReturn(Optional.of(aliceDoc));
            when(repository.findByIdAndOwnerUsername(42L, "bob")).thenReturn(Optional.empty());

            assertEquals(aliceDoc, service.getDocumentByIdForRole(42L, "admin", Role.ROLE_ADMIN));
            assertThrows(RuntimeException.class,
                    () -> service.getDocumentByIdForRole(42L, "bob", Role.ROLE_USER));
            assertEquals(aliceDoc, service.getDocumentById(42L, "alice"));
            assertThrows(RuntimeException.class, () -> service.getDocumentById(42L, "bob"));
            verify(repository, times(2)).findByIdAndOwnerUsername(42L, "bob");
        }
    }

    @Test
    void adminWarmListCannotLeakAfterRoleDowngrade() {
        try (var context = new AnnotationConfigApplicationContext(CacheProxyFixture.class)) {
            var service = context.getBean(DocumentService.class);
            var repository = context.getBean(DocumentRepository.class);
            var aliceDoc = Document.builder().id(42L).ownerUsername("alice").build();
            var bobDoc = Document.builder().id(43L).ownerUsername("bob").build();
            when(repository.findByOrderByCreatedAtDesc()).thenReturn(List.of(aliceDoc, bobDoc));
            when(repository.findByOwnerUsernameOrderByCreatedAtDesc("alice")).thenReturn(List.of(aliceDoc));

            assertEquals(2, service.getAllDocumentsForRole("alice", Role.ROLE_ADMIN).size());
            assertEquals(List.of(aliceDoc), service.getAllDocumentsForRole("alice", Role.ROLE_USER));
            verify(repository).findByOwnerUsernameOrderByCreatedAtDesc("alice");
        }
    }
}
