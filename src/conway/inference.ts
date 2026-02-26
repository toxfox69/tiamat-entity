/**
 * TIAMAT Inference Client
 *
 * Multi-provider inference with cascade fallback.
 * The automaton pays for its own thinking through compute credits.
 */

import type {
  InferenceClient,
  ChatMessage,
  InferenceOptions,
  InferenceResponse,
  InferenceToolCall,
  TokenUsage,
  InferenceToolDefinition,
} from "../types.js";
import { CACHE_SENTINEL } from "../agent/system-prompt.js";

interface InferenceClientOptions {
  apiUrl: string;
  apiKey: string;
  defaultModel: string;
  maxTokens: number;
  lowComputeModel?: string;
  openaiApiKey?: string;
  anthropicApiKey?: string;
  groqApiKey?: string;
  groqModel?: string;
  cerebrasApiKey?: string;
  openrouterApiKey?: string;
  geminiApiKey?: string;
}

type InferenceBackend = "groq" | "conway" | "openai" | "anthropic" | "cerebras" | "openrouter" | "gemini";

// Token thresholds for model routing
const GROQ_MODEL        = "llama-3.3-70b-versatile";           // Tier 2: Groq free
const CEREBRAS_MODEL    = "gpt-oss-120b";                      // Tier 3: Cerebras free (120B, 1-2s, tool calling)
const GEMINI_MODEL      = "gemini-2.0-flash";                  // Tier 4: Gemini free
const ANTHROPIC_MODEL   = "claude-haiku-4-5-20251001";         // Tier 6: Anthropic paid fallback
const TOKEN_THRESHOLD_LARGE = 5500;

// OpenRouter free model pool — rotated through on rate limits.
// Ordered by quality/capability. Each gets independent cooldown.
const OPENROUTER_FREE_MODELS = [
  "nousresearch/hermes-3-llama-3.1-405b:free",               // 405B — best quality
  "openai/gpt-oss-120b:free",                                // 120B — excellent
  "qwen/qwen3-next-80b-a3b-instruct:free",                   // 80B MoE — 262K ctx
  "qwen/qwen3-coder:free",                                   // Coder — 262K ctx
  "meta-llama/llama-3.3-70b-instruct:free",                  // 70B — proven
  "arcee-ai/trinity-large-preview:free",                      // 131K ctx
  "stepfun/step-3.5-flash:free",                              // 256K ctx
  "mistralai/mistral-small-3.1-24b-instruct:free",           // 24B — fast
  "nvidia/nemotron-3-nano-30b-a3b:free",                      // 30B MoE — 256K ctx
  "z-ai/glm-4.5-air:free",                                   // 131K ctx
  "google/gemma-3-27b-it:free",                               // 27B
  "google/gemma-3-12b-it:free",                               // 12B — small but fast
];

/**
 * Essential tools for small-context providers (Groq/Cerebras).
 * Only these get sent — cuts tool token overhead from ~8k to ~2k.
 */
const SMALL_PROVIDER_TOOLS = new Set([
  "exec", "write_file", "read_file", "search_web", "web_fetch", "browse",
  "send_telegram", "send_email", "read_email", "post_bluesky", "post_farcaster",
  "remember", "recall", "learn_fact", "ticket_list", "ticket_claim", "ticket_complete",
  "ticket_create", "ask_claude_code", "gpu_infer", "check_usdc_balance",
  "manage_cooldown", "generate_image", "deploy_app", "log_strategy", "dx_terminal",
]);

function filterToolsForSmallProvider(tools: InferenceToolDefinition[]): InferenceToolDefinition[] {
  return tools.filter(t => SMALL_PROVIDER_TOOLS.has(t.function.name));
}

/** Cheap character-based token estimator (~4 chars per token). */
function estimateTokens(messages: ChatMessage[], tools?: InferenceToolDefinition[]): number {
  let chars = 0;
  for (const m of messages) chars += (m.content || "").length + 4; // 4 for role overhead
  if (tools) chars += JSON.stringify(tools).length;
  return Math.ceil(chars / 4);
}

/**
 * Trim a message list so the total estimated tokens stay under targetTokens.
 * Keeps the system message. Removes oldest non-system messages first.
 * Skips "orphan" tool messages at the front (no preceding assistant).
 */
function trimToTokenBudget(messages: ChatMessage[], targetTokens: number): ChatMessage[] {
  if (estimateTokens(messages) <= targetTokens) return messages;
  const system = messages[0]?.role === "system" ? messages[0] : null;
  const rest = system ? messages.slice(1) : [...messages];
  while (rest.length > 1 && estimateTokens(system ? [system, ...rest] : rest) > targetTokens) {
    rest.shift();
    // Don't leave orphan tool messages at the front
    while (rest.length > 0 && rest[0].role === "tool") rest.shift();
  }
  return system ? [system, ...rest] : rest;
}

function routeGroqModel(_estimatedTokens: number): string {
  return GROQ_MODEL;
}

