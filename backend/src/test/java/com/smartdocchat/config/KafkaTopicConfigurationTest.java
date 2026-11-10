package com.smartdocchat.config;

import org.apache.kafka.clients.admin.NewTopic;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaAdmin;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class KafkaTopicConfigurationTest {

    @Test
    void topicCreationUsesConfiguredPartitionAndReplicaCounts() {
        KafkaProperties properties = new KafkaProperties();
        properties.setTopicPartitions(6);
        properties.setTopicReplicationFactor((short) 3);

        NewTopic topic = new KafkaConfig(properties).documentIngestionTopic();

        assertEquals(6, topic.numPartitions());
        assertEquals((short) 3, topic.replicationFactor());
    }

    @Test
    void producerUsesConfiguredSaslSecurity() {
        KafkaProperties properties = new KafkaProperties();
        properties.setBootstrapServers(List.of("localhost:9092"));
        properties.setSecurityProtocol("SASL_SSL");
        properties.setSaslMechanism("PLAIN");
        properties.setSaslJaasConfig("org.apache.kafka.common.security.plain.PlainLoginModule required username=\"user\" password=\"secret\";");

        var factory = (DefaultKafkaProducerFactory<String, Object>)
                new KafkaConfig(properties).producerFactory();
        var config = factory.getConfigurationProperties();

        assertEquals("SASL_SSL", config.get("security.protocol"));
        assertEquals("PLAIN", config.get("sasl.mechanism"));
        assertEquals(properties.getSaslJaasConfig(), config.get("sasl.jaas.config"));
    }

    @Test
    void topicAdminUsesConfiguredSaslSecurity() {
        KafkaProperties properties = new KafkaProperties();
        properties.setBootstrapServers(List.of("localhost:9092"));
        properties.setSecurityProtocol("SASL_SSL");
        properties.setSaslMechanism("PLAIN");
        properties.setSaslJaasConfig("test-jaas-config");

        KafkaAdmin admin = new KafkaConfig(properties).kafkaAdmin();

        assertEquals("SASL_SSL", admin.getConfigurationProperties().get("security.protocol"));
        assertEquals("PLAIN", admin.getConfigurationProperties().get("sasl.mechanism"));
        assertEquals("test-jaas-config", admin.getConfigurationProperties().get("sasl.jaas.config"));
    }
}
