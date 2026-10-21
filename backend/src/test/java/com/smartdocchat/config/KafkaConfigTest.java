package com.smartdocchat.config;

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.serializer.JsonDeserializer;
import org.springframework.kafka.test.context.EmbeddedKafka;
import org.springframework.kafka.test.utils.KafkaTestUtils;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;

import java.time.Duration;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Integration test for Kafka configuration using Spring's EmbeddedKafka.
 * Uses H2 in-memory database with Flyway disabled to avoid external PostgreSQL dependency.
 * Verifies that the Kafka producer/consumer beans are correctly configured
 * and can send/receive messages with JSON serialization.
 */
@SpringBootTest(properties = {
        "spring.flyway.enabled=false",
        "spring.datasource.url=jdbc:h2:mem:testdb;DB_CLOSE_DELAY=-1;MODE=PostgreSQL",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.jpa.hibernate.ddl-auto=create-drop",
        "spring.jpa.database-platform=org.hibernate.dialect.H2Dialect"
})
@DirtiesContext
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@EmbeddedKafka(partitions = 3, topics = {"document-ingestion", "document-classified", "workflow-completed", "document-purged", "notification"})
class KafkaConfigTest {

    @Autowired
    private KafkaTemplate<String, Object> kafkaTemplate;

    @Value("${spring.kafka.bootstrap-servers}")
    private String bootstrapServers;

    @Test
    void kafkaTemplateBeanIsConfigured() {
        assertNotNull(kafkaTemplate, "KafkaTemplate bean should be configured");
    }

    @Test
    void canSendAndReceiveMessage() throws InterruptedException, java.util.concurrent.ExecutionException, java.util.concurrent.TimeoutException {
        String topic = "document-ingestion";
        String key = "test-key";
        Map<String, Object> payload = Map.of(
                "eventType", "documentIngested",
                "documentId", "doc-123",
                "content", "Test document content"
        );

        // Send message
        kafkaTemplate.send(topic, key, payload).get(10, TimeUnit.SECONDS);

        // Create a consumer to verify receipt using the embedded Kafka bootstrap servers
        var consumerProps = new java.util.HashMap<String, Object>();
        consumerProps.put("bootstrap.servers", bootstrapServers);
        consumerProps.put("group.id", "test-consumer-" + System.nanoTime());
        consumerProps.put("auto.offset.reset", "earliest");
        consumerProps.put("enable.auto.commit", "true");
        consumerProps.put("key.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
        consumerProps.put("value.deserializer", "org.springframework.kafka.support.serializer.JsonDeserializer");
        consumerProps.put(JsonDeserializer.TRUSTED_PACKAGES, "com.smartdocchat.event");
        consumerProps.put(JsonDeserializer.USE_TYPE_INFO_HEADERS, false);
        consumerProps.put(JsonDeserializer.VALUE_DEFAULT_TYPE, "java.util.HashMap");

        var consumer = new KafkaConsumer<String, Object>(consumerProps);
        consumer.subscribe(Collections.singletonList(topic));

        AtomicReference<ConsumerRecord<String, Object>> received = new AtomicReference<>();
        CountDownLatch latch = new CountDownLatch(1);

        // Poll for message
        new Thread(() -> {
            try {
                ConsumerRecords<String, Object> records = consumer.poll(Duration.ofSeconds(10));
                if (!records.isEmpty()) {
                    received.set(records.iterator().next());
                    latch.countDown();
                }
            } finally {
                consumer.close();
            }
        }).start();

        assertTrue(latch.await(15, TimeUnit.SECONDS), "Should receive message within timeout");
        assertNotNull(received.get(), "Received record should not be null");
        assertTrue(received.get().value() instanceof Map, "Value should be deserialized as Map");
        
        @SuppressWarnings("unchecked")
        Map<String, Object> value = (Map<String, Object>) received.get().value();
        assertTrue(value.containsKey("eventType"), "Payload should contain eventType");
    }
}