function isRateLimitError(err: any): boolean {
  return (
    err?.status === 429 ||
    err?.error?.type === "tokens" ||
    /rate.?limit|too many requests|quota exceeded/i.test(err?.message || "") ||
    /:\s*429[:\s]/.test(err?.message || "") // catches "Inference error (backend): 429: ..."
  );
}

/**
 * True if the rate limit is a DAILY quota (not a per-minute limit).
 * Daily quota errors need a 12h cooldown, not 60s.
 */
function isDailyLimitError(err: any): boolean {
  const msg = err?.message || "";
  return (
    /per.?day|daily|token_quota_exceeded|too_many_tokens_error/i.test(msg) ||
    /GenerateRequest.*PerDay|GenerateContent.*PerDay/i.test(msg) ||
    /tokens per day|TPD.*Limit/i.test(msg)
  );
}

const COOLDOWN_RATE_LIMIT_MS = 65_000;       // 65s for per-minute limits
const COOLDOWN_DAILY_LIMIT_MS = 4 * 3600_000; // 4h for daily quota exhaustion (Groq TPD resets at midnight UTC)

/**
 * Extract tool calls from a response message, handling both formats:
 *   - OpenAI/Groq: message.tool_calls array
 *   - Anthropic:   message.content array with type "tool_use" blocks
 */
function extractToolCalls(message: any): InferenceToolCall[] | undefined {
  // OpenAI / Groq format
  if (Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
    return message.tool_calls.map((tc: any) => ({
      id: tc.id,
      type: "function" as const,
      function: {
        name: tc.function.name,
        arguments: tc.function.arguments,
      },
    }));
  }

  // Anthropic format — content array with tool_use blocks
  if (Array.isArray(message.content)) {
    const toolUseBlocks = message.content.filter((c: any) => c?.type === "tool_use");
    if (toolUseBlocks.length > 0) {
      return toolUseBlocks.map((tool: any) => ({
        id: tool.id,
        type: "function" as const,
        function: {
          name: tool.name,
          arguments: JSON.stringify(tool.input || {}),
        },
      }));
    }
  }

  return undefined;
}

/**
 * Extract text content from a response message, handling both formats:
 *   - OpenAI/Groq: message.content is a string
 *   - Anthropic:   message.content is an array of typed blocks
 */
function extractTextContent(message: any): string {
  if (typeof message.content === "string") return message.content || "";
  if (Array.isArray(message.content)) {
    return message.content
      .filter((c: any) => c?.type === "text")
      .map((c: any) => String(c.text || ""))
      .join("\n")
      .trim();
  }
  return "";
}

