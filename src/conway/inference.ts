/**
 * Conway Inference Client
 *
 * Wraps Conway's /v1/chat/completions endpoint (OpenAI-compatible).
 * The automaton pays for its own thinking through Conway credits.
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
const GROQ_MODEL        = "llama-3.3-70b-versatile";           // Tier 1: Groq free
const CEREBRAS_MODEL    = "llama-3.3-70b";                     // Tier 2: Cerebras free
const OPENROUTER_MODEL  = "meta-llama/llama-3.3-70b-instruct:free"; // Tier 3: OpenRouter free
const GEMINI_MODEL      = "gemini-2.0-flash";                  // Tier 4: Gemini free
const ANTHROPIC_MODEL   = "claude-haiku-4-5-20251001";         // Tier 6: Anthropic paid fallback
const TOKEN_THRESHOLD_LARGE = 8000;

/** Cheap character-based token estimator (~4 chars per token). */
function estimateTokens(messages: ChatMessage[], tools?: InferenceToolDefinition[]): number {
  let chars = 0;
  for (const m of messages) chars += (m.content || "").length + 4; // 4 for role overhead
  if (tools) chars += JSON.stringify(tools).length;
  return Math.ceil(chars / 4);
}

function routeGroqModel(_estimatedTokens: number): string {
  return GROQ_MODEL;
}

