package com.smartdocchat.security;

import com.smartdocchat.service.AuditLogService;
import com.smartdocchat.util.JwtTokenProvider;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.core.oidc.user.OidcUser;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.util.Optional;

/**
 * Bridges a successful OIDC login into the existing JWT auth model: issues the
 * same httpOnly {@code jwt_token} cookie the local login issues and redirects
 * the browser back to the SPA. Frontend needs no changes — it reads the token
 * from the response body of /auth/login only for the local flow; for SSO the
 * cookie is authoritative and the redirect lands on the app root.
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class OidcLoginSuccessHandler implements AuthenticationSuccessHandler {

    private static final String JWT_COOKIE_NAME = "jwt_token";
    private static final int JWT_COOKIE_MAX_AGE_SECONDS = 86400; // 24h

    private final JwtTokenProvider tokenProvider;
    private final com.smartdocchat.config.OidcProperties oidcProperties;
    private final AuditLogService auditLogService;

    @Override
    public void onAuthenticationSuccess(HttpServletRequest request, HttpServletResponse response,
                                        Authentication authentication) throws IOException {
        OidcUser oidcUser = (OidcUser) authentication.getPrincipal();
        String username = oidcUser.getName();
        String role = Optional.ofNullable(authentication.getAuthorities())
                .flatMap(auths -> auths.stream()
                        .map(a -> a.getAuthority())
                        .filter(a -> a.startsWith("ROLE_"))
                        .findFirst())
                .orElse("ROLE_USER");

        String token = tokenProvider.generateToken(username, role);

        Cookie jwtCookie = new Cookie(JWT_COOKIE_NAME, token);
        jwtCookie.setHttpOnly(true);
        jwtCookie.setPath("/");
        jwtCookie.setMaxAge(JWT_COOKIE_MAX_AGE_SECONDS);
        jwtCookie.setSecure(request.isSecure() || "https".equalsIgnoreCase(
                Optional.ofNullable(request.getHeader("X-Forwarded-Proto")).orElse("http")));
        jwtCookie.setAttribute("SameSite", jwtCookie.getSecure() ? "None" : "Lax");
        response.addCookie(jwtCookie);

        auditLogService.record(username, "auth.login.sso", "user", username,
                request.getRemoteAddr(), "role=" + role);

        response.sendRedirect(resolvePostLoginTarget(request));

        // Redirect back to the frontend origin that started the flow (from the
        // Referer header of the initial /oauth2/authorization navigation). This
        // keeps production and local dev working without per-env config; falls
        // back to the configured value when Referer is absent (e.g. direct nav).
    }

    private String resolvePostLoginTarget(HttpServletRequest request) {
        String referer = request.getHeader("Referer");
        if (referer != null) {
            try {
                java.net.URI uri = java.net.URI.create(referer);
                String origin = uri.getScheme() + "://" + uri.getHost()
                        + (uri.getPort() > 0 && uri.getPort() != 443 && uri.getPort() != 80 ? ":" + uri.getPort() : "");
                String self = request.getScheme() + "://" + request.getServerName()
                        + (request.getServerPort() > 0 && request.getServerPort() != 443 && request.getServerPort() != 80 ? ":" + request.getServerPort() : "");
                // Only trust cross-origin referers (i.e. the SPA), never redirect to the API itself
                if (uri.getScheme() != null && uri.getHost() != null && !origin.equals(self)) {
                    return origin + "/";
                }
            } catch (IllegalArgumentException ignored) {
                // fall through to configured redirect
            }
        }
        return oidcProperties.getPostLoginRedirect();
    }
}