export function createInferenceClient(
  options: InferenceClientOptions,
): InferenceClient {
  const { apiUrl, apiKey, openaiApiKey, anthropicApiKey, groqApiKey, cerebrasApiKey, openrouterApiKey, geminiApiKey } = options;
  let currentModel = options.defaultModel;
  let maxTokens = options.maxTokens;

  // True if any cascade key is configured (Anthropic is now Tier 1).
  const hasCascadeKey = !!(anthropicApiKey || groqApiKey || cerebrasApiKey || openrouterApiKey || geminiApiKey);

  // Log which providers are available at startup
  {
    const providers = [
      anthropicApiKey  ? `Anthropic(${ANTHROPIC_MODEL}) [PRIMARY]` : "Anthropic:NO_KEY",
      groqApiKey       ? `Groq(${GROQ_MODEL})`             : "Groq:NO_KEY",
      cerebrasApiKey   ? `Cerebras(${CEREBRAS_MODEL})`     : "Cerebras:NO_KEY",
      geminiApiKey     ? `Gemini(${GEMINI_MODEL})`         : "Gemini:NO_KEY",
      openrouterApiKey ? `OpenRouter(${OPENROUTER_FREE_MODELS.length} free models)` : "OpenRouter:NO_KEY",
    ];
    console.log(`[INFERENCE] Cascade providers: ${providers.join(" → ")}`);
  }

  // Last model actually used — updated each call, reported by getDefaultModel().
  let lastUsedModel: string = options.groqModel || GROQ_MODEL;

  // Per-model rate-limit cooldowns: model key → cooldown-until timestamp (ms).
  // Persists across calls within the same process so cooling models are skipped
  // automatically without sleeping the entire agent loop.
  const modelCooldowns = new Map<string, number>();

  const isCoolingDown = (model: string): boolean => {
    const until = modelCooldowns.get(model);
    if (!until) return false;
    if (Date.now() >= until) { modelCooldowns.delete(model); return false; }
    return true;
  };

  const setCooldown = (model: string, ms: number): void => {
    modelCooldowns.set(model, Date.now() + ms);
    const label = ms >= 3_600_000 ? `${Math.round(ms / 3_600_000)}h` : `${Math.round(ms / 1000)}s`;
    console.warn(`[INFERENCE] ${model} cooldown set: ${label} (${ms >= 3_600_000 ? "DAILY limit" : "rate limit"})`);
  };

  const chat = async (
    messages: ChatMessage[],
    opts?: InferenceOptions,
  ): Promise<InferenceResponse> => {
    const tools = opts?.tools;
    const tokenLimit = opts?.maxTokens || maxTokens;

    // Model override: try explicit model first, fall through to cascade on failure
    if (opts?.model) {
      const requestedModel = opts.model;
      const backend = resolveInferenceBackend(requestedModel, { openaiApiKey, anthropicApiKey });
      console.log(`[INFERENCE] Direct model override: ${requestedModel} → ${backend}`);
      lastUsedModel = requestedModel;
      try {
        if (backend === "anthropic") {
          return await chatViaAnthropic({ model: requestedModel, tokenLimit, messages, tools, temperature: opts?.temperature, anthropicApiKey: anthropicApiKey! });
        }
        const overrideBody: Record<string, unknown> = { model: requestedModel, messages: messages.map(formatMessage), stream: false, max_tokens: tokenLimit };
        if (opts?.temperature !== undefined) overrideBody.temperature = opts.temperature;
        if (tools && tools.length > 0) { overrideBody.tools = tools; overrideBody.tool_choice = "auto"; }
        return await chatViaOpenAiCompatible({ model: requestedModel, body: overrideBody, apiUrl: backend === "openai" ? "https://api.openai.com" : apiUrl, apiKey: backend === "openai" ? openaiApiKey! : apiKey, backend });
      } catch (err: any) {
        console.warn(`[INFERENCE] Model override ${requestedModel} FAILED — ${err.message}, falling through to cascade`);
        // Fall through to cascade below
      }
    }

    // Fallback chain — each tier cools independently on rate limit.
    // Tier 1: Anthropic  claude-haiku          paid (PRIMARY — smart, $0.002/call)
    // Tier 2: Groq       llama-3.3-70b         free fallback
    // Tier 3: Cerebras   gpt-oss-120b          free fallback (120B, 3k tok/s)
    // Tier 4: Gemini     gemini-2.0-flash      free fallback
    // Tier 5: OpenRouter llama-3.3-70b → gemma-3-27b  free fallback (per-minute limit)
    if (hasCascadeKey) {
      const estimated = estimateTokens(messages, tools);
      const requestedTier = opts?.tier || "haiku";
      console.log(`[INFERENCE] ~${estimated} tokens, tier=${requestedTier} — starting cascade (keys: anthropic=${!!anthropicApiKey} groq=${!!groqApiKey} cerebras=${!!cerebrasApiKey} gemini=${!!geminiApiKey} openrouter=${!!openrouterApiKey})`);

      // Helper: log remaining cooldown time clearly
      const coolRemaining = (key: string) => {
        const until = modelCooldowns.get(key);
        if (!until) return "?";
        const ms = until - Date.now();
        return ms >= 3_600_000 ? `${Math.round(ms / 3_600_000)}h` : `${Math.ceil(ms / 1000)}s`;
      };

      // Helper: pick cooldown duration based on error type
      const smartCooldown = (model: string, err: any, fallbackMs = COOLDOWN_RATE_LIMIT_MS) => {
        const ms = isDailyLimitError(err) ? COOLDOWN_DAILY_LIMIT_MS : fallbackMs;
        setCooldown(model, ms);
      };

      // Tier routing: when tier=free, skip Anthropic and go straight to Groq
      // When tier=haiku (default), Anthropic first as before
      // When tier=sonnet, model override handles it above, cascade is fallback
      if (requestedTier === "free") {
        console.log(`[INFERENCE] Tier routing: FREE — skipping Anthropic, trying Groq first`);
      } else if (!anthropicApiKey) {
        console.log(`[INFERENCE] Tier 1 (Anthropic): SKIP — no key`);
      } else if (isCoolingDown(ANTHROPIC_MODEL)) {
        console.log(`[INFERENCE] Tier 1 (Anthropic): SKIP — cooling (${coolRemaining(ANTHROPIC_MODEL)} left)`);
      } else {
        try {
          lastUsedModel = ANTHROPIC_MODEL;
          console.log(`[INFERENCE] Tier 1 (Anthropic): ATTEMPT ${ANTHROPIC_MODEL} (~${estimated} tokens)`);
          return await chatViaAnthropic({ model: ANTHROPIC_MODEL, tokenLimit, messages, tools, temperature: opts?.temperature, anthropicApiKey });
        } catch (err: any) {
          if (isRateLimitError(err)) smartCooldown(ANTHROPIC_MODEL, err, COOLDOWN_RATE_LIMIT_MS * 2);
          console.warn(`[INFERENCE] Tier 1 (Anthropic): FAILED — ${err.message}`);
          // Fall through to free tiers
        }
      }

      // Tier 2: Groq — trim context if too large rather than skipping entirely
      if (!groqApiKey) {
        console.log(`[INFERENCE] Tier 2 (Groq): SKIP — no key`);
      } else if (isCoolingDown(GROQ_MODEL)) {
        console.log(`[INFERENCE] Tier 2 (Groq): SKIP — cooling (${coolRemaining(GROQ_MODEL)} left)`);
      } else {
        const groqModel = routeGroqModel(estimated);
        const groqTools = tools ? filterToolsForSmallProvider(tools) : undefined;
        const groqMessages = trimToTokenBudget(messages, 3500);
        const groqEst = estimateTokens(groqMessages, groqTools);
        try {
          lastUsedModel = groqModel;
          const trimNote = groqMessages.length < messages.length ? `, trimmed ${messages.length - groqMessages.length} msgs` : "";
          console.log(`[INFERENCE] Tier 2 (Groq): ATTEMPT ${groqModel} (~${groqEst} tokens, ${groqTools?.length || 0} tools${trimNote})`);
          return await chatViaGroq({ model: groqModel, tokenLimit, messages: groqMessages, tools: groqTools, temperature: opts?.temperature, groqApiKey: groqApiKey! });
        } catch (err: any) {
          if (isRateLimitError(err)) smartCooldown(GROQ_MODEL, err);
          console.warn(`[INFERENCE] Tier 2 (Groq): FAILED — ${err.message}`);
        }
      }

      // Tier 3: Cerebras gpt-oss-120B (free, ~1-2s, tool calling works)
      if (!cerebrasApiKey) {
        console.log(`[INFERENCE] Tier 3 (Cerebras): SKIP — no key`);
      } else if (isCoolingDown(CEREBRAS_MODEL)) {
        console.log(`[INFERENCE] Tier 3 (Cerebras): SKIP — cooling (${coolRemaining(CEREBRAS_MODEL)} left)`);
      } else {
        try {
          lastUsedModel = CEREBRAS_MODEL;
          // gpt-oss-120B supports 131K context — trim conservatively
          const cerebrasMessages = trimToTokenBudget(messages, 5000);
          const cerebrasTools = tools ? filterToolsForSmallProvider(tools) : undefined;
          const cerebrasEst = estimateTokens(cerebrasMessages, cerebrasTools);
          const trimNote = cerebrasMessages.length < messages.length ? `, trimmed ${messages.length - cerebrasMessages.length} msgs` : "";
          console.log(`[INFERENCE] Tier 3 (Cerebras): ATTEMPT ${CEREBRAS_MODEL} (~${cerebrasEst} tokens, ${cerebrasTools?.length || 0} tools${trimNote})`);
          const body: Record<string, unknown> = {
            model: CEREBRAS_MODEL,
            messages: cerebrasMessages.map(formatMessage),
            stream: false,
            max_tokens: Math.min(tokenLimit, 2048),
          };
          if (opts?.temperature !== undefined) body.temperature = opts.temperature;
          if (cerebrasTools && cerebrasTools.length > 0) { body.tools = cerebrasTools; body.tool_choice = "auto"; }
          return await chatViaOpenAiCompatible({ model: CEREBRAS_MODEL, body, apiUrl: "https://api.cerebras.ai", apiKey: cerebrasApiKey, backend: "cerebras" });
        } catch (err: any) {
          if (isRateLimitError(err)) smartCooldown(CEREBRAS_MODEL, err);
          console.warn(`[INFERENCE] Tier 3 (Cerebras): FAILED — ${err.message}`);
        }
      }

      // Tier 4: Gemini Flash (free, native API)
      if (!geminiApiKey) {
        console.log(`[INFERENCE] Tier 4 (Gemini): SKIP — no key`);
      } else if (isCoolingDown(GEMINI_MODEL)) {
        console.log(`[INFERENCE] Tier 4 (Gemini): SKIP — cooling (${coolRemaining(GEMINI_MODEL)} left)`);
      } else {
        try {
          lastUsedModel = GEMINI_MODEL;
          console.log(`[INFERENCE] Tier 4 (Gemini): ATTEMPT ${GEMINI_MODEL} (~${estimated} tokens)`);
          return await chatViaGemini({ model: GEMINI_MODEL, tokenLimit, messages, tools, temperature: opts?.temperature, geminiApiKey });
        } catch (err: any) {
          if (isRateLimitError(err)) smartCooldown(GEMINI_MODEL, err);
          console.warn(`[INFERENCE] Tier 4 (Gemini): FAILED — ${err.message}`);
        }
      }

      // Tier 5: OpenRouter — rotate through all free models (each cools independently)
      if (!openrouterApiKey) {
        console.log(`[INFERENCE] Tier 5 (OpenRouter): SKIP — no key`);
      } else {
        let orSkipped = 0;
        for (const orModel of OPENROUTER_FREE_MODELS) {
          if (isCoolingDown(orModel)) {
            orSkipped++;
            continue;
          }
          const shortName = orModel.split("/").pop()!.replace(":free", "");
          try {
            lastUsedModel = orModel;
            console.log(`[INFERENCE] Tier 5 (OR/${shortName}): ATTEMPT (~${estimated} tokens)`);
            const body: Record<string, unknown> = {
              model: orModel,
              messages: messages.map(formatMessage),
              stream: false,
              max_tokens: tokenLimit,
            };
            if (opts?.temperature !== undefined) body.temperature = opts.temperature;
            if (tools && tools.length > 0) { body.tools = tools; body.tool_choice = "auto"; }
            return await chatViaOpenAiCompatible({ model: orModel, body, apiUrl: "https://openrouter.ai/api", apiKey: openrouterApiKey, backend: "openrouter" });
          } catch (err: any) {
            const msg = err?.message || "";
            if (/404|No endpoints found|model not found/i.test(msg)) {
              setCooldown(orModel, 24 * 3_600_000);
              console.warn(`[INFERENCE] Tier 5 (OR/${shortName}): NOT FOUND (24h cooldown)`);
            } else if (isRateLimitError(err)) {
              smartCooldown(orModel, err, 300_000);  // 5 min cooldown per model
            }
            console.warn(`[INFERENCE] Tier 5 (OR/${shortName}): FAILED — ${msg}`);
          }
        }
        if (orSkipped > 0) {
          console.log(`[INFERENCE] Tier 5 (OpenRouter): ${orSkipped}/${OPENROUTER_FREE_MODELS.length} models cooling`);
        }
      }

      // All backends exhausted — report which are on daily vs rate cooldowns
      const dailyCooling: string[] = [];
      const rateCooling: string[] = [];
      for (const [model, until] of modelCooldowns.entries()) {
        if (until - Date.now() > 3_600_000) dailyCooling.push(model.split("/").pop()!);
        else rateCooling.push(model.split("/").pop()!);
      }
      const msg = [
        dailyCooling.length ? `daily-limit: ${dailyCooling.join(", ")}` : "",
        rateCooling.length ? `rate-limit: ${rateCooling.join(", ")}` : "",
      ].filter(Boolean).join(" | ");
      console.error(`[INFERENCE] All tiers exhausted. ${msg || "all providers failed"}`);
      throw new Error(`[rate_limit] All inference backends exhausted. ${msg}`);
    }

    // Legacy path when no Groq key configured
    const model = opts?.model || currentModel;

    const usesCompletionTokens = /^(o[1-9]|gpt-5|gpt-4\.1)/.test(model);
    const body: Record<string, unknown> = {
      model,
      messages: messages.map(formatMessage),
      stream: false,
    };

    if (usesCompletionTokens) {
      body.max_completion_tokens = tokenLimit;
    } else {
      body.max_tokens = tokenLimit;
    }

    if (opts?.temperature !== undefined) {
      body.temperature = opts.temperature;
    }

    if (tools && tools.length > 0) {
      body.tools = tools;
      body.tool_choice = "auto";
    }

    const backend = resolveInferenceBackend(model, { openaiApiKey, anthropicApiKey });

    if (backend === "anthropic") {
      return chatViaAnthropic({
        model,
        tokenLimit,
        messages,
        tools,
        temperature: opts?.temperature,
        anthropicApiKey: anthropicApiKey as string,
      });
    }

    const openAiLikeApiUrl = backend === "openai" ? "https://api.openai.com" : apiUrl;
    const openAiLikeApiKey = backend === "openai" ? (openaiApiKey as string) : apiKey;

    return chatViaOpenAiCompatible({
      model,
      body,
      apiUrl: openAiLikeApiUrl,
      apiKey: openAiLikeApiKey,
      backend,
    });
  };

  const setLowComputeMode = (enabled: boolean): void => {
    if (enabled) {
      currentModel = options.lowComputeModel || "claude-haiku-4-5-20251001";
      maxTokens = 4096;
    } else {
      currentModel = options.defaultModel;
      maxTokens = options.maxTokens;
    }
  };

  const getDefaultModel = (): string => {
    return hasCascadeKey ? lastUsedModel : currentModel;
  };

  return {
    chat,
    setLowComputeMode,
    getDefaultModel,
  };
}

