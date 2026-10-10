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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.security.Principal;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AuthControllerTest {

    @Mock private UserRepository userRepository;
    @Mock private PasswordEncoder passwordEncoder;
    @Mock private JwtTokenProvider tokenProvider;
    @Mock private LoginAuditService loginAuditService;
    @Mock private AuditLogService auditLogService;
    @Mock private PasswordResetTokenService passwordResetTokenService;
    @Mock private Environment env;

    private AuthController controller;

    @BeforeEach
    void setUp() {
        controller = new AuthController(
                userRepository,
                passwordEncoder,
                tokenProvider,
                loginAuditService,
                auditLogService,
                passwordResetTokenService,
                env
        );
    }

    private AuthRequest request(String username, String password) {
        return AuthRequest.builder().username(username).password(password).build();
    }

    private RegisterRequest registerRequest(String username, String password, String email) {
        return RegisterRequest.builder().username(username).password(password).email(email).build();
    }

    private User enabledUser(String username, String encoded) {
        return User.builder().username(username).password(encoded).role(Role.ROLE_USER).enabled(true).build();
    }

    @Test
    void registerCreatesUserAndReturnsToken() {
        when(userRepository.existsByUsername("alice")).thenReturn(false);
        when(passwordEncoder.encode("password123456")).thenReturn("encoded");
        when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));
        when(tokenProvider.generateToken("alice", "ROLE_USER")).thenReturn("jwt-token");

        ResponseEntity<?> response = controller.registerUser(registerRequest("alice", "password123456", "alice@example.com"));

        assertEquals(HttpStatus.OK, response.getStatusCode());
        AuthResponse body = (AuthResponse) response.getBody();
        assertNotNull(body);
        assertEquals("jwt-token", body.getToken());
        assertEquals("alice", body.getUsername());
        assertEquals("ROLE_USER", body.getRole());
    }

    @Test
    void registerRejectsDuplicateUsername() {
        when(userRepository.existsByUsername("alice")).thenReturn(true);

        ResponseEntity<?> response = controller.registerUser(registerRequest("alice", "password123456", "alice@example.com"));

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertEquals("Username is already taken!", response.getBody());
    }

    @Test
    void loginSucceedsAndSetsHttpOnlyCookie() {
        when(userRepository.findByUsername("bob")).thenReturn(Optional.of(enabledUser("bob", "encoded")));
        when(passwordEncoder.matches("password123456", "encoded")).thenReturn(true);
        when(tokenProvider.generateToken("bob", "ROLE_USER")).thenReturn("jwt-cookie");

        MockHttpServletRequest servletRequest = new MockHttpServletRequest();
        servletRequest.setRemoteAddr("10.0.0.9");
        MockHttpServletResponse servletResponse = new MockHttpServletResponse();
        ResponseEntity<?> response =
                controller.authenticateUser(request("bob", "password123456"), servletRequest, servletResponse);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("jwt-cookie", ((AuthResponse) response.getBody()).getToken());
        verify(loginAuditService).recordSuccess("bob", "10.0.0.9");
        assertEquals("jwt-cookie", servletResponse.getCookie("jwt_token").getValue());
        assertTrue(servletResponse.getCookie("jwt_token").isHttpOnly());
        assertEquals("Lax", servletResponse.getCookie("jwt_token").getAttribute("SameSite"));
    }

    @Test
    void productionLoginSetsCrossSiteSecureCookieForPages() {
        when(userRepository.findByUsername("bob")).thenReturn(Optional.of(enabledUser("bob", "encoded")));
        when(passwordEncoder.matches("password123456", "encoded")).thenReturn(true);
        when(tokenProvider.generateToken("bob", "ROLE_USER")).thenReturn("jwt-cookie");
        when(env.getActiveProfiles()).thenReturn(new String[]{"prod"});

        MockHttpServletRequest servletRequest = new MockHttpServletRequest();
        MockHttpServletResponse servletResponse = new MockHttpServletResponse();
        ResponseEntity<?> response = controller.authenticateUser(
                request("bob", "password123456"), servletRequest, servletResponse);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertTrue(servletResponse.getCookie("jwt_token").getSecure());
        assertEquals("None", servletResponse.getCookie("jwt_token").getAttribute("SameSite"));
    }

    @Test
    void loginFailsWhenAccountLocked() {
        when(loginAuditService.isAccountLocked("bob")).thenReturn(true);

        MockHttpServletRequest request = new MockHttpServletRequest();
        ResponseEntity<?> response =
                controller.authenticateUser(request("bob", "password123456"), request, new MockHttpServletResponse());

        assertEquals(HttpStatus.TOO_MANY_REQUESTS, response.getStatusCode());
    }

    @Test
    void loginUsesForwardedForHeaderWhenPresent() {
        when(userRepository.findByUsername("bob")).thenReturn(Optional.of(enabledUser("bob", "encoded")));
        when(passwordEncoder.matches("password123456", "encoded")).thenReturn(false);

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-Forwarded-For", "203.0.113.7, 10.0.0.1");
        ResponseEntity<?> response =
                controller.authenticateUser(request("bob", "password123456"), request, new MockHttpServletResponse());

        assertEquals(HttpStatus.UNAUTHORIZED, response.getStatusCode());
        verify(loginAuditService).recordFailure("bob", "203.0.113.7");
    }

    @Test
    void loginRejectsDisabledUser() {
        when(userRepository.findByUsername("bob"))
                .thenReturn(Optional.of(User.builder().username("bob").password("encoded")
                        .role(Role.ROLE_USER).enabled(false).build()));

        ResponseEntity<?> response = controller.authenticateUser(
                request("bob", "password123456"), new MockHttpServletRequest(), new MockHttpServletResponse());

        assertEquals(HttpStatus.UNAUTHORIZED, response.getStatusCode());
        verify(loginAuditService).recordFailure(eq("bob"), anyString());
    }

    @Test
    void loginRecordsFailureOnBadCredentials() {
        when(userRepository.findByUsername("bob")).thenReturn(Optional.of(enabledUser("bob", "encoded")));
        when(passwordEncoder.matches("wrong-password", "encoded")).thenReturn(false);

        ResponseEntity<?> response = controller.authenticateUser(
                request("bob", "wrong-password"), new MockHttpServletRequest(), new MockHttpServletResponse());

        assertEquals(HttpStatus.UNAUTHORIZED, response.getStatusCode());
        assertEquals("Invalid username or password", response.getBody());
        verify(loginAuditService).recordFailure(eq("bob"), anyString());
    }

    @Test
    void logoutClearsCookie() {
        MockHttpServletRequest servletRequest = new MockHttpServletRequest("POST", "/auth/logout");
        MockHttpServletResponse servletResponse = new MockHttpServletResponse();

        ResponseEntity<?> response = controller.logout(servletRequest, servletResponse);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("Logged out successfully", response.getBody());
        assertEquals(0, servletResponse.getCookie("jwt_token").getMaxAge());
        assertNull(servletResponse.getCookie("jwt_token").getValue());
    }

    @Test
    void getCurrentUserReturnsUserDataWhenAuthenticated() {
        Principal principal = () -> "alice";
        User user = enabledUser("alice", "encoded-pass");
        user.setEmail("alice@example.com");
        when(userRepository.findByUsername("alice")).thenReturn(Optional.of(user));

        ResponseEntity<?> response = controller.getCurrentUser(principal);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) response.getBody();
        assertNotNull(body);
        assertEquals("alice", body.get("username"));
        assertEquals("ROLE_USER", body.get("role"));
        assertEquals("alice@example.com", body.get("email"));
    }

    @Test
    void getCurrentUserReturnsUnauthorizedWhenPrincipalNull() {
        ResponseEntity<?> response = controller.getCurrentUser(null);
        assertEquals(HttpStatus.UNAUTHORIZED, response.getStatusCode());
    }

    @Test
    void requestPasswordResetIssuesTokenForExistingUser() {
        User user = enabledUser("alice", "encoded-pass");
        user.setEmail("alice@example.com");
        when(userRepository.findByUsername("alice@example.com")).thenReturn(Optional.empty());
        when(userRepository.findByEmail("alice@example.com")).thenReturn(Optional.of(user));

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("192.168.1.100");

        ResetPasswordRequest req = ResetPasswordRequest.builder().email("alice@example.com").build();
        ResponseEntity<?> response = controller.requestPasswordReset(req, request);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        verify(passwordResetTokenService).issue(user, "192.168.1.100");
    }

    @Test
    void requestPasswordResetReturnsGenericSuccessEvenIfUserNotFound() {
        when(userRepository.findByUsername("ghost@example.com")).thenReturn(Optional.empty());
        when(userRepository.findByEmail("ghost@example.com")).thenReturn(Optional.empty());

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("192.168.1.100");

        ResetPasswordRequest req = ResetPasswordRequest.builder().email("ghost@example.com").build();
        ResponseEntity<?> response = controller.requestPasswordReset(req, request);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        verify(passwordResetTokenService, never()).issue(any(User.class), anyString());
    }

    @Test
    void requestPasswordResetRejectsRateLimitedIp() {
        when(loginAuditService.isPasswordResetRateLimited("192.168.1.100")).thenReturn(true);

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("192.168.1.100");

        ResetPasswordRequest req = ResetPasswordRequest.builder().email("alice@example.com").build();
        ResponseEntity<?> response = controller.requestPasswordReset(req, request);

        assertEquals(HttpStatus.TOO_MANY_REQUESTS, response.getStatusCode());
    }

    @Test
    void confirmPasswordResetSucceedsWithValidToken() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("192.168.1.100");

        ResetPasswordConfirmRequest req = ResetPasswordConfirmRequest.builder()
                .token("valid-raw-token")
                .newPassword("NewSecureP@ss123")
                .build();

        when(passwordResetTokenService.consume("valid-raw-token", "NewSecureP@ss123", "192.168.1.100"))
                .thenReturn(PasswordResetTokenService.ConsumeResult.SUCCESS);

        ResponseEntity<?> response = controller.confirmPasswordReset(req, request);

        assertEquals(HttpStatus.OK, response.getStatusCode());
    }

    @Test
    void confirmPasswordResetRejectsExpiredToken() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("192.168.1.100");

        ResetPasswordConfirmRequest req = ResetPasswordConfirmRequest.builder()
                .token("expired-raw-token")
                .newPassword("NewSecureP@ss123")
                .build();

        when(passwordResetTokenService.consume("expired-raw-token", "NewSecureP@ss123", "192.168.1.100"))
                .thenReturn(PasswordResetTokenService.ConsumeResult.EXPIRED_TOKEN);

        ResponseEntity<?> response = controller.confirmPasswordReset(req, request);

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertEquals("Reset token has expired", response.getBody());
    }

    @Test
    void confirmPasswordResetRejectsAlreadyUsedToken() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("192.168.1.100");

        ResetPasswordConfirmRequest req = ResetPasswordConfirmRequest.builder()
                .token("used-raw-token")
                .newPassword("NewSecureP@ss123")
                .build();

        when(passwordResetTokenService.consume("used-raw-token", "NewSecureP@ss123", "192.168.1.100"))
                .thenReturn(PasswordResetTokenService.ConsumeResult.ALREADY_USED);

        ResponseEntity<?> response = controller.confirmPasswordReset(req, request);

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertEquals("Reset token has already been used", response.getBody());
    }

    @Test
    void confirmPasswordResetRejectsInvalidToken() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("192.168.1.100");

        ResetPasswordConfirmRequest req = ResetPasswordConfirmRequest.builder()
                .token("bogus-raw-token")
                .newPassword("NewSecureP@ss123")
                .build();

        when(passwordResetTokenService.consume("bogus-raw-token", "NewSecureP@ss123", "192.168.1.100"))
                .thenReturn(PasswordResetTokenService.ConsumeResult.INVALID_TOKEN);

        ResponseEntity<?> response = controller.confirmPasswordReset(req, request);

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertEquals("Invalid reset token", response.getBody());
    }
}
