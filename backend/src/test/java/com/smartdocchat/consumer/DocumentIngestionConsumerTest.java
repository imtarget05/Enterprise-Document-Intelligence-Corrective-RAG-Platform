package com.smartdocchat.consumer;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentClassifiedEvent;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.DocumentIngestedEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.event.WorkflowCompletedEvent;
import com.smartdocchat.service.DocumentEventPublisher;
import com.smartdocchat.service.DocumentService;
import com.smartdocchat.service.DocumentWorkflowClient;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.kafka.test.context.EmbeddedKafka;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * Test for DocumentIngestionConsumer using EmbeddedKafka and Mockito.
 * Verifies that DocumentIngestedEvent triggers workflow and emits DocumentClassifiedEvent on success,
 * or WorkflowCompletedEvent with FAILED status on failure.
 */
@ExtendWith(MockitoExtension.class)
@EmbeddedKafka(partitions = 3, topics = {"document-ingestion", "document-classified", "workflow-completed", "document-purged", "notification"})
@DirtiesContext
class DocumentIngestionConsumerTest {

    @Mock
    private DocumentService documentService;

    @Mock
    private DocumentWorkflowClient documentWorkflowClient;

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

    private DocumentIngestionConsumer consumer;

    @BeforeEach
    void setUp() {
        lenient().when(kafkaProperties.getTopics()).thenReturn(topics);
        lenient().when(topics.getDocumentIngestion()).thenReturn("document-ingestion");
        lenient().when(topics.getDocumentClassified()).thenReturn("document-classified");
        lenient().when(topics.getWorkflowCompleted()).thenReturn("workflow-completed");
        lenient().when(topics.getDocumentPurged()).thenReturn("document-purged");
        lenient().when(topics.getNotification()).thenReturn("notification");

        // Mock the KafkaTemplate in eventPublisher
        lenient().when(eventPublisher.publishAsync(any(DocumentEvent.class))).thenReturn(CompletableFuture.completedFuture(mock(SendResult.class)));

        consumer = new DocumentIngestionConsumer(documentService, documentWorkflowClient, eventPublisher, kafkaProperties, searchResultCache);
        
        // Set the retry topic configuration via reflection
        ReflectionTestUtils.setField(consumer, "maxAttempts", 3);
        ReflectionTestUtils.setField(consumer, "backoffDelay", 1000L);
        ReflectionTestUtils.setField(consumer, "backoffMultiplier", 2.0);
    }

    @Test
    void handleDocumentIngestedEvent_workflowSuccess_emitsDocumentClassifiedEvent() throws Exception {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        String workflowResult = "{\"documentNumber\":\"123/2024/ND-CP\",\"issuingBody\":\"Government\",\"classification\":\"Decree\",\"confidence\":0.95}";
        
        when(documentWorkflowClient.runWorkflow(anyString(), anyString())).thenReturn(workflowResult);
        
        // Capture the event published
        ArgumentCaptor<DocumentEvent> publishedEventCaptor = ArgumentCaptor.forClass(DocumentEvent.class);

        // When
        consumer.handleDocumentIngestedEvent(event, 0, 0L);

        // Then - verify workflow was called
        verify(documentWorkflowClient).runWorkflow(event.fileName(), event.fileName());
        
        // Verify DocumentClassifiedEvent was published
        verify(eventPublisher).publishAsync(publishedEventCaptor.capture());
        
        DocumentEvent publishedEvent = publishedEventCaptor.getValue();
        assertInstanceOf(DocumentClassifiedEvent.class, publishedEvent);
        
        DocumentClassifiedEvent classifiedEvent = (DocumentClassifiedEvent) publishedEvent;
        assertEquals(event.documentId(), classifiedEvent.documentId());
        assertEquals("123/2024/ND-CP", classifiedEvent.documentNumber());
        assertEquals("Government", classifiedEvent.issuingBody());
        assertEquals("Decree", classifiedEvent.classification());
        assertEquals(0.95, classifiedEvent.confidence());
    }

    @Test
    void handleDocumentIngestedEvent_workflowSuccess_invalidatesSearchCache() throws Exception {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        when(documentWorkflowClient.runWorkflow(anyString(), anyString()))
                .thenReturn("{\"documentNumber\":\"123/2024/ND-CP\",\"issuingBody\":\"Government\",\"classification\":\"Decree\",\"confidence\":0.95}");

        // When
        consumer.handleDocumentIngestedEvent(event, 0, 0L);

        // Then - search results cache is invalidated so new chunks are searchable
        verify(searchResultCache).invalidateAll(CacheNames.SEARCH_RESULTS);
    }