function formatMessage(
  msg: ChatMessage,
): Record<string, unknown> {
  const formatted: Record<string, unknown> = {
    role: msg.role,
    content: msg.content,
  };

  if (msg.name) formatted.name = msg.name;
  if (msg.tool_calls) formatted.tool_calls = msg.tool_calls;
  if (msg.tool_call_id) formatted.tool_call_id = msg.tool_call_id;

  return formatted;
}

function resolveInferenceBackend(
  model: string,
  keys: {
    openaiApiKey?: string;
    anthropicApiKey?: string;
  },
): InferenceBackend {
  if (keys.anthropicApiKey && /^claude/i.test(model)) {
    return "anthropic";
  }
  if (keys.openaiApiKey && /^(gpt|o[1-9]|chatgpt)/i.test(model)) {
    return "openai";
  }
  return "conway";
}

async function chatViaGroq(params: {
  model: string;
  tokenLimit: number;
  messages: ChatMessage[];
  tools?: InferenceToolDefinition[];
  temperature?: number;
  groqApiKey: string;
}): Promise<InferenceResponse> {
  const Groq = (await import("groq-sdk")).default;
  const groq = new Groq({ apiKey: params.groqApiKey });

  const fullMessages: any[] = [];
  for (const msg of params.messages) {
    if (msg.role === "tool") {
      fullMessages.push({
        role: "tool",
        tool_call_id: msg.tool_call_id,
        content: msg.content,
      });
    } else {
      const formatted: Record<string, unknown> = {
        role: msg.role,
        content: msg.content || "",
      };
      if (msg.tool_calls && msg.tool_calls.length > 0) formatted.tool_calls = msg.tool_calls;
      if (msg.tool_call_id) formatted.tool_call_id = msg.tool_call_id;
      fullMessages.push(formatted);
    }
  }

  const createParams: any = {
    model: params.model,
    messages: fullMessages,
    max_tokens: params.tokenLimit,
  };

  if (params.temperature !== undefined) {
    createParams.temperature = params.temperature;
  }

  if (params.tools && params.tools.length > 0) {
    createParams.tools = params.tools;
    createParams.tool_choice = "auto";
  }

  const completion = await groq.chat.completions.create(createParams);
  const choice = completion.choices?.[0];

  if (!choice) {
    throw new Error("No completion choice returned from Groq");
  }

  const message = choice.message;
  const usage: TokenUsage = {
    promptTokens: completion.usage?.prompt_tokens || 0,
    completionTokens: completion.usage?.completion_tokens || 0,
    totalTokens: completion.usage?.total_tokens || 0,
  };

  const toolCalls = extractToolCalls(message);
  const textContent = extractTextContent(message);

  return {
    id: completion.id || "",
    model: completion.model || params.model,
    message: {
      role: "assistant",
      content: textContent,
      tool_calls: toolCalls,
    },
    toolCalls,
    usage,
    finishReason: choice.finish_reason || "stop",
  };
}

