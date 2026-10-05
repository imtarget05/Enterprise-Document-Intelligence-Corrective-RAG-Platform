package com.smartdocchat.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@ConditionalOnProperty(prefix = "spring.mail", name = "host")
@RequiredArgsConstructor
public class SmtpPasswordResetDelivery implements PasswordResetDelivery {

    private final JavaMailSender mailSender;

    @Value("${spring.mail.username:noreply@smartdocchat.com}")
    private String fromAddress;

    @Override
    public void sendResetLink(String email, String rawToken, String resetUrl) {
        try {
            SimpleMailMessage message = new SimpleMailMessage();
            message.setFrom(fromAddress);
            message.setTo(email);
            message.setSubject("Password Reset Request - Smart Document Chatbot");
            message.setText("Hello,\n\nYou requested a password reset. Click the link below or enter the token to reset your password:\n\n"
                    + resetUrl + "\n\nThis link expires in 15 minutes. If you did not request this reset, please ignore this email.\n");
            mailSender.send(message);
            log.info("Sent password reset email via SMTP to {}", email);
        } catch (Exception e) {
            log.error("Failed to send password reset email to {}: {}", email, e.getMessage(), e);
            throw new RuntimeException("Failed to send password reset email", e);
        }
    }
}
