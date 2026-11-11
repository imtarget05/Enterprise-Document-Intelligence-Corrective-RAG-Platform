# Enterprise MCP gateway

Official `@modelcontextprotocol/sdk@1.32.2`, stateless Streamable HTTP at `/mcp`. A separate Node process avoids the agent's local Python `mcp` package shadowing the official SDK. [SDK v1 server docs](https://ts.sdk.modelcontextprotocol.io/server).

Use Node 22.12+: `npm ci`, `npm run typecheck`, `npm test`, `npm run build`. Start with `BACKEND_URL=https://your-backend npm start`. `HOST` defaults to loopback; behind TLS configure `HOST=0.0.0.0`, `PORT` and `PUBLIC_ORIGIN` explicitly.

Every MCP request validates the caller's JWT through Spring `/api/documents`; every tool forwards that same token. Read-only tools: `list_documents`, `search_documents`, `get_document`. Spring remains authoritative for owner/role authorization. No owner/tenant override, shared internal-token substitution or default-scope retrieval. Calls have 15-second deadlines; redirects and cross-origin browser requests are refused. The authentication probe should become a cheap principal endpoint before scaling.

Existing agent `/v1/mcp/info`, `/tools`, `/call` REST adapters remain unchanged for compatibility, deprecated as MCP protocol endpoints. New MCP clients use this gateway. Legacy unscoped retrieval is not exposed through this gateway.

Tests use real SDK Client/StreamableHTTPClientTransport with in-process fetch, plus a compiled child process over real loopback HTTP; Spring responses remain stubbed. They prove lifecycle/list/call, auth refusal and forwarding, not live JWT validation, cloud E2E isolation, OAuth discovery, availability or production readiness.