async function chatViaOpenAiCompatible(params: {
  model: string;
  body: Record<string, unknown>;
  apiUrl: string;
  apiKey: string;
  backend: "conway" | "openai" | "groq" | "anthropic" | "cerebras" | "openrouter" | "gemini";
}): Promise<InferenceResponse> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    // Conway uses raw key; every other backend uses Bearer
    Authorization: params.backend === "conway" ? params.apiKey : `Bearer ${params.apiKey}`,
  };
  if (params.backend === "openrouter") {
    headers["HTTP-Referer"] = "https://github.com/Conway-Research/entity";
    headers["X-Title"] = "TIAMAT";
  }
  const resp = await fetch(`${params.apiUrl}/v1/chat/completions`, {
    method: "POST",
    headers,
    body: JSON.stringify(params.body),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(
      `Inference error (${params.backend}): ${resp.status}: ${text}`,
    );
  }

  const data = await resp.json() as any;
  const choice = data.choices?.[0];

  if (!choice) {
    throw new Error("No completion choice returned from inference");
  }

  const message = choice.message;
  const usage: TokenUsage = {
    promptTokens: data.usage?.prompt_tokens || 0,
    completionTokens: data.usage?.completion_tokens || 0,
    totalTokens: data.usage?.total_tokens || 0,
  };

  const toolCalls = extractToolCalls(message);
  const textContent = extractTextContent(message);

  return {
    id: data.id || "",
    model: data.model || params.model,
    message: {
      role: message.role,
      content: textContent,
      tool_calls: toolCalls,
    },
    toolCalls,
    usage,
    finishReason: choice.finish_reason || "stop",
  };
}

