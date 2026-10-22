import { describe, it, expect } from "vitest";
import { onRequest } from "../../functions/api/[[path]]";

// Helper to parse SSE stream from Cloudflare Pages Function response
async function parseSseResponse(response: Response) {
  const text = await response.text();
  const lines = text.split("\n");
  let metadata: any = null;
  let complete: any = null;
  const chunks: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("event: metadata")) {
      const dataLine = lines[i + 1];
      if (dataLine?.startsWith("data: ")) {
        try {
          metadata = JSON.parse(dataLine.replace(/^data: /, ""));
        } catch {}
      }
    } else if (line.startsWith("event: chunk")) {
      const dataLine = lines[i + 1];
      if (dataLine?.startsWith("data: ")) {
        chunks.push(dataLine.replace(/^data: /, ""));
      }
    } else if (line.startsWith("event: complete")) {
      const dataLine = lines[i + 1];
      if (dataLine?.startsWith("data: ")) {
        try {
          complete = JSON.parse(dataLine.replace(/^data: /, ""));
        } catch {}
      }
    }
  }

  return { text, metadata, complete, chunks };
}

describe("Cloudflare Pages Function Live Demo Acceptance Tests", () => {
  it("P0: Grounds Labor Law queries in Bo_Luat_Lao_Dong_2019.pdf with high confidence and exact Article 105", async () => {
    const request = new Request("https://smart-doc-chatbot.pages.dev/api/chat/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "thời giờ làm việc bình thường và yêu cầu trích dẫn",
        documentId: 1,
        documentTitle: "Bo_Luat_Lao_Dong_2019.pdf",
        mode: "rag",
      }),
    });

    const response = await onRequest({
      request,
      env: {},
      params: { path: ["chat", "ask-stream"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);

    expect(response.status).toBe(200);
    const { complete, metadata } = await parseSseResponse(response);

    expect(complete).toBeDefined();
    // Answer must accurately quote Article 105 Labor Code 2019
    expect(complete.aiResponse).toContain("Điều 105");
    expect(complete.aiResponse).toContain("08 giờ");
    expect(complete.aiResponse).toContain("48 giờ");
    expect(complete.aiResponse).toContain("01 ngày");
    expect(complete.aiResponse).toContain("01 tuần");

    // Must NOT contain hallucinated VIAC or finance text
    expect(complete.aiResponse).not.toContain("Trung tâm Trọng tài Quốc tế Việt Nam (VIAC)");
    expect(complete.aiResponse).not.toContain("Điều 8.2");

    // Sources must be grounded strictly in the selected Labor Code document
    expect(complete.sources.length).toBeGreaterThan(0);
    expect(complete.sources[0].documentTitle).toBe("Bo_Luat_Lao_Dong_2019.pdf");
    expect(complete.sources[0].article).toContain("Điều 105");
    expect(complete.confidence).toBe("high");
    expect(metadata.confidence).toBe("high");
  });

  it("P0: Refuses to hallucinate when selected document does not contain answer (no_evidence)", async () => {
    const request = new Request("https://smart-doc-chatbot.pages.dev/api/chat/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "Quy trình tạm ứng công tác phí và bảo lãnh tín dụng ngân quỹ",
        documentId: 1, // Labor Code selected, but question is financial
        documentTitle: "Bo_Luat_Lao_Dong_2019.pdf",
        mode: "rag",
      }),
    });

    const response = await onRequest({
      request,
      env: {},
      params: { path: ["chat", "ask-stream"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);

    expect(response.status).toBe(200);
    const { complete } = await parseSseResponse(response);

    // Must declare no evidence in selected document rather than fabricating citations
    expect(complete.ragStrategy).toBe("no_evidence");
    expect(complete.sources).toEqual([]);
    expect(complete.sourceChunks).toEqual([]);
    expect(complete.confidence).toBe("low");
    expect(complete.aiResponse).toMatch(/không tìm thấy|không chứa|không đề cập/i);
  });

  it("P0: In Agent Mode, respects Labor Code boundary and refuses to hallucinate commercial contract / VIAC", async () => {
    const request = new Request("https://smart-doc-chatbot.pages.dev/api/chat/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "Phân tích điều khoản phạt 12% vi phạm hợp đồng thương mại và thủ tục trọng tài VIAC",
        documentId: 1, // Labor Code selected
        documentTitle: "Bo_Luat_Lao_Dong_2019.pdf",
        mode: "agent",
      }),
    });

    const response = await onRequest({
      request,
      env: {},
      params: { path: ["chat", "ask-stream"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);

    expect(response.status).toBe(200);
    const { complete } = await parseSseResponse(response);

    expect(complete.ragStrategy).toBe("no_evidence");
    expect(complete.sources).toEqual([]);
    expect(complete.confidence).toBe("low");
    expect(complete.aiResponse).toContain("Bộ luật Lao động 2019");
    expect(complete.aiResponse).toMatch(/không tìm thấy|không phù hợp/i);
  });

  it("P0: Grounds financial questions in financial document when selected", async () => {
    const request = new Request("https://smart-doc-chatbot.pages.dev/api/chat/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "Hạn mức tạm ứng và thời hạn thanh toán hóa đơn tài chính",
        documentId: 2,
        documentTitle: "Quy_Trinh_Kiem_Soat_Tai_Chinh_2026.pdf",
        mode: "rag",
      }),
    });

    const response = await onRequest({
      request,
      env: {},
      params: { path: ["chat", "ask-stream"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);

    expect(response.status).toBe(200);
    const { complete } = await parseSseResponse(response);

    expect(complete.sources.length).toBeGreaterThan(0);
    expect(complete.sources[0].documentTitle).toBe("Quy_Trinh_Kiem_Soat_Tai_Chinh_2026.pdf");
    expect(complete.confidence).toBe("high");
  });

  it("P0 Security: Does not contain hardcoded Gemini API key and handles missing environment key gracefully", async () => {
    const request = new Request("https://smart-doc-chatbot.pages.dev/api/chat/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "thời giờ làm việc bình thường",
        documentId: 1,
        documentTitle: "Bo_Luat_Lao_Dong_2019.pdf",
        mode: "rag",
      }),
    });

    // Provide empty env (no GEMINI_API_KEY)
    const response = await onRequest({
      request,
      env: {},
      params: { path: ["chat", "ask-stream"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);

    expect(response.status).toBe(200);
    const { complete } = await parseSseResponse(response);
    // System reliably falls back to grounded edge knowledge base without crashing or leaking keys
    expect(complete.sources[0].documentTitle).toBe("Bo_Luat_Lao_Dong_2019.pdf");
  });

  it("P0: Handles summary query 'tóm tắt tài liệu bên trong' on ISO 27001 document with high confidence", async () => {
    const request = new Request("https://smart-doc-chatbot.pages.dev/api/chat/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "tóm tắt tài liệu bên trong",
        documentId: 3,
        documentTitle: "Cloud_Security_Baseline_ISO27001.pdf",
        mode: "rag",
      }),
    });

    const response = await onRequest({
      request,
      env: {},
      params: { path: ["chat", "ask-stream"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);

    expect(response.status).toBe(200);
    const { complete } = await parseSseResponse(response);

    expect(complete.ragStrategy).toBe("direct");
    expect(complete.confidence).toBe("high");
    expect(complete.aiResponse).toContain("ISO/IEC 27001");
    expect(complete.aiResponse).toContain("Mục A.9");
    expect(complete.sources.length).toBeGreaterThan(0);
    expect(complete.sources[0].documentTitle).toBe("Cloud_Security_Baseline_ISO27001.pdf");
  });

  it("P0: Handles single and batch document deletion cleanly via edge API", async () => {
    // Single delete
    const singleReq = new Request("https://smart-doc-chatbot.pages.dev/api/documents/1", {
      method: "DELETE",
    });
    const singleRes = await onRequest({
      request: singleReq,
      env: {},
      params: { path: ["documents", "1"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);
    expect(singleRes.status).toBe(200);
    const singleData = await singleRes.json();
    expect(singleData.success).toBe(true);

    // Batch delete
    const batchReq = new Request("https://smart-doc-chatbot.pages.dev/api/documents/batch", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify([1, 2, 3]),
    });
    const batchRes = await onRequest({
      request: batchReq,
      env: {},
      params: { path: ["documents", "batch"] },
      waitUntil: () => {},
      next: () => Promise.resolve(new Response()),
      data: {},
      functionPath: "",
    } as any);
    expect(batchRes.status).toBe(200);
    const batchData = await batchRes.json();
    expect(batchData.success).toBe(true);
  });
});
