# Cost Analysis — Multi-Cloud Production

Generated: 2026-11-12
Basis: Estimated monthly cost at moderate production load (~10k RAG queries/month, ~5k chat messages/month, ~2k IncidentIQ incidents/month).

## 1. Current (Free Tier) — $0/month

| Service | Tier | Cost | Limitation |
|---------|------|------|------------|
| Render | Free | $0 | Spin-down after 15 min inactivity, 502 intermittent |
| Cloudflare Pages | Free | $0 | Build minutes limited, no custom domain SLA |
| Cloudflare Workers | Free | $0 | 100k requests/day limit |
| Cloudflare D1 | Free | $0 | 5GB storage, limited writes |
| Cloudflare Vectorize | Free | $0 | 200k vectors, limited queries |
| Neon Postgres | Free | $0 | 0.5GB storage, auto-suspend |
| Qdrant | Free | $0 | Single replica, no backup |

**Total current: $0/month** — but not production SLA (G8, G10).

## 2. Estimated Production (Paid)

| Service | Tier | Est. Cost/month | Notes |
|---------|------|-----------------|-------|
| Azure Container Apps | Consumption / Paid | $80–150 | Backend API, 2 replicas |
| Azure AKS | 3 nodes | $150–250 | QuanLyKho backend |
| Neon Postgres | Scale | $40–90 | LangGraph checkpoints + metadata |
| Qdrant | Cloud managed | $80–150 | Vector index, HA |
| Cloudflare Workers AI | Paid | $30–60 | Embedding + LLM tokens |
| Cloudflare Pages | Pro | $20 | Custom domain, analytics |
| Cloudflare Workers | Paid | $30–60 | IncidentIQ API + MCP |
| Cloudflare D1 | Paid | $25–50 | IncidentIQ database |
| Cloudflare Vectorize | Paid | $25–50 | IncidentIQ vectors |
| Cloudflare Queues | Paid | $10–20 | ETL + DLQ |
| Cloudflare R2 | Paid | $10–20 | Document storage |
| Upstash Redis | Paid | $20–40 | HITL store |
| Keycloak (Azure CA) | Consumption | $40–80 | SSO / OIDC |

**Estimated production total: $560–1,040/month**

## 3. Break-Even Analysis

| Metric | Free Tier | Production |
|--------|-----------|------------|
| Monthly cost | $0 | $560–1,040 |
| Uptime SLA | None | 99.9% (Azure/AKS) |
| HITL persistence | Lost on redeploy | Persistent (Neon) |
| SSO reliability | Intermittent (Render free) | Reliable (Azure CA) |
| Custom domain | No | Yes (Cloudflare Pages Pro) |

**Go-live recommendation:** Production rollout when monthly active users justify ~$600/month infrastructure cost. Start with Azure Container Apps + Cloudflare Workers AI (lowest entry), add AKS/Qdrant/Neon as load increases.

## 4. Cost Optimization Options

| Option | Savings | Trade-off |
|--------|---------|-----------|
| Azure Container Apps Consumption | ~40% | Scale-to-zero, cold start |
| Neon auto-suspend | ~30% | Connection latency on resume |
| Cloudflare Workers AI free tier | $0 | 100k requests/day cap |
| Render paid (instead of Azure CA) | ~20% | Vendor lock-in, single cloud |
