package com.smartdocchat.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/**
 * Adds a correlation id to every request and emits one structured JSON log line
 * per request (via logback LogstashEncoder + MDC).
 *
 * <p>Produces MDC fields: requestId, method, path, status, durationMs.
 * Accepts an upstream {@code X-Request-Id} if present, otherwise generates one.
 */
@Component
@Order(1)
@Slf4j
public class RequestIdFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        long started = System.currentTimeMillis();
        String requestId = request.getHeader("X-Request-Id");
        if (requestId == null || requestId.isBlank()) {
            requestId = UUID.randomUUID().toString();
        }
        String traceId = request.getHeader("X-Trace-Id");
        if (traceId == null || traceId.isBlank()) {
            traceId = requestId;
        }

        try {
            MDC.put("requestId", requestId);
            MDC.put("traceId", traceId);
            MDC.put("method", request.getMethod());
            MDC.put("path", request.getRequestURI());
            response.setHeader("X-Request-Id", requestId);
            response.setHeader("X-Trace-Id", traceId);

            filterChain.doFilter(request, response);
        } finally {
            MDC.put("status", String.valueOf(response.getStatus()));
            MDC.put("durationMs", String.valueOf(System.currentTimeMillis() - started));
            log.info("request completed");
            MDC.clear();
        }
    }
}