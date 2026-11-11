import { describe, it, expect } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { createGateway } from "../src/gateway.js";

function fixture() {
  const calls: Request[] = [];
  const backend: typeof fetch = async (input, init) => {
    const req = new Request(input, init);
    calls.push(req);
    if (req.headers.get("Authorization") !== "Bearer valid-user-token")
      return Response.json({ error: "unauthorized" }, { status: 401 });
    return Response.json(
      new URL(req.url).pathname.endsWith("/9")
        ? { id: 9, filename: "owned.txt" }
        : [{ id: 9, filename: "owned.txt" }],
    );
  };
  const gateway = createGateway({
    backendUrl: "https://api.internal",
    fetch: backend,
  });
  const fetcher: typeof fetch = (input, init) =>
    gateway(new Request(input, init));
  const client = new Client({ name: "integration-client", version: "1" });
  return {
    calls,
    client,
    transport: new StreamableHTTPClientTransport(
      new URL("http://localhost/mcp"),
      {
        fetch: fetcher,
        requestInit: { headers: { Authorization: "Bearer valid-user-token" } },
      },
    ),
    gateway,
  };
}
describe("Enterprise official SDK gateway", () => {
  it("initializes, lists and calls owner-scoped Spring API with caller token", async () => {
    const f = fixture();
    await f.client.connect(f.transport);
    try {
      expect((await f.client.listTools()).tools.map((t) => t.name)).toContain(
        "get_document",
      );
      const result = await f.client.callTool({
        name: "get_document",
        arguments: { document_id: 9 },
      });
      expect(result.isError).not.toBe(true);
      expect(JSON.parse((result.content as any)[0].text)).toMatchObject({
        id: 9,
      });
      expect(
        f.calls.every(
          (r) => r.headers.get("Authorization") === "Bearer valid-user-token",
        ),
      ).toBe(true);
    } finally {
      await f.client.close();
    }
  });
  it("rejects missing credentials before protocol initialization", async () => {
    expect(
      (
        await fixture().gateway(
          new Request("http://localhost/mcp", { method: "POST", body: "{}" }),
        )
      ).status,
    ).toBe(401);
  });
  it("rejects invalid credentials based on Spring, not token presence", async () => {
    const response = await fixture().gateway(
      new Request("http://localhost/mcp", {
        method: "POST",
        headers: { Authorization: "Bearer invalid" },
        body: "{}",
      }),
    );
    expect(response.status).toBe(401);
  });
  it("rejects owner identity arguments before downstream tool call", async () => {
    const f = fixture();
    await f.client.connect(f.transport);
    try {
      const result = await f.client.callTool({
        name: "get_document",
        arguments: { document_id: 9, user_id: "foreign" },
      });
      expect(result.isError).toBe(true);
      expect(f.calls.some((r) => new URL(r.url).pathname.endsWith("/9"))).toBe(
        false,
      );
    } finally {
      await f.client.close();
    }
  });
});
