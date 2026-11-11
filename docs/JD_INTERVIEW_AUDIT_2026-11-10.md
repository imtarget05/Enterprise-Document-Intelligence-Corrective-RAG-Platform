# Audit hai dự án theo JD Chuyên viên Lập trình AI

Ngày: 10/11/2026. Enterprise HEAD `7bf2c1a`; IncidentIQ HEAD `d081dc3`, cộng working-tree hiện có. Audit đọc mã, đối chiếu tài liệu và chạy một số bộ test local; không triển khai hoặc kiểm tra môi trường production. Không sửa mã ứng dụng. Các thay đổi có sẵn của người dùng được giữ nguyên.

## Kết luận

Hai dự án có nhiều nội dung phù hợp để chuẩn bị phỏng vấn AI Backend/Platform, nhưng chưa đủ bằng chứng hoàn thành toàn bộ JD. Enterprise nên là case chính về RAG và kiến trúc dịch vụ; IncidentIQ là case bổ sung về tenant, incident triage và ETL. Hai dự án không tự chứng minh 3–4 năm kinh nghiệm: cần lịch sử công việc, thời gian sở hữu hệ thống, trách nhiệm cá nhân, phối hợp đội nhóm và kết quả vận hành. Không suy ra số năm từ số dòng code, số framework hoặc test.

## Ma trận yêu cầu

| JD | Enterprise | IncidentIQ | Kết luận |
|---|---|---|---|
| AI/Data Platform, AI Server | Spring API, Python agent, LLM router, storage và orchestration | Python Worker API, D1, Workers AI, Vectorize | Có triển khai kiến trúc; chưa chứng minh vận hành toàn nền tảng |
| MCP Server | Tool registry qua REST tùy biến trong agent/routers/mcp.py | JSON-RPC tools/list và tools/call | Chưa đủ bằng chứng tương thích MCP client chuẩn |
| Contract, Auth/Authz | DTO, validation, JWT/internal token, owner/role checks | Tenant key hash, workspace role, tenant binding ở tool adapter | Có nền tảng; cần negative E2E tại ranh giới thực |
| Timeout, Retry, Idempotency | Client timeout, job retry/DLQ, cache/dedup; Kafka có lỗi semantics nêu bên dưới | Retry/DLQ ETL và idempotency header | Một phần; chưa khép kín khi concurrency và partial failure |
| Rate limit, Audit | Bộ chặn và audit service | API bucket, MCP Map theo isolate, audit DB | Có triển khai; MCP chưa có quota toàn hệ thống và audit có thể mất |
| Versioning, Backward compatibility | Event version, migration, document versions | /api/v1 và migration | Đặt version chưa chứng minh tương thích ngược; cần test client cũ/schema cũ |
| Testing | Agent suite và backend test có thể chạy | API và MCP suite có thể chạy | Bằng chứng local tốt trong phạm vi đã chạy |
| Monitoring, Logging, Tracing | Metrics, Langfuse, monitoring stack và tài liệu | Correlation ID, log cấu trúc, metric tables | Chưa có bằng chứng alert hoạt động, trace E2E và SLO thực tế trong audit này |
| LLM, Embedding, Vector DB, RAG | Spring lexical CRAG và Python Qdrant là hai nhánh khác nhau | Lexical + Vectorize và Workers AI, fallback | Nội dung phù hợp nhất JD; chất lượng live còn thiếu chứng cứ |
| ETL/ELT | Airflow upload DAG, ingestion jobs/Kafka | Inline/queued ETL, chunk/embed/index | Có document ETL; không tương đương DWH |
| Data Foundation, Data Mart/DWH/Lake | Chưa xác lập pipeline phân tích hoàn chỉnh | triage_metrics, rag_eval_runs schema | Khoảng trống lớn; chưa thấy mô hình fact/dimension, incremental aggregate, data quality và lineage đủ để nhận hoàn thành |
| Performance/Cost production | Router/cache/compressor/circuit-breaker có cơ chế | Quota, giới hạn retrieval và metric fields | Chưa có benchmark production và trước/sau tối ưu được kiểm chứng |
| Python, REST, Microservices, gRPC | Python agent/router, REST liên dịch vụ; backend chính Java | Python API và TypeScript adapter | Có bằng chứng Python/REST; chưa thấy triển khai gRPC. JD dùng REST/gRPC nên chưa tự động coi thiếu gRPC là loại |
| Phối hợp Backend/SRE/Security/Product | ADR, runbook, CI là tư liệu thảo luận | CI, preview controls, audit docs | Tài liệu không chứng minh kinh nghiệm phối hợp thực tế |
| Bằng đại học, 3–4 năm | Không xác minh từ repo | Không xác minh từ repo | Cần CV và lịch sử làm việc của ứng viên |

