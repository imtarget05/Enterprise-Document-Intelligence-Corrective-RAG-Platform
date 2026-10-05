package com.smartdocchat.service;

import com.smartdocchat.entity.PasswordResetToken;
import com.smartdocchat.entity.User;
import com.smartdocchat.repository.PasswordResetTokenRepository;
import com.smartdocchat.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class PasswordResetTokenService {

    public enum ConsumeResult {
        SUCCESS,
        INVALID_TOKEN,
        EXPIRED_TOKEN,
        ALREADY_USED
    }

    private final PasswordResetTokenRepository tokenRepository;
    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final PasswordResetDelivery passwordResetDelivery;
    private final AuditLogService auditLogService;

    @Value("${app.auth.reset-token-expiration-minutes:15}")
    private int tokenExpirationMinutes = 15;

    @Value("${app.auth.reset-url-prefix:http://localhost:3000/reset-password/confirm?token=}")
    private String resetUrlPrefix = "http://localhost:3000/reset-password/confirm?token=";

    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    public String generateRawToken() {
        byte[] bytes = new byte[32];
        SECURE_RANDOM.nextBytes(bytes);
        return HexFormat.of().formatHex(bytes);
    }

    public static String hashToken(String rawToken) {
        if (rawToken == null) {
            return "";
        }
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(rawToken.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 algorithm not available", e);
        }
    }

    @Transactional
    public String issue(User user, String requestIp) {
        String rawToken = generateRawToken();
        String hashedToken = hashToken(rawToken);

        PasswordResetToken resetToken = PasswordResetToken.builder()
                .user(user)
                .tokenHash(hashedToken)
                .expiresAt(LocalDateTime.now().plusMinutes(tokenExpirationMinutes))
                .requestIp(requestIp)
                .createdAt(LocalDateTime.now())
                .build();

        tokenRepository.save(resetToken);

        String resetUrl = resetUrlPrefix + rawToken;
        String recipientEmail = user.getEmail() != null && !user.getEmail().isBlank()
                ? user.getEmail()
                : user.getUsername();

        passwordResetDelivery.sendResetLink(recipientEmail, rawToken, resetUrl);

        log.info("Issued password reset token for user: {} (expires in {}m)",
                user.getUsername(), tokenExpirationMinutes);
        auditLogService.record(user.getUsername(), "auth.reset-password.request",
                "user", user.getUsername(), requestIp, "token_issued");

        return rawToken;
    }

    @Transactional
    public ConsumeResult consume(String rawToken, String newPassword, String requestIp) {
        if (rawToken == null || rawToken.isBlank() || newPassword == null || newPassword.isBlank()) {
            return ConsumeResult.INVALID_TOKEN;
        }

        String hashed = hashToken(rawToken);
        Optional<PasswordResetToken> tokenOpt = tokenRepository.findByTokenHash(hashed);
        if (tokenOpt.isEmpty()) {
            log.warn("Password reset confirm failed: token not found");
            return ConsumeResult.INVALID_TOKEN;
        }

        PasswordResetToken token = tokenOpt.get();

        // Constant time comparison to prevent timing attacks
        byte[] expectedHash = token.getTokenHash().getBytes(StandardCharsets.UTF_8);
        byte[] computedHash = hashed.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expectedHash, computedHash)) {
            return ConsumeResult.INVALID_TOKEN;
        }

        if (token.isUsed()) {
            log.warn("Password reset confirm failed: token already used for user {}",
                    token.getUser().getUsername());
            auditLogService.record(token.getUser().getUsername(), "auth.reset-password.confirm",
                    "user", token.getUser().getUsername(), requestIp, "token_already_used");
            return ConsumeResult.ALREADY_USED;
        }

        if (token.isExpired()) {
            log.warn("Password reset confirm failed: token expired for user {}",
                    token.getUser().getUsername());
            auditLogService.record(token.getUser().getUsername(), "auth.reset-password.confirm",
                    "user", token.getUser().getUsername(), requestIp, "token_expired");
            return ConsumeResult.EXPIRED_TOKEN;
        }

        User user = token.getUser();
        user.setPassword(passwordEncoder.encode(newPassword));
        userRepository.save(user);

        token.setUsedAt(LocalDateTime.now());
        tokenRepository.save(token);

        log.info("Password reset successfully completed for user: {}", user.getUsername());
        auditLogService.record(user.getUsername(), "auth.reset-password.confirm",
                "user", user.getUsername(), requestIp, "success");

        return ConsumeResult.SUCCESS;
    }
}
