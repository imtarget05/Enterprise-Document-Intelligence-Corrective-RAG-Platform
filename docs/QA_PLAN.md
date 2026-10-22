# QA PLAN — SmartDocumentChatbot (tiếng Việt)

**Dự án:** SmartDocumentChatbot — Nền tảng RAG hỏi đáp tài liệu doanh nghiệp (đa ngôn ngữ)  
**Đường dẫn:** `/Users/mainguyenbinhtan/Downloads/SmartDocumentChatbot/docs/QA_PLAN.md`  
**Bản soạn thảo:** QA Lead / Test Architect  
**Ngày:** 22-10-2026  
**Trạng thái:** Bản mô tả chi tiết

---

## 1. Test Strategy

### 1.1 Mục tiêu QA
1. **Câu trả lời đúng:** RAG pipeline phải trả lời dựa trên evidence từ tài liệu đã index, không bịa đặt.
2. **Có nguồn (citations):** Mọi câu trả lời có căn cứ phải kèm mảng `sources` (documentTitle, documentNumber, chunkId) và metadata pháp lý (article/clause/point) chỉ khi xác thực được.
3. **Biết từ chối (không hallucinate):** Truy vấn không có tài liệu phù hợp → trả về `"không xác định"` / `no_evidence`, không fallback sang kiến thức chung/web search trừ khi được yêu cầu rõ ràng.
4. **HITL workflow đúng:** Hàng chờ duyệt, badge số, luồng duyệt/từ chối/thực hiện, khôi phục sau sự cố (crash recovery) phải đúng.

### 1.2 Phạm vi kiểm thử
**Trong phạm vi (in-scope):**
- RAG / CRAG 5 lớp: retrieve → relevance grade → knowledge refinement → web search fallback → answer grading/abstention.
- HITL approval queue (badge count vs pending count, approve/reject, crash recovery, snapshot).
- Chat streaming (SSE): status → metadata → content → complete.
- SourceCitations component, phần hiển thị nguồn.
- LLM Router: Ollama (qwen2.5:3b) chính, Cloudflare Workers AI fallback.
- Multi-agent routing (LangGraph agent service).
- Bảo mật: prompt injection, rò rỉ PII trong log, rate limiting (Bucket4j), circuit breaker (Resilience4j), cache isolation theo principal.
- Tính năng phi chức năng: độ chính xác, độ trễ streaming, khả năng tiếp cận (a11y).

**Ngoài phạm vi (out-of-scope):**
- Huấn luyện mô hình LLM embeddings (finetune/).
- Kinh doanh, định giá, SLA hợp đồng với nhà cung cấp Ollama/Cloudflare.
- Di dời dữ liệu sản xuất thực tế (Neon production).

### 1.3 Thí dụ kiểm thử (Test Pyramid)
| Cấp | Mục tiêu | Công cụ | Vị trí | Quy mô ước tính |
|-----|----------|---------|--------|-----------------|
| Unit | Logic đơn vị Java + Python | JUnit / pytest | `backend/src/test`, `agent/tests`, `llm-router` | Backend ~310-395 test; Agent ~221 test; Router ~80 test |
| Integration | Kết nối DB (Neon/Flyway), Qdrant, Redis, Kafka, R2 | Testcontainers / pytest | `backend/src/test/integration`, `agent/tests` | Các kelas integration |
| Contract | API Chat/Agent/Router/Documents | REST Assured / pytest | `backend`, `agent`, `llm-router` | Endpoints công khai |
| E2E (Playwright) | Luồng chat UI, duyệt HITL, citations | Playwright | `frontend/e2e/` | 7 spec (chat, admin, auth, documents, fullstack-smoke, auth, browser-auth-live) |
| Eval | Fixture smoke + live benchmark | pytest eval | `eval/` | 28 test fixture smoke; live benchmark bị chặn bên ngoài |

