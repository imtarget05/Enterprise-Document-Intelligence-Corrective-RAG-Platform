package com.smartdocchat.controller;

import com.smartdocchat.dto.AuthRequest;
import com.smartdocchat.dto.AuthResponse;
import com.smartdocchat.dto.RegisterRequest;
import com.smartdocchat.dto.ResetPasswordConfirmRequest;
import com.smartdocchat.dto.ResetPasswordRequest;
import com.smartdocchat.entity.Role;
import com.smartdocchat.entity.User;
import com.smartdocchat.repository.UserRepository;
import com.smartdocchat.service.AuditLogService;
import com.smartdocchat.service.LoginAuditService;
import com.smartdocchat.service.PasswordResetTokenService;
import com.smartdocchat.util.JwtTokenProvider;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.security.Principal;
import java.util.Map;

@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
@Slf4j
public class AuthController {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider tokenProvider;
    private final LoginAuditService loginAuditService;
    private final AuditLogService auditLogService;
    private final PasswordResetTokenService passwordResetTokenService;
    private final Environment env;

    private static final String JWT_COOKIE_NAME = "jwt_token";
    private static final int JWT_COOKIE_MAX_AGE_SECONDS = 86400;

    @org.springframework.beans.factory.annotation.Value("${oauth2.client-id:}")
    private String googleClientId;

