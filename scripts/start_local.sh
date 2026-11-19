#!/usr/bin/env bash
# Start the local infrastructure used by the SmartDoc RAG demo.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

command -v docker >/dev/null || { echo 'Docker is required.' >&2; exit 1; }
LOCAL_OLLAMA_MODEL=qwen2.5:1.5b docker compose -f docker/docker-compose.local.yml up --build -d postgres qdrant ollama llm-router

# Ollama runs in Docker; no host installation or cloud credentials are needed.
for model in qwen2.5:1.5b nomic-embed-text; do
  if ! docker exec smartdoc-local-ollama ollama list | grep -Fq "$model"; then
    docker exec smartdoc-local-ollama ollama pull "$model"
  fi
done

for endpoint in http://127.0.0.1:6333/healthz http://127.0.0.1:11434/api/tags "http://127.0.0.1:${LOCAL_LLM_ROUTER_PORT:-18001}/health"; do
  ready=false
  for attempt in {1..30}; do
    if curl --fail --silent --output /dev/null "$endpoint"; then ready=true; break; fi
    sleep 2
  done
  if [[ "$ready" != true ]]; then
    echo "Local service did not become ready: $endpoint" >&2
    exit 1
  fi
done

echo 'Local PostgreSQL, Qdrant, Ollama and LLM router are ready.'
echo "Router health: http://127.0.0.1:${LOCAL_LLM_ROUTER_PORT:-18001}/health"
echo 'The Spring backend and agent need their own local configuration, including Redis/Kafka and authentication; this script starts infrastructure only.'
echo 'The recorded 15-question RAG result and its limits are in eval/results/README.md.'