### 1.4 Chất lượng phi chức năng
- **Accuracy:** citation rate 100% cho câu trả lời có căn cứ; hallucination rate 0% cho truy vấn ngoài phạm vi (không có tài liệu).
- **Security:** Không ghi PII vào log gateway (chỉ counts + hash); prompt injection bị chặn trước khi gọi agent; rate limiting Bucket4j; circuit breaker Resilience4j; agent calls phạm vi principal + cache isolation.
- **Performance:** Độ trễ SSE streaming (time-to-first-token, toàn bộ luồng) trong ngưỡng chấp nhận được; rate-limit không chặn lừa người dùng thường.
- **Accessibility:** WCAG 2.1 AA cho SourceCitations, ApprovalsTable, ChatPage (đã có `ChatPage.a11y.test.tsx`).

---

## 2. Môi trường kiểm thử

| Thành phần | Công nghệ chi tiết | Ghi chú |
|------------|-------------------|---------|
| Backend | Java 17, Maven, Spring Boot 3.2, PostgreSQL (Neon), Flyway migrations V1–V17 | `cd backend && mvn test` |
| Agent service | Python 3.11, FastAPI, LangGraph, Qdrant (local/cloud), Redis làm store HITL | `agent/.venv/bin/python -m pytest agent/tests tests -q` |
| LLM Router | Ollama (`qwen2.5:3b`) chính, Cloudflare Workers AI fallback | `cd llm-router && .venv/bin/python -m pytest -q` |
| Frontend | React 18, TypeScript, Vite, Vitest, Playwright | `cd frontend && npm test` |
| Eval | `mock_backend.py` (cổng 8081), `golden_dataset.json` (50 cặp), `questions.json` (30 câu hỏi) | `pytest eval` hoặc `python eval/run_fixture_eval.py` |
| Live benchmark | `python eval/run_live_benchmark.py --base-url http://localhost:8080/api` | Yêu cầu stack sống, **bị chặn bởi dependency bên ngoài** |

Biến môi trường quan trọng: `NEON_DATABASE_URL`, `QDRANT_URL`, `OLLAMA_BASE_URL`, `CLOUDFLARE_API_TOKEN`, `REDIS_URL`, `R2_*`, `HITL_FAIL_CLOSED` (mặc định `true` ngoại trừ local/dev/test).

---

## 3. Danh sách test case ưu tiên (P0/P1/P2)

Tất cả ít nhất 20 test case, nhóm theo vùng:

### 3.1 RAG / CRAG pipeline (S3 fix)

| ID | Ưu tiên | Mô tả test case | Kết quả mong đợi | Cách kiểm tra |
|----|---------|-----------------|------------------|---------------|
| RAG-01 | P0 | Truy vấn không khớp tài liệu nào | Trả về `"không xác định"` / `no_evidence`, không fallback web search | Gọi `/api/chat` với câu hỏi ngoài corpus; assert không có `sources`, confidence thấp |
| RAG-02 | P0 | Truy vấn có chứng cứ | Câu trả lời kèm `sources` có `documentId`, `article`, `clause`, `point`, `score` | Assert mảng `sources` không rỗng và mỗi item có các trường trên |
| RAG-03 | P0 | `buildSources()` trả về rỗng | Trả về `"không xác định"` | Mock retrieval rỗng; assert câu trả lời từ chối |
| RAG-04 | P1 | LLM thất bại | Sinh `synthesizeExtractiveLegalAnswer` từ chunks; nếu không có chunk → `"không xác định"` | Inject lỗi LLM; assert câu trả lời trích xuất từ chunk hoặc từ chối |
| RAG-05 | P0 | `web_search` / `general_knowledge` chỉ khi `webSearch=true` rõ ràng | Không fallback khi không yêu cầu | Gọi với `webSearch=false`/không có; assert không gọi web search |
| RAG-06 | P1 | Vòng lặp cải thiện (corrective loop): confidence thấp → reformulate → re-retrieve → merge top-K | Độ tin cậy tăng hoặc từ chối có căn cứ | Mock confidence thấp lần 1, cao lần 2; assert reformulation được gọi và merge top-K |
| RAG-07 | P0 | Prompt injection bị chặn trước khi gọi agent | Yêu cầu bị từ chối/an toàn, không rò rỉ system prompt | Gửi payload injection; assert agent không được gọi và trả về lỗi an toàn |

### 3.2 HITL approval queue (S2 fix)

