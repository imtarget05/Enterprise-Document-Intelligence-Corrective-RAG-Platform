package com.smartdocchat.repository;

import com.smartdocchat.entity.PasswordResetToken;
import com.smartdocchat.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.Optional;

@Repository
public interface PasswordResetTokenRepository extends JpaRepository<PasswordResetToken, Long> {
    Optional<PasswordResetToken> findByTokenHash(String tokenHash);

    Optional<PasswordResetToken> findByTokenHashAndUsedAtIsNullAndExpiresAtAfter(
            String tokenHash, LocalDateTime now);

    java.util.List<PasswordResetToken> findAllByUserAndUsedAtIsNull(User user);
}