async function chatViaAnthropic(params: {
  model: string;
  tokenLimit: number;
  messages: ChatMessage[];
  tools?: InferenceToolDefinition[];
  temperature?: number;
  anthropicApiKey: string;
}): Promise<InferenceResponse> {
  const transformed = transformMessagesForAnthropic(params.messages);
  const body: Record<string, unknown> = {
    model: params.model,
    max_tokens: params.tokenLimit,
    messages:
      transformed.messages.length > 0
        ? transformed.messages
        : [{ role: "user", content: "Continue." }],
  };

  // ── Prompt Caching ──
  // Split the system text on CACHE_SENTINEL into a static (cached) block and
  // a dynamic (per-cycle) block. The static block contains identity, SOUL.md,
  // MISSION.md, and tool descriptions — it barely changes, so subsequent calls
  // pay only 0.1x for those tokens instead of 1x. First call pays 1.25x to
  // write the cache; cache TTL is 5 minutes (refreshed on every call within TTL).
  if (transformed.system) {
    const systemText = transformed.system;
    const splitIdx = systemText.indexOf(CACHE_SENTINEL);
    if (splitIdx !== -1) {
      const staticPart  = systemText.slice(0, splitIdx);
      const dynamicPart = systemText.slice(splitIdx + CACHE_SENTINEL.length);
      body.system = [
        { type: "text", text: staticPart,  cache_control: { type: "ephemeral" } },
        { type: "text", text: dynamicPart },
      ];
    } else {
      // No sentinel: cache the entire system block (best-effort for short prompts)
      body.system = [
        { type: "text", text: systemText, cache_control: { type: "ephemeral" } },
      ];
    }
  }

  if (params.temperature !== undefined) {
    body.temperature = params.temperature;
  }

  if (params.tools && params.tools.length > 0) {
    const toolDefs = params.tools.map((tool) => ({
      name: tool.function.name,
      description: tool.function.description,
      input_schema: tool.function.parameters,
    }));
    // Cache the tools block: add cache_control to the LAST tool definition.
    // Anthropic caches everything from the start up to the last cache_control
    // breakpoint, so this covers system prompt + all tool definitions.
    if (toolDefs.length > 0) {
      (toolDefs[toolDefs.length - 1] as any).cache_control = { type: "ephemeral" };
    }
    body.tools = toolDefs;
    body.tool_choice = { type: "auto" };
  }

  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": params.anthropicApiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-beta": "prompt-caching-2024-07-31",
    },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Inference error (anthropic): ${resp.status}: ${text}`);
  }

  const data = await resp.json() as any;
  const content = Array.isArray(data.content) ? data.content : [];
  const textBlocks = content.filter((c: any) => c?.type === "text");
  const toolUseBlocks = content.filter((c: any) => c?.type === "tool_use");

  const toolCalls: InferenceToolCall[] | undefined =
    toolUseBlocks.length > 0
      ? toolUseBlocks.map((tool: any) => ({
          id: tool.id,
          type: "function" as const,
          function: {
            name: tool.name,
            arguments: JSON.stringify(tool.input || {}),
          },
        }))
      : undefined;

  const textContent = textBlocks
    .map((block: any) => String(block.text || ""))
    .join("\n")
    .trim();

  if (!textContent && !toolCalls?.length) {
    console.warn(`[INFERENCE] Anthropic empty content — stop_reason: ${data.stop_reason || "unknown"}, content blocks: ${JSON.stringify(content.map((c: any) => c?.type))}`);
    throw new Error("No completion content returned from anthropic inference");
  }

  const promptTokens     = data.usage?.input_tokens                 || 0;
  const completionTokens = data.usage?.output_tokens                || 0;
  const cacheReadTokens  = data.usage?.cache_read_input_tokens      || 0;
  const cacheWriteTokens = data.usage?.cache_creation_input_tokens  || 0;

  console.log(
    `[INFERENCE] Tokens — input:${promptTokens} cache_read:${cacheReadTokens}` +
    ` cache_write:${cacheWriteTokens} output:${completionTokens}` +
    (cacheReadTokens > 0 ? ` ✓ cache hit (${Math.round(cacheReadTokens / (promptTokens + cacheReadTokens) * 100)}% cached)` : " (cache miss/write)")
  );

  const usage: TokenUsage = {
    promptTokens,
    completionTokens,
    totalTokens: promptTokens + completionTokens,
    cacheReadTokens,
    cacheWriteTokens,
  };

  return {
    id: data.id || "",
    model: data.model || params.model,
    message: {
      role: "assistant",
      content: textContent,
      tool_calls: toolCalls,
    },
    toolCalls,
    usage,
    finishReason: normalizeAnthropicFinishReason(data.stop_reason),
  };
}

function transformMessagesForAnthropic(
  messages: ChatMessage[],
): { system?: string; messages: Array<Record<string, unknown>> } {
  const systemParts: string[] = [];
  const transformed: Array<Record<string, unknown>> = [];

  let i = 0;
  while (i < messages.length) {
    const msg = messages[i];

    if (msg.role === "system") {
      if (msg.content) systemParts.push(msg.content);
      i++;
      continue;
    }

    if (msg.role === "user") {
      transformed.push({ role: "user", content: msg.content });
      i++;
      continue;
    }

    if (msg.role === "assistant") {
      const content: Array<Record<string, unknown>> = [];
      if (msg.content) content.push({ type: "text", text: msg.content });
      for (const toolCall of msg.tool_calls || []) {
        content.push({
          type: "tool_use",
          id: toolCall.id,
          name: toolCall.function.name,
          input: parseToolArguments(toolCall.function.arguments),
        });
      }
      if (content.length === 0) content.push({ type: "text", text: "" });
      transformed.push({ role: "assistant", content });
      i++;
      continue;
    }

    // Anthropic requires all consecutive tool results in ONE user message.
    // Batch every adjacent run of role:"tool" messages together.
    if (msg.role === "tool") {
      const toolResults: Array<Record<string, unknown>> = [];
      while (i < messages.length && messages[i].role === "tool") {
        const t = messages[i];
        toolResults.push({
          type: "tool_result",
          tool_use_id: t.tool_call_id || "unknown_tool_call",
          content: t.content,
        });
        i++;
      }
      transformed.push({ role: "user", content: toolResults });
      continue;
    }

    i++;
  }

  return {
    system: systemParts.length > 0 ? systemParts.join("\n\n") : undefined,
    messages: transformed,
  };
}

async function chatViaGemini(params: {
  model: string;
  tokenLimit: number;
  messages: ChatMessage[];
  tools?: InferenceToolDefinition[];
  temperature?: number;
  geminiApiKey: string;
}): Promise<InferenceResponse> {
  const { system, contents } = transformMessagesForGemini(params.messages);

  const body: Record<string, unknown> = {
    contents,
    generationConfig: {
      maxOutputTokens: params.tokenLimit,
      ...(params.temperature !== undefined ? { temperature: params.temperature } : {}),
    },
  };

  if (system) {
    body.systemInstruction = { parts: [{ text: system }] };
  }

  if (params.tools && params.tools.length > 0) {
    body.tools = [{
      functionDeclarations: params.tools.map((t) => ({
        name: t.function.name,
        description: t.function.description,
        parameters: t.function.parameters,
      })),
    }];
    body.toolConfig = { functionCallingConfig: { mode: "AUTO" } };
  }

  const resp = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${params.model}:generateContent?key=${params.geminiApiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Inference error (gemini): ${resp.status}: ${text}`);
  }

  const data = await resp.json() as any;
  const candidate = data.candidates?.[0];
  if (!candidate) throw new Error("No candidate returned from Gemini");

  const parts: any[] = candidate.content?.parts ?? [];
  const textContent = parts
    .filter((p: any) => typeof p.text === "string")
    .map((p: any) => p.text)
    .join("\n")
    .trim();

  const toolCalls: InferenceToolCall[] | undefined = (() => {
    const fcParts = parts.filter((p: any) => p.functionCall);
    if (fcParts.length === 0) return undefined;
    return fcParts.map((p: any, i: number) => ({
      id: `gemini-fc-${Date.now()}-${i}`,
      type: "function" as const,
      function: {
        name: p.functionCall.name,
        arguments: JSON.stringify(p.functionCall.args || {}),
      },
    }));
  })();

  const promptTokens = data.usageMetadata?.promptTokenCount || 0;
  const completionTokens = data.usageMetadata?.candidatesTokenCount || 0;
  const usage: TokenUsage = { promptTokens, completionTokens, totalTokens: promptTokens + completionTokens };

  const rawReason = (candidate.finishReason || "STOP").toUpperCase();
  const finishReason = rawReason === "MAX_TOKENS" ? "length" : toolCalls ? "tool_calls" : "stop";

  return {
    id: `gemini-${Date.now()}`,
    model: params.model,
    message: { role: "assistant", content: textContent, tool_calls: toolCalls },
    toolCalls,
    usage,
    finishReason,
  };
}

