package com.smartdocchat.service;

public interface PasswordResetDelivery {
    void sendResetLink(String email, String rawToken, String resetUrl);
}
