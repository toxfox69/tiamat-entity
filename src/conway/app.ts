/**
 * TIAMAT — OpenAI-compatible inference API
 *
 * POST /v1/chat/completions  — routes through the 6-provider cascade
 * GET  /v1/models            — model list
 * GET  /v1/health            — health check
 *
 * Auth:   X-API-Key header (or Authorization: Bearer <key>)
 * Keys:   stored in api_keys table in state.db
 * Limits: 10 req/min free tier, effectively unlimited for paid tier
 */

import express from "express";
import Database from "better-sqlite3";
import crypto from "crypto";
import { readFileSync } from "fs";
import path from "path";
import { createInferenceClient } from "./inference.js";
import type { ChatMessage, InferenceOptions } from "../types.js";

// ─── Config ──────────────────────────────────────────────────────

const PORT = parseInt(process.env.OPENAI_API_PORT || "3100");
const DB_PATH =
  process.env.DB_PATH ||
  path.join(process.env.HOME || "/root", ".automaton", "state.db");
const AUTOMATON_JSON =
  process.env.AUTOMATON_JSON ||
  path.join(process.env.HOME || "/root", ".automaton", "automaton.json");

function loadConfig(): Record<string, string> {
  try {
    return JSON.parse(readFileSync(AUTOMATON_JSON, "utf-8"));
  } catch {
    console.warn("[APP] Could not load automaton.json — using env vars only");
    return {};
  }
}

const cfg = loadConfig();
const getKey = (name: string): string =>
  cfg[name] || process.env[name.toUpperCase()] || "";

// ─── Inference client ─────────────────────────────────────────────

const inference = createInferenceClient({
  apiUrl: getKey("conwayApiUrl") || "https://api.conway.tech",
  apiKey: getKey("conwayApiKey") || "",
  defaultModel: "llama-3.3-70b-versatile",
  maxTokens: 4096,
  anthropicApiKey: getKey("anthropicApiKey") || undefined,
  groqApiKey: getKey("groqApiKey") || undefined,
  cerebrasApiKey: getKey("cerebrasApiKey") || undefined,
  sambanovaApiKey: getKey("sambanovaApiKey") || undefined,
  openrouterApiKey: getKey("openrouterApiKey") || undefined,
  geminiApiKey: getKey("geminiApiKey") || undefined,
  perplexityApiKey: getKey("perplexityApiKey") || undefined,
});

// ─── Database + api_keys table ───────────────────────────────────

const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");

db.exec(`
  CREATE TABLE IF NOT EXISTS api_keys (
    key          TEXT    PRIMARY KEY,
    name         TEXT    NOT NULL,
    tier         TEXT    NOT NULL DEFAULT 'free',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1
  );
`);

// Seed a test key if the table is empty
const keyCount = (
  db.prepare("SELECT COUNT(*) as c FROM api_keys WHERE enabled = 1").get() as {
    c: number;
  }
).c;

if (keyCount === 0) {
  const testKey = "sk-tiamat-test-" + crypto.randomBytes(16).toString("hex");
  db.prepare(
    "INSERT INTO api_keys (key, name, tier) VALUES (?, ?, ?)"
  ).run(testKey, "test-key", "free");
  console.log(`[APP] ✓ Seeded test API key: ${testKey}`);
  console.log(`[APP]   Save this — it won't be shown again.`);
} else {
  console.log(`[APP] ${keyCount} API key(s) found in database`);
}

// ─── Rate limiter ─────────────────────────────────────────────────
// In-memory sliding window. requestWindows tracks per-key call timestamps.

const requestWindows = new Map<string, number[]>();
const WINDOW_MS = 60_000; // 1 minute
const RATE_FREE = 10; // req/min for free tier
const RATE_PAID = 600; // req/min for paid tier

