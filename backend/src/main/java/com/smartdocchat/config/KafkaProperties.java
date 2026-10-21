package com.smartdocchat.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Configuration properties for Spring Kafka.
 * Maps all {@code spring.kafka.*} properties with nested consumer, producer,
 * topics, and listener configuration sections.
 */
@Getter
@Setter
@Component
@ConfigurationProperties(prefix = "spring.kafka")
public class KafkaProperties {

    private List<String> bootstrapServers;

    private final Consumer consumer = new Consumer();
    private final Producer producer = new Producer();
    private final Topics topics = new Topics();
    private final Listener listener = new Listener();

    @Getter
    @Setter
    public static class Consumer {
        private String groupId;
        private String autoOffsetReset;
        private String keyDeserializer;
        private String valueDeserializer;
        private Map<String, String> properties = new HashMap<>();
    }

    @Getter
    @Setter
    public static class Producer {
        private String keySerializer;
        private String valueSerializer;
        private Map<String, String> properties = new HashMap<>();
    }

    @Getter
    @Setter
    public static class Topics {
        private String documentIngestion = "document-ingestion";
        private String documentClassified = "document-classified";
        private String workflowCompleted = "workflow-completed";
        private String documentPurged = "document-purged";
        private String notification = "notification";
    }

    @Getter
    @Setter
    public static class Listener {
        private String ackMode = "RECORD";
        private int concurrency = 3;
        private long pollTimeout = 3000;
    }
}