import { createServer } from "node:http";
import { createGateway } from "./gateway.js";
const backendUrl = process.env.BACKEND_URL;
if (!backendUrl) throw new Error("BACKEND_URL required");
const gateway = createGateway({ backendUrl });
const server = createServer(async (req, res) => {
  try {
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 1024 * 1024) {
        res.writeHead(413).end();
        return;
      }
      chunks.push(chunk);
    }
    const headers = new Headers();
    for (const [key, value] of Object.entries(req.headers)) {
      if (value !== undefined)
        headers.set(key, Array.isArray(value) ? value.join(",") : value);
    }
    // Use configured local origin instead of trusting Host for authorization decisions.
    const origin =
      process.env.PUBLIC_ORIGIN ??
      "http://localhost:" + (process.env.PORT ?? "9100");
    const request = new Request(new URL(req.url ?? "/", origin), {
      method: req.method,
      headers,
      body: chunks.length ? Buffer.concat(chunks) : undefined,
    });
    const response = await gateway(request);
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch {
    res.writeHead(500).end("Request failed");
  }
});
server.requestTimeout = 30000;
server.headersTimeout = 10000;
server.listen(
  Number(process.env.PORT ?? 9100),
  process.env.HOST ?? "127.0.0.1",
  () => {
    const address = server.address();
    if (address && typeof address !== "string")
      console.log(JSON.stringify({ listening: address.port }));
  },
);
