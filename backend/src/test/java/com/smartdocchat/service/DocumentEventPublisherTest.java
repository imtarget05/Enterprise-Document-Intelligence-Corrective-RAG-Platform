package com.smartdocchat.service;

import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.DocumentIngestedEvent;
import com.smartdocchat.event.DocumentPurgedEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.event.WorkflowCompletedEvent;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.quality.Strictness;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class DocumentEventPublisherTest {

    @Mock
    private KafkaTemplate<String, Object> kafkaTemplate;

    @Mock
    private KafkaProperties kafkaProperties;

    @Mock
    private KafkaProperties.Topics topics;

    private DocumentEventPublisher publisher;

    @BeforeEach
    void setUp() {
        when(kafkaProperties.getTopics()).thenReturn(topics);
        when(topics.getDocumentIngestion()).thenReturn("document-ingestion");
        when(topics.getDocumentClassified()).thenReturn("document-classified");
        when(topics.getWorkflowCompleted()).thenReturn("workflow-completed");
        when(topics.getDocumentPurged()).thenReturn("document-purged");

        publisher = new DocumentEventPublisher(kafkaTemplate, kafkaProperties);
    }

    @Test
    void publish_sendsToCorrectTopic_withCorrectKey_forDocumentIngestedEvent() {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        CompletableFuture<SendResult<String, Object>> future = mock(CompletableFuture.class);
        when(kafkaTemplate.send(eq("document-ingestion"), eq(event.eventId().toString()), eq(event))).thenReturn(future);

        // When
        publisher.publish(event);

        // Then
        ArgumentCaptor<String> topicCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<DocumentEvent> eventCaptor = ArgumentCaptor.forClass(DocumentEvent.class);
        verify(kafkaTemplate).send(topicCaptor.capture(), keyCaptor.capture(), eventCaptor.capture());

        assertEquals("document-ingestion", topicCaptor.getValue());
        assertEquals(event.eventId().toString(), keyCaptor.getValue());
        assertEquals(event, eventCaptor.getValue());
    }

    @Test
    void publish_sendsToCorrectTopic_withCorrectKey_forDocumentPurgedEvent() {
        // Given
        DocumentPurgedEvent event = createDocumentPurgedEvent();
        CompletableFuture<SendResult<String, Object>> future = mock(CompletableFuture.class);
        when(kafkaTemplate.send(eq("document-purged"), eq(event.eventId().toString()), eq(event))).thenReturn(future);

        // When
        publisher.publish(event);

        // Then
        ArgumentCaptor<String> topicCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        verify(kafkaTemplate).send(topicCaptor.capture(), keyCaptor.capture(), any(DocumentEvent.class));

        assertEquals("document-purged", topicCaptor.getValue());
        assertEquals(event.eventId().toString(), keyCaptor.getValue());
    }

    @Test
    void publish_sendsToCorrectTopic_withCorrectKey_forWorkflowCompletedEvent() {
        // Given
        WorkflowCompletedEvent event = createWorkflowCompletedEvent();
        CompletableFuture<SendResult<String, Object>> future = mock(CompletableFuture.class);
        when(kafkaTemplate.send(eq("workflow-completed"), eq(event.eventId().toString()), eq(event))).thenReturn(future);

        // When
        publisher.publish(event);

        // Then
        ArgumentCaptor<String> topicCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        verify(kafkaTemplate).send(topicCaptor.capture(), keyCaptor.capture(), any(DocumentEvent.class));

        assertEquals("workflow-completed", topicCaptor.getValue());
        assertEquals(event.eventId().toString(), keyCaptor.getValue());
    }

    @Test
    void publishAsync_returnsCompletableFuture() {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        CompletableFuture<SendResult<String, Object>> future = mock(CompletableFuture.class);
        when(kafkaTemplate.send(eq("document-ingestion"), eq(event.eventId().toString()), eq(event))).thenReturn(future);

        // When
        CompletableFuture<SendResult<String, Object>> result = publisher.publishAsync(event);

        // Then
        assertNotNull(result);
        assertTrue(result instanceof CompletableFuture);
        assertSame(future, result); // publishAsync returns the future directly
    }

    @Test
    void publish_registersErrorCallback() {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        CompletableFuture<SendResult<String, Object>> future = mock(CompletableFuture.class);
        when(kafkaTemplate.send(eq("document-ingestion"), eq(event.eventId().toString()), eq(event))).thenReturn(future);

        // When
        publisher.publish(event);

        // Then - verify whenComplete was called to register callback
        verify(future).whenComplete(any(java.util.function.BiConsumer.class));
    }

    @Test
    void publishAsync_completesFutureOnSuccess() {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        CompletableFuture<SendResult<String, Object>> future = new CompletableFuture<>();
        when(kafkaTemplate.send(eq("document-ingestion"), eq(event.eventId().toString()), eq(event))).thenReturn(future);

        // When
        CompletableFuture<SendResult<String, Object>> result = publisher.publishAsync(event);

        // Simulate success
        SendResult<String, Object> sendResult = mock(SendResult.class);
        RecordMetadata recordMetadata = mock(RecordMetadata.class);
        when(sendResult.getRecordMetadata()).thenReturn(recordMetadata);
        when(recordMetadata.partition()).thenReturn(0);
        when(recordMetadata.offset()).thenReturn(100L);
        future.complete(sendResult);

        // Then
        assertTrue(result.isDone());
        assertEquals(sendResult, result.join());
    }

    @Test
    void publishAsync_completesFutureExceptionallyOnFailure() {
        // Given
        DocumentIngestedEvent event = createDocumentIngestedEvent();
        CompletableFuture<SendResult<String, Object>> future = new CompletableFuture<>();
        when(kafkaTemplate.send(eq("document-ingestion"), eq(event.eventId().toString()), eq(event))).thenReturn(future);

        // When
        CompletableFuture<SendResult<String, Object>> result = publisher.publishAsync(event);

        // Simulate failure
        Exception testException = new RuntimeException("Kafka send failed");
        future.completeExceptionally(testException);

        // Then
        assertTrue(result.isCompletedExceptionally());
        assertThrows(CompletionException.class, () -> result.join());
    }

    private DocumentIngestedEvent createDocumentIngestedEvent() {
        EventMetadata metadata = new EventMetadata("corr-1", "cause-1", "test", "1.0");
        return DocumentIngestedEvent.create(metadata, 1L, "test.pdf", "user", "pdf", 1024L, "hash123", "USER");
    }

    private DocumentPurgedEvent createDocumentPurgedEvent() {
        EventMetadata metadata = new EventMetadata("corr-2", "cause-2", "test", "1.0");
        return DocumentPurgedEvent.create(metadata, 1L, "test.pdf", "admin", "Retention expired");
    }

    private WorkflowCompletedEvent createWorkflowCompletedEvent() {
        EventMetadata metadata = new EventMetadata("corr-3", "cause-3", "test", "1.0");
        return WorkflowCompletedEvent.create(metadata, 1L, "{\"result\": \"ok\"}", "SUCCESS", 5000L);
    }
}