package com.smartdocchat.consumer;

import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentClassifiedEvent;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.event.WorkflowCompletedEvent;
import com.smartdocchat.service.DocumentEventPublisher;
import com.smartdocchat.service.DocumentService;
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
 * Test for DocumentClassificationConsumer using EmbeddedKafka and Mockito.
 * Verifies that DocumentClassifiedEvent updates document and emits WorkflowCompletedEvent with SUCCESS.
 */
@ExtendWith(MockitoExtension.class)
@EmbeddedKafka(partitions = 3, topics = {"document-ingestion", "document-classified", "workflow-completed", "document-purged", "notification"})
@DirtiesContext
class DocumentClassificationConsumerTest {

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

    private DocumentClassificationConsumer consumer;

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

        consumer = new DocumentClassificationConsumer(documentService, eventPublisher, kafkaProperties);
        
        // Set the retry topic configuration via reflection
        ReflectionTestUtils.setField(consumer, "maxAttempts", 3);
        ReflectionTestUtils.setField(consumer, "backoffDelay", 1000L);
        ReflectionTestUtils.setField(consumer, "backoffMultiplier", 2.0);
    }

    @Test
    void handleDocumentClassifiedEvent_updatesDocumentAndEmitsWorkflowCompletedSuccess() throws Exception {
        // Given
        DocumentClassifiedEvent event = createDocumentClassifiedEvent();
        
        // Capture the event published
        ArgumentCaptor<DocumentEvent> publishedEventCaptor = ArgumentCaptor.forClass(DocumentEvent.class);

        // When
        consumer.handleDocumentClassifiedEvent(event, 0, 0L);

        // Then - verify document was updated
        verify(documentService).updateDocumentClassification(
                eq(event.documentId()),
                eq(event.documentNumber()),
                eq(event.issuingBody()),
                eq(event.issueDate()),
                eq(event.effectiveDate()),
                eq(event.classification()),
                eq(event.confidence())
        );
        
        // Verify WorkflowCompletedEvent with SUCCESS was published
        verify(eventPublisher).publishAsync(publishedEventCaptor.capture());
        
        DocumentEvent publishedEvent = publishedEventCaptor.getValue();
        assertInstanceOf(WorkflowCompletedEvent.class, publishedEvent);
        
        WorkflowCompletedEvent workflowEvent = (WorkflowCompletedEvent) publishedEvent;
        assertEquals(event.documentId(), workflowEvent.documentId());
        assertEquals("SUCCESS", workflowEvent.status());
        assertNotNull(workflowEvent.processingTimeMs());
        assertTrue(workflowEvent.workflowResult().contains(event.documentNumber()));
    }

    @Test
    void handleDocumentClassifiedEvent_nullDocumentId_handlesGracefully() throws Exception {
        // Given - event with null documentId (edge case)
        DocumentClassifiedEvent event = new DocumentClassifiedEvent(
                UUID.randomUUID(),
                "documentClassified",
                Instant.now(),
                new EventMetadata("corr-1", null, "test", "1.0"),
                null, // null documentId
                "123/2024/ND-CP",
                "Government",
                LocalDate.of(2024, 1, 15),
                LocalDate.of(2024, 2, 1),
                "Decree",
                0.95
        );
        
        ArgumentCaptor<DocumentEvent> publishedEventCaptor = ArgumentCaptor.forClass(DocumentEvent.class);

        // When
        consumer.handleDocumentClassifiedEvent(event, 0, 0L);

        // Then - should not crash, should still emit WorkflowCompletedEvent
        verify(eventPublisher).publishAsync(publishedEventCaptor.capture());
        DocumentEvent publishedEvent = publishedEventCaptor.getValue();
        assertInstanceOf(WorkflowCompletedEvent.class, publishedEvent);
        
        WorkflowCompletedEvent workflowEvent = (WorkflowCompletedEvent) publishedEvent;
        assertEquals("SUCCESS", workflowEvent.status()); // Still SUCCESS as classification was received
    }

    @Test
    void handleDocumentClassifiedEvent_documentServiceThrows_exceptionPropagated() throws Exception {
        // Given
        DocumentClassifiedEvent event = createDocumentClassifiedEvent();
        
        doThrow(new RuntimeException("Database error")).when(documentService)
                .updateDocumentClassification(anyLong(), anyString(), anyString(), any(), any(), anyString(), anyDouble());
        
        // When/Then - exception should propagate for retry
        assertThrows(RuntimeException.class, () -> consumer.handleDocumentClassifiedEvent(event, 0, 0L));
        
        // Verify no event was published (exception before publish)
        verify(eventPublisher, never()).publishAsync(any(DocumentEvent.class));
    }

    private DocumentClassifiedEvent createDocumentClassifiedEvent() {
        EventMetadata metadata = new EventMetadata("corr-1", "cause-1", "test", "1.0");
        return DocumentClassifiedEvent.create(
                metadata,
                1L,
                "123/2024/ND-CP",
                "Government",
                LocalDate.of(2024, 1, 15),
                LocalDate.of(2024, 2, 1),
                "Decree",
                0.95
        );
    }
}