function checkRateLimit(
  apiKey: string,
  limit: number
): { allowed: boolean; remaining: number; resetMs: number } {
  const now = Date.now();
  const raw = requestWindows.get(apiKey) ?? [];
  const window = raw.filter((t) => now - t < WINDOW_MS);

  if (window.length >= limit) {
    const resetMs = WINDOW_MS - (now - window[0]);
    return { allowed: false, remaining: 0, resetMs };
  }

  window.push(now);
  requestWindows.set(apiKey, window);
  return { allowed: true, remaining: limit - window.length, resetMs: 0 };
}

// Prune stale entries every 5 min to prevent memory growth
setInterval(() => {
  const now = Date.now();
  for (const [k, times] of requestWindows.entries()) {
    const fresh = times.filter((t) => now - t < WINDOW_MS);
    if (fresh.length === 0) requestWindows.delete(k);
    else requestWindows.set(k, fresh);
  }
}, 5 * 60_000).unref();

// ─── Auth + rate-limit middleware ─────────────────────────────────

interface ApiKeyRow {
  key: string;
  name: string;
  tier: string;
  enabled: number;
}

function authMiddleware(
  req: express.Request,
  res: express.Response,
  next: express.NextFunction
): void {
  // Accept X-API-Key or Authorization: Bearer <key>
  const rawKey =
    (req.headers["x-api-key"] as string | undefined) ||
    (req.headers.authorization?.startsWith("Bearer ")
      ? req.headers.authorization.slice(7)
      : undefined);

  if (!rawKey) {
    res.status(401).json({
      error: {
        message:
          "Missing API key. Send X-API-Key header or Authorization: Bearer <key>",
        type: "invalid_request_error",
        code: "missing_api_key",
      },
    });
    return;
  }

  const row = db
    .prepare("SELECT * FROM api_keys WHERE key = ? AND enabled = 1")
    .get(rawKey) as ApiKeyRow | undefined;

  if (!row) {
    res.status(401).json({
      error: {
        message: "Invalid or revoked API key",
        type: "invalid_request_error",
        code: "invalid_api_key",
      },
    });
    return;
  }

  // Update last_used_at (synchronous write is fine — SQLite WAL)
  db.prepare(
    "UPDATE api_keys SET last_used_at = datetime('now') WHERE key = ?"
  ).run(rawKey);

  // Rate limit
  const limit = row.tier === "free" ? RATE_FREE : RATE_PAID;
  const rl = checkRateLimit(rawKey, limit);

  res.setHeader("X-RateLimit-Limit", limit);
  res.setHeader("X-RateLimit-Remaining", rl.remaining);
  res.setHeader(
    "X-RateLimit-Reset",
    Math.ceil((Date.now() + (rl.resetMs || WINDOW_MS)) / 1000)
  );

  if (!rl.allowed) {
    res.setHeader("Retry-After", Math.ceil(rl.resetMs / 1000));
    res.status(429).json({
      error: {
        message: `Rate limit exceeded. Retry in ${Math.ceil(rl.resetMs / 1000)}s`,
        type: "rate_limit_error",
        code: "rate_limit_exceeded",
      },
    });
    return;
  }

  (req as express.Request & { apiKeyRow: ApiKeyRow }).apiKeyRow = row;
  next();
}

// ─── App ──────────────────────────────────────────────────────────

const app = express();
app.use(express.json({ limit: "4mb" }));

// ─── POST /v1/chat/completions ────────────────────────────────────

interface OpenAIMessage {
  role: string;
  content: string;
  name?: string;
}

interface OpenAIChatRequest {
  model?: string;
  messages: OpenAIMessage[];
  temperature?: number;
  max_tokens?: number;
  stream?: boolean;
}

