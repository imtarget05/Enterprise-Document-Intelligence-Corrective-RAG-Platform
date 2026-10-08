"""
Agent service settings – loaded from environment variables / .env

Security note:
    Secrets (internal_service_token, qdrant_api_key, postgres_password) have NO
    insecure defaults. They MUST be provided via environment variables / .env.
    The application will refuse to start in production if they are missing or
    still equal to a known placeholder value.
"""

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load the repository .env into os.environ BEFORE any validation runs so that
# APP_ENV (and every other variable) is visible to both pydantic-settings and
# the os.getenv calls in _is_strict_env(). Existing real environment variables
# take priority over the file (override=False).
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

# Values that must never appear in production. If a secret equals one of these
# (case-insensitive) the Settings validator will raise on instantiation.
_INSECURE_SECRET_VALUES = {
    "",
    "postgres",
    "qdrant_key_123",
    "local-development-service-token-change-me",
    "change-me",
    "change-me-to-a-secure-random-token",
    "change-me-to-a-long-secure-random-string",
    "admin",
    "changeme",
    "password",
}

# Environment name used to decide whether insecure defaults are tolerated.
# Anything other than "local" / "dev" / "development" / "test" is treated as
# production-grade and enforces strict secret validation.
_PERMISSIVE_ENVS = {"local", "dev", "development", "test"}