## Phát hiện trực tiếp cần ưu tiên

1. **Enterprise: nội dung workflow Kafka không đúng hợp đồng.** `DocumentIngestionConsumer.handleDocumentIngestedEvent` gọi `runWorkflow(event.fileName(), event.fileName())`. `DocumentWorkflowClient.runWorkflow(text, filename)` đưa đối số đầu vào body.text, không tải nội dung file. Nhánh này có thể phân loại tên file thay vì nội dung. Cần lấy text đã parse theo document ID và test tên file khác nghĩa hoàn toàn nội dung.
2. **Enterprise: retry annotation không bảo đảm retry lỗi workflow.** Client bắt lỗi rồi trả null; consumer xử lý null thành FAILED và bắt exception mà không ném lại. Khi emit FAILED thành công, lỗi gốc không tới cơ chế retry của framework. Cần phân biệt lỗi tạm thời/vĩnh viễn, ném lại lỗi tạm thời, kiểm chứng số lần retry và DLQ bằng broker thật hoặc embedded broker.
3. **Enterprise: chuyển từ DB job sang Kafka chưa có bảo đảm phục hồi được chứng minh.** Upload vẫn enqueue DB job rồi publishAsync; poller mặc định tắt. Publisher trả future nhưng caller không chờ/ghi trạng thái gửi; chưa thấy atomic outbox tại đường gọi được đọc. DB commit và publish có thể lệch nhau. Cần xác lập nguồn công việc chính, outbox/reconciliation, test mất broker ở thời điểm commit và replay sau restart.
4. **IncidentIQ: idempotency upload chưa an toàn khi đồng thời.** API SELECT theo key rồi INSERT; migration chỉ có CREATE INDEX, không UNIQUE cho cặp tenant/key. Hai request đồng thời có thể cùng vượt SELECT. Cần unique constraint, giải quyết duplicate ở DB và xử lý key trùng nhưng payload khác.
5. **MCP: cần tách tool adapter và giao thức MCP.** Enterprise expose /info, /tools, /call qua REST. IncidentIQ chỉ dispatch tools/list và tools/call, các method khác bị từ chối, kể cả initialize. Chưa nên nói đã tích hợp MCP client chuẩn; cần lifecycle/negotiation/transport và bài test client thực tế theo phiên bản giao thức chọn dùng.
6. **IncidentIQ: độ bền kiểm soát vận hành còn hạn chế.** callApiWorker dùng fetch không có deadline/abort tường minh; MCP rateLimitStore là Map trong process/isolate; auditToolExecution nuốt lỗi ghi DB. Cần deadline xuyên chuỗi, quota dùng chung và chính sách audit fail-open/fail-closed có cảnh báo.
7. **Enterprise HITL đã tiến triển so với tài liệu cũ, nhưng chưa chứng minh exactly-once.** Router hiện truyền idempotency key, cho resume approved và trả already_executed. Test durable_outbox hiện dùng store trong process và AsyncMock, không kill/restart tiến trình hoặc thực hiện external side effect. Resume một request approved đang chạy cũng cần kiểm tra concurrent execution/lease và dedup ở hệ thống nhận. Không lặp lại kết luận cũ rằng hoàn toàn không có resume; cũng không gọi đây là durable exactly-once đã chứng minh.
8. **Data Mart còn sơ bộ.** Migration 003 IncidentIQ tạo triage_metrics và rag_eval_runs. Tên hoặc comment “data mart” không đủ chứng minh có pipeline DWH. Cần luồng dữ liệu thật, grain rõ ràng, dedup, aggregate theo thời gian, backfill, kiểm tra freshness và reconciliation.

Các phát hiện trên là phân tích mã và thiếu bằng chứng; chưa thực hiện khai thác hoặc fault injection mới. Không coi thiếu bằng chứng là chắc chắn hệ thống đã gặp sự cố production.

## Kiểm chứng ngày 10/11

- Enterprise: `agent/.venv/bin/python -m pytest agent/tests tests -q -m 'not integration and not slow'`: 350 passed, 1 deselected, 18 warnings.
- Enterprise: Maven nhóm DocumentJobServiceTest, DocumentJobExecutorTest, DocumentEventPublisherTest, DocumentIngestionConsumerTest, DocumentServiceOwnerCacheIsolationTest, ChatServiceCitationTest: tổng 30 test, không failure/error/skip, exit 0. Không chạy full backend/frontend trong audit này.
- Enterprise router: không chạy được bằng môi trường riêng vì llm-router/.venv/bin/python không tồn tại. Không báo router suite xanh.
- IncidentIQ: `uv run --python 3.13 --frozen pytest -q tests/api`: 70 passed, 17 warnings. Log cho thấy pytest/plugin được nạp từ đường dẫn Python hệ thống 3.15; cần chạy lại bằng runner đã khóa hoàn toàn trước khi khẳng định CI parity Python 3.13. uv tạo lại .venv khi chạy.
- IncidentIQ MCP: typecheck thành công, 15 test passed.
- Chưa chạy lại dependency audit; số advisory trong README/qa-audit là lịch sử, không là kết quả mới.
- Chưa kiểm tra hosted CI, cloud deployment, live quality, load/cost, backup/restore hoặc alert delivery.
- Công cụ Jev không kết nối được sau một lần thử lại gateway; các nhận định được đối chiếu thủ công bằng mã nguồn. Không dùng kết quả mô hình để thay thế test.

