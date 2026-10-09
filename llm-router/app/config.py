import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name, "")
    if val == "":
        return default
    return val.lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    cloudflare_account_id: str = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    cloudflare_api_token: str = os.getenv("CLOUDFLARE_API_TOKEN", "")
    cloudflare_api_base: str = os.getenv(
        "CLOUDFLARE_API_BASE", "https://api.cloudflare.com/client/v4"
    )
    cloudflare_chat_model: str = os.getenv(
        "CLOUDFLARE_CHAT_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    cloudflare_embed_model: str = os.getenv(
        "CLOUDFLARE_EMBED_MODEL", "@cf/baai/bge-base-en-v1.5"
    )
    cloudflare_timeout_seconds: float = _float_env("CLOUDFLARE_TIMEOUT_SECONDS", 60.0)
    # Circuit breaker: after this many consecutive provider failures the
    # circuit opens and requests fail fast for circuit_open_seconds.
    circuit_failure_threshold: int = _int_env("CIRCUIT_FAILURE_THRESHOLD", 5)
    circuit_open_seconds: float = _float_env("CIRCUIT_OPEN_SECONDS", 30.0)
    confidence_threshold: float = _float_env("ROUTER_CONFIDENCE_THRESHOLD", 0.7)
    internal_token: str = os.getenv("ROUTER_INTERNAL_TOKEN", "")
    # Local Ollama (opt-in): when LOCAL_OLLAMA_URL is set (e.g.
    # http://localhost:11434) and the server answers its health probe, chat
    # requests are served by the locally downloaded model (user pulled it via
    # `ollama pull`, e.g. qwen2.5:3b — Makefile target `local-ollama-pull`).
    # When unset or unreachable the router uses Cloudflare — deliberately
    # WITHOUT mid-request fallback between the two, so behaviour stays
    # predictable (Decision: local-first, no auto-fallback).
    # M1 Pro 16GB plan (2026-09-18): KEEP qwen2.5:3b as default chat RAG model
    # (num_ctx 4096, keep_alive 5m) + nomic-embed-text (kept so stored vectors
    # stay valid). qwen2.5-coder:1.5b loads ONLY for task=code, and
    # qwen3-embedding:0.6b is the optional Vietnamese embedding upgrade.
    # OLLAMA_NUM_PARALLEL=1, OLLAMA_MAX_LOADED_MODELS=1 to fit 16GB RAM.
    local_ollama_url: str = os.getenv("LOCAL_OLLAMA_URL", "")
    local_ollama_model: str = os.getenv("LOCAL_OLLAMA_MODEL", "qwen2.5:3b")
    local_ollama_code_model: str = os.getenv(
        "LOCAL_OLLAMA_CODE_MODEL", "qwen2.5-coder:1.5b"
    )
    local_ollama_embed_model: str = os.getenv(
        "LOCAL_OLLAMA_EMBED_MODEL", "nomic-embed-text"
    )
    local_ollama_num_ctx: int = _int_env("LOCAL_OLLAMA_NUM_CTX", 4096)
    local_ollama_keep_alive: str = os.getenv("LOCAL_OLLAMA_KEEP_ALIVE", "5m")
    local_ollama_timeout_seconds: float = _float_env(
        "LOCAL_OLLAMA_TIMEOUT_SECONDS", 120.0
    )
    max_local_concurrency: int = _int_env("MAX_LOCAL_CONCURRENCY", 2)
    local_queue_timeout_seconds: float = _float_env(
        "LOCAL_QUEUE_TIMEOUT_SECONDS", 0.5
    )
    local_busy_retry_after_seconds: int = _int_env(
        "LOCAL_BUSY_RETRY_AFTER_SECONDS", 2
    )
    local_ollama_health_ttl_seconds: float = _float_env(
        "LOCAL_OLLAMA_HEALTH_TTL_SECONDS", 10.0
    )
    # Local LM Studio (OpenAI-compatible, DEFAULT local tier since 2026-09-19):
    # when LOCAL_LMSTUDIO_URL is set (LM Studio → Developer tab → Start
    # Server, default http://localhost:1234/v1) and the server answers its
    # health probe (GET /v1/models), chat + embeddings are served by the
    # models the user downloaded in LM Studio — default
    # qwen2.5-vl-3b-instruct + text-embedding-nomic-embed-text-v1.5.
    # Priority when both locals are configured: LM Studio → Ollama →
    # Cloudflare (predictable, never mid-request fallback between tiers).
    # When unset or unreachable the router falls back to Ollama/Cloudflare.
    local_lmstudio_url: str = os.getenv("LOCAL_LMSTUDIO_URL", "")
    local_lmstudio_model: str = os.getenv(
        "LOCAL_LMSTUDIO_MODEL", "qwen2.5-vl-3b-instruct"
    )
    local_lmstudio_embed_model: str = os.getenv(
        "LOCAL_LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5"
    )
    local_lmstudio_api_key: str = os.getenv("LOCAL_LMSTUDIO_API_KEY", "lm-studio")
    # Prompt compression: heuristic-based token reduction before LLM calls.
    prompt_compression_enabled: bool = _bool_env("PROMPT_COMPRESSION_ENABLED", True)
    prompt_compression_ratio: float = _float_env("PROMPT_COMPRESSION_RATIO", 0.5)
    prompt_compression_min_tokens: int = _int_env("PROMPT_COMPRESSION_MIN_TOKENS", 1000)
    # Response cache: Redis-backed LLM response caching.
    response_cache_enabled: bool = _bool_env("RESPONSE_CACHE_ENABLED", True)
    response_cache_ttl_seconds: int = _int_env("RESPONSE_CACHE_TTL_SECONDS", 300)

    def __post_init__(self) -> None:
        if self.app_env.strip().lower() not in {"local", "dev", "development", "test", "testing"} and not self.internal_token.strip():
            raise ValueError(
                "ROUTER_INTERNAL_TOKEN must be set in non-local environments."
            )


settings = Settings()