def _is_strict_env() -> bool:
    env = os.getenv("APP_ENV", "production").strip().lower()
    return env not in _PERMISSIVE_ENVS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env", env_file_encoding="utf-8", extra="ignore"
    )

    # Deployment environment (local | dev | staging | production). Drives strict
    # secret validation. Defaults to "production" so misconfiguration fails safe.
    app_env: str = "production"

    # Spring Boot internal auth — NO default. Must be set explicitly.
    internal_service_token: str = ""

    # Ollama-compatible LLM Router (Cloudflare Workers AI behind the router)
    llm_base_url: str = "http://llm-router:8000"
    llm_chat_model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    llm_embedding_model: str = "@cf/baai/bge-base-en-v1.5"
    llm_temperature: float = 0.3

    # Local Ollama (M1 Pro 16GB plan 2026-09-18): when LOCAL_OLLAMA_URL is set
    # (e.g. http://localhost:11434) the agent talks directly to the local
    # models instead of the cloud router — qwen2.5:3b for chat/RAG
    # (num_ctx 4096, keep_alive 5m), qwen2.5-coder:1.5b for task=code,
    # nomic-embed-text kept so stored Qdrant vectors stay valid
    # (qwen3-embedding:0.6b opt-in for Vietnamese, requires re-index).
    local_ollama_url: str = ""
    local_ollama_chat_model: str = "qwen2.5:3b"
    local_ollama_code_model: str = "qwen2.5-coder:1.5b"
    local_ollama_embed_model: str = "nomic-embed-text"

    # Local LM Studio (OpenAI-compatible, DEFAULT local tier since 2026-09-19):
    # when LOCAL_LMSTUDIO_URL is set (LM Studio → Start Server, default
    # http://localhost:1234/v1) the agent talks directly to the models
    # downloaded in LM Studio — default qwen2.5-vl-3b-instruct +
    # text-embedding-nomic-embed-text-v1.5. Takes priority over Ollama.
    local_lmstudio_url: str = ""
    local_lmstudio_chat_model: str = "qwen2.5-vl-3b-instruct"
    local_lmstudio_embed_model: str = "text-embedding-nomic-embed-text-v1.5"
    local_lmstudio_api_key: str = "lm-studio"

    # Qdrant — NO default api key. Must be set explicitly when Qdrant requires auth.
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_use_https: bool = False

    # PostgreSQL (long-term memory) — NO default password. Must be set explicitly.
    postgres_db: str = "smart_doc_chatbot"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Tavily web search (optional — leave empty to disable)
    tavily_api_key: str = ""

    # Phase 3 – Google
    google_credentials_json: str = ""  # path to credentials.json or inline JSON
    google_token_json: str = ""  # path to token.json

    # Phase 3 – Slack
    slack_bot_token: str = ""

    # Connector ingestion
    connector_chunk_size: int = 1200
    connector_chunk_overlap: int = 180

    # Microsoft SharePoint / Graph
    sharepoint_mock_enabled: bool = True
    microsoft_graph_token: str = ""
    sharepoint_site_id: str = ""
    sharepoint_drive_id: str = ""

    # Phase 4 – Email (SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""

    # Phase 4 – Webhooks / integrations
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    # Governance — Human-in-the-Loop approval for orchestrated actions
    hitl_require_approval: bool = True
    hitl_approval_ttl_seconds: int = 3600
    # HITL approval store backend: "auto" | "redis" | "memory".
    # auto → Redis when REDIS_URL is set, otherwise in-memory.
    hitl_store_backend: str = "auto"
    # Fail-closed when the Redis approval store is unreachable.
    # None → auto-derive from APP_ENV (fail closed everywhere except
    # local/dev/development/test), mirroring rate_limiter.py.
    hitl_fail_closed: Optional[bool] = None
    notion_api_token: str = ""
    teams_webhook_url: str = ""

    # ── Security ────────────────────────────────────────────────────────────
    # Comma-separated list of origins allowed to call this service from a browser.
    # CORS only matters for browser callers; Spring Boot internal calls bypass it.
    # In production, AGENT_ALLOWED_ORIGINS MUST be set explicitly and must NOT
    # contain localhost/127.0.0.1 origins. The validator below enforces this.
    agent_allowed_origins: str = (
        "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000"
    )

    # Maximum body size (bytes) accepted by agent endpoints.
    # Prevents prompt-injection via oversized payloads (default 512 KB).
    agent_max_request_bytes: int = 524_288  # 512 KB

    # Rate limiting per authenticated user-id (requests per minute).
    # LLM calls are expensive; keep this conservative.
    agent_rate_limit_rpm: int = 20

    # ── Cost tracking ──────────────────────────────────────────────────────
    # JSON map model -> price per 1k tokens (USD). Example:
    # {"@cf/meta/llama-3.3-70b-instruct-fp8-fast":0.0003,"default":0.0003}
    # Leave as "{}" to disable cost tracking.
    cost_per_1k_tokens: str = "{}"

    # ── Prometheus ─────────────────────────────────────────────────────────
    # If true, the agent service exposes a /metrics endpoint for Prometheus
    # scraping. Disable for environments without Prometheus.
    prometheus_enabled: bool = True

    # ── Redis (rate limiting + short-term memory) ────────────────────────────
    # Optional. When set, the rate limiter uses Redis sorted-sets for accurate
    # per-IP counting across multiple replicas. Falls back to in-memory if blank.
    # Example: redis://redis:6379/0
    redis_url: str = ""

    # ── LangGraph ───────────────────────────────────────────────────────────
    # SQLite file backing the workflow checkpointer — what allows an interrupted
    # run to be resumed after a restart. A relative path resolves against the
    # service working directory (the container image uses /app). Override with
    # LANGGRAPH_CHECKPOINT_DB. Use ":memory:" only for throwaway processes:
    # checkpoints are then lost as soon as the process exits.
    langgraph_checkpoint_db: str = "checkpoints.sqlite"

    # ── Validators ───────────────────────────────────────────────────────────
    @field_validator("internal_service_token")
    @classmethod
    def _validate_internal_token(cls, v: str) -> str:
        if _is_strict_env() and v.strip().lower() in _INSECURE_SECRET_VALUES:
            raise ValueError(
                "INTERNAL_SERVICE_TOKEN must be set to a strong, unique value "
                "in non-local environments (current value is empty or a known "
                "placeholder). Set it via the INTERNAL_SERVICE_TOKEN env var."
            )
        if _is_strict_env() and len(v.strip()) < 32:
            raise ValueError(
                "INTERNAL_SERVICE_TOKEN must be at least 32 characters long in "
                "non-local environments to resist brute-force attacks."
            )
        return v

    @field_validator("qdrant_api_key")
    @classmethod
    def _validate_qdrant_key(cls, v: str) -> str:
        # Qdrant key may legitimately be empty for local unauthenticated Qdrant.
        if v.strip() and v.strip().lower() in _INSECURE_SECRET_VALUES:
            raise ValueError(
                "QDRANT_API_KEY is set to a known insecure placeholder. "
                "Provide the real cluster API key or leave it empty for local "
                "unauthenticated Qdrant."
            )
        return v

    @field_validator("postgres_password")
    @classmethod
    def _validate_pg_password(cls, v: str) -> str:
        if _is_strict_env() and v.strip().lower() in _INSECURE_SECRET_VALUES:
            raise ValueError(
                "POSTGRES_PASSWORD must be set to a strong value in non-local "
                "environments (current value is empty or 'postgres'). Set it "
                "via the POSTGRES_PASSWORD env var."
            )
        if _is_strict_env() and len(v.strip()) < 12:
            raise ValueError(
                "POSTGRES_PASSWORD must be at least 12 characters long in "
                "non-local environments."
            )
        return v

    @field_validator("agent_allowed_origins")
    @classmethod
    def _validate_cors_origins(cls, v: str) -> str:
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if not origins:
            raise ValueError("AGENT_ALLOWED_ORIGINS must contain at least one origin.")
        if _is_strict_env():
            forbidden = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
            bad = [o for o in origins if any(f in o for f in forbidden)]
            if bad:
                raise ValueError(
                    f"AGENT_ALLOWED_ORIGINS must not contain loopback/dev "
                    f"origins in non-local environments: {bad}"
                )
        return ",".join(origins)

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.agent_allowed_origins.split(",") if o.strip()]


def _warn_local_defaults() -> None:
    """Emit a visible warning when running with permissive local defaults."""
    if not _is_strict_env():
        import logging

        logging.getLogger("agent.settings").warning(
            "APP_ENV is set to a local/dev profile — insecure secret defaults "
            "are tolerated. NEVER use this profile in production."
        )


_warn_local_defaults()
settings = Settings()
