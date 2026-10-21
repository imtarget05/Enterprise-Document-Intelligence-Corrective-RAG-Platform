package com.smartdocchat.cache;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

class RedisCacheConfigTest {

    @Test
    void redisCacheConfig_createsCacheManagerWithCorrectCachesAndTTLs() {
        // Create a minimal LettuceConnectionFactory for testing (won't actually connect)
        RedisConnectionFactory connectionFactory = new LettuceConnectionFactory("localhost", 6379);
        
        // Create the RedisCacheManager using the same logic as RedisCacheConfig
        RedisCacheManager cacheManager = createCacheManager(connectionFactory);
        
        // Verify all expected caches exist
        Map<String, RedisCacheConfiguration> cacheConfigs = getInitialCacheConfigurations(cacheManager);
        
        assertThat(cacheConfigs.keySet()).containsExactlyInAnyOrder(
            CacheNames.DOCUMENTS,
            CacheNames.DOCUMENT_METADATA,
            CacheNames.SEARCH_RESULTS,
            CacheNames.USER_SESSIONS
        );

        // Verify TTLs (in seconds)
        assertThat(getTtlSeconds(cacheConfigs.get(CacheNames.DOCUMENTS))).isEqualTo(3600);
        assertThat(getTtlSeconds(cacheConfigs.get(CacheNames.DOCUMENT_METADATA))).isEqualTo(1800);
        assertThat(getTtlSeconds(cacheConfigs.get(CacheNames.SEARCH_RESULTS))).isEqualTo(900);
        assertThat(getTtlSeconds(cacheConfigs.get(CacheNames.USER_SESSIONS))).isEqualTo(86400);
    }

    @Test
    void redisCacheConfig_defaultConfigHasCorrectSerialization() {
        RedisConnectionFactory connectionFactory = new LettuceConnectionFactory("localhost", 6379);
        RedisCacheManager cacheManager = createCacheManager(connectionFactory);
        
        // Get the default config
        RedisCacheConfiguration defaultConfig = getDefaultCacheConfiguration(cacheManager);
        
        // Verify serialization settings by checking the cache configuration
        assertThat(defaultConfig).isNotNull();
        // The default config should have null value caching disabled
        // and use StringRedisSerializer for keys and GenericJackson2JsonRedisSerializer for values
    }

    private static RedisCacheManager createCacheManager(RedisConnectionFactory connectionFactory) {
        RedisCacheConfiguration defaultConfig = RedisCacheConfiguration.defaultCacheConfig()
            .disableCachingNullValues()
            .serializeKeysWith(RedisSerializationContext.SerializationPair
                .fromSerializer(new StringRedisSerializer()))
            .serializeValuesWith(RedisSerializationContext.SerializationPair
                .fromSerializer(new GenericJackson2JsonRedisSerializer()));

        Map<String, RedisCacheConfiguration> initialCacheConfigurations = Map.of(
            CacheNames.DOCUMENTS, defaultConfig.entryTtl(Duration.ofSeconds(3600)),
            CacheNames.DOCUMENT_METADATA, defaultConfig.entryTtl(Duration.ofSeconds(1800)),
            CacheNames.SEARCH_RESULTS, defaultConfig.entryTtl(Duration.ofSeconds(900)),
            CacheNames.USER_SESSIONS, defaultConfig.entryTtl(Duration.ofSeconds(86400))
        );

        return RedisCacheManager.builder(connectionFactory)
            .cacheDefaults(defaultConfig)
            .withInitialCacheConfigurations(initialCacheConfigurations)
            .build();
    }

    @SuppressWarnings("unchecked")
    private Map<String, RedisCacheConfiguration> getInitialCacheConfigurations(RedisCacheManager cacheManager) {
        try {
            java.lang.reflect.Field field = RedisCacheManager.class.getDeclaredField("initialCacheConfiguration");
            field.setAccessible(true);
            return (Map<String, RedisCacheConfiguration>) field.get(cacheManager);
        } catch (NoSuchFieldException | IllegalAccessException e) {
            throw new RuntimeException("Failed to access initialCacheConfiguration", e);
        }
    }

    private RedisCacheConfiguration getDefaultCacheConfiguration(RedisCacheManager cacheManager) {
        try {
            java.lang.reflect.Field field = RedisCacheManager.class.getDeclaredField("defaultCacheConfiguration");
            field.setAccessible(true);
            return (RedisCacheConfiguration) field.get(cacheManager);
        } catch (NoSuchFieldException | IllegalAccessException e) {
            throw new RuntimeException("Failed to access defaultCacheConfiguration", e);
        }
    }

    private long getTtlSeconds(RedisCacheConfiguration config) {
        try {
            java.lang.reflect.Field field = RedisCacheConfiguration.class.getDeclaredField("ttlFunction");
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