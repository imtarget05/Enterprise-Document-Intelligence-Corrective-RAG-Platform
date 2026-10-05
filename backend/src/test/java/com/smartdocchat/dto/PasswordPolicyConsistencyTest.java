package com.smartdocchat.dto;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Guards against password-policy drift between registration and password
 * reset. Historically register required 12 characters while reset-confirm only
 * required 6, so an attacker with a leaked reset token could set a password far
 * weaker than the registration policy allows — silently downgrading account
 * security. These tests fail if the two policies ever diverge again.
 */
class PasswordPolicyConsistencyTest {

    private static Validator validator;

    @BeforeAll
    static void setUp() {
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            validator = factory.getValidator();
        }
    }

    /** Shortest password length {@code RegisterRequest} accepts. */
    private static int registerMinPasswordLength() {
        for (int len = 1; len <= 100; len++) {
            RegisterRequest dto = RegisterRequest.builder()
                    .username("alice").password("a".repeat(len)).email("a@b.co").build();
            if (passwordViolations(dto).isEmpty()) {
                return len;
            }
        }
        return 101;
    }

    /** Shortest password length {@code ResetPasswordConfirmRequest} accepts. */
    private static int resetMinPasswordLength() {
        for (int len = 1; len <= 100; len++) {
            ResetPasswordConfirmRequest dto = ResetPasswordConfirmRequest.builder()
                    .token("valid-token").newPassword("a".repeat(len)).build();
            if (passwordViolations(dto).isEmpty()) {
                return len;
            }
        }
        return 101;
    }

    private static Set<ConstraintViolation<RegisterRequest>> passwordViolations(RegisterRequest dto) {
        return validator.validate(dto).stream()
                .filter(v -> v.getPropertyPath().toString().equals("password"))
                .collect(Collectors.toSet());
    }

    private static Set<ConstraintViolation<ResetPasswordConfirmRequest>> passwordViolations(
            ResetPasswordConfirmRequest dto) {
        return validator.validate(dto).stream()
                .filter(v -> v.getPropertyPath().toString().equals("newPassword"))
                .collect(Collectors.toSet());
    }

    @Test
    void resetConfirmAcceptsNothingShorterThanRegistration() {
        int registerMin = registerMinPasswordLength();
        int resetMin = resetMinPasswordLength();

        // Guard against a vacuous pass: the probe must actually find an
        // accepted length, not bail out at the loop ceiling.
        assertTrue(registerMin < 101, "Register probe never found an accepted password length");
        assertTrue(resetMin < 101, "Reset probe never found an accepted password length");

        assertTrue(registerMin >= 12,
                "Registration password minimum drifted below 12: " + registerMin);
        assertTrue(resetMin >= 12,
                "Reset password minimum (" + resetMin + ") is weaker than the "
                        + "12-character registration policy");
        assertFalse(resetMin < registerMin,
                "Password reset (" + resetMin + ") accepts weaker passwords than "
                        + "registration (" + registerMin + ")");
    }

    @Test
    void resetConfirmRequiresToken() {
        Set<ConstraintViolation<ResetPasswordConfirmRequest>> violations =
                validator.validate(ResetPasswordConfirmRequest.builder()
                        .token("")
                        .newPassword("StrongEnoughPass123")
                        .build());

        assertTrue(violations.stream()
                        .anyMatch(v -> v.getPropertyPath().toString().equals("token")),
                "Reset confirm must require a token — that is the proof of ownership");
    }

    @Test
    void resetConfirmAcceptsARegistrationStrengthPassword() {
        Set<ConstraintViolation<ResetPasswordConfirmRequest>> violations =
                validator.validate(ResetPasswordConfirmRequest.builder()
                        .token("valid-token")
                        .newPassword("StrongEnoughPass123")
                        .build());

        assertTrue(violations.isEmpty(),
                "Expected no violations but got: " + violations);
    }
}
