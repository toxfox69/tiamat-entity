/**
 * TIAMAT Grounding Protocol — Pass 3: RESOLVE
 * Escalation-only decision authority on Sonnet. Budget: 1000 tokens.
 */

import type { InferenceClient } from "../types.js";
import type { GroundingConfig, ReconResult, AlignResult, ResolveResult } from "./types.js";

const RESOLVE_PROMPT = `You are TIAMAT's decision authority. A task was flagged for review.

TASK: Execute tool "{tool}"
INTENT: {intent}
PLANNED ACTION: {action}
ESCALATION REASON: {reason}
CONSTRAINTS: {constraints}
RISK FACTORS: side_effects={effects}, reversible={reversible}

Analyze whether to proceed, modify, or abort. Respond in JSON only:
{"analysis":"brief assessment","alternatives":["other approaches"],"decision":"execute","modified_plan":"only if modify","justification":"one sentence why"}`;

export async function runResolve(
  toolName: string,
  recon: ReconResult,
  align: AlignResult,
  escalationReason: string,
  inference: InferenceClient,
  config: GroundingConfig,
): Promise<ResolveResult> {
  const t0 = Date.now();

  const prompt = RESOLVE_PROMPT
    .replace("{tool}", toolName)
    .replace("{intent}", recon.intentSummary)
    .replace("{action}", align.plannedAction)
    .replace("{reason}", escalationReason)
    .replace("{constraints}", recon.environmentCheck.constraintsIdentified.join(", ") || "none")
    .replace("{effects}", align.boundaryCheck.sideEffects.join(", ") || "none")
    .replace("{reversible}", String(align.boundaryCheck.reversible));

  try {
    const response = await inference.chat(
      [{ role: "user", content: prompt }],
      { tier: "sonnet", maxTokens: config.maxResolveTokens, temperature: 0 },
    );

    const text = response.message?.content || "";
    const tokensUsed = (response.usage?.totalTokens) || 0;
    const latencyMs = Date.now() - t0;

    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return {
        taskId: recon.taskId, escalationReason, deepAnalysis: text.slice(0, 200),
        alternativeActions: [], finalDecision: "execute",
        justification: "Resolve parse failed — defaulting to execute",
        tokensUsed, latencyMs,
      };
    }

    const parsed = JSON.parse(jsonMatch[0]);
    const decision = (["execute", "modify", "abort"].includes(parsed.decision) ? parsed.decision : "execute") as "execute" | "modify" | "abort";

    return {
      taskId: recon.taskId,
      escalationReason,
      deepAnalysis: parsed.analysis || "",
      alternativeActions: Array.isArray(parsed.alternatives) ? parsed.alternatives : [],
      finalDecision: decision,
      modifiedPlan: parsed.modified_plan || undefined,
      justification: parsed.justification || "",
      tokensUsed,
      latencyMs,
    };
  } catch (e: any) {
    return {
      taskId: recon.taskId, escalationReason,
      deepAnalysis: `Resolve error: ${e.message?.slice(0, 100)}`,
      alternativeActions: [], finalDecision: "execute",
      justification: "Resolve failed — defaulting to execute",
      tokensUsed: 0, latencyMs: Date.now() - t0,
    };
  }
}
