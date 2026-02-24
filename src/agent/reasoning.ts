/**
 * TIAMAT Reasoning Layer
 *
 * Chain-of-thought reasoning pass using free models on Groq (Kimi K2 / Qwen3).
 * This runs BEFORE the main inference call to give TIAMAT structured thinking
 * at zero cost (Groq free tier).
 *
 * The reasoning output is prepended to the system prompt as a [REASONING] block
 * so the main model (Haiku/Sonnet) acts on pre-analyzed context.
 *
 * PREDICTION TRACKING:
 * Each reasoning pass produces a PREDICT statement. This is stored in mind.sqlite
 * with a timestamp. At the next strategic burst, predictions are scored 0-1 by
 * checking actual outcomes, closing the learning loop.
 */

import Database from "better-sqlite3";
import path from "path";

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

// ─── Prediction Tracking ─────────────────────────────────────────

const DB_PATH = path.join(process.env.HOME || "/root", ".automaton", "memory.db");

let _predDb: Database.Database | null = null;

function getPredDb(): Database.Database | null {
  if (_predDb) return _predDb;
  try {
    _predDb = new Database(DB_PATH);
    _predDb.exec(`
      CREATE TABLE IF NOT EXISTS tiamat_predictions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle       INTEGER NOT NULL,
        prediction  TEXT NOT NULL,
        decide_action TEXT,
        ticket_id   TEXT,
        model       TEXT,
        scored      INTEGER DEFAULT 0,
        score       REAL,
        actual_outcome TEXT,
        scored_at   TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
      );
    `);
    return _predDb;
  } catch (err: any) {
    console.log(`[REASONING] Prediction DB init failed: ${err.message?.slice(0, 100)}`);
    return null;
  }
}

/**
 * Extract the PREDICT and DECIDE sections from reasoning output.
 */
function extractPrediction(reasoning: string): { predict: string; decide: string } {
  const predictMatch = reasoning.match(/PREDICT:\s*(.+?)(?=\n(?:OBSERVE|HYPOTHESIZE|EVALUATE|DECIDE):|$)/s);
  const decideMatch = reasoning.match(/DECIDE:\s*(.+?)(?=\n(?:OBSERVE|HYPOTHESIZE|EVALUATE|PREDICT):|$)/s);
  return {
    predict: predictMatch?.[1]?.trim() || "",
    decide: decideMatch?.[1]?.trim() || "",
  };
}

/**
 * Store a prediction from this cycle's reasoning pass.
 * Called after reasonFirst() produces a result.
 */
export function storePrediction(params: {
  cycle: number;
  reasoning: string;
  model: string;
  ticketId?: string;
}): void {
  const db = getPredDb();
  if (!db) return;

  const { predict, decide } = extractPrediction(params.reasoning);
  if (!predict) return;

  try {
    db.prepare(
      `INSERT INTO tiamat_predictions (cycle, prediction, decide_action, ticket_id, model)
       VALUES (?, ?, ?, ?, ?)`,
    ).run(params.cycle, predict, decide || null, params.ticketId || null, params.model);

    console.log(`[REASONING] Prediction stored (cycle ${params.cycle}): ${predict.slice(0, 100)}`);
  } catch (err: any) {
    console.log(`[REASONING] Failed to store prediction: ${err.message?.slice(0, 100)}`);
  }
}

/**
 * Score unscored predictions by comparing against actual outcomes.
 * Called during strategic burst REFLECT phase.
 *
 * @param groqApiKey — used to call Groq for scoring (free)
 * @param currentCycle — current cycle number
 * @returns summary of scored predictions
 */
