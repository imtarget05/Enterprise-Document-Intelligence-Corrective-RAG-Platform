package com.smartdocchat.cache;

import java.time.Duration;
import java.util.Map;

import org.springframework.cache.annotation.EnableCaching;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

@Configuration
@EnableCaching
public class RedisCacheConfig {

    @Bean
    @org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean(org.springframework.cache.CacheManager.class)
    public RedisCacheManager cacheManager(RedisConnectionFactory connectionFactory) {
        // Default cache configuration
        RedisCacheConfiguration defaultConfig = RedisCacheConfiguration.defaultCacheConfig()
            .disableCachingNullValues()
            .serializeKeysWith(RedisSerializationContext.SerializationPair
                .fromSerializer(new StringRedisSerializer()))
            .serializeValuesWith(RedisSerializationContext.SerializationPair
                .fromSerializer(new GenericJackson2JsonRedisSerializer()));

        // Per-cache TTL configurations
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
}