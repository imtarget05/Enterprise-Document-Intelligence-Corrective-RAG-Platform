package com.smartdocchat.consumer;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.test.context.EmbeddedKafka;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.util.ReflectionTestUtils;

import com.smartdocchat.cache.CacheNames;
import com.smartdocchat.cache.SearchResultCache;
import com.smartdocchat.config.KafkaProperties;
import com.smartdocchat.event.DocumentPurgedEvent;
import com.smartdocchat.event.EventMetadata;

/**
 * Tests for {@link DocumentPurgedConsumer}: purging a document must evict the
 * write-through search cache so removed chunks are never returned.
 */
@ExtendWith(MockitoExtension.class)
@EmbeddedKafka(partitions = 3, topics = {"document-ingestion", "document-classified", "workflow-completed", "document-purged", "notification"})
@DirtiesContext
class DocumentPurgedConsumerTest {

    @Mock
    private SearchResultCache searchResultCache;

    @Mock
    private KafkaProperties kafkaProperties;

    @Mock
    private KafkaProperties.Topics topics;

    private DocumentPurgedConsumer consumer;

    @BeforeEach
    void setUp() {
        lenient().when(kafkaProperties.getTopics()).thenReturn(topics);
        lenient().when(topics.getDocumentPurged()).thenReturn("document-purged");

        consumer = new DocumentPurgedConsumer(searchResultCache, kafkaProperties);

        ReflectionTestUtils.setField(consumer, "maxAttempts", 3);
        ReflectionTestUtils.setField(consumer, "backoffDelay", 1000L);
        ReflectionTestUtils.setField(consumer, "backoffMultiplier", 2.0);
    }

    @Test
    void handleDocumentPurgedEvent_invalidatesSearchCache() {
        // Given
        DocumentPurgedEvent event = createEvent();

        // When
        consumer.handleDocumentPurgedEvent(event, 0, 0L);

        // Then - purged chunks must no longer be served from the cache
        verify(searchResultCache).invalidateAll(CacheNames.SEARCH_RESULTS);
    }

    private DocumentPurgedEvent createEvent() {
        EventMetadata metadata = new EventMetadata("corr-1", "cause-1", "test", "1.0");
        return DocumentPurgedEvent.create(metadata, 1L, "test.pdf", "user", "User deletion request");
    }
}
