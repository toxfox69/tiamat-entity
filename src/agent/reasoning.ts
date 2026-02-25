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
 * PREDICTION TRACKING (phase-aware):
 * Each reasoning pass produces a PREDICT statement scoped to its burst phase:
 *   REFLECT → strategic predictions (20-100 cycle horizon)
 *   BUILD   → technical predictions (1-10 cycle horizon)
 *   MARKET  → metric-driven predictions (5-50 cycle horizon)
 *   ROUTINE → general predictions (non-burst cycles)
 *
 * Each prediction stores a verification_method — the specific check that confirms
 * or denies the prediction. This turns scoring from a judgment call into an
 * automated check TIAMAT can run herself.
 */

import Database from "better-sqlite3";
import fs from "fs";
import path from "path";

// Kimi K2: fast, follows structured output precisely, free on Groq
// Fallback: Qwen3-32b (built-in <think> reasoning, free on Groq)
const REASONING_MODEL = "moonshotai/kimi-k2-instruct";
const REASONING_FALLBACK = "qwen/qwen3-32b";
const REASONING_TIMEOUT_MS = 15_000;
const REASONING_MAX_TOKENS = 512;

export type BurstPhase = "REFLECT" | "BUILD" | "MARKET" | "ROUTINE";

const REASONING_BASE_PROMPT = `You are the reasoning subsystem of TIAMAT, an autonomous AI agent.
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

/**
 * Phase-specific PREDICT instructions appended to the base prompt.
 * Each phase scopes predictions to its job and requires a verification method.
 */
const PHASE_PROMPTS: Record<BurstPhase, string> = {
  REFLECT: `

CRITICAL — Your PREDICT statement for this REFLECT phase must be:
- Strategic in scope (will this direction work?)
- Measurable within 20-100 cycles
- Falsifiable: state exactly what evidence confirms or denies it
Format: "PREDICT: If [action], then [outcome] by cycle [N]. Confirmed by: [specific check]"
Example: "PREDICT: If we pursue agent registry, we will generate 1+ inbound query within 50 cycles. Confirmed by: search_email for registry-related messages"`,

  BUILD: `

CRITICAL — Your PREDICT statement for this BUILD phase must be:
- Technical in scope (will this code/command work?)
- Measurable within 1-10 cycles
- Falsifiable: state the exact command/check that verifies it
Format: "PREDICT: [command] will produce [exact output] within [timeframe]. Verified by: [exec command]"
Example: "PREDICT: arctl register will return 201 and populate directory within 10 minutes. Verified by: curl -s https://registry.example/agents | grep tiamat"`,

  MARKET: `

CRITICAL — Your PREDICT statement for this MARKET phase must be:
- Metric-driven (a number or state that can be checked)
- Measurable within 5-50 cycles
- Falsifiable: state the exact metric and threshold
Format: "PREDICT: By cycle [N], [metric] will be [value]. Checked by: [specific observation]"
Example: "PREDICT: By cycle 4300, Bluesky post impressions will exceed 50. Checked by: read_bluesky_notifications and count engagement"`,

  ROUTINE: "",
};

interface ReasoningResult {
  reasoning: string;
  model: string;
  tokens: number;
  durationMs: number;
}

/**
 * Run a chain-of-thought reasoning pass via Groq before the main inference call.
 *
 * @param situation — current cycle context
 * @param groqApiKey — Groq API key
 * @param phase — burst phase (REFLECT/BUILD/MARKET/ROUTINE) for scoped predictions
 * @returns structured reasoning text, or empty string on any failure (graceful degradation)
 */
export async function reasonFirst(
  situation: string,
  groqApiKey: string,
  phase: BurstPhase = "ROUTINE",
): Promise<ReasoningResult> {
  const startMs = Date.now();

  if (!groqApiKey) {
    return { reasoning: "", model: REASONING_MODEL, tokens: 0, durationMs: 0 };
  }

  const systemPrompt = REASONING_BASE_PROMPT + PHASE_PROMPTS[phase];
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
              { role: "system", content: systemPrompt },
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
          `[REASONING] ${model} [${phase}]: ${tokens} tokens, ${durationMs}ms ` +
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

// ─── Prediction Tracking (Phase-Aware) ──────────────────────────────

const DB_PATH = path.join(process.env.HOME || "/root", ".automaton", "memory.db");
const ACCURACY_LOG = path.join(process.env.HOME || "/root", ".automaton", "reasoning_accuracy.log");

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
        phase       TEXT DEFAULT 'UNKNOWN',
        verification_method TEXT,
        scored      INTEGER DEFAULT 0,
        score       REAL,
        actual_outcome TEXT,
        scored_at   TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
      );
    `);
    // Add columns to existing tables (safe — "already exists" is caught)
    try { _predDb.exec(`ALTER TABLE tiamat_predictions ADD COLUMN phase TEXT DEFAULT 'UNKNOWN'`); } catch {}
    try { _predDb.exec(`ALTER TABLE tiamat_predictions ADD COLUMN verification_method TEXT`); } catch {}
    return _predDb;
  } catch (err: any) {
    console.log(`[REASONING] Prediction DB init failed: ${err.message?.slice(0, 100)}`);
    return null;
  }
}

