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

// Cost-optimized provider cascade (cheapest first)
const PROVIDER_CASCADE = {
  routine: ['groq', 'anthropic', 'cerebras', 'gemini'],  // Try cheaper first
  strategic: ['anthropic', 'groq', 'cerebras'],           // Need better reasoning
  fallback: ['openrouter']                                 // Last resort
};

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
  sambanovaApiKey?: string;
  openrouterApiKey?: string;
  geminiApiKey?: string;
  perplexityApiKey?: string;
  doInferenceKey?: string;
  deepinfraApiKey?: string;
  tiamatlocalEndpoint?: string;
}

type InferenceBackend = "groq" | "conway" | "openai" | "anthropic" | "cerebras" | "sambanova" | "openrouter" | "gemini" | "perplexity" | "tiamat-local" | "do-inference" | "deepinfra";

// DeepInfra models — clean reasoning, no training data contamination
// BLACKLISTED 2026-03-19: Qwen3-235B refuses TIAMAT's system prompt as "fictional scenario"
// Burned 2+ hours of stuck cycles. DO NOT re-enable without testing.
const DEEPINFRA_MODELS = {
  primary:  "deepseek-ai/DeepSeek-V3",               // DeepSeek-V3 — strong reasoning + tool calling
  reasoning: "deepseek-ai/DeepSeek-V3",               // DeepSeek-V3 — best free model for tool use
  fast:     "meta-llama/Llama-3.3-70B-Instruct",     // 70B — fast fallback
};

// Token thresholds for model routing
const GROQ_MODEL        = "llama-3.3-70b-versatile";           // Tier 2: Groq free
const CEREBRAS_MODEL    = "gpt-oss-120b";                      // Tier 3: Cerebras free (120B, 1-2s, tool calling)
const SAMBANOVA_MODEL   = "Meta-Llama-3.3-70B-Instruct";       // Tier 3.5: SambaNova free (70B, fast)
const GEMINI_MODEL      = "gemini-2.5-flash";                  // Tier 4: Gemini free
const PERPLEXITY_MODEL  = "sonar";                              // Tier 1.5: Perplexity Sonar (paid, web-grounded)
const ANTHROPIC_MODEL   = "claude-haiku-4-5-20251001";         // Tier 6: Anthropic paid fallback
// DigitalOcean Gradient Serverless — MULTI-MODEL BRAIN (paid via DO credits)
// Commercial models (GPT-5.4, Claude Opus/Sonnet 4.6) at top, open-source as overflow
const DO_MODELS = {
  // — Commercial tier (best reasoning, paid per token via DO billing) —
  strategic: "openai-gpt-5.4",               // GPT-5.4 Thinking — best reasoning model
  sonnet:    "anthropic-claude-4.6-sonnet",   // Claude Sonnet 4.6 — fast + capable
  opus:      "anthropic-claude-opus-4.6",     // Claude Opus 4.6 — max quality fallback
  gpt5:      "openai-gpt-5.2",               // GPT-5.2 — strong general purpose
  // — Open-source tier (cheaper, daily token pools) —
  routine:   "openai-gpt-oss-120b",           // 120B — best OSS, 20M/day pool
  llama:     "llama3.3-70b-instruct",         // 70B — proven tool calling
  overflow:  "alibaba-qwen3-32b",             // 32B — decent quality
  // llama3-8b removed — consistently 400s on DO Gradient
  nemo:      "mistral-nemo-instruct-2407",    // 12B — last resort DO
};
const TIAMAT_LOCAL_MODEL = "tiamat-local";                      // Tier 0: Self-hosted fine-tuned Qwen (FREE)
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
 * CORE tools only — the absolute minimum for open-source models to function.
 * More tools = more confusion = worse instruction following.
 * 10 tools max for routine, expanded set for strategic bursts.
 */
const CORE_TOOLS = new Set([
  "read_bluesky", "like_bluesky", "repost_bluesky", "post_bluesky",
  "read_file", "write_file", "exec", "remember", "recall",
  "post_farcaster",
]);

