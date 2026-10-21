package com.smartdocchat.integration;

import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.entity.Document;
import com.smartdocchat.event.DocumentClassifiedEvent;
import com.smartdocchat.event.DocumentEvent;
import com.smartdocchat.event.DocumentIngestedEvent;
import com.smartdocchat.event.EventMetadata;
import com.smartdocchat.event.WorkflowCompletedEvent;
import com.smartdocchat.repository.DocumentRepository;
import com.smartdocchat.service.DocumentService;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.serializer.JsonDeserializer;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.TestPropertySource;
import org.testcontainers.containers.KafkaContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.awaitility.Awaitility.await;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration test for the complete Kafka event-driven document ingestion flow.
 * Uses Testcontainers for real Kafka and PostgreSQL instances.
 * 
 * Tests the full event chain:
 * 1. Document upload -> DocumentIngestedEvent published
 * 2. DocumentIngestionConsumer consumes -> triggers workflow -> emits DocumentClassifiedEvent
 * 3. DocumentClassificationConsumer consumes -> updates document -> emits WorkflowCompletedEvent (SUCCESS)
 * 4. WorkflowCompletionConsumer consumes -> updates document workflow result
 */
@SpringBootTest
@Testcontainers
@TestPropertySource(properties = {
    "job.polling.enabled=false",
    "spring.kafka.listener.ack-mode=RECORD",
    "spring.kafka.listener.concurrency=1",
    "spring.kafka.consumer.auto-offset-reset=earliest",
    "spring.jpa.hibernate.ddl-auto=create-drop",
    "spring.flyway.enabled=false"
})
class KafkaIntegrationTest {

    @Container
    static final PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
            .withDatabaseName("smartdoc_test")
            .withUsername("postgres")
            .withPassword("postgres");

    @Container
    static final KafkaContainer kafka = new KafkaContainer("confluentinc/cp-kafka:7.5.0");

    @Autowired
    private DocumentService documentService;

    @Autowired
    private DocumentRepository documentRepository;

    @Autowired
    private KafkaTemplate<String, Object> kafkaTemplate;

    @Autowired
    private KafkaProperties kafkaProperties;

    // Test consumer to capture events
    private static KafkaConsumer<String, Object> testConsumer;
    private static final CountDownLatch classifiedLatch = new CountDownLatch(1);
    private static final CountDownLatch workflowCompletedLatch = new CountDownLatch(1);
    private static final AtomicReference<DocumentClassifiedEvent> capturedClassifiedEvent = new AtomicReference<>();
    private static final AtomicReference<WorkflowCompletedEvent> capturedWorkflowCompletedEvent = new AtomicReference<>();
    private static String documentIngestionTopic;
    private static String documentClassifiedTopic;
    private static String workflowCompletedTopic;

