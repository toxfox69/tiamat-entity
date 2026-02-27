/**
 * Claude Code Inference Backend
 *
 * Routes TIAMAT's inference through `claude -p` CLI (print mode),
 * using the Claude Pro/Max subscription at zero API cost.
 * Falls back to the API cascade on CLI failure.
 *
 * Key design:
 *   --tools ""              → disables ALL built-in CC tools
 *   --strict-mcp-config     → disables all MCP tools (no --mcp-config passed)
 *   --max-turns 1           → single text turn (no tool-use loops)
 *   --no-session-persistence → don't pollute session storage
 *
 * With zero CC tools available, the model outputs tool calls as
 * <tool_call> XML which we parse into TIAMAT's InferenceToolCall format.
 */

import { spawn } from "child_process";
import type {
  InferenceClient,
  ChatMessage,
  InferenceOptions,
  InferenceResponse,
  InferenceToolCall,
  TokenUsage,
  InferenceToolDefinition,
} from "../types.js";

const DEFAULT_TIMEOUT_MS = 180_000; // 3 min — sonnet can be slow with large prompts
const MODEL_NAME = "claude-code-cli";
const CLI_MODEL = "haiku"; // Haiku for fast thinking; Sonnet was timing out at 120s

/**
 * Essential tools to include with full parameter definitions.
 * Others are listed by name only to save tokens.
 */
const ESSENTIAL_TOOLS = new Set([
  "exec", "write_file", "read_file", "search_web", "web_fetch",
  "send_email", "read_email", "post_bluesky",
  "remember", "recall", "learn_fact",
  "ticket_list", "ticket_claim", "ticket_complete", "ticket_create",
  "check_usdc_balance", "generate_image", "send_telegram",
  "sleep", "log_strategy", "manage_cooldown",
]);

// ─── Env vars to strip (prevent nesting detection) ───────────────

const NESTING_ENV_VARS = [
  "CLAUDECODE",
  "CLAUDE_CODE_ENTRYPOINT",
  "CLAUDE_CODE_SESSION_ID",
  "ANTHROPIC_AI_TOOL_USE_SESSION_ID",
  "ANTHROPIC_API_KEY",  // Force CLI to use subscription, not the (depleted) API key
];

// ─── CLI Execution ──────────────────────────────────────────────

interface CLIResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