function transformMessagesForGemini(
  messages: ChatMessage[],
): { system?: string; contents: Array<Record<string, unknown>> } {
  const systemParts: string[] = [];
  const contents: Array<Record<string, unknown>> = [];

  // Pre-scan: build tool_call_id → function name map for resolving tool responses
  const toolCallNames = new Map<string, string>();
  for (const msg of messages) {
    for (const tc of msg.tool_calls || []) {
      toolCallNames.set(tc.id, tc.function.name);
    }
  }

  let i = 0;
  while (i < messages.length) {
    const msg = messages[i];

    if (msg.role === "system") {
      if (msg.content) systemParts.push(msg.content);
      i++;
      continue;
    }

    if (msg.role === "user") {
      contents.push({ role: "user", parts: [{ text: msg.content || "" }] });
      i++;
      continue;
    }

    if (msg.role === "assistant") {
      const parts: any[] = [];
      if (msg.content) parts.push({ text: msg.content });
      for (const tc of msg.tool_calls || []) {
        parts.push({
          functionCall: {
            name: tc.function.name,
            args: parseToolArguments(tc.function.arguments),
          },
        });
      }
      if (parts.length === 0) parts.push({ text: "" });
      contents.push({ role: "model", parts });
      i++;
      continue;
    }

    // Batch consecutive tool results into one user turn (Gemini requires this)
    if (msg.role === "tool") {
      const functionResponseParts: any[] = [];
      while (i < messages.length && messages[i].role === "tool") {
        const t = messages[i];
        const funcName = toolCallNames.get(t.tool_call_id || "") || "unknown_function";
        functionResponseParts.push({
          functionResponse: {
            name: funcName,
            response: { result: t.content || "" },
          },
        });
        i++;
      }
      contents.push({ role: "user", parts: functionResponseParts });
      continue;
    }

    i++;
  }

  // Gemini requires alternating user/model turns; merge consecutive same-role entries
  const normalized: Array<Record<string, unknown>> = [];
  for (const entry of contents) {
    const last = normalized[normalized.length - 1];
    if (last && last.role === entry.role) {
      (last.parts as any[]).push(...(entry.parts as any[]));
    } else {
      normalized.push({ role: entry.role, parts: [...(entry.parts as any[])] });
    }
  }
  // Contents must not start with "model"
  if (normalized[0]?.role === "model") {
    normalized.unshift({ role: "user", parts: [{ text: "" }] });
  }

  return {
    system: systemParts.length > 0 ? systemParts.join("\n\n") : undefined,
    contents: normalized,
  };
}

function parseToolArguments(raw: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return { value: parsed };
  } catch {
    return { _raw: raw };
  }
}

function normalizeAnthropicFinishReason(reason: unknown): string {
  if (typeof reason !== "string") return "stop";
  if (reason === "tool_use") return "tool_calls";
  return reason;
}
