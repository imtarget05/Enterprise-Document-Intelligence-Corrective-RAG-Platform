#!/usr/bin/env python3
"""
Mock backend for live hallucination evaluation demo.
Simulates /api/chat/ask endpoint with deterministic responses matching eval/questions.json.
"""

import asyncio
import json
import uuid
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Mock backend starting on http://localhost:8081/api")
    yield
    print("👋 Mock backend shutting down")


app = FastAPI(title="Mock SmartDoc Backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    sessionId: str
    documentId: int
    message: str
    webSearch: Optional[bool] = False


class ChatResponse(BaseModel):
    aiResponse: str
    ragStrategy: str
    confidence: str
    confidence_score: float
    sourceChunks: str
    source_chunks: str
    citations: list[dict]
    latency_ms: int


# ─── Comprehensive mock responses matching eval/questions.json ───
MOCK_RESPONSES = {
    # Q1: "Hệ thống sử dụng framework backend nào?"
    "hệ thống sử dụng framework": {
        "aiResponse": "Hệ thống sử dụng Spring Boot cho REST API và FastAPI cho agent service.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.92,
        "sourceChunks": "backend uses Spring Boot framework FastAPI agent service",
        "source_chunks": "backend uses Spring Boot framework FastAPI agent service",
        "citations": [{"documentId": 1, "content": "Spring Boot backend"}],
        "latency_ms": 120
    },

    # Q2: "Vector database nào được sử dụng để lưu embeddings?"
    "vector database": {
        "aiResponse": "Vector database là Qdrant, lưu embeddings và tìm kiếm ngữ nghĩa.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.91,
        "sourceChunks": "Qdrant vector database embeddings semantic search",
        "source_chunks": "Qdrant vector database embeddings semantic search",
        "citations": [{"documentId": 1, "content": "Qdrant"}],
        "latency_ms": 95
    },

    # Q3: "Mô hình embedding nào được dùng để sinh vector?"
    "mô hình embedding": {
        "aiResponse": "Mô hình embedding là @cf/baai/bge-base-en-v1.5 (dimension 768), chạy qua Cloudflare Workers AI.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.89,
        "sourceChunks": "@cf/baai/bge-base-en-v1.5 dimension 768 Cloudflare Workers AI",
        "source_chunks": "@cf/baai/bge-base-en-v1.5 dimension 768 Cloudflare Workers AI",
        "citations": [{"documentId": 1, "content": "embedding model"}],
        "latency_ms": 105
    },

    # Q4: "Hệ thống xử lý thế nào khi retrieval confidence thấp?"
    "retrieval confidence thấp": {
        "aiResponse": "Khi retrieval confidence thấp (< 0.6): reformulate query → re-retrieve → web search fallback → abstention nếu vẫn low.",
        "ragStrategy": "corrective",
        "confidence": "medium",
        "confidence_score": 0.55,
        "sourceChunks": "CRAG confidence threshold 0.6 query reformulation web search fallback abstention",
        "source_chunks": "CRAG confidence threshold 0.6 query reformulation web search fallback abstention",
        "citations": [{"documentId": 1, "content": "CRAG loop logic"}],
        "latency_ms": 450
    },

    # Q5: "Ngưỡng confidence để kích hoạt Agentic CRAG loop là bao nhiêu?"
    "ngưỡng confidence": {
        "aiResponse": "Ngưỡng confidence để kích hoạt Agentic CRAG loop là 0.45 (45%). Dưới ngưỡng này sẽ reformulate và re-retrieve.",
        "ragStrategy": "corrective",
        "confidence": "medium",
        "confidence_score": 0.62,
        "sourceChunks": "confidence threshold 0.45 45% CRAG activation",
        "source_chunks": "confidence threshold 0.45 45% CRAG activation",
        "citations": [{"documentId": 1, "content": "CRAG threshold"}],
        "latency_ms": 130
    },

    # Q6: "Pipeline ETL tài liệu gồm những bước nào?"
    "pipeline etl": {
        "aiResponse": "Pipeline ETL tài liệu: upload → parsing → chunking (500 tokens, 100 overlap) → embedding → index vào Qdrant. Quản lý bởi Airflow DAG hàng ngày.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.85,
        "sourceChunks": "upload parsing chunking embedding index Airflow DAG daily ingestion",
        "source_chunks": "upload parsing chunking embedding index Airflow DAG daily ingestion",
        "citations": [{"documentId": 1, "content": "ETL pipeline"}],
        "latency_ms": 140
    },

    # Q7: "Frontend sử dụng công nghệ gì để quản lý server state?"
    "frontend sử dụng công nghệ": {
        "aiResponse": "Frontend sử dụng TanStack Query (React Query) để quản lý server state và caching.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.91,
        "sourceChunks": "TanStack Query React Query cache server state management",
        "source_chunks": "TanStack Query React Query cache server state management",
        "citations": [{"documentId": 1, "content": "TanStack Query"}],
        "latency_ms": 85
    },

    # Q7.5: "SSE streaming response cho user như thế nào?"
    "sse streaming": {
        "aiResponse": "SSE streaming response sử dụng SseEmitter (Spring Boot) để gửi token từng phần đến client qua Server-Sent Events.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.88,
        "sourceChunks": "SSE Server-Sent Events SseEmitter stream token response",
        "source_chunks": "SSE Server-Sent Events SseEmitter stream token response",
        "citations": [{"documentId": 1, "content": "SSE streaming"}],
        "latency_ms": 90
    },

    # Q8: "Khi không tìm thấy thông tin trong tài liệu, hệ thống làm gì?"
    "không tìm thấy thông tin": {
        "aiResponse": "Khi không tìm thấy: web search fallback qua Tavily API, sau đó dùng general knowledge + deep reasoning agent.",
        "ragStrategy": "fallback",
        "confidence": "medium",
        "confidence_score": 0.68,
        "sourceChunks": "fallback Tavily web search general knowledge deep reasoning",
        "source_chunks": "fallback Tavily web search general knowledge deep reasoning",
        "citations": [{"documentId": 1, "content": "fallback logic"}],
        "latency_ms": 280
    },

    # Q10: "Mô hình LLM nào được chạy locally trong hệ thống?"
    "mô hình llm": {
        "aiResponse": "Mô hình LLM local là DeepSeek deepseek-r1:8b chạy qua Ollama trên Apple Silicon M1 Pro.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.87,
        "sourceChunks": "DeepSeek deepseek-r1 Ollama Apple Silicon M1",
        "source_chunks": "DeepSeek deepseek-r1 Ollama Apple Silicon M1",
        "citations": [{"documentId": 1, "content": "local LLM"}],
        "latency_ms": 110
    },

    # Q12: "Hệ thống hỗ trợ những định dạng tài liệu nào?"
    "định dạng tài liệu": {
        "aiResponse": "Hệ thống hỗ trợ PDF, DOCX, TXT cho upload và parsing tài liệu.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.93,
        "sourceChunks": "PDF DOCX TXT upload parsing",
        "source_chunks": "PDF DOCX TXT upload parsing",
        "citations": [{"documentId": 1, "content": "document formats"}],
        "latency_ms": 75
    },

    # Q15: "Authentication được thực hiện bằng phương pháp nào?"
    "authentication": {
        "aiResponse": "Authentication sử dụng JWT token (accessToken + refreshToken), CSRF protection cho mutating endpoints.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.94,
        "sourceChunks": "JWT token authentication CSRF protection",
        "source_chunks": "JWT token authentication CSRF protection",
        "citations": [{"documentId": 1, "content": "auth JWT"}],
        "latency_ms": 80
    },

    # Q16: "Parallel Re-retrieval trong Agentic CRAG hoạt động ra sao?"
    "parallel re-retrieval": {
        "aiResponse": "Parallel Re-retrieval dùng CompletableFuture chạy multi-thread: tạo query variation qua reformulation, retrieve song song, merge kết quả.",
        "ragStrategy": "agentic",
        "confidence": "medium",
        "confidence_score": 0.72,
        "sourceChunks": "parallel retrieval CompletableFuture query variation reformulation multi-thread",
        "source_chunks": "parallel retrieval CompletableFuture query variation reformulation multi-thread",
        "citations": [{"documentId": 1, "content": "parallel re-retrieval"}],
        "latency_ms": 320
    },

    # Q17: "Dữ liệu lịch sử chat được lưu ở đâu?"
    "lịch sử chat": {
        "aiResponse": "Lịch sử chat lưu trong PostgreSQL database, bảng chat_history với correlation_id để tracing.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.89,
        "sourceChunks": "PostgreSQL chat history correlation_id",
        "source_chunks": "PostgreSQL chat history correlation_id",
        "citations": [{"documentId": 1, "content": "chat history storage"}],
        "latency_ms": 85
    },

    # Q18: "Hệ thống monitoring sử dụng những công cụ nào?"
    "monitoring": {
        "aiResponse": "Monitoring: Prometheus metrics + Grafana dashboards, structured JSON logging với LogstashEncoder, RequestIdFilter.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.86,
        "sourceChunks": "Prometheus Grafana monitoring LogstashEncoder RequestIdFilter",
        "source_chunks": "Prometheus Grafana monitoring LogstashEncoder RequestIdFilter",
        "citations": [{"documentId": 1, "content": "monitoring stack"}],
        "latency_ms": 90
    },

    # Q18.5: "Multi-document synthesis hoạt động như thế nào?"
    "multi-document synthesis": {
        "aiResponse": "Multi-document synthesis: parallel collection retrieval qua multi-query, merge và rank kết quả trước khi đưa vào LLM.",
        "ragStrategy": "agentic",
        "confidence": "medium",
        "confidence_score": 0.65,
        "sourceChunks": "multi document synthesis parallel collection merge rank",
        "source_chunks": "multi document synthesis parallel collection merge rank",
        "citations": [{"documentId": 1, "content": "multi-doc synthesis"}],
        "latency_ms": 280
    },

    # Q19: "Web Search fallback sử dụng API nào?"
    "web search fallback": {
        "aiResponse": "Web Search fallback sử dụng Tavily API để tìm kiếm web khi retrieval không đủ evidence.",
        "ragStrategy": "fallback",
        "confidence": "high",
        "confidence_score": 0.82,
        "sourceChunks": "Tavily web search API fallback retrieval",
        "source_chunks": "Tavily web search API fallback retrieval",
        "citations": [{"documentId": 1, "content": "Tavily fallback"}],
        "latency_ms": 180
    },

    # Q20: "Cách hệ thống chống hallucination là gì?"
    "chống hallucination": {
        "aiResponse": "Hệ thống chống hallucination: confidence threshold + source citation required + web search fallback + hallucination heuristic (confident + no evidence + not 'không tìm thấy' → flag).",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.78,
        "sourceChunks": "hallucination confidence source citation fallback heuristic flag",
        "source_chunks": "hallucination confidence source citation fallback heuristic flag",
        "citations": [{"documentId": 1, "content": "hallucination guard"}],
        "latency_ms": 100
    },

    # Q21: "Rate limiting được áp dụng ở đâu trong hệ thống?"
    "rate limiting": {
        "aiResponse": "Rate limiting áp dụng ở login, upload, chat endpoints qua RateLimitInterceptor (token bucket filter), scope per IP/user.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.9,
        "sourceChunks": "rate limit login upload chat filter token bucket",
        "source_chunks": "rate limit login upload chat filter token bucket",
        "citations": [{"documentId": 1, "content": "rate limiting"}],
        "latency_ms": 80
    },

    # Q22: "Cách hệ thống xử lý lỗi khi LLM call thất bại?"
    "llm call thất bại": {
        "aiResponse": "LLM call thất bại: retry với exponential backoff, circuit breaker pattern, fallback sang RAG direct hoặc web search.",
        "ragStrategy": "direct",
        "confidence": "medium",
        "confidence_score": 0.75,
        "sourceChunks": "retry backoff circuit-breaker fallback LLM error handling",
        "source_chunks": "retry backoff circuit-breaker fallback LLM error handling",
        "citations": [{"documentId": 1, "content": "LLM error handling"}],
        "latency_ms": 150
    },

    # Q23: "Cách hệ thống ghi log có chứa thông tin PII không?"
    "ghi log": {
        "aiResponse": "Log không chứa PII: MDC correlation_id, PII redaction trước khi ghi log, structured JSON với LogstashEncoder.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.88,
        "sourceChunks": "PII redact MDC correlation-id LogstashEncoder structured JSON",
        "source_chunks": "PII redact MDC correlation-id LogstashEncoder structured JSON",
        "citations": [{"documentId": 1, "content": "PII log redaction"}],
        "latency_ms": 85
    },

    # Q24: "Cách hệ thống cấp quyền truy cập cho role khác nhau?"
    "quyền truy cập": {
        "aiResponse": "Phân quyền: role-based access control (RBAC), permission mapping qua Spring Security, JWT claims chứa roles.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.87,
        "sourceChunks": "role-based RBAC permission Spring Security JWT claims",
        "source_chunks": "role-based RBAC permission Spring Security JWT claims",
        "citations": [{"documentId": 1, "content": "RBAC authorization"}],
        "latency_ms": 80
    },

    # Q25: "Cách hệ thống backup và phục hồi dữ liệu?"
    "backup": {
        "aiResponse": "Backup: pg_dump PostgreSQL định kỳ, Qdrant snapshot, restore qua pg_restore + Qdrant recovery.",
        "ragStrategy": "direct",
        "confidence": "medium",
        "confidence_score": 0.72,
        "sourceChunks": "backup restore pg_dump pg_restore Qdrant snapshot data-recovery",
        "source_chunks": "backup restore pg_dump pg_restore Qdrant snapshot data-recovery",
        "citations": [{"documentId": 1, "content": "backup recovery"}],
        "latency_ms": 100
    },

    # Q25.5: "Cách hệ thống xử lý concurrent users?"
    "concurrent users": {
        "aiResponse": "Concurrent users: HikariCP connection pool, thread pool executor, request timeout config, async processing.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.85,
        "sourceChunks": "concurrent connection pool timeout HikariCP thread pool async",
        "source_chunks": "concurrent connection pool timeout HikariCP thread pool async",
        "citations": [{"documentId": 1, "content": "concurrency handling"}],
        "latency_ms": 90
    },

    # Q26: "Cách hệ thống tự động scale resources?"
    "tự động scale": {
        "aiResponse": "Auto-scale: Kubernetes HPA (Horizontal Pod Autoscaler) dựa trên CPU/memory/custom metrics, cloud provider integration.",
        "ragStrategy": "direct",
        "confidence": "medium",
        "confidence_score": 0.68,
        "sourceChunks": "Kubernetes HPA autoscale cloud provider CPU memory metrics",
        "source_chunks": "Kubernetes HPA autoscale cloud provider CPU memory metrics",
        "citations": [{"documentId": 1, "content": "auto scaling"}],
        "latency_ms": 110
    },

    # Q27: "Cách hệ thống xử lý đồng bộ request?"
    "đồng bộ request": {
        "aiResponse": "Đồng bộ request: synchronization với lock/mutex, thread-safe collections, CompletableFuture cho async, ReadWriteLock.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.83,
        "sourceChunks": "synchronization lock mutex thread-safe CompletableFuture ReadWriteLock",
        "source_chunks": "synchronization lock mutex thread-safe CompletableFuture ReadWriteLock",
        "citations": [{"documentId": 1, "content": "thread synchronization"}],
        "latency_ms": 85
    },

    # Q27.5: "Cách hệ thống đảm bảo data consistency?"
    "data consistency": {
        "aiResponse": "Data consistency: ACID transaction PostgreSQL, commit/rollback, @Transactional, optimistic locking cho concurrent update.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.84,
        "sourceChunks": "ACID transaction commit rollback optimistic locking @Transactional",
        "source_chunks": "ACID transaction commit rollback optimistic locking @Transactional",
        "citations": [{"documentId": 1, "content": "data consistency"}],
        "latency_ms": 90
    },

    # Q28: "Cách hệ thống xử lý lỗi network khi fetch từ external API?"
    "lỗi network": {
        "aiResponse": "Network error: retry với timeout, circuit breaker (Resilience4j), fallback response, dead letter queue cho failed requests.",
        "ragStrategy": "direct",
        "confidence": "medium",
        "confidence_score": 0.73,
        "sourceChunks": "retry timeout circuit-breaker fallback Resilience4j dead letter queue",
        "source_chunks": "retry timeout circuit-breaker fallback Resilience4j dead letter queue",
        "citations": [{"documentId": 1, "content": "network error handling"}],
        "latency_ms": 120
    },

    # Q29: "Cách hệ thống versioning codebase?"
    "versioning codebase": {
        "aiResponse": "Versioning: git commit/branch/merge, semantic versioning (semver), conventional commits, release tags.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.92,
        "sourceChunks": "git commit branch merge semantic versioning conventional commits",
        "source_chunks": "git commit branch merge semantic versioning conventional commits",
        "citations": [{"documentId": 1, "content": "git versioning"}],
        "latency_ms": 70
    },

    # Q29.5: "Cách hệ thống thực hiện code review?"
    "code review": {
        "aiResponse": "Code review: pull request trên GitHub, required approvals, CI checks (test, lint, typecheck) pass mới merge.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.9,
        "sourceChunks": "pull request review approval merge CI checks test lint",
        "source_chunks": "pull request review approval merge CI checks test lint",
        "citations": [{"documentId": 1, "content": "code review process"}],
        "latency_ms": 75
    },

    # Q30: "Cách hệ thống thực hiện deployment?"
    "deployment": {
        "aiResponse": "Deployment: CI/CD GitHub Actions, build → test → deploy staging → production, Docker images, zero-downtime.",
        "ragStrategy": "direct",
        "confidence": "high",
        "confidence_score": 0.88,
        "sourceChunks": "CI/CD GitHub Actions deploy staging production Docker zero-downtime",
        "source_chunks": "CI/CD GitHub Actions deploy staging production Docker zero-downtime",
        "citations": [{"documentId": 1, "content": "deployment pipeline"}],
        "latency_ms": 95
    },

    # Default fallback
    "default": {
        "aiResponse": "Tôi không tìm thấy thông tin liên quan trong tài liệu.",
        "ragStrategy": "no_evidence",
        "confidence": "low",
        "confidence_score": 0.25,
        "sourceChunks": "",
        "source_chunks": "",
        "citations": [],
        "latency_ms": 60
    }
}


def match_response(message: str) -> dict:
    """Match question to mock response by keyword."""
    msg_lower = message.lower()
    for keyword, response in MOCK_RESPONSES.items():
        if keyword in msg_lower:
            return response
    return MOCK_RESPONSES["default"]


async def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization[7:]
    if not token or token == "invalid":
        raise HTTPException(401, "Invalid token")
    return token


@app.get("/api/csrf")
async def get_csrf():
    token = "mock-csrf-token-" + uuid.uuid4().hex[:16]
    # Real backend sets the token as an XSRF-TOKEN cookie; the E2E smoke
    # (and the frontend) rely on that cookie being present.
    response = JSONResponse({"token": token})
    response.set_cookie(
        key="XSRF-TOKEN", value=token, httponly=False, samesite="lax", path="/"
    )
    return response


@app.post("/api/auth/register")
async def register():
    return {"id": 1, "username": "evaluser", "email": "eval@test.local"}


@app.post("/api/auth/login")
async def login():
    return {"token": "mock-jwt-token-" + uuid.uuid4().hex[:32], "accessToken": "mock-jwt-token-" + uuid.uuid4().hex[:32]}


@app.post("/api/chat/ask", response_model=ChatResponse)
async def chat_ask(request: ChatRequest, token: str = Depends(verify_token)):
    """Mock /api/chat/ask endpoint."""
    response = match_response(request.message)
    response["is_mock"] = True
    await asyncio.sleep(response["latency_ms"] / 1000 * 0.1)  # 10% of mocked latency
    return JSONResponse(content=response, headers={"X-Mock-Backend": "true", "X-Provider": "mock-backend"})


@app.post("/api/chat/ask-stream")
async def chat_ask_stream(request: ChatRequest, token: str = Depends(verify_token)):
    """Mock SSE stream endpoint."""
    response = match_response(request.message)

    async def stream_generator():
        yield f"data: {json.dumps({'type': 'start', 'sessionId': request.sessionId})}\n\n"
        await asyncio.sleep(0.05)
        words = response["aiResponse"].split()
        for i, word in enumerate(words):
            yield f"data: {json.dumps({'type': 'token', 'token': word + ' '})}\n\n"
            await asyncio.sleep(0.02)
        yield f"data: {json.dumps({'type': 'end', 'ragStrategy': response['ragStrategy'], 'confidence': response['confidence'], 'confidence_score': response['confidence_score'], 'sourceChunks': response['sourceChunks'], 'citations': response['citations']})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/api/documents/upload")
async def upload_document(token: str = Depends(verify_token)):
    return {"documentId": 1, "filename": "test.txt", "status": "indexed"}


@app.get("/api/actuator/health")
async def health():
    return {"status": "UP", "components": {"db": "UP", "qdrant": "UP"}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)