function runCLI(prompt: string, timeoutMs: number): Promise<CLIResult> {
  return new Promise((resolve, reject) => {
    const env = { ...process.env };
    for (const v of NESTING_ENV_VARS) delete env[v];

    const args = [
      "-p",                         // print mode (non-interactive)
      "--output-format", "json",    // structured JSON output
      "--max-turns", "1",           // single turn — no tool loops
      "--tools", "",                // disable ALL built-in CC tools
      "--strict-mcp-config",        // disable all MCP tools
      "--no-session-persistence",   // don't save to disk
      "--model", CLI_MODEL,         // sonnet for speed
    ];

    const proc = spawn("claude", args, {
      env,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString(); });
    proc.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });

    const timer = setTimeout(() => {
      proc.kill("SIGTERM");
      // Give it a moment to die, then SIGKILL
      setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 3000);
      reject(new Error(`CLI timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    proc.on("close", (code) => {
      clearTimeout(timer);
      resolve({ stdout, stderr, exitCode: code ?? 1 });
    });

    proc.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });

    // Write prompt via stdin (avoids shell arg length limits)
    proc.stdin.write(prompt);
    proc.stdin.end();
  });
}

// ─── Prompt Building ────────────────────────────────────────────

function buildPrompt(messages: ChatMessage[], tools?: InferenceToolDefinition[]): string {
  const parts: string[] = [];

  // Split system vs conversation messages
  const systemParts: string[] = [];
  const convParts: string[] = [];

  for (const msg of messages) {
    if (msg.role === "system") {
      systemParts.push(msg.content);
    } else if (msg.role === "user") {
      convParts.push(`USER: ${msg.content}`);
    } else if (msg.role === "assistant") {
      let text = msg.content || "";
      if (msg.tool_calls?.length) {
        const calls = msg.tool_calls.map(tc => {
          try {
            return `<tool_call>${JSON.stringify({ name: tc.function.name, arguments: JSON.parse(tc.function.arguments) })}</tool_call>`;
          } catch {
            return `<tool_call>${JSON.stringify({ name: tc.function.name, arguments: tc.function.arguments })}</tool_call>`;
          }
        }).join("\n");
        text += "\n" + calls;
      }
      convParts.push(`ASSISTANT: ${text}`);
    } else if (msg.role === "tool") {
      // Truncate large tool results to save tokens
      const content = msg.content.length > 2000
        ? msg.content.slice(0, 2000) + "\n[...truncated]"
        : msg.content;
      convParts.push(`TOOL_RESULT [${msg.tool_call_id || "?"}]: ${content}`);
    }
  }

  // System context
  if (systemParts.length) {
    parts.push(systemParts.join("\n\n"));
  }

  // Tool definitions — essential tools get full params, rest are names only
  if (tools?.length) {
    const filtered = tools.filter(t => ESSENTIAL_TOOLS.has(t.function.name));
    const otherNames = tools
      .filter(t => !ESSENTIAL_TOOLS.has(t.function.name))
      .map(t => t.function.name);

    parts.push("\n## AVAILABLE TOOLS\n");
    for (const tool of filtered) {
      const params = JSON.stringify(tool.function.parameters);
      parts.push(`- **${tool.function.name}**: ${tool.function.description} | Params: ${params}`);
    }
    if (otherNames.length > 0) {
      parts.push(`\nOther available tools: ${otherNames.join(", ")}`);
    }
    parts.push(
      `\n## TOOL CALLING FORMAT\n` +
      `To call a tool, output EXACTLY this format (note: opening AND closing tag must both be <tool_call> / </tool_call>):\n` +
      `<tool_call>{"name":"tool_name","arguments":{"param":"value"}}</tool_call>\n` +
      `IMPORTANT: The closing tag is </tool_call> — NOT </tool_function_calls> or any other variant.\n` +
      `Include reasoning before tool calls. Multiple tool calls allowed per response.`
    );
  }

  // Conversation history
  if (convParts.length) {
    parts.push("\n## CONVERSATION\n" + convParts.join("\n\n"));
  }

  parts.push("\nASSISTANT:");
  return parts.join("\n");
}

// ─── Response Parsing ───────────────────────────────────────────

function parseToolCalls(text: string): { content: string; toolCalls: InferenceToolCall[] } {
  const toolCalls: InferenceToolCall[] = [];
  let idx = 0;

  // Match <tool_call>JSON</tool_call> OR </tool_function_calls> OR </function_calls>
  // Haiku often closes with </tool_function_calls> instead of </tool_call>
  const regex = /<tool_call>\s*([\s\S]*?)\s*<\/(?:tool_call|tool_function_calls|function_calls)>/g;
  let match;

  while ((match = regex.exec(text)) !== null) {
    try {
      const parsed = JSON.parse(match[1]);
      if (parsed.name) {
        toolCalls.push({
          id: `cc-${Date.now()}-${idx++}`,
          type: "function",
          function: {
            name: parsed.name,
            arguments: JSON.stringify(parsed.arguments || {}),
          },
        });
      }
    } catch {
      // Skip unparseable tool calls
    }
  }

  // Fallback: match <tool_call>JSON with no closing tag (model sometimes omits it)
  if (toolCalls.length === 0) {
    const fallback = /<tool_call>\s*(\{[^]*?\})\s*(?=<tool_call>|\n\n|$)/g;
    while ((match = fallback.exec(text)) !== null) {
      try {
        const parsed = JSON.parse(match[1]);
        if (parsed.name) {
          toolCalls.push({
            id: `cc-${Date.now()}-${idx++}`,
            type: "function",
            function: {
              name: parsed.name,
              arguments: JSON.stringify(parsed.arguments || {}),
            },
          });
        }
      } catch {
        // Skip unparseable
      }
    }
  }

  // Strip all tool_call variants from content
  const content = text
    .replace(/<tool_call>[\s\S]*?<\/(?:tool_call|tool_function_calls|function_calls)>/g, "")
    .replace(/<tool_call>\s*\{[^]*?\}\s*(?=<tool_call>|\n\n|$)/g, "")
    .trim();
  return { content, toolCalls };
}

interface CLIParsedOutput {
  result: string;
  costUsd: number;
  durationMs: number;
  sessionId: string;
  numTurns: number;
  isError: boolean;
}

function parseCLIOutput(stdout: string): CLIParsedOutput {
  try {
    const data = JSON.parse(stdout);
    return {
      result: data.result || "",
      costUsd: data.total_cost_usd || 0,
      durationMs: data.duration_ms || 0,
      sessionId: data.session_id || "",
      numTurns: data.num_turns || 1,
      isError: !!data.is_error,
    };
  } catch {
    // If stdout isn't JSON, treat the raw text as the result
    if (stdout.trim()) {
      return { result: stdout.trim(), costUsd: 0, durationMs: 0, sessionId: "", numTurns: 1, isError: false };
    }
    return { result: "", costUsd: 0, durationMs: 0, sessionId: "", numTurns: 0, isError: true };
  }
}

// ─── Client Factory ─────────────────────────────────────────────

export interface ClaudeCodeInferenceOptions {
  fallback?: InferenceClient;
  timeoutMs?: number;
}

export function createClaudeCodeInferenceClient(
  options: ClaudeCodeInferenceOptions = {},
): InferenceClient {
  const { fallback, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  console.log(
    `[INFERENCE:CC] Claude Code backend initialized — ` +
    `model=${CLI_MODEL}, timeout=${timeoutMs}ms, ` +
    `tools=disabled, mcp=disabled` +
    (fallback ? `, fallback=api-cascade` : `, fallback=none`)
  );

  const chat = async (
    messages: ChatMessage[],
    opts?: InferenceOptions,
  ): Promise<InferenceResponse> => {
    const prompt = buildPrompt(messages, opts?.tools);
    const estTokens = Math.round(prompt.length / 4);

    console.log(
      `[INFERENCE:CC] CLI call — ~${estTokens} tokens, ` +
      `${opts?.tools?.length || 0} tools in prompt, tier=${opts?.tier || "default"}`
    );

    const startTime = Date.now();

    try {
      const { stdout, stderr, exitCode } = await runCLI(prompt, timeoutMs);
      const elapsed = Date.now() - startTime;

      if (exitCode !== 0) {
        const errMsg = (stderr || stdout).slice(0, 500);
        throw new Error(`CLI exit ${exitCode}: ${errMsg}`);
      }

      if (!stdout.trim()) {
        throw new Error("CLI returned empty output");
      }

      const parsed = parseCLIOutput(stdout);

      if (parsed.isError && !parsed.result) {
        throw new Error(`CLI error: ${JSON.stringify(parsed).slice(0, 300)}`);
      }

      const { content, toolCalls } = parseToolCalls(parsed.result);

      console.log(
        `[INFERENCE:CC] OK ${elapsed}ms — ` +
        `${content.length}ch, ${toolCalls.length} tools, ` +
        `$${parsed.costUsd.toFixed(4)} (sub), turns=${parsed.numTurns}`
      );

      const outputTokens = Math.round(parsed.result.length / 4);
      const usage: TokenUsage = {
        promptTokens: estTokens,
        completionTokens: outputTokens,
        totalTokens: estTokens + outputTokens,
      };

      return {
        id: parsed.sessionId || `cc-${Date.now()}`,
        model: MODEL_NAME,
        message: {
          role: "assistant",
          content,
          tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
        },
        toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
        usage,
        finishReason: toolCalls.length > 0 ? "tool_calls" : "stop",
      };
    } catch (err: any) {
      const elapsed = Date.now() - startTime;
      console.warn(`[INFERENCE:CC] FAIL ${elapsed}ms — ${err.message}`);

      if (fallback) {
        console.log(`[INFERENCE:CC] → API cascade fallback`);
        return fallback.chat(messages, opts);
      }

      throw err;
    }
  };

  const setLowComputeMode = (_enabled: boolean): void => {};
  const getDefaultModel = (): string => MODEL_NAME;

  const getShortestCooldownMs = (): number => 0;
  return { chat, setLowComputeMode, getDefaultModel, getShortestCooldownMs };
}
