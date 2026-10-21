package com.smartdocchat.config;

import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.core.ProducerFactory;
import org.springframework.kafka.listener.ContainerProperties;
import org.springframework.kafka.support.serializer.JsonDeserializer;
import org.springframework.kafka.support.serializer.JsonSerializer;

import java.util.HashMap;
import java.util.Map;

/**
 * Kafka configuration for the Smart Document Chatbot.
 * <p>
 * Provides:
 * <ul>
 *   <li>JSON-based {@link ProducerFactory} and {@link KafkaTemplate} for sending events</li>
 *   <li>JSON-based {@link ConsumerFactory} and listener container factory for receiving events</li>
 *   <li>{@link NewTopic} beans for each domain topic (dev defaults: partitions=3, replication=1)</li>
 * </ul>
 * <p>
 * Uses Jackson {@link JsonSerializer}/{@link JsonDeserializer} with type mapping
 * for polymorphic event deserialization. Type mappings are registered only if
 * the event classes are available on the classpath.
 */
@Configuration
public class KafkaConfig {

    private final KafkaProperties kafkaProperties;

    public KafkaConfig(KafkaProperties kafkaProperties) {
        this.kafkaProperties = kafkaProperties;
    }

    /**
     * Producer factory using JSON serialization.
     * Configures type mappings for polymorphic event deserialization on the consumer side.
     */
    @Bean
    public ProducerFactory<String, Object> producerFactory() {
        Map<String, Object> props = new HashMap<>();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, kafkaProperties.getBootstrapServers());
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, JsonSerializer.class);
        // Add custom producer properties from config
        if (kafkaProperties.getProducer().getProperties() != null) {
            props.putAll(kafkaProperties.getProducer().getProperties());
        }
        // Add type mapping for polymorphic events (only if classes exist)
        addTypeMappingsIfAvailable(props);
        return new DefaultKafkaProducerFactory<>(props);
    }

    /**
     * KafkaTemplate for sending messages.
     */
    @Bean
    public KafkaTemplate<String, Object> kafkaTemplate(ProducerFactory<String, Object> producerFactory) {
        return new KafkaTemplate<>(producerFactory);
    }

    /**
     * Consumer factory using JSON deserialization with trusted packages.
     */
    @Bean
    public ConsumerFactory<String, Object> consumerFactory() {
        Map<String, Object> props = new HashMap<>();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, kafkaProperties.getBootstrapServers());
        props.put(ConsumerConfig.GROUP_ID_CONFIG, kafkaProperties.getConsumer().getGroupId());
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, kafkaProperties.getConsumer().getAutoOffsetReset());
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, JsonDeserializer.class);
        // Trust packages for JSON deserialization
        props.put(JsonDeserializer.TRUSTED_PACKAGES, "com.smartdocchat.event");
        // Type mappings for polymorphic deserialization (only if classes exist)
        addTypeMappingsIfAvailable(props);
        // Use type headers for deserialization
        props.put(JsonDeserializer.USE_TYPE_INFO_HEADERS, true);
        props.put(JsonDeserializer.VALUE_DEFAULT_TYPE, "java.util.HashMap");
        // Add custom consumer properties from config
        if (kafkaProperties.getConsumer().getProperties() != null) {
            props.putAll(kafkaProperties.getConsumer().getProperties());
        }
        return new DefaultKafkaConsumerFactory<>(props);
    }

    /**
     * Concurrent message listener container factory.
     * Configures concurrency, acknowledgment mode, and poll timeout.
     */
    @Bean
    public ConcurrentKafkaListenerContainerFactory<String, Object> kafkaListenerContainerFactory(
            ConsumerFactory<String, Object> consumerFactory) {
        ConcurrentKafkaListenerContainerFactory<String, Object> factory =
                new ConcurrentKafkaListenerContainerFactory<>();
        factory.setConsumerFactory(consumerFactory);
        factory.setConcurrency(kafkaProperties.getListener().getConcurrency());
        factory.getContainerProperties().setAckMode(
                ContainerProperties.AckMode.valueOf(kafkaProperties.getListener().getAckMode()));
        factory.getContainerProperties().setPollTimeout(kafkaProperties.getListener().getPollTimeout());
        return factory;
    }

    // ===== Topic Definitions =====

    @Bean
    public NewTopic documentIngestionTopic() {
        return topicBuilder(kafkaProperties.getTopics().getDocumentIngestion());
    }

    @Bean
    public NewTopic documentClassifiedTopic() {
        return topicBuilder(kafkaProperties.getTopics().getDocumentClassified());
    }

    @Bean
    public NewTopic workflowCompletedTopic() {
        return topicBuilder(kafkaProperties.getTopics().getWorkflowCompleted());
    }

    @Bean
    public NewTopic documentPurgedTopic() {
        return topicBuilder(kafkaProperties.getTopics().getDocumentPurged());
    }

    @Bean
    public NewTopic notificationTopic() {
        return topicBuilder(kafkaProperties.getTopics().getNotification());
    }

    private NewTopic topicBuilder(String name) {
        return new NewTopic(name, 3, (short) 1);
    }

    /**
     * Adds type mappings for polymorphic event serialization/deserialization
     * only if the event classes are available on the classpath.
     */
    private void addTypeMappingsIfAvailable(Map<String, Object> props) {
        StringBuilder mappings = new StringBuilder();
        boolean first = true;
        
        // Try to load each event class and add to mappings if available
        String[] eventTypes = {
                "documentIngested:com.smartdocchat.event.DocumentIngestedEvent",
                "documentClassified:com.smartdocchat.event.DocumentClassifiedEvent",
                "workflowCompleted:com.smartdocchat.event.WorkflowCompletedEvent",
                "documentPurged:com.smartdocchat.event.DocumentPurgedEvent"
        };
        
        for (String mapping : eventTypes) {
            String[] parts = mapping.split(":");
            String typeName = parts[0];
            String className = parts[1];
            try {
                Class.forName(className);
                if (!first) {
                    mappings.append(",");
                }
                mappings.append(typeName).append(":").append(className);
                first = false;
            } catch (ClassNotFoundException ignored) {
                // Class not available, skip this mapping
            }
        }
        
        if (!first) {
            props.put(JsonSerializer.TYPE_MAPPINGS, mappings.toString());
            props.put(JsonDeserializer.TYPE_MAPPINGS, mappings.toString());
        }
    }
}