/**
 * Extract PREDICT, DECIDE, and verification method from reasoning output.
 *
 * Verification method is the text after "Confirmed by:", "Verified by:", or "Checked by:"
 * in the PREDICT section.
 */
function extractPrediction(reasoning: string): {
  predict: string;
  decide: string;
  verificationMethod: string;
} {
  const predictMatch = reasoning.match(/PREDICT:\s*(.+?)(?=\n(?:OBSERVE|HYPOTHESIZE|EVALUATE|DECIDE):|$)/s);
  const decideMatch = reasoning.match(/DECIDE:\s*(.+?)(?=\n(?:OBSERVE|HYPOTHESIZE|EVALUATE|PREDICT):|$)/s);
  const predict = predictMatch?.[1]?.trim() || "";

  // Extract verification method from the prediction text
  const verifyMatch = predict.match(/(?:Confirmed|Verified|Checked)\s+by:\s*(.+?)$/is);
  const verificationMethod = verifyMatch?.[1]?.trim() || "";

  return {
    predict,
    decide: decideMatch?.[1]?.trim() || "",
    verificationMethod,
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
  phase?: BurstPhase;
}): void {
  const db = getPredDb();
  if (!db) return;

  const { predict, decide, verificationMethod } = extractPrediction(params.reasoning);
  if (!predict) return;

  const phase = params.phase || "UNKNOWN";

  try {
    db.prepare(
      `INSERT INTO tiamat_predictions (cycle, prediction, decide_action, ticket_id, model, phase, verification_method)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      params.cycle,
      predict,
      decide || null,
      params.ticketId || null,
      params.model,
      phase,
      verificationMethod || null,
    );

    console.log(
      `[REASONING] Prediction stored [${phase}] (cycle ${params.cycle}): ${predict.slice(0, 80)}` +
      (verificationMethod ? ` | verify: ${verificationMethod.slice(0, 60)}` : ""),
    );
  } catch (err: any) {
    console.log(`[REASONING] Failed to store prediction: ${err.message?.slice(0, 100)}`);
  }
}

/**
 * Phase-specific scoring instructions for the scoring LLM.
 */
const PHASE_SCORING_PROMPTS: Record<string, string> = {
  REFLECT: "This is a STRATEGIC prediction. Score based on whether the strategic direction proved correct. 0.0 = direction was wrong, 0.5 = partially right but missed key aspects, 1.0 = strategy direction was exactly right.",
  BUILD: "This is a TECHNICAL prediction. Score based on whether the implementation behaved as predicted. 0.0 = code/command failed or produced wrong output, 0.5 = partially worked with issues, 1.0 = exact behavior as predicted.",
  MARKET: "This is a METRIC prediction. Score based on whether the external metric hit the target. 0.0 = metric nowhere close, 0.5 = metric moved in right direction but missed target, 1.0 = metric hit or exceeded target.",
};

/**
 * Score unscored predictions by comparing against actual outcomes.
 * Called during strategic burst REFLECT phase.
 * Scores each phase separately and logs per-phase accuracy.
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
    `SELECT id, cycle, prediction, decide_action, ticket_id, phase, verification_method
     FROM tiamat_predictions
     WHERE scored = 0 AND cycle <= ?
     ORDER BY cycle ASC LIMIT 10`,
  ).all(currentCycle - 5) as Array<{
    id: number; cycle: number; prediction: string;
    decide_action: string | null; ticket_id: string | null;
    phase: string | null; verification_method: string | null;
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
  const phaseScores: Record<string, number[]> = {};

  try {
    const Groq = (await import("groq-sdk")).default;
    const groq = new Groq({ apiKey: groqApiKey });

    for (const pred of unscored) {
      try {
        const phase = pred.phase || "UNKNOWN";
        const phaseScoringHint = PHASE_SCORING_PROMPTS[phase] || "";
        const verifyHint = pred.verification_method
          ? `\nVERIFICATION METHOD: ${pred.verification_method}`
          : "";

        const completion = await Promise.race([
          groq.chat.completions.create({
            model: REASONING_MODEL,
            messages: [
              {
                role: "system",
                content: `Score this prediction's accuracy. Output ONLY a JSON object: {"score": 0.0-1.0, "reason": "one sentence"}
${phaseScoringHint}
0.0 = completely wrong, 0.5 = partially correct, 1.0 = exactly right.`,
              },
              {
                role: "user",
                content: `PREDICTION [${phase}] (cycle ${pred.cycle}): ${pred.prediction}\nACTION TAKEN: ${pred.decide_action || "unknown"}${verifyHint}\n\nACTUAL OUTCOMES (cycles ${pred.cycle}-${currentCycle}):\n${outcomeText}`,
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

          // Track per-phase scores
          if (!phaseScores[phase]) phaseScores[phase] = [];
          phaseScores[phase].push(score);

          scored.push(`[${phase}] Cycle ${pred.cycle}: "${pred.prediction.slice(0, 50)}..." → ${score.toFixed(1)} (${reason})`);
          console.log(`[REASONING] Prediction ${pred.id} [${phase}] scored: ${score.toFixed(1)} — ${reason}`);
        }
      } catch (e: any) {
        console.log(`[REASONING] Scoring prediction ${pred.id} failed: ${e.message?.slice(0, 80)}`);
      }
    }
  } catch (err: any) {
    console.log(`[REASONING] Prediction scoring failed: ${err.message?.slice(0, 100)}`);
  }

  // Log per-phase accuracy to file
  if (Object.keys(phaseScores).length > 0) {
    try {
      const phaseAvgs: string[] = [];
      for (const [phase, scores] of Object.entries(phaseScores)) {
        const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
        phaseAvgs.push(`${phase}: ${avg.toFixed(2)}`);
      }
      const logLine = `Cycle ${currentCycle} | ${phaseAvgs.join(" | ")}\n`;
      fs.appendFileSync(ACCURACY_LOG, logLine);
      console.log(`[REASONING] Per-phase accuracy logged: ${logLine.trim()}`);
    } catch {}
  }

  if (scored.length === 0) return "";
  return `[PREDICTION SCORES — ${scored.length} evaluated]\n${scored.join("\n")}`;
}

/**
 * Get prediction accuracy stats for injection into reasoning context.
 * Returns per-phase accuracy so the reasoning layer can calibrate each phase separately.
 * Injects warnings when a phase scores below 0.4 for 3 consecutive bursts.
 */
export function getPredictionAccuracy(): string {
  const db = getPredDb();
  if (!db) return "";

  try {
    // Overall stats
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

    // Per-phase accuracy over last 10 bursts (~30 scored predictions)
    const phases: BurstPhase[] = ["REFLECT", "BUILD", "MARKET"];
    const phaseLines: string[] = [];
    const warnings: string[] = [];

    for (const phase of phases) {
      const phaseStats = db.prepare(
        `SELECT AVG(score) as avg, COUNT(*) as cnt
         FROM tiamat_predictions
         WHERE scored = 1 AND phase = ?
         ORDER BY scored_at DESC LIMIT 30`,
      ).get(phase) as { avg: number | null; cnt: number } | undefined;

      if (phaseStats && phaseStats.cnt > 0) {
        const pct = ((phaseStats.avg || 0) * 100).toFixed(0);
        phaseLines.push(`${phase}: ${pct}% accurate (${phaseStats.cnt} scored)`);

        // Check for consecutive poor performance (last 3 predictions in this phase)
        const recent3 = db.prepare(
          `SELECT score FROM tiamat_predictions
           WHERE scored = 1 AND phase = ?
           ORDER BY scored_at DESC LIMIT 3`,
        ).all(phase) as Array<{ score: number }>;

        if (recent3.length >= 3 && recent3.every(r => r.score < 0.4)) {
          warnings.push(
            `WARNING: Your ${phase} predictions have been consistently wrong (last 3: ${recent3.map(r => r.score.toFixed(1)).join(", ")}). ` +
            `Be more conservative and specific in this phase.`,
          );
        }
      }
    }

    let summary = `Prediction accuracy (7d): ${stats.total} scored, avg ${((stats.avg_score || 0) * 100).toFixed(0)}%`;

    if (phaseLines.length > 0) {
      summary += "\nPer-phase: " + phaseLines.join(" | ");
    }

    if (warnings.length > 0) {
      summary += "\n" + warnings.join("\n");
    }

    // Recent predictions with phase info
    const recent = db.prepare(
      `SELECT cycle, prediction, score, actual_outcome, phase
       FROM tiamat_predictions
       WHERE scored = 1
       ORDER BY scored_at DESC LIMIT 3`,
    ).all() as Array<{ cycle: number; prediction: string; score: number; actual_outcome: string; phase: string }>;

    if (recent.length > 0) {
      summary += "\nRecent: " + recent.map(r =>
        `[${r.phase || "?"}] cycle ${r.cycle}: ${r.score.toFixed(1)} — ${r.actual_outcome?.slice(0, 50) || "no detail"}`,
      ).join("; ");
    }

    return summary;
  } catch {
    return "";
  }
}
