package com.smartdocchat.consumer;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.concurrent.CompletableFuture;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.kafka.test.context.EmbeddedKafka;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.util.ReflectionTestUtils;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.event.WorkflowCompletedEvent;
import com.smartdocchat.service.DocumentEventPublisher;
import com.smartdocchat.service.DocumentService;

/**
 * Tests for {@link WorkflowCompletionConsumer}, focused on write-through search
 * cache invalidation when a document workflow completes successfully.
 */
@ExtendWith(MockitoExtension.class)
@EmbeddedKafka(partitions = 3, topics = {"document-ingestion", "document-classified", "workflow-completed", "document-purged", "notification"})
@DirtiesContext
class WorkflowCompletionConsumerTest {

    @Mock
    private DocumentService documentService;

    @Mock
    private DocumentEventPublisher eventPublisher;

    @Mock
    private KafkaProperties kafkaProperties;

    @Mock
    private KafkaProperties.Topics topics;

    @Mock
    private KafkaTemplate<String, DocumentEvent> kafkaTemplate;

    @Mock
    private SearchResultCache searchResultCache;

    private WorkflowCompletionConsumer consumer;

    @BeforeEach
    void setUp() {
        lenient().when(kafkaProperties.getTopics()).thenReturn(topics);
        lenient().when(topics.getDocumentIngestion()).thenReturn("document-ingestion");
        lenient().when(topics.getDocumentClassified()).thenReturn("document-classified");
        lenient().when(topics.getWorkflowCompleted()).thenReturn("workflow-completed");
        lenient().when(topics.getDocumentPurged()).thenReturn("document-purged");
        lenient().when(topics.getNotification()).thenReturn("notification");

        lenient().when(eventPublisher.publishAsync(any(DocumentEvent.class)))
                .thenReturn(CompletableFuture.completedFuture(mock(SendResult.class)));

        consumer = new WorkflowCompletionConsumer(documentService, eventPublisher, kafkaProperties, searchResultCache);

        ReflectionTestUtils.setField(consumer, "maxAttempts", 3);
        ReflectionTestUtils.setField(consumer, "backoffDelay", 1000L);
        ReflectionTestUtils.setField(consumer, "backoffMultiplier", 2.0);
    }

    @Test
    void handleWorkflowCompletedEvent_success_invalidatesSearchCache() {
        // Given
        WorkflowCompletedEvent event = createEvent("SUCCESS");

        // When
        consumer.handleWorkflowCompletedEvent(event, 0, 0L);

        // Then - the document changed, so cached search results must be evicted
        verify(documentService).updateWorkflowResult(event.documentId(), event.workflowResult(), event.status());
        verify(searchResultCache).invalidateAll(CacheNames.SEARCH_RESULTS);
    }

    @Test
    void handleWorkflowCompletedEvent_failed_doesNotInvalidateSearchCache() {
        // Given
        WorkflowCompletedEvent event = createEvent("FAILED");

        // When
        consumer.handleWorkflowCompletedEvent(event, 0, 0L);

        // Then - nothing changed, so the search cache must stay intact
        verify(searchResultCache, never()).invalidateAll(anyString());
    }

    private WorkflowCompletedEvent createEvent(String status) {
        EventMetadata metadata = new EventMetadata("corr-1", "cause-1", "test", "1.0");
        return WorkflowCompletedEvent.create(metadata, 1L, "{\"classification\":\"Decree\"}", status, 100L);
    }
}
