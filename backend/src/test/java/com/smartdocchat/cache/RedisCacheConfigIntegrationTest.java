package com.smartdocchat.cache;

import static org.assertj.core.api.Assertions.assertThat;

import java.lang.reflect.Field;
import java.time.Duration;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.data.redis.DataRedisTest;
import org.springframework.cache.CacheManager;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.test.context.ActiveProfiles;

@DataRedisTest
@Import(RedisCacheConfig.class)
@ActiveProfiles("test")
class RedisCacheConfigIntegrationTest {

    @Autowired
    private CacheManager cacheManager;

    @Test
    void cacheManager_hasAllExpectedCaches() {
        Set<String> cacheNames = new java.util.HashSet<>(cacheManager.getCacheNames());
        
        assertThat(cacheNames).containsExactlyInAnyOrder(
            CacheNames.DOCUMENTS,
            CacheNames.DOCUMENT_METADATA,
            CacheNames.SEARCH_RESULTS,
            CacheNames.USER_SESSIONS
        );
    }

    @Test
    void cacheManager_isRedisCacheManager() {
        assertThat(cacheManager).isInstanceOf(RedisCacheManager.class);
    }

    @Test
    void cacheManager_ttlConfiguredCorrectly() {
        RedisCacheManager redisCacheManager = (RedisCacheManager) cacheManager;
        Map<String, RedisCacheConfiguration> initialCacheConfigs = getInitialCacheConfigurations(redisCacheManager);
        
        assertThat(initialCacheConfigs).containsKey(CacheNames.DOCUMENTS);
        assertThat(initialCacheConfigs).containsKey(CacheNames.DOCUMENT_METADATA);
        assertThat(initialCacheConfigs).containsKey(CacheNames.SEARCH_RESULTS);
        assertThat(initialCacheConfigs).containsKey(CacheNames.USER_SESSIONS);

        // Verify TTLs (in seconds) using the ttlFunction
        assertThat(getTtlSeconds(initialCacheConfigs.get(CacheNames.DOCUMENTS))).isEqualTo(3600);
        assertThat(getTtlSeconds(initialCacheConfigs.get(CacheNames.DOCUMENT_METADATA))).isEqualTo(1800);
        assertThat(getTtlSeconds(initialCacheConfigs.get(CacheNames.SEARCH_RESULTS))).isEqualTo(900);
        assertThat(getTtlSeconds(initialCacheConfigs.get(CacheNames.USER_SESSIONS))).isEqualTo(86400);
    }

    @SuppressWarnings("unchecked")
    private Map<String, RedisCacheConfiguration> getInitialCacheConfigurations(RedisCacheManager cacheManager) {
        try {
            Field field = RedisCacheManager.class.getDeclaredField("initialCacheConfiguration");
            field.setAccessible(true);
            return (Map<String, RedisCacheConfiguration>) field.get(cacheManager);
        } catch (NoSuchFieldException | IllegalAccessException e) {
            throw new RuntimeException("Failed to access initialCacheConfiguration", e);
        }
    }

    private long getTtlSeconds(RedisCacheConfiguration config) {
        try {
            Field field = RedisCacheConfiguration.class.getDeclaredField("ttlFunction");
            field.setAccessible(true);
            Object ttlFunction = field.get(config);
            if (ttlFunction != null) {
                // FixedDurationTtlFunction has a duration() method
                java.lang.reflect.Method method = ttlFunction.getClass().getMethod("duration");
                Duration ttl = (Duration) method.invoke(ttlFunction);
                return ttl != null ? ttl.getSeconds() : -1;
            }
            return -1;
        } catch (Exception e) {
            throw new RuntimeException("Failed to access ttlFunction field", e);
        }
    }
}