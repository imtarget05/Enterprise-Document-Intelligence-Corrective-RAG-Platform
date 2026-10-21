package com.smartdocchat.cache;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.cache.CacheManager;
import org.springframework.cache.concurrent.ConcurrentMapCache;
import org.springframework.cache.support.SimpleCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

import java.util.Arrays;

@TestConfiguration
public class SimpleCacheTestConfig {

    @Bean
    @Primary
    public CacheManager cacheManager() {
        SimpleCacheManager cacheManager = new SimpleCacheManager();
        cacheManager.setCaches(Arrays.asList(
            new ConcurrentMapCache(CacheNames.DOCUMENTS),
            new ConcurrentMapCache(CacheNames.DOCUMENT_METADATA),
            new ConcurrentMapCache(CacheNames.SEARCH_RESULTS),
            new ConcurrentMapCache(CacheNames.USER_SESSIONS),
            new ConcurrentMapCache(CacheNames.RATE_LIMITS)
        ));
        return cacheManager;
    }
}