| ID | Ưu tiên | Mô tả test case | Kết quả mong đợi | Cách kiểm tra |
|----|---------|-----------------|------------------|---------------|
| HITL-01 | P0 | Badge hiển thị số API (raw pending), không phải `pending.length - decisions.length` | Badge `"Đang chờ duyệt: 5"` khi count: 5 có 2 dòng đã quyết | Gọi API approvals; so sánh badge UI với `pending` count từ API |
| HITL-02 | P0 | count: 5 với 2 dòng đã quyết → badge hiển thị "Đang chờ duyệt: 5" | Badge đúng 5 | Unit test `ApprovalsTable` + API controller |
| HITL-03 | P0 | Duyệt/từ chối chuyển pending → approved/rejected/executed | Trạng thái luồng đúng | Playwright e2e: click Approve/Reject; assert trạng thái chuyển |
| HITL-04 | P1 | Khôi phục sự cố: approved nhưng chưa thực hiện → tiếp tục từ snapshot (gap to document) | Side effect được thực hiện lại sau khởi động lại | Simulate crash sau approved, trước executed; assert snapshot được resume |
| HITL-05 | P0 | `HITL_FAIL_CLOSED` mặc định `true` (ngoại trừ local/dev/test) | Các môi trường staging/prod fail-closed | Kiểm tra biến môi trường và mã guard |

### 3.3 Citations & sources

| ID | Ưu tiên | Mô tả test case | Kết quả mong đợi | Cách kiểm tra |
|----|---------|-----------------|------------------|---------------|
| CIT-01 | P0 | Mọi câu trả lời có căn cứ có mảng `sources` | `sources` có `documentTitle`, `documentNumber`, `chunkId` | Assert từng grounded answer |
| CIT-02 | P1 | Metadata pháp lý (article/clause/point) chỉ khi xác thực được, null không bịa đả | Các trường null khi không có bằng chứng | Assert không có giá trị bịa đặt |
| CIT-03 | P2 | Nội dung nguồn bị cắt ngắn ở 300 ký tự | `content.length <= 300` | Assert độ dài |

### 3.4 Mock / hardcoded answers (rủi ro)

| ID | Ưu tiên | Mô tả test case | Kết quả mong đợi | Cách kiểm tra |
|----|---------|-----------------|------------------|---------------|
| MOCK-01 | P1 | `mock_backend.py` MOCK_RESPONSES: không câu trả lời hardcoded nào mâu thuẫn với RAG thực | Không có mâu thuẫn | So sánh MOCK_RESPONSES với golden_dataset / RAG thực |
| MOCK-02 | P0 | `golden-049` / `golden-050` có placeholder `"câu trả lời mẫu"` | Thay bằng câu trả lời thực hoặc đánh dấu là placeholder | Đọc `eval/golden_dataset.json` dòng 917-945; đánh dấu P0 fix |

### 3.5 Frontend UX

| ID | Ưu tiên | Mô tả test case | Kết quả mong đợi | Cách kiểm tra |
|----|---------|-----------------|------------------|---------------|
| UI-01 | P0 | `ApprovalsTable` badge đúng, trạng thái approve/reject (pending/working/approved/rejected/error) | Badge và state machine đúng | Vitest `ApprovalsTable.test.tsx` + Playwright |
| UI-02 | P1 | `SourceCitations` render trích dẫn chính xác | Citations hiển thị đúng | Vitest `SourceCitations.test.tsx` |
| UI-03 | P1 | `ChatPage` SSE streaming: status → metadata → content → complete | Thứ tự sự kiện đúng | Playwright `chat-ui.spec.ts`, `chat-flow.spec.ts` |

### 3.6 Security

| ID | Ưu tiên | Mô tả test case | Kết quả mong đợi | Cách kiểm tra |
|----|---------|-----------------|------------------|---------------|
| SEC-01 | P0 | Không PII trong log gateway (chỉ counts + sha) | Log không chứa PII thuần túy | Security grep + log audit |
| SEC-02 | P1 | Rate limiting (Bucket4j) | Giới hạn yêu cầu | Test interceptor/rate limit |
| SEC-03 | P1 | Circuit breaker (Resilience4j) | Ngắt mạch khi LLM/error | Test circuit breaker state |
| SEC-04 | P1 | Agent calls phạm vi principal + cache isolation | Cache bị cách ly theo người dùng | Test `DocumentServiceOwnerCacheIsolationTest` |

