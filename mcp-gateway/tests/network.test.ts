import { it, expect } from "vitest";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
it("serves a real SDK client from the compiled child process", async () => {
  const backend = createServer((req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.headers.authorization !== "Bearer network-user") {
      res.writeHead(401).end("{}");
      return;
    }
    res.end(JSON.stringify([{ id: 7, filename: "network.txt" }]));
  });
  await new Promise<void>((resolve) => backend.listen(0, "127.0.0.1", resolve));
  const addr = backend.address();
  if (!addr || typeof addr === "string") throw new Error("no backend port");
  const child = spawn(process.execPath, ["dist/node.js"], {
    env: {
      ...process.env,
      BACKEND_URL: `http://127.0.0.1:${addr.port}`,
      PORT: "0",
      HOST: "127.0.0.1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const client = new Client({ name: "network-smoke", version: "1" });
  try {
    const port = await new Promise<number>((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("gateway startup timeout")),
        10000,
      );
      child.once("exit", (code) => {
        clearTimeout(timeout);
        reject(new Error(`gateway exit ${code}`));
      });
      child.stdout!.on("data", (data) => {
        const match = String(data).match(/"listening":(\d+)/);
        if (match) {
          clearTimeout(timeout);
          resolve(Number(match[1]));
        }
      });
    });
    await client.connect(
      new StreamableHTTPClientTransport(
        new URL(`http://127.0.0.1:${port}/mcp`),
        { requestInit: { headers: { Authorization: "Bearer network-user" } } },
      ),
    );
    const result = await client.callTool({
      name: "list_documents",
      arguments: {},
    });
    expect(result.isError).not.toBe(true);
    expect((result.content as any)[0].text).toContain("network.txt");
  } finally {
    await client.close();
    child.kill();
    await new Promise<void>((resolve) => backend.close(() => resolve()));
  }
}, 15000);
