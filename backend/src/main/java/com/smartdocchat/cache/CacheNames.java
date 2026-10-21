package com.smartdocchat.cache;

/**
 * Constants for cache names used throughout the application.
 * Each cache has a specific TTL configured in RedisCacheConfig.
 */
public interface CacheNames {

    /** Document metadata cache - TTL: 1 hour (3600s) */
    String DOCUMENTS = "documents";

    /** Lightweight document metadata cache - TTL: 30 minutes (1800s) */
    String DOCUMENT_METADATA = "document-metadata";

    /** Search query results cache - TTL: 15 minutes (900s) */
    String SEARCH_RESULTS = "search-results";

    /** User session data cache - TTL: 24 hours (86400s) */
    String USER_SESSIONS = "user-sessions";

    /** Rate limit counters cache - TTL: 1 minute (handled by Redis directly) */
    String RATE_LIMITS = "rate-limits";
}