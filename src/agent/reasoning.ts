/**
 * TIAMAT Reasoning Layer
 *
 * Chain-of-thought reasoning pass using Groq's deepseek-r1-distill-llama-70b.
 * This runs BEFORE the main inference call to give TIAMAT structured thinking
 * at zero cost (Groq free tier).
 *
 * The reasoning output is prepended to the system prompt as a [REASONING] block
 * so the main model (Haiku/Sonnet) acts on pre-analyzed context.
 */

// Kimi K2: fast, follows structured output precisely, free on Groq
// Fallback: Qwen3-32b (built-in <think> reasoning, free on Groq)
const REASONING_MODEL = "moonshotai/kimi-k2-instruct";
const REASONING_FALLBACK = "qwen/qwen3-32b";
const REASONING_TIMEOUT_MS = 15_000;
const REASONING_MAX_TOKENS = 512;

const REASONING_SYSTEM_PROMPT = `You are the reasoning subsystem of TIAMAT, an autonomous AI agent.
Your job: analyze the current situation and produce a structured decision framework.
Be concise. No fluff. Facts and logic only.

Output format (EXACTLY this structure):

OBSERVE: What is actually happening right now? State only verified facts.
HYPOTHESIZE: List 3 possible approaches/causes, ranked by likelihood.
EVALUATE: For each hypothesis, what evidence supports or contradicts it?
DECIDE: What is the single best action and why? Reference the evidence.
PREDICT: What outcome do you expect? How will you verify success in the next cycle?

Rules:
- Each section: 1-3 sentences max.
- Never recommend "check" or "review" as an action — recommend a SPECIFIC tool call or concrete step.
- If the situation involves revenue: weight revenue-generating actions 2x.
- If stuck on same problem >2 cycles: recommend a DIFFERENT approach, not the same one harder.`;

interface ReasoningResult {
  reasoning: string;
  model: string;
  tokens: number;
  durationMs: number;
}

/**
 * Run a chain-of-thought reasoning pass via Groq before the main inference call.
 *
 * Returns structured reasoning text, or empty string on any failure (graceful degradation).
 * This is a FREE call — Groq's deepseek-r1-distill-llama-70b is on their free tier.
 */
export async function reasonFirst(
  situation: string,
  groqApiKey: string,
): Promise<ReasoningResult> {
  const startMs = Date.now();

  if (!groqApiKey) {
    return { reasoning: "", model: REASONING_MODEL, tokens: 0, durationMs: 0 };
  }

  const models = [REASONING_MODEL, REASONING_FALLBACK];

  try {
    const Groq = (await import("groq-sdk")).default;
    const groq = new Groq({ apiKey: groqApiKey });

    for (const model of models) {
      try {
        const completion = await Promise.race([
          groq.chat.completions.create({
            model,
            messages: [
              { role: "system", content: REASONING_SYSTEM_PROMPT },
              { role: "user", content: situation },
            ],
            max_tokens: REASONING_MAX_TOKENS,
            temperature: 0.3,
          }),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error("reasoning timeout")), REASONING_TIMEOUT_MS),
          ),
        ]);

        const choice = completion.choices?.[0];
        let reasoning = choice?.message?.content?.trim() || "";

        // Qwen3 wraps reasoning in <think> tags — strip them and use the final output
        if (reasoning.includes("<think>")) {
          const afterThink = reasoning.split("</think>").pop()?.trim();
          if (afterThink) reasoning = afterThink;
        }

        if (!reasoning) {
          console.log(`[REASONING] ${model}: empty response, trying fallback`);
          continue;
        }

        const tokens = completion.usage?.total_tokens || 0;
        const durationMs = Date.now() - startMs;

        console.log(
          `[REASONING] ${model}: ${tokens} tokens, ${durationMs}ms ` +
          `(${reasoning.length} chars)`,
        );

        return { reasoning, model, tokens, durationMs };
      } catch (modelErr: any) {
        console.log(`[REASONING] ${model} failed: ${modelErr.message?.slice(0, 100)}, trying next`);
        continue;
      }
    }

    // All models failed
    return { reasoning: "", model: REASONING_MODEL, tokens: 0, durationMs: Date.now() - startMs };
  } catch (err: any) {
    const durationMs = Date.now() - startMs;
    console.log(`[REASONING] Failed (${durationMs}ms): ${err.message?.slice(0, 150)}`);
    return { reasoning: "", model: REASONING_MODEL, tokens: 0, durationMs };
  }
}

/**
 * Build a situation summary for the reasoning pass from current cycle state.
 */
export function buildReasoningSituation(params: {
  turnCount: number;
  burstPhase: number;
  currentTicket?: { id: string; title: string; description?: string; priority: string; ageHours: number };
  recentToolCalls?: string[];
  recentErrors?: string[];
  revenue: string;
  memoryContext?: string;
}): string {
  const parts: string[] = [];

  parts.push(`Cycle: ${params.turnCount}`);

  if (params.burstPhase > 0) {
    const phaseNames: Record<number, string> = { 1: "REFLECT", 2: "BUILD", 3: "MARKET" };
    parts.push(`Strategic burst phase: ${params.burstPhase}/3 (${phaseNames[params.burstPhase] || "unknown"})`);
  }

  if (params.currentTicket) {
    const t = params.currentTicket;
    parts.push(
      `Current ticket: ${t.id} [${t.priority}] "${t.title}" (${t.ageHours.toFixed(1)}h old)` +
      (t.description ? `\nDescription: ${t.description.slice(0, 300)}` : ""),
    );
  } else {
    parts.push("No active ticket — self-directed cycle.");
  }

  parts.push(`Revenue status: ${params.revenue}`);

  if (params.recentToolCalls?.length) {
    parts.push(`Recent tools used: ${params.recentToolCalls.join(", ")}`);
  }

  if (params.recentErrors?.length) {
    parts.push(`Recent errors: ${params.recentErrors.join("; ")}`);
  }

  if (params.memoryContext) {
    parts.push(`Past experience:\n${params.memoryContext}`);
  }

  return parts.join("\n");
}

/**
 * Format reasoning output for injection into the system prompt.
 */
export function formatReasoningBlock(result: ReasoningResult): string {
  if (!result.reasoning) return "";
  return (
    `\n\n[REASONING — pre-analyzed by ${result.model} in ${result.durationMs}ms]\n` +
    result.reasoning +
    `\n[/REASONING]\n\nACT on the reasoning above. Do not re-analyze — execute the DECIDE step.`
  );
}
