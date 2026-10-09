import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// The module caches the token in module state, so reset between tests.
async function importCsrf() {
  return import("./csrf");
}

describe("csrf", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.cookie = "XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("bootstraps the token from the /csrf endpoint and sends it as a header", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ token: "token-1" }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrf = await importCsrf();

    await csrf.bootstrapCsrfToken();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/csrf");
    expect(csrf.csrfHeaders()).toEqual({ "X-XSRF-TOKEN": "token-1" });
  });

  it("retries while the endpoint errors and keeps the token once it succeeds", async () => {
    let calls = 0;
    const fetchMock = vi.fn(async () => {
      calls += 1;
      if (calls < 3) return new Response("cold start", { status: 503 });
      return new Response(JSON.stringify({ token: "token-2" }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const csrf = await importCsrf();

    const pending = csrf.bootstrapCsrfToken();
    await vi.advanceTimersByTimeAsync(6_000);
    await pending;

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(csrf.csrfHeaders()).toEqual({ "X-XSRF-TOKEN": "token-2" });
  });

  it("resolves without a token after three failed attempts", async () => {
    const fetchMock = vi.fn(async () => new Response("down", { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    const csrf = await importCsrf();

    const pending = csrf.bootstrapCsrfToken();
    await vi.advanceTimersByTimeAsync(6_000);
    await pending;

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(csrf.csrfHeaders()).toEqual({});
  });

  it("falls back to the XSRF-TOKEN cookie when no token was bootstrapped", async () => {
    document.cookie = "XSRF-TOKEN=cookie-token";
    const csrf = await importCsrf();

    expect(csrf.csrfHeaders()).toEqual({ "X-XSRF-TOKEN": "cookie-token" });
  });

  it("ensureCsrfHeaders refetches when force=true", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ token: "token-3" }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    const csrf = await importCsrf();

    await csrf.bootstrapCsrfToken();
    await csrf.ensureCsrfHeaders(true);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(csrf.csrfHeaders()).toEqual({ "X-XSRF-TOKEN": "token-3" });
  });
});