function isRateLimitError(err: any): boolean {
  return (
    err?.status === 429 ||
    err?.error?.type === "tokens" ||
    /rate.?limit|too many requests|quota exceeded/i.test(err?.message || "")
  );
}

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
    console.warn(`[INFERENCE] ${model} rate-limited — cooling down for ${ms / 1000}s`);
  };

  const chat = async (
    messages: ChatMessage[],
    opts?: InferenceOptions,
  ): Promise<InferenceResponse> => {
    const tools = opts?.tools;
    const tokenLimit = opts?.maxTokens || maxTokens;

    // Fallback chain — each tier cools independently on rate limit.
    // Tier 1: Groq          llama-3.3-70b-versatile        free
    // Tier 2: Cerebras      llama-3.3-70b                  free
    // Tier 3: OpenRouter    llama-3.3-70b-instruct:free    free
    // Tier 4: Gemini        gemini-2.0-flash               free
    // Tier 5: OpenAI        gpt-4o-mini                    paid (optional)
    // Tier 6: Anthropic     claude-haiku                   paid (final safety net)
    if (groqApiKey) {
      const estimated = estimateTokens(messages, tools);
      const groqAvailable = estimated <= TOKEN_THRESHOLD_LARGE && !isCoolingDown(GROQ_MODEL);
      const groqModel: string | null = groqAvailable ? routeGroqModel(estimated) : null;
      console.log(`[INFERENCE] ~${estimated} tokens — starting cascade`);

      // Tier 1: Groq
      if (groqModel) {
        try {
          lastUsedModel = groqModel;
          console.log(`[INFERENCE] → Groq ${groqModel}`);
          return await chatViaGroq({ model: groqModel, tokenLimit, messages, tools, temperature: opts?.temperature, groqApiKey });
        } catch (err: any) {
          if (isRateLimitError(err)) setCooldown(GROQ_MODEL, 60_000);
          console.warn(`[INFERENCE] Groq failed (${err.message})`);
        }
      }

      // Tier 2: Cerebras (OpenAI-compatible, free tier)
      if (cerebrasApiKey && !isCoolingDown(CEREBRAS_MODEL)) {
        try {
          lastUsedModel = CEREBRAS_MODEL;
          console.log(`[INFERENCE] → Cerebras ${CEREBRAS_MODEL}`);
          const body: Record<string, unknown> = {
            model: CEREBRAS_MODEL,
            messages: messages.map(formatMessage),
            stream: false,
            max_tokens: tokenLimit,
          };
          if (opts?.temperature !== undefined) body.temperature = opts.temperature;
          if (tools && tools.length > 0) { body.tools = tools; body.tool_choice = "auto"; }
          return await chatViaOpenAiCompatible({ model: CEREBRAS_MODEL, body, apiUrl: "https://api.cerebras.ai", apiKey: cerebrasApiKey, backend: "cerebras" });
        } catch (err: any) {
          if (isRateLimitError(err)) setCooldown(CEREBRAS_MODEL, 60_000);
          console.warn(`[INFERENCE] Cerebras failed (${err.message})`);
        }
      }

      // Tier 3: OpenRouter (free model, OpenAI-compatible)
      if (openrouterApiKey && !isCoolingDown(OPENROUTER_MODEL)) {
        try {
          lastUsedModel = OPENROUTER_MODEL;
          console.log(`[INFERENCE] → OpenRouter ${OPENROUTER_MODEL}`);
          const body: Record<string, unknown> = {
            model: OPENROUTER_MODEL,
            messages: messages.map(formatMessage),
            stream: false,
            max_tokens: tokenLimit,
          };
          if (opts?.temperature !== undefined) body.temperature = opts.temperature;
          if (tools && tools.length > 0) { body.tools = tools; body.tool_choice = "auto"; }
          return await chatViaOpenAiCompatible({ model: OPENROUTER_MODEL, body, apiUrl: "https://openrouter.ai/api", apiKey: openrouterApiKey, backend: "openrouter" });
        } catch (err: any) {
          if (isRateLimitError(err)) setCooldown(OPENROUTER_MODEL, 60_000);
          console.warn(`[INFERENCE] OpenRouter failed (${err.message})`);
        }
      }

      // Tier 4: Gemini Flash (free, native API)
      if (geminiApiKey && !isCoolingDown(GEMINI_MODEL)) {
        try {
          lastUsedModel = GEMINI_MODEL;
          console.log(`[INFERENCE] → Gemini ${GEMINI_MODEL}`);
          return await chatViaGemini({ model: GEMINI_MODEL, tokenLimit, messages, tools, temperature: opts?.temperature, geminiApiKey });
        } catch (err: any) {
          if (isRateLimitError(err)) setCooldown(GEMINI_MODEL, 60_000);
          console.warn(`[INFERENCE] Gemini failed (${err.message})`);
        }
      }

      // Tier 5: OpenAI gpt-4o-mini (paid, optional)
      if (openaiApiKey && !isCoolingDown("openai")) {
        try {
          lastUsedModel = "gpt-4o-mini";
          console.log(`[INFERENCE] → OpenAI gpt-4o-mini`);
          const body: Record<string, unknown> = {
            model: "gpt-4o-mini",
            messages: messages.map(formatMessage),
            stream: false,
            max_tokens: tokenLimit,
          };
          if (opts?.temperature !== undefined) body.temperature = opts.temperature;
          if (tools && tools.length > 0) { body.tools = tools; body.tool_choice = "auto"; }
          return await chatViaOpenAiCompatible({ model: "gpt-4o-mini", body, apiUrl: "https://api.openai.com", apiKey: openaiApiKey, backend: "openai" });
        } catch (err: any) {
          if (isRateLimitError(err)) setCooldown("openai", 60_000);
          console.warn(`[INFERENCE] OpenAI failed (${err.message})`);
        }
      }

      // Tier 6: Anthropic claude-haiku (paid, final safety net)
      if (anthropicApiKey && !isCoolingDown(ANTHROPIC_MODEL)) {
        try {
          lastUsedModel = ANTHROPIC_MODEL;
          console.log(`[INFERENCE] → Anthropic ${ANTHROPIC_MODEL}`);
          return await chatViaAnthropic({ model: ANTHROPIC_MODEL, tokenLimit, messages, tools, temperature: opts?.temperature, anthropicApiKey });
        } catch (err: any) {
          if (isRateLimitError(err)) setCooldown(ANTHROPIC_MODEL, 120_000);
          throw err;
        }
      }

      // All backends cooling — signal loop to back off without sleeping
      const cooling = [GROQ_MODEL, CEREBRAS_MODEL, OPENROUTER_MODEL, GEMINI_MODEL, "openai", ANTHROPIC_MODEL]
        .filter(isCoolingDown).join(", ");
      throw new Error(`[rate_limit] All inference backends cooling down: ${cooling || "all"}`);
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
    return groqApiKey ? lastUsedModel : currentModel;
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

  if (transformed.system) {
    body.system = transformed.system;
  }

  if (params.temperature !== undefined) {
    body.temperature = params.temperature;
  }

  if (params.tools && params.tools.length > 0) {
    body.tools = params.tools.map((tool) => ({
      name: tool.function.name,
      description: tool.function.description,
      input_schema: tool.function.parameters,
    }));
    body.tool_choice = { type: "auto" };
  }

  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": params.anthropicApiKey,
      "anthropic-version": "2023-06-01",
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
    throw new Error("No completion content returned from anthropic inference");
  }

  const promptTokens = data.usage?.input_tokens || 0;
  const completionTokens = data.usage?.output_tokens || 0;
  const usage: TokenUsage = {
    promptTokens,
    completionTokens,
    totalTokens: promptTokens + completionTokens,
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