**Tổng: 23 test case (12 P0, 7 P1, 4 P2).**

---

## 4. Test data management

- `eval/golden_dataset.json`: 50 cặp QA (golden-001 … golden-050). Lưu ý: golden-049, golden-050 là placeholder `"Câu trả lời mẫu cho phụ case..."` → cần thay bằng câu trả lời thực hoặc đánh dấu placeholder (MOCK-02).
- `eval/questions.json`: 30 câu hỏi kèm `expected_answer_contains`, `expected_source_keywords`, `expected_min_confidence`.
- `eval/fixtures/`: `8d_failure_risk_fixture.txt`, `rag_nghithu_fixture.txt` dùng cho fixture smoke.
- `eval/mock_backend.py`: `MOCK_RESPONSES` (~30 mục), chạy trên cổng 8081 cho eval không cần LLM thực.
- Quy tắc: dữ liệu eval không được commit PII thực; sensitive data dùng fixture giả tạo.

---

## 5. Tự động hóa & CI/CD

| Pipeline | Lệnh | Quy mô | Ghi chú |
|----------|------|--------|---------|
| Backend | `cd backend && mvn test` | ~310–395 test, 53+ lớp test | JUnit, bao gồm integration + security |
| Agent | `agent/.venv/bin/python -m pytest agent/tests tests -q` | ~221 test | FastAPI/LangGraph |
| LLM Router | `cd llm-router && .venv/bin/python -m pytest -q` | ~80 test | Ollama + Workers AI |
| Frontend | `cd frontend && npm test` | 104 unit + 7 e2e | Vitest + Playwright |
| Eval | `pytest eval` hoặc `python eval/run_fixture_eval.py` | 28 test fixture smoke | Không cần stack sống |
| Live benchmark | `python eval/run_live_benchmark.py --base-url http://localhost:8080/api` | — | Yêu cầu stack sống, **bị chặn bởi dependency bên ngoài (Ollama/Qdrant)**; dùng fixture smoke làm thay thế |

CI gate: chạy toàn bộ suite trên PR; P0 phải xanh trước khi merge.

---

## 6. Tiêu chí xuất bản (Definition of Done / Release criteria)

- Tất cả test case **P0 pass**.
- **Citation rate 100%** cho câu trả lời có căn cứ.
- **Hallucination rate 0%** cho truy vấn ngoài phạm vi (không có tài liệu khớp).
- Badge HITL khớp với số pending từ API (không sai lệch `pending.length - decisions.length`).
- Trang bằng chứng (evidence page) được cập nhật sau mỗi lần chạy eval.
- Live benchmark được ghi chép là **bị chặn** (blocked) do dependency bên ngoài; dùng fixture smoke làm thay thế cho đến khi có môi trường tích hợp.

---

## 7. Rủi ro & khắc phục

| Rủi ro | Mức độ | Khắc phục |
|--------|--------|-----------|
| Live LLM benchmark bị chặn bởi dependency bên ngoài (Ollama/Qdrant) | Cao | Ghi chép trạng thái blocked; dùng `pytest eval` / fixture smoke làm thay thế cho đến khi có staging stack |
| Cửa sổ sự cố HITL: approved nhưng chưa có side effect được thực hiện | Trung bình | Ghi chép là known gap; lên kế hoạch durable outbox (outbox pattern) để đảm bảo thực hiện cuối cùng |
| Câu trả lời mock có thể drift khỏi RAG thực | Trung bình | Ngừng sử dụng `mock_backend.py` hoặc đồng bộ với golden_dataset; đánh dấu MOCK-01 |

---

### Tiện ích (verify command sau khi bạn lưu file)
```bash
ls -la /Users/mainguyenbinhtan/Downloads/SmartDocumentChatbot/docs/QA_PLAN.md
```

### Câu hỏi mở (cần xác định với équipe)
1. Mục tiêu con số cho độ trễ SSE streaming (time-to-first-token / tổng thời gian) là bao nhiêu ms?
2. Môi trường staging có Ollama/Qdrant sẵn sàng để chạy live benchmark chưa?
3. Ai là chủ sở hữu việc thay golden-049/golden-050 khỏi placeholder thành câu trả lời thực?