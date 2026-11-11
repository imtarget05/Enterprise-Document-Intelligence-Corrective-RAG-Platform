import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";

type Config = { backendUrl: string; fetch?: typeof fetch };
const tools: Tool[] = [
  {
    name: "list_documents",
    description: "List documents authorized for the caller",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "search_documents",
    description: "Search documents authorized for the caller",
    inputSchema: {
      type: "object",
      properties: { query: { type: "string", minLength: 1, maxLength: 1000 } },
      required: ["query"],
      additionalProperties: false,
    },
  },
  {
    name: "get_document",
    description: "Read a document through Spring owner/role authorization",
    inputSchema: {
      type: "object",
      properties: { document_id: { type: "integer", minimum: 1 } },
      required: ["document_id"],
      additionalProperties: false,
    },
  },
];

/** Uses the published SDK v1 transport, not the custom agent/mcp package.
 * https://ts.sdk.modelcontextprotocol.io/server
 * No shared service token: Spring resolves the original user's JWT principal.
 */
export function createGateway(
  config: Config,
): (request: Request) => Promise<Response> {
  const base = new URL(config.backendUrl);
  if (!["http:", "https:"].includes(base.protocol))
    throw new Error("HTTP backend required");
  const fetcher = config.fetch ?? fetch;
  return async (request) => {
    const url = new URL(request.url);
    if (url.pathname !== "/mcp")
      return new Response("Not found", { status: 404 });
    if (
      request.headers.has("Origin") &&
      request.headers.get("Origin") !== url.origin
    )
      return new Response("Origin forbidden", { status: 403 });
    const authorization = request.headers.get("Authorization") ?? "";
    if (!/^Bearer \S+$/.test(authorization))
      return Response.json({ error: "unauthorized" }, { status: 401 });
    const upstream = async (path: string) =>
      fetcher(new URL(path, base), {
        headers: { Authorization: authorization, Accept: "application/json" },
        signal: AbortSignal.timeout(15000),
        redirect: "error",
      });
    // This read-only authorization probe delegates JWT validity to the existing API.
    try {
      const auth = await upstream("/api/documents");
      await auth.body?.cancel();
      if (!auth.ok)
        return Response.json(
          { error: "backend_authorization_failed" },
          {
            status:
              auth.status === 401 || auth.status === 403 ? auth.status : 503,
          },
        );
    } catch {
      return Response.json({ error: "backend_unavailable" }, { status: 503 });
    }
    const server = new Server(
      { name: "enterprise-document-intelligence", version: "1.0.0" },
      { capabilities: { tools: {} } },
    );
    server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }));
    server.setRequestHandler(CallToolRequestSchema, async ({ params }) => {
      const args = params.arguments ?? {};
      const fail = (error: string) => ({
        isError: true,
        content: [{ type: "text" as const, text: JSON.stringify({ error }) }],
      });
      let path: string;
      if (params.name === "list_documents" && Object.keys(args).length === 0)
        path = "/api/documents";
      else if (
        params.name === "search_documents" &&
        Object.keys(args).length === 1 &&
        typeof args.query === "string" &&
        args.query.length > 0 &&
        args.query.length <= 1000
      )
        path = "/api/documents/search?q=" + encodeURIComponent(args.query);
      else if (
        params.name === "get_document" &&
        Object.keys(args).length === 1 &&
        Number.isSafeInteger(args.document_id) &&
        Number(args.document_id) > 0
      )
        path = "/api/documents/" + args.document_id;
      else return fail("invalid_tool_or_arguments");
      try {
        const response = await upstream(path);
        if (!response.ok) {
          await response.body?.cancel();
          return fail("backend_status_" + response.status);
        }
        const reader = response.body?.getReader();
        if (!reader) return fail("empty_backend_response");
        const chunks: Uint8Array[] = [];
        let size = 0;
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            size += value.length;
            if (size > 1024 * 1024) {
              await reader.cancel();
              return fail("backend_response_too_large");
            }
            chunks.push(value);
          }
        } finally {
          reader.releaseLock();
        }
        const body = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) {
          body.set(chunk, offset);
          offset += chunk.length;
        }
        const data = JSON.parse(new TextDecoder().decode(body));
        return { content: [{ type: "text", text: JSON.stringify(data) }] };
      } catch {
        return fail("backend_unavailable");
      }
    });
    const transport = new WebStandardStreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
      maxRequestBodySize: 1024 * 1024,
    });
    await server.connect(transport);
    try {
      return await transport.handleRequest(request);
    } finally {
      await server.close();
    }
  };
}
