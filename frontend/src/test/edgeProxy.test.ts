import { afterEach, describe, expect, it, vi } from "vitest";
import { onRequest } from "../../functions/api/[[path]]";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("production Pages API proxy", () => {
  it("forwards authentication requests to the configured backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ authenticated: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new Request("https://pages.example/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer client-token" },
      body: JSON.stringify({ username: "user", password: "pass" }),
    });

    const response = await onRequest({
      request,
      env: { BACKEND_URL: "https://backend.example/api" },
    } as Parameters<typeof onRequest>[0]);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBeInstanceOf(URL);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "https://backend.example/api/auth/login",
    );
    const fetchOptions = fetchMock.mock.calls[0][1] as RequestInit;
    const forwardedHeaders = new Headers(fetchOptions.headers);
    expect(fetchOptions.method).toBe("POST");
    expect(forwardedHeaders.get("Authorization")).toBe("Bearer client-token");
    expect(forwardedHeaders.get("X-Forwarded-Host")).toBe("pages.example");
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ authenticated: true });
  });

  it("fails closed when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));
    const response = await onRequest({
      request: new Request("https://pages.example/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: "admin", password: "anything" }),
      }),
      env: { BACKEND_URL: "https://backend.example/api" },
    } as Parameters<typeof onRequest>[0]);

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ error: "UpstreamUnavailable" });
  });

  it("rejects non-HTTPS backend configuration", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const response = await onRequest({
      request: new Request("https://pages.example/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: "admin", password: "anything" }),
      }),
      env: { BACKEND_URL: "http://backend.example/api" },
    } as Parameters<typeof onRequest>[0]);

    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
