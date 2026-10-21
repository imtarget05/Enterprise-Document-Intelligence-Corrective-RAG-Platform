package com.smartdocchat.cache;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.stereotype.Service;

import java.util.concurrent.Callable;

/**
 * Write-through cache for search results.
 * Provides explicit control over caching behavior without using @Cacheable annotations.
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class SearchResultCache {

    private final CacheManager cacheManager;

    /**
     * Gets a value from cache or computes it if not present (write-through pattern).
     * Exceptions from computeFunction are NOT cached.
     *
     * @param cacheName the name of the cache to use
     * @param key the cache key
     * @param computeFunction the function to compute the value if not in cache
     * @param <T> the type of the cached value
     * @return the cached or computed value
     */
    public <T> T getOrCompute(String cacheName, String key, Callable<T> computeFunction) {
        Cache cache = cacheManager.getCache(cacheName);
        if (cache == null) {
            log.warn("Cache '{}' not found, executing compute function directly", cacheName);
            return computeUncached(computeFunction);
        }

        Cache.ValueWrapper wrapper = cache.get(key);
        if (wrapper != null) {
            log.debug("Cache hit for key '{}' in cache '{}'", key, cacheName);
            @SuppressWarnings("unchecked")
            T value = (T) wrapper.get();
            return value;
        }

        log.debug("Cache miss for key '{}' in cache '{}', computing value", key, cacheName);
        T value = computeUncached(computeFunction);
        cache.put(key, value);
        return value;
    }

    /**
     * Gets a value from the default search results cache or computes it if not present.
     *
     * @param key the cache key
     * @param computeFunction the function to compute the value if not in cache
     * @param <T> the type of the cached value
     * @return the cached or computed value
     */
    public <T> T getOrCompute(String key, Callable<T> computeFunction) {
        return getOrCompute(CacheNames.SEARCH_RESULTS, key, computeFunction);
    }

    /**
     * Invalidates (evicts) a specific key from the cache.
     *
     * @param cacheName the name of the cache
     * @param key the key to evict
     */
    public void invalidate(String cacheName, String key) {
        Cache cache = cacheManager.getCache(cacheName);
        if (cache != null) {
            cache.evict(key);
            log.debug("Invalidated key '{}' from cache '{}'", key, cacheName);
        } else {
            log.warn("Cache '{}' not found, cannot invalidate key '{}'", cacheName, key);
        }
    }

    /**
     * Invalidates (evicts) a specific key from the default search results cache.
     *
     * @param key the key to evict
     */
    public void invalidate(String key) {
        invalidate(CacheNames.SEARCH_RESULTS, key);
    }

    /**
     * Clears all entries from the specified cache.
     *
     * @param cacheName the name of the cache to clear
     */
    public void invalidateAll(String cacheName) {
        Cache cache = cacheManager.getCache(cacheName);
        if (cache != null) {
            cache.clear();
            log.debug("Cleared all entries from cache '{}'", cacheName);
        } else {
            log.warn("Cache '{}' not found, cannot clear", cacheName);
        }
    }

    /**
     * Clears all entries from the default search results cache.
     */
    public void invalidateAll() {
        invalidateAll(CacheNames.SEARCH_RESULTS);
    }

    private <T> T computeUncached(Callable<T> computeFunction) {
        try {
            return computeFunction.call();
        } catch (Exception e) {
            log.debug("Compute function threw exception, not caching: {}", e.getMessage());
            if (e instanceof RuntimeException) {
                throw (RuntimeException) e;
            }
            throw new RuntimeException("Cache compute function failed", e);
        }
    }
}