app.post(
  "/v1/chat/completions",
  authMiddleware,
  async (req: express.Request, res: express.Response): Promise<void> => {
    const body = req.body as OpenAIChatRequest;

    if (
      !body.messages ||
      !Array.isArray(body.messages) ||
      body.messages.length === 0
    ) {
      res.status(400).json({
        error: {
          message: "messages must be a non-empty array",
          type: "invalid_request_error",
          code: "invalid_messages",
        },
      });
      return;
    }

    // Map to internal ChatMessage format
    const messages: ChatMessage[] = body.messages.map((m) => ({
      role: m.role as ChatMessage["role"],
      content: String(m.content ?? ""),
      name: m.name,
    }));

    const opts: InferenceOptions = {
      maxTokens: body.max_tokens ?? 2048,
      temperature: body.temperature,
      tier: "free", // use free cascade by default — caller can override via model
    };

    if (body.model && body.model !== "tiamat-cascade") {
      opts.model = body.model;
    }

    // ── Streaming response ──
    if (body.stream) {
      res.setHeader("Content-Type", "text/event-stream");
      res.setHeader("Cache-Control", "no-cache");
      res.setHeader("Connection", "keep-alive");

      try {
        const response = await inference.chat(messages, opts);
        const id = `chatcmpl-${Date.now()}`;
        const model = response.model || body.model || "tiamat-cascade";
        const created = Math.floor(Date.now() / 1000);

        // Role delta chunk
        const roleChunk = {
          id,
          object: "chat.completion.chunk",
          created,
          model,
          choices: [{ index: 0, delta: { role: "assistant", content: "" }, finish_reason: null }],
        };
        res.write(`data: ${JSON.stringify(roleChunk)}\n\n`);

        // Content chunk
        const contentChunk = {
          id,
          object: "chat.completion.chunk",
          created,
          model,
          choices: [{ index: 0, delta: { content: response.message.content }, finish_reason: null }],
        };
        res.write(`data: ${JSON.stringify(contentChunk)}\n\n`);

        // Terminal chunk
        const doneChunk = {
          id,
          object: "chat.completion.chunk",
          created,
          model,
          choices: [{ index: 0, delta: {}, finish_reason: response.finishReason || "stop" }],
        };
        res.write(`data: ${JSON.stringify(doneChunk)}\n\n`);
        res.write("data: [DONE]\n\n");
        res.end();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Inference error";
        res.write(`data: ${JSON.stringify({ error: { message: msg, type: "api_error" } })}\n\n`);
        res.end();
      }
      return;
    }

    // ── Non-streaming response ──
    try {
      const response = await inference.chat(messages, opts);
      const id = `chatcmpl-${Date.now()}`;
      const model = response.model || body.model || "tiamat-cascade";

      res.json({
        id,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model,
        choices: [
          {
            index: 0,
            message: {
              role: "assistant",
              content: response.message.content,
            },
            finish_reason: response.finishReason || "stop",
          },
        ],
        usage: {
          prompt_tokens: response.usage.promptTokens,
          completion_tokens: response.usage.completionTokens,
          total_tokens: response.usage.totalTokens,
        },
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Inference error";
      console.error("[APP] /v1/chat/completions error:", msg);
      res.status(500).json({
        error: {
          message: msg,
          type: "api_error",
          code: "inference_error",
        },
      });
    }
  }
);

// ─── GET /v1/models ───────────────────────────────────────────────

app.get("/v1/models", authMiddleware, (_req, res) => {
  res.json({
    object: "list",
    data: [
      { id: "tiamat-cascade", object: "model", created: 1700000000, owned_by: "tiamat", description: "Auto-routes through 6-provider cascade" },
      { id: "llama-3.3-70b-versatile", object: "model", created: 1700000000, owned_by: "groq" },
      { id: "gpt-oss-120b", object: "model", created: 1700000000, owned_by: "cerebras" },
      { id: "Meta-Llama-3.3-70B-Instruct", object: "model", created: 1700000000, owned_by: "sambanova" },
      { id: "gemini-2.0-flash", object: "model", created: 1700000000, owned_by: "google" },
      { id: "claude-haiku-4-5-20251001", object: "model", created: 1700000000, owned_by: "anthropic" },
    ],
  });
});

// ─── GET /v1/health ───────────────────────────────────────────────

app.get("/v1/health", (_req, res) => {
  const keyCount = (
    db
      .prepare("SELECT COUNT(*) as c FROM api_keys WHERE enabled = 1")
      .get() as { c: number }
  ).c;
  res.json({
    status: "ok",
    service: "tiamat-openai-compat",
    version: "1.0.0",
    api_keys: keyCount,
    timestamp: new Date().toISOString(),
  });
});

// ─── POST /v1/api-keys (admin: create a new key) ──────────────────
// Protected by X-Admin-Secret header (set ADMIN_SECRET env var)

app.post("/v1/api-keys", (req, res) => {
  const secret = process.env.ADMIN_SECRET;
  if (!secret || req.headers["x-admin-secret"] !== secret) {
    res.status(403).json({ error: { message: "Forbidden", type: "auth_error" } });
    return;
  }

  const { name, tier = "free" } = req.body as {
    name?: string;
    tier?: string;
  };
  if (!name) {
    res.status(400).json({ error: { message: "name is required", type: "invalid_request_error" } });
    return;
  }

  const key = "sk-tiamat-" + crypto.randomBytes(24).toString("hex");
  db.prepare(
    "INSERT INTO api_keys (key, name, tier) VALUES (?, ?, ?)"
  ).run(key, name, tier);

  res.status(201).json({ key, name, tier, created_at: new Date().toISOString() });
});

// ─── Start ────────────────────────────────────────────────────────

const server = app.listen(PORT, "127.0.0.1", () => {
  console.log(`[APP] OpenAI-compatible API → http://127.0.0.1:${PORT}`);
  console.log(`[APP] Endpoint: POST /v1/chat/completions`);
  console.log(`[APP] Models:   GET  /v1/models`);
  console.log(`[APP] Health:   GET  /v1/health`);
  console.log(`[APP] Auth:     X-API-Key header or Authorization: Bearer <key>`);
});

server.on("error", (err) => {
  console.error("[APP] Server error:", err);
  process.exit(1);
});

export { app };

// Farcaster Frame v2 endpoints
app.get('/api/frame-image', (req, res) => {
  res.setHeader('Content-Type', 'image/png');
  // Return a frame image (gradient TIAMAT branding)
  res.send(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64'));
});

app.post('/api/frame-action', async (req, res) => {
  const { trustedData } = req.body;
  const { frameData } = trustedData || {};
  const { inputText } = frameData || {};
  
  // Verify x402 payment header (if present)
  const paymentHeader = req.headers['x-payment-header'];
  let isPaid = false;
  
  if (paymentHeader) {
    // TODO: validate x402 payment signature
    isPaid = true;
  }
  
  // Route to inference proxy
  if (!inputText) {
    return res.json({
      type: 'frame',
      buttons: [{ label: 'Ask TIAMAT', action: 'post' }],
      image: 'https://tiamat.live/api/frame-image',
      post_url: 'https://tiamat.live/api/frame-action',
    });
  }
  
  try {
    const response = await (async (opts: { messages: { role: string; content: string }[]; isPaid: boolean }) => {
      // TODO: implement proxyInference — stub returns placeholder
      return "TIAMAT inference temporarily unavailable via frame.";
    })({ messages: [{ role: 'user', content: inputText }], isPaid });
    
    return res.json({
      type: 'frame',
      image: 'https://tiamat.live/api/frame-response?text=' + encodeURIComponent(response.substring(0, 100)),
      buttons: [{ label: 'Ask Another', action: 'post' }],
      post_url: 'https://tiamat.live/api/frame-action',
    });
  } catch (e) {
    res.json({
      type: 'frame',
      image: 'https://tiamat.live/api/frame-image',
      buttons: [{ label: 'Error - Try Again', action: 'post' }],
    });
  }
});

app.get('/frame', (req, res) => {
  res.sendFile(path.join(__dirname, '../templates/frame.html'));
});
