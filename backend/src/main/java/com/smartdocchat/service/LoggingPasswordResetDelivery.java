package com.smartdocchat.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@ConditionalOnMissingBean(SmtpPasswordResetDelivery.class)
public class LoggingPasswordResetDelivery implements PasswordResetDelivery {

    @Override
    public void sendResetLink(String email, String rawToken, String resetUrl) {
        log.info("PASSWORD RESET DISPATCH [DEV/TEST MODE] -> To: {} | Reset URL: {} | Raw Token: {}",
                email, resetUrl, rawToken);
    }
}
