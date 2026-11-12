package com.smartdocchat.config;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class SecretStrengthValidatorTest {

    private static final String STRONG_SECRET = "YTI4YjQ1NzQ1NmE4YjQ1NzQ1NmE4YjQ1NzQ1NmE4YjQ1NzQ1NmE4YjQ=";

    private SecretStrengthValidator validator(String profile, String secret) {
        MockEnvironment env = new MockEnvironment();
        env.setActiveProfiles(profile);
        return new SecretStrengthValidator(env, secret);
    }

    @Test
    void committedDevSecretIsRejectedInProduction() {
        assertThrows(IllegalStateException.class,
                () -> validator("production", SecretStrengthValidator.DEV_ONLY_JWT_SECRET).afterPropertiesSet());
    }

    @Test
    void committedDevSecretIsRejectedInProdProfile() {
        assertThrows(IllegalStateException.class,
                () -> validator("prod", SecretStrengthValidator.DEV_ONLY_JWT_SECRET).afterPropertiesSet());
    }

    @Test
    void committedDevSecretIsRejectedInStaging() {
        assertThrows(IllegalStateException.class,
                () -> validator("staging", SecretStrengthValidator.DEV_ONLY_JWT_SECRET).afterPropertiesSet());
    }

    @Test
    void blankSecretIsRejectedInDeployedProfiles() {
        assertThrows(IllegalStateException.class,
                () -> validator("production", "").afterPropertiesSet());
        assertThrows(IllegalStateException.class,
                () -> validator("prod", "").afterPropertiesSet());
        assertThrows(IllegalStateException.class,
                () -> validator("staging", "  ").afterPropertiesSet());
    }

    @Test
    void strongSecretIsAcceptedInProduction() {
        assertDoesNotThrow(() -> validator("production", STRONG_SECRET).afterPropertiesSet());
    }

    @Test
    void strongSecretIsAcceptedInProdProfile() {
        assertDoesNotThrow(() -> validator("prod", STRONG_SECRET).afterPropertiesSet());
    }

    @Test
    void devSecretIsAllowedInLocalProfiles() {
        assertDoesNotThrow(() -> validator("local", SecretStrengthValidator.DEV_ONLY_JWT_SECRET).afterPropertiesSet());
        assertDoesNotThrow(() -> validator("default", SecretStrengthValidator.DEV_ONLY_JWT_SECRET).afterPropertiesSet());
    }
}