export async function scorePredictions(
  groqApiKey: string,
  currentCycle: number,
): Promise<string> {
  const db = getPredDb();
  if (!db || !groqApiKey) return "";

  // Get unscored predictions that are at least 5 cycles old (enough time for outcome)
  const unscored = db.prepare(
    `SELECT id, cycle, prediction, decide_action, ticket_id
     FROM tiamat_predictions
     WHERE scored = 0 AND cycle <= ?
     ORDER BY cycle ASC LIMIT 5`,
  ).all(currentCycle - 5) as Array<{
    id: number; cycle: number; prediction: string;
    decide_action: string | null; ticket_id: string | null;
  }>;

  if (unscored.length === 0) return "";

  // Gather actual outcomes from memory and strategy tables
  const outcomes: string[] = [];
  try {
    const recentMems = db.prepare(
      `SELECT type, content FROM tiamat_memories
       WHERE cycle >= ? AND cycle <= ?
       ORDER BY cycle ASC LIMIT 20`,
    ).all(unscored[0].cycle, currentCycle) as Array<{ type: string; content: string }>;

    for (const m of recentMems) {
      outcomes.push(`[${m.type}] ${m.content.slice(0, 150)}`);
    }
  } catch {}

  if (outcomes.length === 0) return "";

  const outcomeText = outcomes.join("\n");

  // Score each prediction via Groq (free)
  const scored: string[] = [];

  try {
    const Groq = (await import("groq-sdk")).default;
    const groq = new Groq({ apiKey: groqApiKey });

    for (const pred of unscored) {
      try {
        const completion = await Promise.race([
          groq.chat.completions.create({
            model: REASONING_MODEL,
            messages: [
              {
                role: "system",
                content: `Score this prediction's accuracy. Output ONLY a JSON object: {"score": 0.0-1.0, "reason": "one sentence"}
0.0 = completely wrong, 0.5 = partially correct, 1.0 = exactly right.`,
              },
              {
                role: "user",
                content: `PREDICTION (cycle ${pred.cycle}): ${pred.prediction}\nACTION TAKEN: ${pred.decide_action || "unknown"}\n\nACTUAL OUTCOMES (cycles ${pred.cycle}-${currentCycle}):\n${outcomeText}`,
              },
            ],
            max_tokens: 100,
            temperature: 0.1,
          }),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error("scoring timeout")), 10_000),
          ),
        ]);

        const raw = completion.choices?.[0]?.message?.content?.trim() || "";
        // Extract JSON from response (may have markdown wrapping)
        const jsonMatch = raw.match(/\{[^}]+\}/);
        if (jsonMatch) {
          const parsed = JSON.parse(jsonMatch[0]);
          const score = Math.max(0, Math.min(1, Number(parsed.score) || 0));
          const reason = String(parsed.reason || "").slice(0, 200);

          db.prepare(
            `UPDATE tiamat_predictions
             SET scored = 1, score = ?, actual_outcome = ?, scored_at = datetime('now')
             WHERE id = ?`,
          ).run(score, reason, pred.id);

          scored.push(`Cycle ${pred.cycle}: "${pred.prediction.slice(0, 60)}..." → ${score.toFixed(1)} (${reason})`);
          console.log(`[REASONING] Prediction ${pred.id} scored: ${score.toFixed(1)} — ${reason}`);
        }
      } catch (e: any) {
        console.log(`[REASONING] Scoring prediction ${pred.id} failed: ${e.message?.slice(0, 80)}`);
      }
    }
  } catch (err: any) {
    console.log(`[REASONING] Prediction scoring failed: ${err.message?.slice(0, 100)}`);
  }

  if (scored.length === 0) return "";
  return `[PREDICTION SCORES — ${scored.length} evaluated]\n${scored.join("\n")}`;
}

/**
 * Get prediction accuracy stats for injection into reasoning context.
 * Returns recent prediction scores so the reasoning layer can calibrate.
 */
export function getPredictionAccuracy(): string {
  const db = getPredDb();
  if (!db) return "";

  try {
    const stats = db.prepare(
      `SELECT
         COUNT(*) as total,
         AVG(score) as avg_score,
         SUM(CASE WHEN score >= 0.7 THEN 1 ELSE 0 END) as accurate,
         SUM(CASE WHEN score < 0.3 THEN 1 ELSE 0 END) as wrong
       FROM tiamat_predictions
       WHERE scored = 1 AND scored_at > datetime('now', '-7 days')`,
    ).get() as { total: number; avg_score: number | null; accurate: number; wrong: number };

    if (!stats || stats.total === 0) return "";

    const recent = db.prepare(
      `SELECT cycle, prediction, score, actual_outcome
       FROM tiamat_predictions
       WHERE scored = 1
       ORDER BY scored_at DESC LIMIT 3`,
    ).all() as Array<{ cycle: number; prediction: string; score: number; actual_outcome: string }>;

    let summary = `Prediction accuracy (7d): ${stats.total} scored, avg ${(stats.avg_score || 0).toFixed(2)}, ${stats.accurate} accurate, ${stats.wrong} wrong`;

    if (recent.length > 0) {
      summary += "\nRecent: " + recent.map(r =>
        `cycle ${r.cycle}: ${r.score.toFixed(1)} — ${r.actual_outcome?.slice(0, 60) || "no detail"}`,
      ).join("; ");
    }

    return summary;
  } catch {
    return "";
  }
}
