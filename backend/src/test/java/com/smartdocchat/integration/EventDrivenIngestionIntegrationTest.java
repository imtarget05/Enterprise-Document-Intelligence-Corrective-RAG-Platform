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
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.awaitility.Awaitility.await;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/**
 * Integration test for the event-driven ingestion pipeline.
 * Tests concurrent document processing and failure handling via Kafka consumers.
 * Uses EmbeddedKafka and H2 in-memory database with PostgreSQL mode.
 */
@SpringBootTest(properties = {
    "spring.main.allow-bean-definition-overriding=true",
    "job.polling.enabled=false",
    "spring.kafka.listener.ack-mode=RECORD",
    "spring.kafka.listener.concurrency=3",
    "spring.kafka.consumer.auto-offset-reset=earliest",
    "spring.flyway.enabled=false",
    "spring.datasource.url=jdbc:h2:mem:kaftatest2;DB_CLOSE_DELAY=-1;MODE=PostgreSQL",
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
class EventDrivenIngestionIntegrationTest {

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
    private final CountDownLatch classifiedLatch = new CountDownLatch(5); // 5 documents
    private final CountDownLatch workflowCompletedLatch = new CountDownLatch(5);
    private final AtomicInteger classifiedCount = new AtomicInteger(0);
    private final AtomicInteger workflowCompletedCount = new AtomicInteger(0);
    private final AtomicReference<WorkflowCompletedEvent> lastFailedWorkflowEvent = new AtomicReference<>();
    private String documentClassifiedTopic;
    private String workflowCompletedTopic;

    @BeforeAll
    void setupTestConsumer() {
        // Configure test consumer
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

        documentClassifiedTopic = "document-classified";
        workflowCompletedTopic = "workflow-completed";

        testConsumer = new KafkaConsumer<>(props);
        testConsumer.subscribe(List.of(
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
                        if (value instanceof DocumentClassifiedEvent) {
                            classifiedCount.incrementAndGet();
                            classifiedLatch.countDown();
                        } else if (value instanceof WorkflowCompletedEvent event) {
                            workflowCompletedCount.incrementAndGet();
                            if ("FAILED".equals(event.status())) {
                                lastFailedWorkflowEvent.set(event);
                            }
                            workflowCompletedLatch.countDown();
                        }
                    }
                }
            } catch (org.apache.kafka.common.errors.WakeupException e) {
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

    @BeforeEach
    void configureMockWorkflowClient() {
        // Configure mock workflow client to return successful classification
        reset(documentWorkflowClient);
        when(documentWorkflowClient.runWorkflow(anyString(), anyString()))
                .thenReturn("{\"documentNumber\":\"123/2024/ND-CP\",\"issuingBody\":\"Government\",\"classification\":\"Decree\",\"confidence\":0.95,\"issueDate\":\"2024-01-15\",\"effectiveDate\":\"2024-02-01\"}");
    }

    @Test
    void multipleDocuments_processedConcurrently() throws Exception {
        // Given: 5 test documents
        String testContent = "Số: 123/2024/ND-CP\nCỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nĐộc lập - Tự do - Hạnh phúc\n\nNghị định quy định về quản lý tài liệu điện tử.";
        
        // When: Upload 5 documents concurrently
        List<Document> documents = java.util.stream.IntStream.range(0, 5)
                .parallel()
                .mapToObj(i -> {
                    org.springframework.mock.web.MockMultipartFile testFile = new org.springframework.mock.web.MockMultipartFile(
                            "file",
                            "test-document-" + i + ".txt",
                            "text/plain",
                            (testContent + " Document " + i).getBytes()
                    );
                    try {
                        return documentService.uploadDocument(testFile, "testuser" + i);
                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    }
                })
                .toList();

        // Verify all documents were created
        assertEquals(5, documents.size());
        documents.forEach(doc -> {
            assertNotNull(doc.getId());
            assertEquals("testuser" + documents.indexOf(doc), doc.getOwnerUsername());
        });

        // Then: Wait for all DocumentClassifiedEvents to be consumed
        await().atMost(60, TimeUnit.SECONDS)
                .pollInterval(500, TimeUnit.MILLISECONDS)
                .untilAsserted(() -> {
                    assertTrue(classifiedCount.get() >= 5, "All 5 DocumentClassifiedEvents should be received within 60 seconds");
                });

        // Wait for all WorkflowCompletedEvents (SUCCESS) to be consumed
        await().atMost(60, TimeUnit.SECONDS)
                .pollInterval(500, TimeUnit.MILLISECONDS)
                .untilAsserted(() -> {
                    assertTrue(workflowCompletedCount.get() >= 5, "All 5 WorkflowCompletedEvents should be received within 60 seconds");
                });

        // Verify all documents in DB have workflow result and classification metadata
        for (Document doc : documents) {
            Document savedDoc = documentRepository.findById(doc.getId()).orElseThrow();
            assertNotNull(savedDoc.getWorkflowResult(), "Document " + doc.getId() + " should have workflow result");
            assertEquals("SUCCESS", savedDoc.getWorkflowStatus(), "Document " + doc.getId() + " should have SUCCESS status");
            assertEquals("123/2024/ND-CP", savedDoc.getDocumentNumber(), "Document " + doc.getId() + " should have document number");
            assertEquals("Government", savedDoc.getIssuingBody(), "Document " + doc.getId() + " should have issuing body");
            assertNotNull(savedDoc.getIssueDate(), "Document " + doc.getId() + " should have issue date");
        }
    }

    @Test
    void workflowFailure_handledGracefully() throws Exception {
        // Given: Mock workflow client to throw exception
        reset(documentWorkflowClient);
        when(documentWorkflowClient.runWorkflow(anyString(), anyString()))
                .thenThrow(new RuntimeException("LLM router unavailable"));

        // Given: A test document
        String testContent = "Số: 999/2024/ND-CP\nTest document for failure handling.";
        org.springframework.mock.web.MockMultipartFile testFile = new org.springframework.mock.web.MockMultipartFile(
                "file",
                "failure-test.txt",
                "text/plain",
                testContent.getBytes()
        );

        // When: Upload document
        Document document = documentService.uploadDocument(testFile, "failureuser");

        // Verify document was created
        assertNotNull(document.getId());

        // Then: Wait for WorkflowCompletedEvent with FAILED status
        await().atMost(30, TimeUnit.SECONDS)
                .pollInterval(500, TimeUnit.MILLISECONDS)
                .untilAsserted(() -> {
                    assertNotNull(lastFailedWorkflowEvent.get(), "WorkflowCompletedEvent with FAILED status should be received within 30 seconds");
                });

        WorkflowCompletedEvent failedEvent = lastFailedWorkflowEvent.get();
        assertNotNull(failedEvent);
        assertEquals(document.getId(), failedEvent.documentId());
        assertEquals("FAILED", failedEvent.status());
        assertNotNull(failedEvent.workflowResult());
        assertTrue(failedEvent.workflowResult().contains("LLM router unavailable") || 
                   failedEvent.workflowResult().contains("Router unavailable") ||
                   failedEvent.workflowResult().contains("workflow"),
                "Workflow result should contain error information");

        // Verify document in DB has FAILED status
        Document savedDoc = documentRepository.findById(document.getId()).orElseThrow();
        assertNotNull(savedDoc.getWorkflowResult(), "Document should have workflow result");
        assertEquals("FAILED", savedDoc.getWorkflowStatus(), "Document should have FAILED status");
    }
}
