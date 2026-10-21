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
import com.smartdocchat.service.DocumentWorkflowClient;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.serializer.JsonDeserializer;
import org.springframework.kafka.test.EmbeddedKafkaBroker;
import org.springframework.kafka.test.context.EmbeddedKafka;
import org.springframework.test.annotation.DirtiesContext;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.awaitility.Awaitility.await;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.when;

/**
 * Integration test for the complete Kafka event-driven document ingestion flow.
 * Uses Spring's EmbeddedKafka and H2 in-memory database with PostgreSQL mode.
 * 
 * Tests the full event chain:
 * 1. Document upload -> DocumentIngestedEvent published
 * 2. DocumentIngestionConsumer consumes -> triggers workflow -> emits DocumentClassifiedEvent
 * 3. DocumentClassificationConsumer consumes -> updates document -> emits WorkflowCompletedEvent (SUCCESS)
 * 4. WorkflowCompletionConsumer consumes -> updates document workflow result
 */
@SpringBootTest(properties = {
    "spring.main.allow-bean-definition-overriding=true",
    "job.polling.enabled=false",
    "spring.kafka.listener.ack-mode=RECORD",
    "spring.kafka.listener.concurrency=1",
    "spring.kafka.consumer.auto-offset-reset=earliest",
    "spring.flyway.enabled=false",
    "spring.datasource.url=jdbc:h2:mem:kaftatest;DB_CLOSE_DELAY=-1;MODE=PostgreSQL",
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.datasource.username=sa",
    "spring.datasource.password=",
    "spring.jpa.hibernate.ddl-auto=create-drop",
    "spring.jpa.database-platform=org.hibernate.dialect.H2Dialect"
})
@DirtiesContext
@EmbeddedKafka(partitions = 3, topics = {
    "document-ingestion",
    "document-classified",
    "workflow-completed",
    "document-purged",
    "notification"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@org.springframework.context.annotation.Import(com.smartdocchat.cache.SimpleCacheTestConfig.class)
class KafkaIntegrationTest {

    @Autowired
    private EmbeddedKafkaBroker embeddedKafkaBroker;

    @Autowired
    private DocumentService documentService;

    @Autowired
    private DocumentRepository documentRepository;

    @Autowired
    private KafkaTemplate<String, Object> kafkaTemplate;

    @Autowired
    private KafkaProperties kafkaProperties;

    @MockBean
    private DocumentWorkflowClient documentWorkflowClient;

    // Test consumer to capture events
    private KafkaConsumer<String, Object> testConsumer;
    private Thread consumerThread;
    private volatile boolean running = true;
    private final CountDownLatch classifiedLatch = new CountDownLatch(1);
    private final CountDownLatch workflowCompletedLatch = new CountDownLatch(1);
    private final AtomicReference<DocumentClassifiedEvent> capturedClassifiedEvent = new AtomicReference<>();
    private final AtomicReference<WorkflowCompletedEvent> capturedWorkflowCompletedEvent = new AtomicReference<>();
    private String documentIngestionTopic;
    private String documentClassifiedTopic;
    private String workflowCompletedTopic;

    @BeforeAll
    void setupTestConsumer() {
        // Configure test consumer to listen to all relevant topics
        var props = new java.util.Properties();
        props.put("bootstrap.servers", embeddedKafkaBroker.getBrokersAsString());
        props.put("group.id", "test-integration-group-" + System.currentTimeMillis());
        props.put("key.deserializer", StringDeserializer.class);
        props.put("value.deserializer", JsonDeserializer.class);
        props.put(JsonDeserializer.TRUSTED_PACKAGES, "*");
        props.put(JsonDeserializer.USE_TYPE_INFO_HEADERS, true);
        String typeMappings = "documentIngested:com.smartdocchat.event.DocumentIngestedEvent," +
                "documentClassified:com.smartdocchat.event.DocumentClassifiedEvent," +
                "workflowCompleted:com.smartdocchat.event.WorkflowCompletedEvent," +
                "documentPurged:com.smartdocchat.event.DocumentPurgedEvent";
        props.put(JsonDeserializer.TYPE_MAPPINGS, typeMappings);
        props.put(JsonDeserializer.VALUE_DEFAULT_TYPE, "java.util.HashMap");
        props.put("auto.offset.reset", "earliest");
        props.put("enable.auto.commit", "true");

        // Use default topic names
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
        consumerThread = new Thread(() -> {
            try {
                while (running) {
                    ConsumerRecords<String, Object> records = testConsumer.poll(Duration.ofMillis(200));
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
            } catch (org.apache.kafka.common.errors.WakeupException e) {
                // Ignore exception if closing
                if (running) throw e;
            } finally {
                try {
                    testConsumer.close();
                } catch (Exception ignore) {}
            }
        });
        consumerThread.setDaemon(true);
        consumerThread.start();
    }

    @BeforeEach
    void configureMockWorkflowClient() {
        reset(documentWorkflowClient);
        when(documentWorkflowClient.runWorkflow(anyString(), anyString()))
                .thenReturn("{\"documentNumber\":\"123/2024/ND-CP\",\"issuingBody\":\"Government\",\"classification\":\"Decree\",\"confidence\":0.95,\"issueDate\":\"2024-01-15\",\"effectiveDate\":\"2024-02-01\"}");
    }

    @AfterAll
    void cleanupTestConsumer() {
        running = false;
        if (testConsumer != null) {
            testConsumer.wakeup();
        }
        if (consumerThread != null) {
            try {
                consumerThread.join(3000);
            } catch (InterruptedException ignored) {}
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
        assertTrue(workflowEvent.processingTimeMs() >= 0);

        // Verify document in DB has workflow result and classification metadata
        Document savedDoc = documentRepository.findById(document.getId()).orElseThrow();
        assertNotNull(savedDoc.getWorkflowResult());
        assertEquals("SUCCESS", savedDoc.getWorkflowStatus());
        assertEquals("123/2024/ND-CP", savedDoc.getDocumentNumber());
        assertEquals("Government", savedDoc.getIssuingBody());
        assertNotNull(savedDoc.getIssueDate());
    }
}
