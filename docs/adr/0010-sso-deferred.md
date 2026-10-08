# ADR-0010: SSO Deferred — Google OAuth Canonical, Keycloak Parked (2026-10-08)

## Status
Accepted (deferral, not cancellation).

## Context
`render.yaml` ships 4 services incl. `smartdoc-keycloak`, but
`SSO_OIDC_ENABLED=false` (Keycloak public URL unreachable from Render) and
live probe 2026-10-08 shows Keycloak answering HTTP 404 on
`/realms/master` while the Spring backend itself `000`-times-out on
`/api/actuator/health`. OIDC wiring exists in code
(`OidcProperties.java`, `OAuth2Config.java`, `application.yml`) but the IdP
plane is not healthy. Google OAuth (One Tap, redirect pinned to the
onrender backend) is the working auth path.

## Decision
1. Canonical auth = Google OAuth (already live); Keycloak/SSO stays OFF
   (`SSO_OIDC_ENABLED=false`) until the Keycloak service is healthy AND
   `SSO_OIDC_ISSUER_URI` points at its public URL.
2. Do NOT remove the keycloak service from render.yaml (capability evidence).
3. Revisit when: Keycloak `/realms/smartdoc/.well-known/openid-configuration`
   returns 200 from public internet.

## Consequences
- No false SSO claim in docs/demos; Google OAuth covers recruiter + prod login.
- Keycloak free-tier keeps sleeping; no action needed until revisit trigger.