## Học phỏng vấn theo thứ tự

1. Vẽ hai luồng tách biệt: upload -> parse/chunk -> storage/index; question -> auth -> retrieval -> evidence gate -> LLM -> citation/abstention. Với Enterprise phải chỉ rõ Spring PostgreSQL lexical khác Python Qdrant.
2. Giải thích một failure có thật trong thiết kế: DB thành công nhưng vector/Kafka thất bại. Nêu trạng thái, người sở hữu retry, deterministic ID, DLQ/replay, cách tránh duplicate và cách biết đã khôi phục.
3. Giải thích identity: principal từ auth quyết định tenant/owner; tenant trong tool argument không có quyền quyết định danh tính. Demo request tenant khác bị từ chối trước downstream call.
4. Giải thích timeout budget, retry chỉ lỗi transient và jitter; không retry side effect thiếu idempotency. Phân biệt at-least-once delivery với exactly-once business effect.
5. Thiết kế evaluation thật: corpus đại diện, câu hỏi có/không có đáp án, nhãn nguồn, train/test tách biệt; Recall@K/MRR cho retrieval, citation/groundedness cho answer; báo p50/p95, error rate và cost mỗi request thành công. Không dùng synthetic fixture như accuracy production.
6. Bổ sung lát cắt analytics: fact_triage theo một lần triage, dimension tenant/service/date, daily aggregate, watermark/incremental update, late arrivals, backfill và quality checks. Chỉ nhận đã làm khi chạy được dữ liệu thật và replay ra cùng kết quả.
7. Chuẩn bị câu chuyện cá nhân: phần tự thiết kế/viết, phần dùng thư viện hoặc AI hỗ trợ, quyết định đã thay đổi vì test hoặc sự cố, người phối hợp và kết quả đo được. Không nhận toàn bộ repo là đóng góp cá nhân nếu chưa có bằng chứng.

## Câu hỏi tự kiểm tra

| Câu hỏi | Điểm bắt buộc trong câu trả lời |
|---|---|
| Tại sao RAG thay vì fine-tune kiến thức? | Cập nhật dữ liệu, provenance, quyền truy cập; fine-tune phục vụ hành vi/định dạng khác với retrieval |
| Upload báo thành công nhưng không tìm thấy tài liệu? | Tách accepted/processed/indexed; job ID; queue lag; lỗi embed/index; reconcile D1/Postgres với vector store |
| Có retry là đã đáng tin cậy chưa? | Exception phải đến đúng retry owner; giới hạn attempt; backoff; idempotency; DLQ; test failure thật |
| Hai request cùng idempotency key? | Unique ở storage và atomic claim; payload hash; conflict semantics; kết quả replay |
| Rò tài liệu tenant khác phòng thế nào? | Principal binding, filter khi query, kiểm tra owner nguồn, cache key có scope, negative E2E |
| Cache giúp giảm chi phí ra sao? | Hit rate đo được, TTL/invalidation, scope và model/prompt version; so trước/sau trên cùng workload |
| Đã làm MCP chuẩn chưa? | Mô tả adapter hiện có và giới hạn; chứng minh handshake/client interoperability trước khi nhận đạt |
| Đã làm DWH chưa? | Document/vector index không là DWH; nêu mô hình phân tích và vận hành dữ liệu còn thiếu |
| Chứng minh 3–4 năm thế nào? | Lịch sử làm việc thật, ownership qua thời gian, incident, phối hợp, trade-off, tác động; portfolio chỉ hỗ trợ |

## Mốc đủ mạnh để bảo vệ kỹ thuật

Ưu tiên sửa và kiểm chứng lỗi Kafka/content, idempotency đồng thời, MCP lifecycle; sau đó chạy một luồng E2E thật cùng negative auth và fault injection. Giữ artifact cùng revision, config không chứa secret, dataset version, raw metric và giới hạn. Cuối cùng bổ sung analytics mart nhỏ và một buổi diễn tập recovery có log/trace/alert. Không cần thêm framework hoặc RLHF để che những thiếu hụt này.
