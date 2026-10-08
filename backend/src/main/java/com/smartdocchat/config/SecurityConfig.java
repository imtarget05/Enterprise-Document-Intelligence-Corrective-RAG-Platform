package com.smartdocchat.config;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfTokenRequestAttributeHandler;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.Arrays;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity(prePostEnabled = true)
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtAuthenticationFilter jwtAuthenticationFilter;
    private final OidcProperties oidcProperties;
    private final com.smartdocchat.security.CustomOidcUserService customOidcUserService;
    private final com.smartdocchat.security.OidcLoginSuccessHandler oidcLoginSuccessHandler;
    private final com.smartdocchat.service.OAuth2UserService oAuth2UserService;
    private final com.smartdocchat.security.CookieAuthorizationRequestRepository cookieAuthorizationRequestRepository;

    @Value("${cors.allowed-origins:http://localhost:3000,http://localhost:3001,http://localhost:8080,http://127.0.0.1:3000}")
    private String allowedOrigins;

    @Value("${oauth2.issuer-uri:}")
    private String oauth2IssuerUri;

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        CookieCsrfTokenRepository csrfTokenRepository = new CookieCsrfTokenRepository();
        csrfTokenRepository.setCookieHttpOnly(true);
        csrfTokenRepository.setCookiePath("/");
        csrfTokenRepository.setCookieName("XSRF-TOKEN");
        csrfTokenRepository.setHeaderName("X-XSRF-TOKEN");
        csrfTokenRepository.setCookieCustomizer(c -> c.sameSite("None"));

        http
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            .headers(headers -> headers
                .contentSecurityPolicy(csp -> csp.policyDirectives(
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                        + "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"))
                .frameOptions(frame -> frame.deny())
                .httpStrictTransportSecurity(hsts -> hsts
                    .includeSubDomains(true)
                    .maxAgeInSeconds(31_536_000))
                .referrerPolicy(referrer -> referrer.policy(
                    org.springframework.security.web.header.writers.ReferrerPolicyHeaderWriter
                        .ReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN))
            )
            .csrf(csrf -> csrf
                .csrfTokenRepository(csrfTokenRepository)
                .csrfTokenRequestHandler(new CsrfTokenRequestAttributeHandler())
                .ignoringRequestMatchers("/auth/google", "/auth/google-client-id")
            )
            .sessionManagement(session -> session.sessionCreationPolicy(
                    oidcProperties.isEnabled()
                            ? SessionCreationPolicy.IF_REQUIRED
                            : SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers(
                    "/auth/login",
                    "/auth/register",
                    "/auth/logout",
                    "/auth/reset-password/request",
                    "/auth/reset-password/confirm",
                    "/auth/google",
                    "/auth/google-client-id"
                ).permitAll()
                .requestMatchers("/csrf").permitAll()
                .requestMatchers("/login/oauth2/**", "/oauth2/**").permitAll()
                .requestMatchers(
                    "/v3/api-docs/**",
                    "/swagger-ui/**",
                    "/swagger-ui.html"
                ).permitAll()
                .requestMatchers("/actuator/health/**", "/actuator/info").permitAll()
                .requestMatchers("/actuator/prometheus").permitAll()
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .requestMatchers("/agent/approvals/**").hasAnyRole("ADMIN", "ENGINEER")
                .requestMatchers(HttpMethod.GET, "/documents/**").authenticated()
                .requestMatchers(HttpMethod.DELETE, "/documents/**").authenticated()
                .anyRequest().authenticated()
            );

        http.addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);

        if (oidcProperties.isEnabled()) {
            http.oauth2Login(oauth2 -> oauth2
                .authorizationEndpoint(a -> a.authorizationRequestRepository(cookieAuthorizationRequestRepository))
                .userInfoEndpoint(userInfo -> userInfo.oidcUserService(customOidcUserService))
                .successHandler(oidcLoginSuccessHandler));
        }

        if (!oidcProperties.isEnabled() && oauth2IssuerUri != null && !oauth2IssuerUri.isBlank()) {
            http.oauth2Login(oauth2 -> oauth2
                .authorizationEndpoint(a -> a.authorizationRequestRepository(cookieAuthorizationRequestRepository))
                .userInfoEndpoint(userInfo -> userInfo.oidcUserService(oAuth2UserService))
                .successHandler(oidcLoginSuccessHandler));
        }

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration configuration = new CorsConfiguration();
        // Origin PATTERNS (not exact origins): supports wildcards such as
        // https://*.smart-doc-chatbot.pages.dev so Cloudflare Pages preview
        // deployments (random subdomains) pass CORS preflights too.
        configuration.setAllowedOriginPatterns(
                Arrays.stream(allowedOrigins.split(",")).map(String::trim).toList());
        configuration.setAllowedMethods(Arrays.asList("GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"));
        configuration.setAllowedHeaders(Arrays.asList("Authorization", "Content-Type", "Cache-Control", "X-XSRF-TOKEN"));
        configuration.setExposedHeaders(Arrays.asList("Authorization", "X-Request-Id", "X-XSRF-TOKEN"));
        configuration.setAllowCredentials(true);
        configuration.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", configuration);
        return source;
    }
}
