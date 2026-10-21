package com.smartdocchat.cache;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.cache.CacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.junit.jupiter.SpringExtension;

@ExtendWith(SpringExtension.class)
@ContextConfiguration(classes = {SearchResultCacheTest.TestConfig.class, SimpleCacheTestConfig.class})
@TestPropertySource(properties = "spring.data.redis.enabled=false")
class SearchResultCacheTest {

    @TestConfiguration
    static class TestConfig {
        @Bean
        public SearchResultCache searchResultCache(CacheManager cacheManager) {
            return new SearchResultCache(cacheManager);
        }
    }

    @Autowired
    private SearchResultCache searchResultCache;

    @Autowired
    private CacheManager cacheManager;

    @Test
    void getOrCompute_cachesResult_onFirstCall() {
        // Given
        String cacheName = CacheNames.SEARCH_RESULTS;
        String key = "test-key";
        AtomicInteger computeCount = new AtomicInteger(0);
        String expectedValue = "cached-value";

        Callable<String> computeFunction = () -> {
            computeCount.incrementAndGet();
            return expectedValue;
        };

        // When - first call (cache miss)
        String result1 = searchResultCache.getOrCompute(cacheName, key, computeFunction);

        // Then - compute function called once
        assertThat(result1).isEqualTo(expectedValue);
        assertThat(computeCount.get()).isEqualTo(1);

        // When - second call (cache hit)
        String result2 = searchResultCache.getOrCompute(cacheName, key, computeFunction);

        // Then - compute function NOT called again
        assertThat(result2).isEqualTo(expectedValue);
        assertThat(computeCount.get()).isEqualTo(1); // Still 1, not 2
    }

    @Test
    void getOrCompute_doesNotCacheExceptions() {
        // Given
        String cacheName = CacheNames.SEARCH_RESULTS;
        String key = "exception-key";
        AtomicInteger computeCount = new AtomicInteger(0);
        RuntimeException testException = new RuntimeException("Compute failed");

        Callable<String> computeFunction = () -> {
            computeCount.incrementAndGet();
            throw testException;
        };

        // When - first call throws exception
        assertThatThrownBy(() -> searchResultCache.getOrCompute(cacheName, key, computeFunction))
            .isInstanceOf(RuntimeException.class)
            .hasMessage("Compute failed");

        // Then - compute function called once
        assertThat(computeCount.get()).isEqualTo(1);

        // When - second call (should call compute function again since exception wasn't cached)
        assertThatThrownBy(() -> searchResultCache.getOrCompute(cacheName, key, computeFunction))
            .isInstanceOf(RuntimeException.class)
            .hasMessage("Compute failed");

        // Then - compute function called again (not cached)
        assertThat(computeCount.get()).isEqualTo(2);
    }

    @Test
    void invalidate_evictsSpecificKey() {
        // Given
        String cacheName = CacheNames.SEARCH_RESULTS;
        String key1 = "key1";
        String key2 = "key2";
        String value1 = "value1";
        String value2 = "value2";

        // Populate cache with two keys
        searchResultCache.getOrCompute(cacheName, key1, () -> value1);
        searchResultCache.getOrCompute(cacheName, key2, () -> value2);

        // Verify both keys exist
        assertThat(cacheManager.getCache(cacheName).get(key1)).isNotNull();
        assertThat(cacheManager.getCache(cacheName).get(key2)).isNotNull();

        // When - invalidate only key1
        searchResultCache.invalidate(cacheName, key1);

        // Then - key1 evicted, key2 remains
        assertThat(cacheManager.getCache(cacheName).get(key1)).isNull();
        assertThat(cacheManager.getCache(cacheName).get(key2)).isNotNull();
    }

    @Test
    void invalidateAll_clearsCache() {
        // Given
        String cacheName = CacheNames.SEARCH_RESULTS;
        String key1 = "key1";
        String key2 = "key2";
        String key3 = "key3";
        String value1 = "value1";
        String value2 = "value2";
        String value3 = "value3";

        // Populate cache with multiple keys
        searchResultCache.getOrCompute(cacheName, key1, () -> value1);
        searchResultCache.getOrCompute(cacheName, key2, () -> value2);
        searchResultCache.getOrCompute(cacheName, key3, () -> value3);

        // Verify all keys exist
        assertThat(cacheManager.getCache(cacheName).get(key1)).isNotNull();
        assertThat(cacheManager.getCache(cacheName).get(key2)).isNotNull();
        assertThat(cacheManager.getCache(cacheName).get(key3)).isNotNull();

        // When - invalidate all
        searchResultCache.invalidateAll(cacheName);

        // Then - all keys evicted
        assertThat(cacheManager.getCache(cacheName).get(key1)).isNull();
        assertThat(cacheManager.getCache(cacheName).get(key2)).isNull();
        assertThat(cacheManager.getCache(cacheName).get(key3)).isNull();
    }

    @Test
    void getOrCompute_usesDefaultCacheName_whenNotSpecified() {
        // Given
        String key = "default-cache-key";
        String expectedValue = "default-cache-value";
        AtomicInteger computeCount = new AtomicInteger(0);

        Callable<String> computeFunction = () -> {
            computeCount.incrementAndGet();
            return expectedValue;
        };

        // When - use default cache name (SEARCH_RESULTS)
        String result1 = searchResultCache.getOrCompute(key, computeFunction);
        String result2 = searchResultCache.getOrCompute(key, computeFunction);

        // Then
        assertThat(result1).isEqualTo(expectedValue);
        assertThat(result2).isEqualTo(expectedValue);
        assertThat(computeCount.get()).isEqualTo(1);
    }
}