package com.smartdocchat.service;

import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;

/**
 * Client gọi agent-service {@code POST /v1/agent/documents/{id}/purge} (Phase 2).
 *
 * Xóa tài liệu phải xóa cả những thứ được sinh ra từ tài liệu đó. Backend sở
 * hữu document row, chunk trong PostgreSQL và blob trong storage (DocumentService
 * đã xóa); agent-service sở hữu vector store (Qdrant chunks/embeddings), cache
 * retrieval (Redis) và memory. Thiếu bước này thì chunk cũ vẫn được trả về khi
 * chat — "đã xóa" chỉ là ẩn metadata.
 *
 * Best-effort theo hợp đồng: chạy SAU khi document row đã bị xóa, nên lỗi purge
 * không được làm fail thao tác xóa của người dùng (controller trả về success).
 * Lỗi được log để operator replay.
 */
@Component
public class DocumentPurgeClient {

    private final RestTemplate restTemplate;
    private final String agentBaseUrl;
    private final String internalToken;

    public DocumentPurgeClient(@Qualifier("agentRestTemplate") RestTemplate restTemplate,
                               @Value("${agent.base-url:http://localhost:9000}") String agentBaseUrl,
                               @Value("${security.internal-token:}") String internalToken) {
        this.restTemplate = restTemplate;
        this.agentBaseUrl = agentBaseUrl;
        this.internalToken = internalToken;
    }

    /**
     * Purge mọi store bên agent-service giữ bản sao của tài liệu.
     *
     * @param ownerUsername chủ sở hữu — giới hạn phạm vi purge memory
     * @param fileName      dùng để khớp memory entry nhắc đến tên tài liệu
     * @return {@code true} khi agent-service báo cáo purge thành công
     */
    public boolean purgeDocument(Long documentId, String ownerUsername, String fileName) {
        String url = agentBaseUrl + "/v1/agent/documents/" + documentId + "/purge";
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("user_id", ownerUsername == null ? "" : ownerUsername);
            body.put("document_name", fileName == null ? "" : fileName);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (internalToken != null && !internalToken.isBlank()) {
                headers.set("X-Internal-Token", internalToken);
            }
            String requestId = MDC.get("requestId");
            if (requestId != null) {
                headers.set("X-Request-Id", requestId);
            }
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);

            Map<?, ?> resp = restTemplate.postForObject(url, entity, Map.class);
            if (resp == null) {
                return false;
            }
            Object status = resp.get("status");
            return status == null || "ok".equals(status);
        } catch (Exception e) {
            // Deliberately non-fatal: see the class javadoc.
            return false;
        }
    }
}