    /**
     * Public endpoint exposing the Google OAuth client ID so the SPA can
     * initialize Google Identity Services (popup flow).
     */
    @GetMapping("/google-client-id")
    public ResponseEntity<?> googleClientId() {
        if (googleClientId == null || googleClientId.isBlank()) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(java.util.Map.of("clientId", ""));
        }
        return ResponseEntity.ok(java.util.Map.of("clientId", googleClientId));
    }

    /**
     * Google Identity Services sign-in: verifies the ID token issued by the
     * GIS popup client-side, then issues the standard app JWT. Unlike the
     * redirect flow this does not depend on Google session cookies, which
     * Safari's ITP breaks (chooser loop).
     */
    @PostMapping("/google")
    public ResponseEntity<?> googleLogin(@RequestBody java.util.Map<String, String> body,
                                         HttpServletRequest request,
                                         HttpServletResponse response) {
        String idToken = body == null ? null : body.get("credential");
        if (idToken == null || idToken.isBlank()) {
            return ResponseEntity.badRequest().body("Missing Google credential");
        }

        java.util.Map<String, Object> info;
        try {
            java.net.http.HttpClient client = java.net.http.HttpClient.newHttpClient();
            java.net.http.HttpRequest req = java.net.http.HttpRequest.newBuilder()
                    .uri(java.net.URI.create(
                            "https://oauth2.googleapis.com/tokeninfo?id_token=" + idToken))
                    .GET().build();
            java.net.http.HttpResponse<String> resp =
                    client.send(req, java.net.http.HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) {
                return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Invalid Google token");
            }
            info = new com.fasterxml.jackson.databind.ObjectMapper()
                    .readValue(resp.body(), new com.fasterxml.jackson.core.type.TypeReference<>() {});
        } catch (Exception e) {
            log.warn("Google tokeninfo verification failed: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Google verification failed");
        }

        // Verify audience, expiry and email verification
        String aud = String.valueOf(info.get("aud"));
        if (googleClientId.isBlank() || !googleClientId.equals(aud)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Google token audience mismatch");
        }
        if (!Boolean.parseBoolean(String.valueOf(info.get("email_verified")))) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Google email not verified");
        }
        long exp = Long.parseLong(String.valueOf(info.getOrDefault("exp", "0")));
        if (System.currentTimeMillis() / 1000 >= exp) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Google token expired");
        }

        String email = String.valueOf(info.get("email"));
        User user = userRepository.findByUsername(email).orElseGet(() -> {
            User created = User.builder()
                    .username(email)
                    .password(passwordEncoder.encode(java.util.UUID.randomUUID().toString()))
                    .email(email)
                    .role(Role.ROLE_USER)
                    .enabled(true)
                    .build();
            return userRepository.save(created);
        });

        String token = tokenProvider.generateToken(user.getUsername(), user.getRole().name());
        auditLogService.record(user.getUsername(), "auth.login.google", "user",
                user.getUsername(), getClientIp(request), "success");

        Cookie jwtCookie = new Cookie(JWT_COOKIE_NAME, token);
        jwtCookie.setHttpOnly(true);
        jwtCookie.setPath("/");
        jwtCookie.setMaxAge(JWT_COOKIE_MAX_AGE_SECONDS);
        jwtCookie.setAttribute("SameSite", "Lax");
        jwtCookie.setSecure(isSecureCookie(request));
        response.addCookie(jwtCookie);

        return ResponseEntity.ok(AuthResponse.builder()
                .token(resolveResponseToken(token))
                .username(user.getUsername())
                .role(user.getRole().name())
                .build());
    }

    @PostMapping("/register")
    public ResponseEntity<?> registerUser(@Valid @RequestBody RegisterRequest registerRequest) {
        log.info("Registering user: {}", registerRequest.getUsername());

        if (userRepository.existsByUsername(registerRequest.getUsername())) {
            return ResponseEntity
                    .status(HttpStatus.BAD_REQUEST)
                    .body("Username is already taken!");
        }

        User user = User.builder()
                .username(registerRequest.getUsername())
                .password(passwordEncoder.encode(registerRequest.getPassword()))
                .email(registerRequest.getEmail())
                .role(Role.ROLE_USER)
                .enabled(true)
                .build();

        userRepository.save(user);

        String token = tokenProvider.generateToken(user.getUsername(), user.getRole().name());
        return ResponseEntity.ok(AuthResponse.builder()
                .token(resolveResponseToken(token))
                .username(user.getUsername())
                .role(user.getRole().name())
                .build());
    }

    @PostMapping("/login")
    public ResponseEntity<?> authenticateUser(
            @Valid @RequestBody AuthRequest authRequest,
            HttpServletRequest request,
            HttpServletResponse response) {

        String clientIp = getClientIp(request);
        String username = authRequest.getUsername();
        log.info("Authenticating user: {} from ip: {}", username, clientIp);

        if (loginAuditService.isAccountLocked(username)) {
            log.warn("Login attempt for locked account: {}", username);
            return ResponseEntity
                    .status(HttpStatus.TOO_MANY_REQUESTS)
                    .body("Account temporarily locked due to multiple failed login attempts. Please try again later.");
        }

        return userRepository.findByUsername(username)
                .filter(User::getEnabled)
                .filter(user -> passwordEncoder.matches(authRequest.getPassword(), user.getPassword()))
                .<ResponseEntity<?>>map(user -> {
                    loginAuditService.recordSuccess(username, clientIp);
                    auditLogService.record(username, "auth.login", "user", username, clientIp, "success");

                    String token = tokenProvider.generateToken(user.getUsername(), user.getRole().name());

                    Cookie jwtCookie = new Cookie(JWT_COOKIE_NAME, token);
                    jwtCookie.setHttpOnly(true);
                    jwtCookie.setPath("/");
                    jwtCookie.setMaxAge(JWT_COOKIE_MAX_AGE_SECONDS);
                    jwtCookie.setAttribute("SameSite", "Lax");
                    jwtCookie.setSecure(isSecureCookie(request));
                    response.addCookie(jwtCookie);

                    return ResponseEntity.ok(AuthResponse.builder()
                            .token(resolveResponseToken(token))
                            .username(user.getUsername())
                            .role(user.getRole().name())
                            .build());
                })
                .orElseGet(() -> {
                    loginAuditService.recordFailure(username, clientIp);
                    auditLogService.record(username, "auth.login.failed", "user", username, clientIp, "invalid credentials");
                    return ResponseEntity
                            .status(HttpStatus.UNAUTHORIZED)
                            .body("Invalid username or password");
                });
    }

    @PostMapping("/logout")
    public ResponseEntity<?> logout(HttpServletRequest request, HttpServletResponse response) {
        Cookie jwtCookie = new Cookie(JWT_COOKIE_NAME, null);
        jwtCookie.setHttpOnly(true);
        jwtCookie.setPath("/");
        jwtCookie.setMaxAge(0);
        jwtCookie.setAttribute("SameSite", "Lax");
        jwtCookie.setSecure(isSecureCookie(request));
        response.addCookie(jwtCookie);
        return ResponseEntity.ok("Logged out successfully");
    }

    @GetMapping("/me")
    public ResponseEntity<?> getCurrentUser(Principal principal) {
        if (principal == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }
        return userRepository.findByUsername(principal.getName())
                .filter(User::getEnabled)
                .map(user -> ResponseEntity.ok(Map.of(
                        "username", user.getUsername(),
                        "role", user.getRole().name(),
                        "email", user.getEmail() != null ? user.getEmail() : ""
                )))
                .orElse(ResponseEntity.status(HttpStatus.UNAUTHORIZED).build());
    }

    @PostMapping("/reset-password/request")
    public ResponseEntity<?> requestPasswordReset(@Valid @RequestBody ResetPasswordRequest req, HttpServletRequest request) {
        String clientIp = getClientIp(request);
        if (loginAuditService.isPasswordResetRateLimited(clientIp)
                || (req.getEmail() != null && loginAuditService.isPasswordResetRateLimited(req.getEmail()))) {
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                    .body("Too many password reset requests. Please try again later.");
        }

        loginAuditService.recordPasswordResetAttempt(clientIp);
        if (req.getEmail() != null) {
            loginAuditService.recordPasswordResetAttempt(req.getEmail());
        }

        var userOpt = userRepository.findByUsername(req.getEmail());
        if (userOpt.isEmpty()) {
            userOpt = userRepository.findByEmail(req.getEmail());
        }

        if (userOpt.isPresent()) {
            User user = userOpt.get();
            if (Boolean.TRUE.equals(user.getEnabled())) {
                passwordResetTokenService.issue(user, clientIp);
            }
        } else {
            auditLogService.record("anonymous", "auth.reset-password.request", "user", req.getEmail(), clientIp, "user_not_found");
        }

        // Generic response to prevent user enumeration
        return ResponseEntity.ok(Map.of(
                "message", "If an account exists, a reset link has been sent"
        ));
    }

    @PostMapping("/reset-password/confirm")
    public ResponseEntity<?> confirmPasswordReset(@Valid @RequestBody ResetPasswordConfirmRequest req, HttpServletRequest request) {
        String clientIp = getClientIp(request);
        if (loginAuditService.isPasswordResetRateLimited(clientIp)) {
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                    .body("Too many attempts. Please try again later.");
        }

        PasswordResetTokenService.ConsumeResult result =
                passwordResetTokenService.consume(req.getToken(), req.getNewPassword(), clientIp);

        return switch (result) {
            case SUCCESS -> ResponseEntity.ok(Map.of("message", "Password has been reset successfully"));
            case EXPIRED_TOKEN -> {
                loginAuditService.recordPasswordResetAttempt(clientIp);
                yield ResponseEntity.status(HttpStatus.BAD_REQUEST).body("Reset token has expired");
            }
            case ALREADY_USED -> {
                loginAuditService.recordPasswordResetAttempt(clientIp);
                yield ResponseEntity.status(HttpStatus.BAD_REQUEST).body("Reset token has already been used");
            }
            case INVALID_TOKEN -> {
                loginAuditService.recordPasswordResetAttempt(clientIp);
                yield ResponseEntity.status(HttpStatus.BAD_REQUEST).body("Invalid reset token");
            }
        };
    }

    private boolean isSecureCookie(HttpServletRequest request) {
        if ("https".equalsIgnoreCase(request.getHeader("X-Forwarded-Proto"))) {
            return true;
        }
        if (request.isSecure()) {
            return true;
        }
        if (env != null && env.getActiveProfiles() != null && java.util.Arrays.asList(env.getActiveProfiles()).contains("prod")) {
            return true;
        }
        return false;
    }

    private String resolveResponseToken(String token) {
        if (env != null && env.getActiveProfiles() != null && java.util.Arrays.asList(env.getActiveProfiles()).contains("prod")) {
            return null;
        }
        return token;
    }

    private String getClientIp(HttpServletRequest request) {
        String xfHeader = request.getHeader("X-Forwarded-For");
        if (xfHeader != null && !xfHeader.isBlank()) {
            return xfHeader.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