    @Test
    void handleDocumentIngestedEvent_workflowFailure_doesNotInvalidateSearchCache() throws Exception {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        when(documentWorkflowClient.runWorkflow(anyString(), anyString())).thenReturn(null);

        // When
        consumer.handleDocumentIngestedEvent(event, 0, 0L);

        // Then - nothing changed, so the search cache must stay intact
        verify(searchResultCache, never()).invalidateAll(anyString());
    }

    @Test
    void handleDocumentIngestedEvent_workflowFailure_emitsWorkflowCompletedEventFailed() throws Exception {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        
        when(documentWorkflowClient.runWorkflow(anyString(), anyString())).thenReturn(null);
        
        // Capture the event published
        ArgumentCaptor<DocumentEvent> publishedEventCaptor = ArgumentCaptor.forClass(DocumentEvent.class);

        // When
        consumer.handleDocumentIngestedEvent(event, 0, 0L);

        // Then - verify workflow was called
        verify(documentWorkflowClient).runWorkflow(event.fileName(), event.fileName());
        
        // Verify WorkflowCompletedEvent with FAILED status was published
        verify(eventPublisher).publishAsync(publishedEventCaptor.capture());
        
        DocumentEvent publishedEvent = publishedEventCaptor.getValue();
        assertInstanceOf(WorkflowCompletedEvent.class, publishedEvent);
        
        WorkflowCompletedEvent workflowEvent = (WorkflowCompletedEvent) publishedEvent;
        assertEquals(event.documentId(), workflowEvent.documentId());
        assertEquals("FAILED", workflowEvent.status());
        assertNotNull(workflowEvent.processingTimeMs());
    }

    @Test
    void handleDocumentIngestedEvent_workflowThrowsException_emitsWorkflowCompletedEventFailed() throws Exception {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        
        when(documentWorkflowClient.runWorkflow(anyString(), anyString())).thenThrow(new RuntimeException("Router unavailable"));
        
        // Capture the event published
        ArgumentCaptor<DocumentEvent> publishedEventCaptor = ArgumentCaptor.forClass(DocumentEvent.class);

        // When
        consumer.handleDocumentIngestedEvent(event, 0, 0L);

        // Then - verify workflow was called
        verify(documentWorkflowClient).runWorkflow(event.fileName(), event.fileName());
        
        // Verify WorkflowCompletedEvent with FAILED status was published
        verify(eventPublisher).publishAsync(publishedEventCaptor.capture());
        
        DocumentEvent publishedEvent = publishedEventCaptor.getValue();
        assertInstanceOf(WorkflowCompletedEvent.class, publishedEvent);
        
        WorkflowCompletedEvent workflowEvent = (WorkflowCompletedEvent) publishedEvent;
        assertEquals(event.documentId(), workflowEvent.documentId());
        assertEquals("FAILED", workflowEvent.status());
    }

    @Test
    void handleDocumentIngestedEvent_nullDocumentId_handlesGracefully() throws Exception {
        // Given - event with null documentId (edge case)
        DocumentIngestedEvent event = new DocumentIngestedEvent(
                UUID.randomUUID(),
                "documentIngested",
                Instant.now(),
                new EventMetadata("corr-1", null, "test", "1.0"),
                null, // null documentId
                "test.pdf",
                "user",
                "pdf",
                1024L,
                "hash123",
                "USER"
        );
        
        lenient().when(documentWorkflowClient.runWorkflow(anyString(), anyString())).thenReturn("{}");
        
        ArgumentCaptor<DocumentEvent> publishedEventCaptor = ArgumentCaptor.forClass(DocumentEvent.class);

        // When
        consumer.handleDocumentIngestedEvent(event, 0, 0L);

        // Then - should not crash, should emit failed event
        verify(eventPublisher).publishAsync(publishedEventCaptor.capture());
        DocumentEvent publishedEvent = publishedEventCaptor.getValue();
        assertInstanceOf(WorkflowCompletedEvent.class, publishedEvent);
    }

    private DocumentIngestedEvent createDocumentIngestedEvent() {
        EventMetadata metadata = new EventMetadata("corr-1", "cause-1", "test", "1.0");
        return DocumentIngestedEvent.create(metadata, 1L, "test.pdf", "user", "pdf", 1024L, "hash123", "USER");
    }
}