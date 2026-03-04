"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface McpAppFrameProps {
  /** Rendered HTML content (from ui:// resource) */
  htmlContent: string;
  /** Tool name – used for a11y label */
  toolName: string;
  /** The raw tool result to push on ui/initialize */
  toolResult: unknown;
  /** Archestra agent ID – used to proxy tool calls back to the backend */
  agentId: string;
  /** Minimum height of the iframe (px). Default 320. */
  minHeight?: number;
}

type JsonRpcRequest = {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  params?: unknown;
};

type JsonRpcResponse = {
  jsonrpc: "2.0";
  id: string | number;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
};

/**
 * Renders an MCP App inside a sandboxed iframe and bridges the JSON-RPC
 * postMessage protocol between the app and Archestra's backend.
 *
 * Protocol reference:
 * https://apps.extensions.modelcontextprotocol.io
 */
export function McpAppFrame({
  htmlContent,
  toolName,
  toolResult,
  agentId,
  minHeight = 320,
}: McpAppFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [frameHeight, setFrameHeight] = useState(minHeight);

  /** Send a JSON-RPC response to the iframe */
  const send = useCallback((msg: JsonRpcResponse) => {
    iframeRef.current?.contentWindow?.postMessage(msg, "*");
  }, []);

  /** Forward a tools/call request from the iframe to Archestra's backend */
  const proxyToolCall = useCallback(
    async (req: JsonRpcRequest) => {
      const { name, arguments: args } = (req.params ?? {}) as {
        name?: string;
        arguments?: Record<string, unknown>;
      };

      try {
        const res = await fetch("/api/mcp-apps/tool-call", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            agentId,
            toolName: name,
            arguments: args ?? {},
          }),
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${await res.text()}`);
        }

        const data: unknown = await res.json();
        send({ jsonrpc: "2.0", id: req.id, result: data });
      } catch (err) {
        send({
          jsonrpc: "2.0",
          id: req.id,
          error: {
            code: -32603,
            message: err instanceof Error ? err.message : "Tool call failed",
          },
        });
      }
    },
    [agentId, send],
  );

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const onMessage = async (event: MessageEvent) => {
      // Ignore messages that don't come from our iframe
      if (event.source !== iframe.contentWindow) return;

      const req = event.data as JsonRpcRequest;
      if (!req || req.jsonrpc !== "2.0" || !req.method) return;

      switch (req.method) {
        // App is ready — send it the tool result and server info
        case "ui/initialize":
          send({
            jsonrpc: "2.0",
            id: req.id,
            result: {
              protocolVersion: "2026-01-26",
              serverInfo: { name: "archestra", version: "1.0.0" },
              capabilities: { tools: {} },
              toolResult,
            },
          });
          break;

        // App wants to call an MCP tool — proxy via backend
        case "tools/call":
          await proxyToolCall(req);
          break;

        // App wants to open a link
        case "ui/openLink": {
          const { url } = (req.params ?? {}) as { url?: string };
          if (url) window.open(url, "_blank", "noopener,noreferrer");
          send({ jsonrpc: "2.0", id: req.id, result: null });
          break;
        }

        // App reports its desired height
        case "ui/resize": {
          const { height } = (req.params ?? {}) as { height?: number };
          if (typeof height === "number" && height > 0) {
            setFrameHeight(Math.max(minHeight, height));
          }
          send({ jsonrpc: "2.0", id: req.id, result: null });
          break;
        }

        default:
          send({
            jsonrpc: "2.0",
            id: req.id,
            error: {
              code: -32601,
              message: `Method not found: ${req.method}`,
            },
          });
      }
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [send, proxyToolCall, toolResult]);

  return (
    <div className={cn("w-full overflow-hidden rounded-md border")}>
      <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-1.5">
        <span className="text-xs text-muted-foreground">
          Interactive App · {toolName}
        </span>
      </div>
      <iframe
        ref={iframeRef}
        srcDoc={htmlContent}
        // allow-scripts: required for app JS
        // allow-forms: for form interactions
        // allow-popups: for ui/openLink fallback
        // allow-same-origin is intentionally NOT included — keeps sandbox strict
        sandbox="allow-scripts allow-forms allow-popups"
        className="w-full bg-background"
        style={{ height: frameHeight, border: "none" }}
        title={`MCP App: ${toolName}`}
      />
    </div>
  );
}

// ─── Helper exported for use in ToolOutput ───────────────────────────────────

/**
 * Inspect a tool output value and extract HTML content if it is an MCP App
 * resource (type "resource", mimeType "text/html").
 *
 * Handles both raw content-block arrays and the wrapped
 * `{ content: [...], isError: boolean }` format Archestra's backend produces.
 */
export function extractMcpAppHtml(output: unknown): string | null {
  let blocks: unknown = output;

  // Handle stringified JSON
  if (typeof output === "string") {
    try {
      blocks = JSON.parse(output);
    } catch {
      return null;
    }
  }

  // Unwrap { content: [...] } envelope
  if (
    typeof blocks === "object" &&
    blocks !== null &&
    "content" in blocks &&
    Array.isArray((blocks as { content: unknown }).content)
  ) {
    blocks = (blocks as { content: unknown[] }).content;
  }

  if (!Array.isArray(blocks)) return null;

  for (const block of blocks) {
    if (
      typeof block === "object" &&
      block !== null &&
      (block as { type?: string }).type === "resource"
    ) {
      const resource = (
        block as {
          resource?: { mimeType?: string; text?: string; uri?: string };
        }
      ).resource;

      if (resource?.mimeType === "text/html" && resource.text) {
        return resource.text;
      }
    }
  }

  return null;
}
