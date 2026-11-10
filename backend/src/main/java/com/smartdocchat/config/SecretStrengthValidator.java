package com.smartdocchat.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import java.util.Arrays;

/**
 * Fail-fast startup guard for deployed environments.
 *
 * <p>The repository intentionally keeps a committed development-only JWT secret
 * so local development works without configuration. Staging and production must
 * never run with that secret (or a blank one): this validator aborts startup in
 * non-local profiles instead of silently serving requests signed with a known
 * key.
 */
@Component
@Slf4j
public class SecretStrengthValidator implements InitializingBean {

    /** Committed base64 default in application.yml — development only. */
    static final String DEV_ONLY_JWT_SECRET =
            "c21hcnQtZG9jLWNoYXRib3Qtc2VjcmV0LWtleS1mb3ItbG9jYWwtZGV2ZWxvcG1lbnQtMjAyNg==";

    private final Environment environment;
    private final String jwtSecret;

    public SecretStrengthValidator(Environment environment,
                                   @Value("${jwt.secret:}") String jwtSecret) {
        this.environment = environment;
        this.jwtSecret = jwtSecret;
    }

    @Override
    public void afterPropertiesSet() {
        boolean deployed = Arrays.stream(environment.getActiveProfiles())
                .anyMatch(profile -> profile.equals("staging")
                        || profile.equals("prod")
                        || profile.equals("production"));
        if (!deployed) {
            return;
        }
        if (jwtSecret == null || jwtSecret.isBlank()) {
            throw new IllegalStateException(
                    "JWT_SECRET must be set in a deployed environment (openssl rand -base64 48)");
        }
        if (jwtSecret.equals(DEV_ONLY_JWT_SECRET)) {
            throw new IllegalStateException(
                    "Refusing to start: JWT_SECRET is still the committed development-only secret. "
                            + "Rotate it with: openssl rand -base64 48");
        }
        log.info("Deployed-environment secret validation passed");
    }
}