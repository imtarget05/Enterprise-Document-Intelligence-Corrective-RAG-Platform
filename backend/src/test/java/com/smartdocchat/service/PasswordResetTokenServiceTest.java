package com.smartdocchat.service;

import com.smartdocchat.entity.PasswordResetToken;
import com.smartdocchat.entity.Role;
import com.smartdocchat.entity.User;
import com.smartdocchat.repository.PasswordResetTokenRepository;
import com.smartdocchat.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.time.LocalDateTime;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class PasswordResetTokenServiceTest {

    @Mock private PasswordResetTokenRepository tokenRepository;
    @Mock private UserRepository userRepository;
    @Mock private PasswordEncoder passwordEncoder;
    @Mock private PasswordResetDelivery passwordResetDelivery;
    @Mock private AuditLogService auditLogService;

    private PasswordResetTokenService service;

    @BeforeEach
    void setUp() {
        service = new PasswordResetTokenService(
                tokenRepository,
                userRepository,
                passwordEncoder,
                passwordResetDelivery,
                auditLogService
        );
    }

    private User sampleUser() {
        return User.builder()
                .id(42L)
                .username("john_doe")
                .email("john@example.com")
                .password("old-hashed-pass")
                .role(Role.ROLE_USER)
                .enabled(true)
                .build();
    }

    @Test
    void issueGeneratesTokenSavesHashedTokenAndCallsDelivery() {
        User user = sampleUser();

        String rawToken = service.issue(user, "10.0.0.5");

        assertNotNull(rawToken);
        assertEquals(64, rawToken.length()); // 32 bytes hex = 64 chars

        ArgumentCaptor<PasswordResetToken> tokenCaptor = ArgumentCaptor.forClass(PasswordResetToken.class);
        verify(tokenRepository).save(tokenCaptor.capture());

        PasswordResetToken savedToken = tokenCaptor.getValue();
        assertEquals(user, savedToken.getUser());
        assertEquals("10.0.0.5", savedToken.getRequestIp());
        assertEquals(PasswordResetTokenService.hashToken(rawToken), savedToken.getTokenHash());
        assertTrue(savedToken.getExpiresAt().isAfter(LocalDateTime.now()));
        assertNull(savedToken.getUsedAt());

        verify(passwordResetDelivery).sendResetLink(eq("john@example.com"), eq(rawToken), anyString());
    }

    @Test
    void consumeSucceedsForValidUnexpiredToken() {
        User user = sampleUser();
        String rawToken = service.generateRawToken();
        String hash = PasswordResetTokenService.hashToken(rawToken);

        PasswordResetToken resetToken = PasswordResetToken.builder()
                .id(1L)
                .user(user)
                .tokenHash(hash)
                .expiresAt(LocalDateTime.now().plusMinutes(10))
                .createdAt(LocalDateTime.now().minusMinutes(5))
                .build();

        when(tokenRepository.findByTokenHash(hash)).thenReturn(Optional.of(resetToken));
        when(passwordEncoder.encode("NewSecret123!")).thenReturn("new-encoded-hash");

        PasswordResetTokenService.ConsumeResult result = service.consume(rawToken, "NewSecret123!", "10.0.0.5");

        assertEquals(PasswordResetTokenService.ConsumeResult.SUCCESS, result);
        assertEquals("new-encoded-hash", user.getPassword());
        assertNotNull(resetToken.getUsedAt());
        verify(userRepository).save(user);
        verify(tokenRepository).save(resetToken);
    }

    @Test
    void consumeFailsForUnknownToken() {
        String rawToken = "unknown-token";
        String hash = PasswordResetTokenService.hashToken(rawToken);

        when(tokenRepository.findByTokenHash(hash)).thenReturn(Optional.empty());

        PasswordResetTokenService.ConsumeResult result = service.consume(rawToken, "NewSecret123!", "10.0.0.5");

        assertEquals(PasswordResetTokenService.ConsumeResult.INVALID_TOKEN, result);
        verify(userRepository, never()).save(any(User.class));
    }

    @Test
    void consumeFailsForExpiredToken() {
        User user = sampleUser();
        String rawToken = service.generateRawToken();
        String hash = PasswordResetTokenService.hashToken(rawToken);

        PasswordResetToken resetToken = PasswordResetToken.builder()
                .id(1L)
                .user(user)
                .tokenHash(hash)
                .expiresAt(LocalDateTime.now().minusMinutes(1)) // Expired
                .createdAt(LocalDateTime.now().minusMinutes(20))
                .build();

        when(tokenRepository.findByTokenHash(hash)).thenReturn(Optional.of(resetToken));

        PasswordResetTokenService.ConsumeResult result = service.consume(rawToken, "NewSecret123!", "10.0.0.5");

        assertEquals(PasswordResetTokenService.ConsumeResult.EXPIRED_TOKEN, result);
        verify(userRepository, never()).save(any(User.class));
    }

    @Test
    void consumeFailsForAlreadyUsedToken() {
        User user = sampleUser();
        String rawToken = service.generateRawToken();
        String hash = PasswordResetTokenService.hashToken(rawToken);

        PasswordResetToken resetToken = PasswordResetToken.builder()
                .id(1L)
                .user(user)
                .tokenHash(hash)
                .expiresAt(LocalDateTime.now().plusMinutes(10))
                .usedAt(LocalDateTime.now().minusMinutes(2)) // Already used
                .createdAt(LocalDateTime.now().minusMinutes(5))
                .build();

        when(tokenRepository.findByTokenHash(hash)).thenReturn(Optional.of(resetToken));

        PasswordResetTokenService.ConsumeResult result = service.consume(rawToken, "NewSecret123!", "10.0.0.5");

        assertEquals(PasswordResetTokenService.ConsumeResult.ALREADY_USED, result);
        verify(userRepository, never()).save(any(User.class));
    }
}