    @DynamicPropertySource
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.kafka.bootstrap-servers", kafka::getBootstrapServers);
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.jpa.hibernate.ddl-auto", () -> "create-drop");
        registry.add("spring.flyway.enabled", () -> "false");
    }

    @BeforeAll
    static void setupTestConsumer() {
        // Configure test consumer to listen to all relevant topics
        var props = new java.util.Properties();
        props.put("bootstrap.servers", kafka.getBootstrapServers());
        props.put("group.id", "test-integration-group-" + System.currentTimeMillis());
        props.put("key.deserializer", StringDeserializer.class);
        props.put("value.deserializer", JsonDeserializer.class);
        props.put(JsonDeserializer.TRUSTED_PACKAGES, "com.smartdocchat.event");
        props.put(JsonDeserializer.USE_TYPE_INFO_HEADERS, true);
        props.put(JsonDeserializer.VALUE_DEFAULT_TYPE, "java.util.HashMap");
        props.put("auto.offset.reset", "earliest");
        props.put("enable.auto.commit", "true");

        // Use default topic names since kafkaProperties is not available in static context
        documentIngestionTopic = "document-ingestion";
        documentClassifiedTopic = "document-classified";
        workflowCompletedTopic = "workflow-completed";

        testConsumer = new KafkaConsumer<>(props);
        testConsumer.subscribe(List.of(
                documentIngestionTopic,
                documentClassifiedTopic,
                workflowCompletedTopic
        ));

        // Start polling in a background thread
        Thread consumerThread = new Thread(() -> {
            while (!Thread.currentThread().isInterrupted()) {
                ConsumerRecords<String, Object> records = testConsumer.poll(Duration.ofMillis(1000));
                for (ConsumerRecord<String, Object> record : records) {
                    Object value = record.value();
                    if (value instanceof DocumentClassifiedEvent event) {
                        capturedClassifiedEvent.set(event);
                        classifiedLatch.countDown();
                    } else if (value instanceof WorkflowCompletedEvent event) {
                        capturedWorkflowCompletedEvent.set(event);
                        workflowCompletedLatch.countDown();
                    }
                }
            }
        });
        consumerThread.setDaemon(true);
        consumerThread.start();
    }

    @AfterAll
    static void cleanupTestConsumer() {
        if (testConsumer != null) {
            testConsumer.close();
        }
    }

    @Test
    void fullEventFlow_uploadDocument_emitsAndConsumesEvents() throws Exception {
        // Given: A test document file
        String testContent = "Số: 123/2024/ND-CP\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nĐộc lập - Tự do - Hạnh phúc\n\nNghị định quy định về quản lý tài liệu điện tử.";
        org.springframework.mock.web.MockMultipartFile testFile = new org.springframework.mock.web.MockMultipartFile(
                "file",
                "test-document.txt",
                "text/plain",
                testContent.getBytes()
        );

        // When: Upload document (this triggers DocumentIngestedEvent)
        Document document = documentService.uploadDocument(testFile, "testuser");

        // Verify document was created
        assertNotNull(document.getId());
        assertEquals("test-document.txt", document.getFileName());
        assertEquals("testuser", document.getOwnerUsername());

        // Then: Wait for DocumentClassifiedEvent to be consumed (from document-classified topic)
        await().atMost(30, TimeUnit.SECONDS)
                .pollInterval(500, TimeUnit.MILLISECONDS)
                .untilAsserted(() -> {
                    assertEquals(0, classifiedLatch.getCount(), "DocumentClassifiedEvent should be received within 30 seconds");
                });

        DocumentClassifiedEvent classifiedEvent = capturedClassifiedEvent.get();
        assertNotNull(classifiedEvent);
        assertEquals(document.getId(), classifiedEvent.documentId());
        assertEquals("123/2024/ND-CP", classifiedEvent.documentNumber());
        assertEquals("Government", classifiedEvent.issuingBody());
        assertEquals("Decree", classifiedEvent.classification());
        assertNotNull(classifiedEvent.confidence());
        assertTrue(classifiedEvent.confidence() > 0.0 && classifiedEvent.confidence() <= 1.0);

        // Wait for WorkflowCompletedEvent to be consumed (from workflow-completed topic)
        await().atMost(30, TimeUnit.SECONDS)
                .pollInterval(500, TimeUnit.MILLISECONDS)
                .untilAsserted(() -> {
                    assertEquals(0, workflowCompletedLatch.getCount(), "WorkflowCompletedEvent should be received within 30 seconds");
                });

        WorkflowCompletedEvent workflowEvent = capturedWorkflowCompletedEvent.get();
        assertNotNull(workflowEvent);
        assertEquals(document.getId(), workflowEvent.documentId());
        assertEquals("SUCCESS", workflowEvent.status());
        assertNotNull(workflowEvent.workflowResult());
        assertNotNull(workflowEvent.processingTimeMs());
        assertTrue(workflowEvent.processingTimeMs() > 0);

        // Verify document in DB has workflow result and classification metadata
        Document savedDoc = documentRepository.findById(document.getId()).orElseThrow();
        assertNotNull(savedDoc.getWorkflowResult());
        assertEquals("SUCCESS", savedDoc.getWorkflowStatus());
        assertEquals("123/2024/ND-CP", savedDoc.getDocumentNumber());
        assertEquals("Government", savedDoc.getIssuingBody());
        assertNotNull(savedDoc.getIssueDate());
    }
}