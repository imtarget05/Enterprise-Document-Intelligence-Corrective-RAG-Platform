# Kiểm chứng đồ án — 12/11/2026

## Phạm vi và phiên bản

Nhánh `codex/live-validation-ci`, PR #39. Đã đồng bộ thay đổi mới trên `main`
(`0c7dcf3`), giữ nguyên migration V23 từ main và bổ sung test PostgreSQL.
Các kết quả bên dưới được chạy lại trên bản có sửa JSON mặc định của Jackson 3.

## Sửa lỗi đã thực hiện

- Chuẩn hóa đường dẫn GHCR về chữ thường trong cả build và deploy.
- Image Python cài `requirements.txt` có thật thay vì tham chiếu Poetry thiếu.
- Router chạy đúng `app.main:app`; loại file môi trường khỏi build context.
- Backend gửi `X-Internal-Token` khi gọi agent.
- Chat JSON dùng constructor không tham số, giữ mặc định `false` khi thiếu cờ tùy chọn.
- Smoke test yêu cầu dữ kiện Paris và strategy thành công; không chấp nhận error/no_evidence.
- Regression test smoke được thêm vào CI.
- Agent truyền khóa checkpoint theo người dùng + phiên cho cả chat, stream và duyệt HITL.
- Corrective retrieval không còn lỗi biến `variants` chưa khởi tạo khi lượt đầu rỗng.
- Agent gửi token nội bộ cho chat và embedding tới router.
- Image agent dùng PyTorch CPU; kích thước image giảm từ 3.649.797.948 xuống 622.150.238 byte.

## Kết quả đã xác minh

| Kiểm tra | Kết quả | Bằng chứng |
|---|---|---|
| Toàn bộ backend | 411 tests, 0 failures/errors/skips | `backend-tests.json` |
| Regression smoke | 3 tests PASS | `python3 -m unittest discover -s scripts/tests` |
| Regression retrieval grader | 6 tests PASS | `python3 -m unittest discover -s eval/tests -p test_live_benchmark_scoring.py` |
| Full-stack E2E, bật idempotency nghiêm ngặt | 2/2 PASS | `fullstack-e2e.txt` |
| RAG smoke, Cloudflare inference thật | PASS | `rag-smoke.txt` |
| Agent trên image CPU | 352 PASS, 1 SKIP | `agent-tests.txt` |
| Smoke qua agent, không fallback về Java RAG | PASS, strategy=agentic | `agent-smoke.txt` |
| RAG pháp lý 30 câu | 30 phản hồi và 30 phản hồi có nguồn; 28 direct, 2 corrective | `legal-rag30-trace.json` |
| Build image router cục bộ | PASS, khởi động và health HTTP 200 | Docker `edi-router-validation` |
| Build backend/router trên GitHub Actions | PASS | Run `43244704371` |

## Giới hạn quan trọng của agent smoke

Agent smoke xác nhận đường backend → agent → router hoạt động. Trace thực tế dùng
`[Deep Reasoning - low document confidence]` với retrieval score 0. Đây **không phải**
bằng chứng truy xuất tài liệu thành công. Luồng hiện tại chưa chuyển `document_ids`
ở `AgentClient.invokeAgent`; ingestion vào Qdrant và truyền citation về frontend
còn cần hoàn thiện trước khi nghiệm thu agent RAG có căn cứ. Classic RAG đã kiểm
tra riêng bằng PostgreSQL chunks và các trace trong báo cáo này.

## Đánh giá chất lượng: chưa được coi là đạt toàn bộ

Trace 30 câu là bằng chứng thực thi, không phải điểm đúng nội dung 100%.
A1, A2, A14 trả lời không tìm thấy thông tin dù thuộc nhóm có đáp án.
Các trường `result_manual` vẫn để trống: chưa có chấm nội dung độc lập theo rubric.
Nguồn tham chiếu/citation tồn tại không tự chứng minh câu trả lời đúng.

Bộ 3 câu kỹ thuật khớp corpus 8D cho Hit@5=100%, Recall@5=100%, MRR=1,
nhưng keyword answer score=0% trong lần chạy này. Đây là so khớp từ khóa tiếng Anh,
không phải chấm ngữ nghĩa câu trả lời tiếng Việt. Xem `engineering-benchmark.json`.
Không dùng bộ 31 câu kiến trúc với corpus 8D để tuyên bố độ chính xác RAG.

## Môi trường thực thi

Backend `http://127.0.0.1:8080/api`; PostgreSQL sạch riêng `edi_validation_20261112`;
Redis, Kafka, Qdrant cục bộ; router dùng Cloudflare Workers AI thật. Không sử dụng mock backend.
Các dịch vụ cục bộ chỉ bind cổng ra `127.0.0.1`.

Đây là kiểm chứng cục bộ, không thay thế production canary. Chưa có URL EDI preview
hoạt động được xác nhận trong tài khoản cloud đã kiểm tra. Không đánh dấu canary
SKIP là PASS. Không commit token, API key hay file OAuth.

## IncidentIQ

Repo IncidentIQ đã có báo cáo `docs/evidence/preview-e2e-validation-2026-11-12.md`
trên nhánh `agent/prod-hardening-incidentiq`: luồng upload/ETL/RAG, cách ly tenant,
MCP và các lỗi live đã sửa. Trong phiên này kiểm tra lại preview readiness HTTP 200:
D1, Vectorize, Workers AI, ETL queue đều `ok`; production health cũng trả `ok`.
Kết quả CI/Sonar PASS trước đó thuộc PR #1 và commit của PR đó; không suy rộng
thành PASS cho mọi thay đổi mới trong nhánh hardening.

## Lệnh tái kiểm tra

```sh
mvn -f backend/pom.xml test
python3 -m unittest discover -s scripts/tests
python3 scripts/production_smoke.py --base-url http://127.0.0.1:8080/api --mode rag
python3 eval/run_rag_30.py --base-url http://127.0.0.1:8080/api --output /tmp/legal-rag30.json
cd frontend
E2E_API_URL=http://127.0.0.1:8080/api E2E_BASE_URL=http://127.0.0.1:8080 E2E_EXPECT_IDEMPOTENT=1 npx playwright test e2e/fullstack-smoke.spec.ts
```

## Kiểm chứng đóng gói cuối

Image CPU đã build lại sau các bản sửa agent, khởi động health HTTP 200 và chạy
352 tests PASS/1 SKIP trên chính image đó. Test dùng HF_HUB_OFFLINE và
TRANSFORMERS_OFFLINE để không tải model bên ngoài trong suite cục bộ. Đây không
phải bỏ qua test: chỉ ngăn network/model download ngoài phạm vi unit tests.

Run build cloud cuối: https://github.com/imtarget05/Enterprise-Document-Intelligence-Corrective-RAG-Platform/actions/runs/43248300349
Run GPU cũ đã được hủy do được thay thế bằng image CPU.