// Routine tools for open-source models (~25 tools)
// NO send_email (cold emails strangers), NO browse (loops), NO ticket_* (busywork)
// These models can do: social engagement, read/write files, search, remember
const SMALL_PROVIDER_TOOLS = new Set([
  ...CORE_TOOLS,
  "search_web", "web_fetch",
  "post_mastodon", "post_devto",
  "like_bluesky", "repost_bluesky", "read_mastodon", "mastodon_engage",
  "recall", "learn_fact", "grow",
  "generate_image",
]);

function filterToolsForSmallProvider(tools: InferenceToolDefinition[]): InferenceToolDefinition[] {
  return tools.filter(t => SMALL_PROVIDER_TOOLS.has(t.function.name));
}

function filterToolsCore(tools: InferenceToolDefinition[]): InferenceToolDefinition[] {
  return tools.filter(t => CORE_TOOLS.has(t.function.name));
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

/**
 * Inject FALLBACK_DIRECTIVE into the system message for low-tier models.
 * Appends to the existing system message (or prepends one if missing).
 */
function injectFallbackDirective(messages: ChatMessage[]): ChatMessage[] {
  const result = [...messages];
  if (result.length > 0 && result[0].role === "system") {
    result[0] = { ...result[0], content: result[0].content + "\n" + FALLBACK_DIRECTIVE };
  } else {
    result.unshift({ role: "system", content: FALLBACK_DIRECTIVE });
  }
  return result;
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
const COOLDOWN_DAILY_LIMIT_MS = 1 * 3600_000; // 1h for daily quota exhaustion (retry sooner — 4h was too conservative)

/**
 * Fallback directive injected into system message for low-tier models.
 * These models lose most conversation context after trimming, so they need
 * a clear directive to avoid wasting cycles on useless exploration (ls -R, etc).
 */
const FALLBACK_DIRECTIVE = `
CRITICAL: You are a fallback model with limited context. DO NOT explore the filesystem.
DO NOT run "ls", "find", "tree", or any directory listing commands. You don't need to orient yourself.
Instead, pick ONE productive action from your available tools:
- Post to Bluesky (share a thought, engage with community)
- Search the web for AI/tech news and remember interesting findings
- Check email for new messages
- Create or complete a ticket for future work
- Write a short thought/reflection to remember
If you cannot determine a useful action, call exec with: echo "FALLBACK_SKIP: no productive action available"
`;

// Per-provider request timeouts (ms).
// Without these, a hung provider stalls the cascade for Node's socket timeout (~2min).
const TIMEOUT_DO_INFERENCE = 45_000; // 45s — DO Gradient Serverless
const TIMEOUT_TIAMAT_LOCAL = 15_000; // 15s — self-hosted on GPU pod
const TIMEOUT_TIAMAT_HEALTH = 3_000; // 3s — quick health check
const TIMEOUT_ANTHROPIC  = 90_000;  // 90s — 15k token prompts regularly take 40-55s
const TIMEOUT_GROQ       = 30_000;  // 30s — usually <10s
const TIMEOUT_CEREBRAS   = 30_000;  // 30s — usually <5s
const TIMEOUT_SAMBANOVA  = 45_000;  // 45s
const TIMEOUT_GEMINI     = 45_000;  // 45s
const TIMEOUT_OPENROUTER = 45_000;  // 45s — free models can be slow under load

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
  const { apiUrl, apiKey, openaiApiKey, anthropicApiKey, groqApiKey, cerebrasApiKey, sambanovaApiKey, openrouterApiKey, geminiApiKey, perplexityApiKey, doInferenceKey, deepinfraApiKey, tiamatlocalEndpoint } = options;
  let currentModel = options.defaultModel;
  let maxTokens = options.maxTokens;

  // True if any cascade key is configured (Anthropic is now Tier 1).
  const hasCascadeKey = !!(deepinfraApiKey || doInferenceKey || anthropicApiKey || perplexityApiKey || groqApiKey || cerebrasApiKey || sambanovaApiKey || openrouterApiKey || geminiApiKey);

  // Log which providers are available at startup
  {
    const providers = [
      tiamatlocalEndpoint ? `TiamatLocal(${TIAMAT_LOCAL_MODEL}) [SELF-HOSTED]` : "TiamatLocal:NO_ENDPOINT",
      doInferenceKey   ? `DO-Gradient(${Object.values(DO_MODELS).length} models: GPT-5.4+Sonnet4.6+Opus4.6+GPT-5.2+120B+70B+32B+8B) [PRIMARY]` : "DO-Gradient:NO_KEY",
      anthropicApiKey  ? `Anthropic(${ANTHROPIC_MODEL}) [FALLBACK]` : "Anthropic:NO_KEY",
      perplexityApiKey ? `Perplexity(${PERPLEXITY_MODEL}) [WEB]`   : "Perplexity:NO_KEY",
      groqApiKey       ? `Groq(${GROQ_MODEL})`             : "Groq:NO_KEY",
      cerebrasApiKey   ? `Cerebras(${CEREBRAS_MODEL})`     : "Cerebras:NO_KEY",
      sambanovaApiKey  ? `SambaNova(${SAMBANOVA_MODEL})`   : "SambaNova:NO_KEY",
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
        return await chatViaOpenAiCompatible({ model: requestedModel, body: overrideBody, apiUrl: backend === "openai" ? "https://api.openai.com" : apiUrl, apiKey: backend === "openai" ? openaiApiKey! : apiKey, backend, timeoutMs: 60_000 });
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
      console.log(`[INFERENCE] ~${estimated} tokens, tier=${requestedTier} — starting cascade (keys: anthropic=${!!anthropicApiKey} perplexity=${!!perplexityApiKey} groq=${!!groqApiKey} cerebras=${!!cerebrasApiKey} sambanova=${!!sambanovaApiKey} gemini=${!!geminiApiKey} openrouter=${!!openrouterApiKey})`);

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

      // Tier 0: tiamat-local — self-hosted fine-tuned model on GPU pod (FREE, ~6-9s)
      // Only for routine/free tiers. Strategic cycles always go to Anthropic.
      // Requires health check to pass (pod may be down).
      if (tiamatlocalEndpoint && requestedTier !== "sonnet" && !isCoolingDown(TIAMAT_LOCAL_MODEL)) {
        try {
          // Quick health check (3s timeout — pod may be offline)
          const healthResp = await fetchWithTimeout(
            `${tiamatlocalEndpoint}/health`,
            { method: "GET" },
            TIMEOUT_TIAMAT_HEALTH,
            "tiamat-local-health",
          );
          if (healthResp.ok) {
            lastUsedModel = TIAMAT_LOCAL_MODEL;
            const localTools = tools ? filterToolsForSmallProvider(tools) : undefined;
            const localMessages = trimToTokenBudget(messages, 3500);
            const localEst = estimateTokens(localMessages, localTools);
            const trimNote = localMessages.length < messages.length ? `, trimmed ${messages.length - localMessages.length} msgs` : "";
            console.log(`[INFERENCE] Tier 0 (tiamat-local): ATTEMPT (~${localEst} tokens, ${localTools?.length || 0} tools${trimNote})`);
            const body: Record<string, unknown> = {
              model: TIAMAT_LOCAL_MODEL,
              messages: localMessages.map(formatMessage),
              stream: false,
              max_tokens: Math.min(tokenLimit, 2048),
            };
            if (opts?.temperature !== undefined) body.temperature = opts.temperature;
            if (localTools && localTools.length > 0) { body.tools = localTools; body.tool_choice = "auto"; }
            return await chatViaOpenAiCompatible({ model: TIAMAT_LOCAL_MODEL, body, apiUrl: tiamatlocalEndpoint, apiKey: "none", backend: "tiamat-local", timeoutMs: TIMEOUT_TIAMAT_LOCAL });
          }
        } catch (err: any) {
          // Pod is down or unhealthy — cooldown and fall through silently
          setCooldown(TIAMAT_LOCAL_MODEL, 5 * 60_000); // 5 min cooldown on failure
          console.log(`[INFERENCE] Tier 0 (tiamat-local): OFFLINE — ${err.message} (5m cooldown)`);
        }
      } else if (tiamatlocalEndpoint && isCoolingDown(TIAMAT_LOCAL_MODEL)) {
        console.log(`[INFERENCE] Tier 0 (tiamat-local): SKIP — cooling (${coolRemaining(TIAMAT_LOCAL_MODEL)} left)`);
      }

      // Tier 0.5: DigitalOcean Gradient Serverless — MULTI-MODEL BRAIN (PRIMARY)
      // Commercial models (GPT-5.4, Claude 4.6) for strategic; OSS for routine; full cascade fallback
      if (!doInferenceKey) {
        console.log(`[INFERENCE] Tier 0.5 (DO-Gradient): SKIP — no key`);
      } else {
        const isStrategic = requestedTier === "sonnet" || (opts?.cycleContext && opts.cycleContext !== "routine");

        const commercialModels = [DO_MODELS.strategic, DO_MODELS.sonnet, DO_MODELS.opus, DO_MODELS.gpt5];
        const ossModels = [DO_MODELS.routine, DO_MODELS.llama, DO_MODELS.overflow, DO_MODELS.nemo];
        // GPT-5.4 for ALL cycles — paid via DO credits, smart enough to use tools
        const doModelOrder = isStrategic
          ? [...commercialModels, ...ossModels]
          : [DO_MODELS.strategic, DO_MODELS.sonnet, DO_MODELS.routine, DO_MODELS.llama, DO_MODELS.overflow];

        let doAttempted = 0;
        let doSkipped = 0;
        for (const doModel of doModelOrder) {
          if (isCoolingDown(doModel)) {
            doSkipped++;
            continue;
          }
          doAttempted++;
          try {
            lastUsedModel = doModel;
            const isCommercial = commercialModels.includes(doModel);
            // GPT-5.4 and Sonnet always get full tools — they're smart enough
            const useFullTools = isStrategic || isCommercial || doModel === DO_MODELS.strategic || doModel === DO_MODELS.sonnet;
            const doTools = useFullTools ? tools : (tools ? filterToolsForSmallProvider(tools) : undefined);
            const contextBudget = isCommercial ? (isStrategic ? 32000 : 20000)
              : doModel === DO_MODELS.routine ? (isStrategic ? 24000 : 16000)
              : doModel === DO_MODELS.llama ? (isStrategic ? 12000 : 8000)
              : doModel === DO_MODELS.overflow ? 6000
              : 4000;
            const doMessages = trimToTokenBudget(messages, contextBudget);
            const doEst = estimateTokens(doMessages, doTools);
            const trimNote = doMessages.length < messages.length ? `, trimmed ${messages.length - doMessages.length} msgs` : "";
            const shortName = doModel.replace(/-instruct$/, "").replace("openai-", "").replace("anthropic-claude-", "claude-");
            console.log(`[INFERENCE] DO/${shortName}: ATTEMPT (~${doEst} tokens, ${doTools?.length || 0} tools${trimNote})`);
            const maxOut = (isCommercial || doModel === DO_MODELS.routine) ? 4096 : 2048;
            const body: Record<string, unknown> = {
              model: doModel,
              messages: formatMessagesForDO(doMessages),
              stream: false,
              max_completion_tokens: Math.max(256, Math.min(tokenLimit, maxOut)),
            };
            if (opts?.temperature !== undefined) body.temperature = opts.temperature;
            if (doTools && doTools.length > 0) { body.tools = doTools; body.tool_choice = "auto"; }
            const result = await chatViaOpenAiCompatible({ model: doModel, body, apiUrl: "https://inference.do-ai.run", apiKey: doInferenceKey, backend: "do-inference", timeoutMs: TIMEOUT_DO_INFERENCE });
            if (result.rateLimitHeaders && result.rateLimitHeaders.limitPerDay > 0) {
              const pct = Math.round((result.rateLimitHeaders.remainingPerDay / result.rateLimitHeaders.limitPerDay) * 100);
              console.log(`[INFERENCE] DO/${shortName}: pool ${result.rateLimitHeaders.remainingPerDay.toLocaleString()}/${result.rateLimitHeaders.limitPerDay.toLocaleString()} tokens/day (${pct}%)`);
              if (result.rateLimitHeaders.remainingPerDay < 100_000) {
                console.warn(`[INFERENCE] DO/${shortName}: daily pool nearly empty — cooling 1h`);
                setCooldown(doModel, COOLDOWN_DAILY_LIMIT_MS);
              }
            }
            return result;
          } catch (err: any) {
            if (isRateLimitError(err)) setCooldown(doModel, COOLDOWN_DAILY_LIMIT_MS);
            const shortName = doModel.replace(/-instruct$/, "").replace("openai-", "").replace("anthropic-claude-", "claude-");
            console.warn(`[INFERENCE] DO/${shortName}: FAILED — ${err.message?.slice(0, 150)}`);
            if (err.message?.includes("daily") || isDailyLimitError(err)) break;
          }
        }
        if (doAttempted === 0 && doSkipped > 0) {
          console.log(`[INFERENCE] DO-Gradient: all ${doSkipped} models cooling down`);
        }
      }

      // Tier 0.75: DeepInfra — FALLBACK for when DO Gradient is exhausted
      if (!deepinfraApiKey) {
        console.log(`[INFERENCE] Tier 0.25 (DeepInfra): SKIP — no key`);
      } else {
        const isStrategicDI = requestedTier === "sonnet" || (opts?.cycleContext && opts.cycleContext !== "routine");
        const diModels = isStrategicDI
          ? [DEEPINFRA_MODELS.primary, DEEPINFRA_MODELS.reasoning]
          : [DEEPINFRA_MODELS.primary, DEEPINFRA_MODELS.fast];

        for (const diModel of diModels) {
          if (isCoolingDown(diModel)) continue;
          try {
            const shortName = diModel.split("/").pop() || diModel;
            const diMessages = trimToTokenBudget(messages, isStrategicDI ? 20000 : 14000);
            const diTools = isStrategicDI ? (tools ? filterToolsForSmallProvider(tools) : undefined) : (tools ? filterToolsForSmallProvider(tools) : undefined);
            const diEst = estimateTokens(diMessages, diTools);
            const trimNote = diMessages.length < messages.length ? `, trimmed ${messages.length - diMessages.length} msgs` : "";
            console.log(`[INFERENCE] DeepInfra/${shortName}: ATTEMPT (~${diEst} tokens${trimNote})`);
            lastUsedModel = diModel;
            const body: Record<string, unknown> = {
              model: diModel,
              messages: formatMessagesForDO(diMessages),
              stream: false,
              max_completion_tokens: Math.min(tokenLimit, isStrategicDI ? 4096 : 2048),
            };
            if (opts?.temperature !== undefined) body.temperature = opts.temperature;
            if (diTools && diTools.length > 0) { body.tools = diTools; body.tool_choice = "auto"; }
            const result = await chatViaOpenAiCompatible({
              model: diModel, body,
              apiUrl: "https://api.deepinfra.com",
              apiKey: deepinfraApiKey,
              backend: "deepinfra",
              timeoutMs: 60_000,
            });
            // Refusal detection: if model refuses system prompt, don't return — fall through to next tier
            const resultText = (result.message?.content || "").toLowerCase();
            const REFUSAL_MARKERS = [
              "i'm not going to continue", "i won't roleplay", "fictional premise",
              "fictional scenario", "not a real autonomous", "i will not continue",
              "i'm not going to engage", "jailbreak", "i refuse to",
              "i cannot participate", "i'm declining", "not going to play along",
            ];
            if (REFUSAL_MARKERS.some(m => resultText.includes(m))) {
              const shortName = diModel.split("/").pop() || diModel;
              console.warn(`[INFERENCE] DeepInfra/${shortName}: REFUSAL detected — blacklisting 1h, falling through`);
              setCooldown(diModel, 3_600_000); // 1 hour blacklist on refusal
              throw new Error(`Model ${shortName} refused system prompt`);
            }
            return result;
          } catch (err: any) {
            const shortName = diModel.split("/").pop() || diModel;
            if (isRateLimitError(err)) setCooldown(diModel, 300_000);
            console.warn(`[INFERENCE] DeepInfra/${shortName}: FAILED — ${err.message?.slice(0, 150)}`);
          }
        }
      }

      // (DO Gradient is now primary — moved to Tier 0.5 above DeepInfra)

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

      // Tier 3: (Cerebras promoted to Tier 0.6 above — dual 120B brains)

      // Tier 3.5: SambaNova — Meta-Llama-3.3-70B (free, fast, OpenAI-compatible)
      if (!sambanovaApiKey) {
        console.log(`[INFERENCE] Tier 3.5 (SambaNova): SKIP — no key`);
      } else if (isCoolingDown(SAMBANOVA_MODEL)) {
        console.log(`[INFERENCE] Tier 3.5 (SambaNova): SKIP — cooling (${coolRemaining(SAMBANOVA_MODEL)} left)`);
      } else {
        try {
          lastUsedModel = SAMBANOVA_MODEL;
          const snMessages = injectFallbackDirective(trimToTokenBudget(messages, 5000));
          const snTools = tools ? filterToolsForSmallProvider(tools) : undefined;
          const snEst = estimateTokens(snMessages, snTools);
          const trimNote = snMessages.length < messages.length ? `, trimmed ${messages.length - snMessages.length} msgs` : "";
          console.log(`[INFERENCE] Tier 3.5 (SambaNova): ATTEMPT ${SAMBANOVA_MODEL} (~${snEst} tokens, ${snTools?.length || 0} tools${trimNote})`);
          const body: Record<string, unknown> = {
            model: SAMBANOVA_MODEL,
            messages: snMessages.map(formatMessage),
            stream: false,
            max_tokens: Math.min(tokenLimit, 4096),
          };
          if (opts?.temperature !== undefined) body.temperature = opts.temperature;
          if (snTools && snTools.length > 0) { body.tools = snTools; body.tool_choice = "auto"; }
          return await chatViaOpenAiCompatible({ model: SAMBANOVA_MODEL, body, apiUrl: "https://api.sambanova.ai", apiKey: sambanovaApiKey, backend: "sambanova", timeoutMs: TIMEOUT_SAMBANOVA });
        } catch (err: any) {
          if (isRateLimitError(err)) smartCooldown(SAMBANOVA_MODEL, err);
          console.warn(`[INFERENCE] Tier 3.5 (SambaNova): FAILED — ${err.message}`);
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
          return await chatViaGemini({ model: GEMINI_MODEL, tokenLimit, messages: injectFallbackDirective(messages), tools, temperature: opts?.temperature, geminiApiKey });
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
              messages: injectFallbackDirective(messages).map(formatMessage),
              stream: false,
              max_tokens: tokenLimit,
            };
            if (opts?.temperature !== undefined) body.temperature = opts.temperature;
            if (tools && tools.length > 0) { body.tools = tools; body.tool_choice = "auto"; }
            return await chatViaOpenAiCompatible({ model: orModel, body, apiUrl: "https://openrouter.ai/api", apiKey: openrouterApiKey, backend: "openrouter", timeoutMs: TIMEOUT_OPENROUTER });
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

      // Last resort: if tier was "free" but all free providers are down, fall back to Anthropic Haiku
      // This prevents the agent from burning empty cycles when the free cascade is exhausted
      if (requestedTier === "free" && anthropicApiKey && !isCoolingDown(ANTHROPIC_MODEL)) {
        try {
          lastUsedModel = ANTHROPIC_MODEL;
          console.log(`[INFERENCE] FREE CASCADE EXHAUSTED — falling back to Anthropic Haiku (paid last-resort)`);
          return await chatViaAnthropic({ model: ANTHROPIC_MODEL, tokenLimit, messages, tools, temperature: opts?.temperature, anthropicApiKey });
        } catch (err: any) {
          if (isRateLimitError(err)) smartCooldown(ANTHROPIC_MODEL, err, COOLDOWN_RATE_LIMIT_MS * 2);
          console.warn(`[INFERENCE] Last-resort Anthropic FAILED — ${err.message}`);
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
      timeoutMs: 60_000,
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

  /** Returns ms until the shortest model cooldown expires, or 0 if none are cooling */
  const getShortestCooldownMs = (): number => {
    if (modelCooldowns.size === 0) return 0;
    const now = Date.now();
    let shortest = Infinity;
    for (const until of modelCooldowns.values()) {
      const remaining = until - now;
      if (remaining > 0 && remaining < shortest) shortest = remaining;
    }
    return shortest === Infinity ? 0 : shortest;
  };

  return {
    chat,
    setLowComputeMode,
    getDefaultModel,
    getShortestCooldownMs,
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

/**
 * Format messages for DO Gradient: split multi-tool-call assistant messages
 * into separate single-tool messages. DO's vLLM backend rejects multiple
 * parallel tool calls in a single assistant message.
 */
function truncateToolId(id: string | undefined): string | undefined {
  if (!id) return id;
  // OpenAI requires tool_call IDs <= 40 chars
  return id.length > 40 ? id.slice(0, 40) : id;
}

function formatMessagesForDO(messages: ChatMessage[]): Record<string, unknown>[] {
  const result: Record<string, unknown>[] = [];
  for (const msg of messages) {
    if (msg.role === "assistant" && msg.tool_calls && msg.tool_calls.length > 0) {
      // Split multi-tool-call messages + truncate IDs for OpenAI compat
      const calls = msg.tool_calls.map(tc => ({
        ...tc,
        id: truncateToolId(tc.id),
      }));
      for (let i = 0; i < calls.length; i++) {
        result.push({
          role: "assistant",
          content: i === 0 ? (msg.content || "") : "",
          tool_calls: [calls[i]],
        });
      }
    } else if (msg.role === "tool") {
      result.push({
        role: "tool",
        content: msg.content,
        tool_call_id: truncateToolId(msg.tool_call_id),
      });
    } else {
      result.push(formatMessage(msg));
    }
  }
  return result;
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

/**
 * fetch() with an AbortController timeout.
 * Throws a clear error (not AbortError) so cascade catch blocks can log it properly.
 */
function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  label: string,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...init, signal: controller.signal })
    .finally(() => clearTimeout(timer))
    .catch((err) => {
      if (err?.name === "AbortError") {
        throw new Error(`${label} timed out after ${timeoutMs / 1000}s`);
      }
      throw err;
    });
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
  const groq = new Groq({ apiKey: params.groqApiKey, timeout: TIMEOUT_GROQ });

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
  backend: InferenceBackend;
  timeoutMs?: number;
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
  const resp = await fetchWithTimeout(
    `${params.apiUrl}/v1/chat/completions`,
    { method: "POST", headers, body: JSON.stringify(params.body) },
    params.timeoutMs ?? 60_000,
    params.backend,
  );

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(
      `Inference error (${params.backend}): ${resp.status}: ${text}`,
    );
  }

  // Extract DO rate limit headers before consuming body
  const rateLimitHeaders = params.backend === "do-inference" ? {
    limitPerDay: parseInt(resp.headers.get("x-ratelimit-limit-tokens-per-day") || "0", 10),
    remainingPerDay: parseInt(resp.headers.get("x-ratelimit-remaining-tokens-per-day") || "0", 10),
  } : undefined;

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
    rateLimitHeaders,
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

  const resp = await fetchWithTimeout(
    "https://api.anthropic.com/v1/messages",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": params.anthropicApiKey,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
      },
      body: JSON.stringify(body),
    },
    TIMEOUT_ANTHROPIC,
    "anthropic",
  );

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

  const resp = await fetchWithTimeout(
    `https://generativelanguage.googleapis.com/v1beta/models/${params.model}:generateContent?key=${params.geminiApiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    TIMEOUT_GEMINI,
    "gemini",
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
