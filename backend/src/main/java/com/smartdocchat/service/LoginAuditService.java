package com.smartdocchat.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;

@Slf4j
@Service
public class LoginAuditService {

    private static final int MAX_FAILED_ATTEMPTS = 5;
    private static final long LOCKOUT_DURATION_MINUTES = 15;
    private static final Duration ATTEMPT_WINDOW = Duration.ofMinutes(30);

    private final RedisTemplate<String, String> redisTemplate;

    @Autowired
    public LoginAuditService(@Autowired(required = false) RedisTemplate<String, String> redisTemplate) {
        this.redisTemplate = redisTemplate;
        if (redisTemplate == null) {
            log.warn("Redis not available — login audit logging disabled (log-only mode)");
        }
    }

    public void recordFailure(String username, String ipAddress) {
        if (redisTemplate == null) {
            log.warn("Failed login attempt for user {} from IP {} (Redis unavailable, log-only)",
                    username, ipAddress);
            return;
        }
        String key = "login:failures:" + username.toLowerCase();
        try {
            Long count = redisTemplate.opsForValue().increment(key);
            if (count != null && count == 1) {
                redisTemplate.expire(key, ATTEMPT_WINDOW);
            }
            redisTemplate.opsForHash().put("login:last_failure:" + username.toLowerCase(),
                    "ip", ipAddress);
            redisTemplate.opsForHash().put("login:last_failure:" + username.toLowerCase(),
                    "time", Instant.now().toString());
            log.warn("Failed login attempt {} for user {} from IP {}",
                    count, username, ipAddress);
        } catch (Exception e) {
            log.warn("Redis login audit failed for user {}, falling back to log-only", username, e);
        }
    }

    public void recordSuccess(String username, String ipAddress) {
        if (redisTemplate == null) {
            log.info("Successful login for user {} from IP {} (Redis unavailable, log-only)",
                    username, ipAddress);
            return;
        }
        String key = "login:failures:" + username.toLowerCase();
        try {
            redisTemplate.delete(key);
            redisTemplate.delete("login:last_failure:" + username.toLowerCase());
            log.info("Successful login for user {} from IP {}", username, ipAddress);
        } catch (Exception e) {
            log.warn("Redis login audit cleanup failed for user {}", username, e);
        }
    }

    public boolean isAccountLocked(String username) {
        if (redisTemplate == null) {
            return false;
        }
        String key = "login:failures:" + username.toLowerCase();
        try {
            String count = redisTemplate.opsForValue().get(key);
            if (count != null && Integer.parseInt(count) >= MAX_FAILED_ATTEMPTS) {
                return true;
            }
        } catch (Exception e) {
            log.warn("Redis account lock check failed for user {}, allowing (fail-open)", username, e);
        }
        return false;
    }

    public boolean isPasswordResetRateLimited(String identifier) {
        if (redisTemplate == null || identifier == null) {
            return false;
        }
        String key = "reset:rate:" + identifier.toLowerCase();
        try {
            String count = redisTemplate.opsForValue().get(key);
            if (count != null && Integer.parseInt(count) >= MAX_FAILED_ATTEMPTS) {
                return true;
            }
        } catch (Exception e) {
            log.warn("Redis reset rate check failed for {}, allowing (fail-open)", identifier, e);
        }
        return false;
    }

    public void recordPasswordResetAttempt(String identifier) {
        if (redisTemplate == null || identifier == null) {
            return;
        }
        String key = "reset:rate:" + identifier.toLowerCase();
        try {
            Long count = redisTemplate.opsForValue().increment(key);
            if (count != null && count == 1) {
                redisTemplate.expire(key, Duration.ofMinutes(15));
            }
        } catch (Exception e) {
            log.warn("Redis reset attempt record failed for {}", identifier, e);
        }
    }
}
