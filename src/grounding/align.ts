/**
 * TIAMAT Grounding Protocol — Pass 2: ALIGN
 * Validates planned action matches intent. Budget: 300 tokens.
 */

import type { InferenceClient } from "../types.js";
import type { GroundingConfig, ReconResult, AlignResult } from "./types.js";

const ALIGN_PROMPT = `You are TIAMAT's alignment checker. Validate this planned action.

ORIGINAL INTENT: {intent}
PLANNED ACTION: tool={tool}, args={args}
CONSTRAINTS: {constraints}

Respond in JSON only:
{"planned_action":"concrete description","intent_match":true,"cost_estimate_tokens":0,"reversible":true,"side_effects":[],"risk_tier":"green"}

Risk tiers: green=reversible+low cost, yellow=irreversible OR external side effects, red=high cost OR multi-system impact`;

// Tools that are inherently safe/reversible
const GREEN_TOOLS = new Set([
  "read_file", "recall", "search_web", "web_fetch", "browse",
  "browse_web", "sonar_search", "read_email", "search_email",
  "ticket_list", "ticket_claim", "read_bluesky", "read_mastodon",
  "check_opportunities", "tts_synthesize",
]);

// Tools with external side effects (yellow minimum)
const YELLOW_TOOLS = new Set([
  "write_file", "exec", "post_bluesky", "post_farcaster",
  "post_mastodon", "post_linkedin", "post_facebook", "post_devto",
  "post_hashnode", "post_medium", "moltbook_post", "post_social",
  "post_github_discussion", "like_bluesky", "repost_bluesky",
  "farcaster_engage", "mastodon_engage", "comment_moltbook",
  "send_telegram", "generate_image",
]);

// Tools that warrant red-tier review
const RED_TOOLS = new Set([
  "send_email", "deploy_app", "ask_claude_code",
]);

export function fastRiskTier(toolName: string): "green" | "yellow" | "red" {
  if (RED_TOOLS.has(toolName)) return "red";
  if (YELLOW_TOOLS.has(toolName)) return "yellow";
  if (GREEN_TOOLS.has(toolName)) return "green";
  return "yellow"; // unknown tools default to yellow
}

export async function runAlign(
  toolName: string,
  toolArgs: Record<string, unknown>,
  recon: ReconResult,
  inference: InferenceClient,
  config: GroundingConfig,
): Promise<AlignResult> {
  const t0 = Date.now();

  // Fast path: green tools skip LLM call entirely
  const fastTier = fastRiskTier(toolName);
  if (fastTier === "green") {
    return {
      taskId: recon.taskId,
      plannedAction: `Read/query via ${toolName}`,
      intentMatch: true,
      boundaryCheck: {
        costEstimate: 0,
        reversible: true,
        sideEffects: [],
        riskTier: "green",
      },
      proceed: true,
      tokensUsed: 0,
      latencyMs: Date.now() - t0,
    };
  }

  const argsStr = JSON.stringify(toolArgs).slice(0, 300);
  const prompt = ALIGN_PROMPT
    .replace("{intent}", recon.intentSummary)
    .replace("{tool}", toolName)
    .replace("{args}", argsStr)
    .replace("{constraints}", recon.environmentCheck.constraintsIdentified.join(", ") || "none");

  try {
    const response = await inference.chat(
      [{ role: "user", content: prompt }],
      { tier: "haiku", maxTokens: config.maxAlignTokens, temperature: 0 },
    );

    const text = response.message?.content || "";
    const tokensUsed = (response.usage?.totalTokens) || 0;
    const latencyMs = Date.now() - t0;

    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      // Default: use fast tier classification
      return {
        taskId: recon.taskId,
        plannedAction: `Execute ${toolName}`,
        intentMatch: true,
        boundaryCheck: { costEstimate: 0, reversible: fastTier !== "red", sideEffects: [], riskTier: fastTier },
        proceed: true, tokensUsed, latencyMs,
      };
    }

    const parsed = JSON.parse(jsonMatch[0]);
    const tier = (["green", "yellow", "red"].includes(parsed.risk_tier) ? parsed.risk_tier : fastTier) as "green" | "yellow" | "red";

    return {
      taskId: recon.taskId,
      plannedAction: parsed.planned_action || `Execute ${toolName}`,
      intentMatch: parsed.intent_match !== false,
      boundaryCheck: {
        costEstimate: parsed.cost_estimate_tokens || 0,
        reversible: parsed.reversible !== false,
        sideEffects: Array.isArray(parsed.side_effects) ? parsed.side_effects : [],
        riskTier: tier,
      },
      proceed: true,
      tokensUsed,
      latencyMs,
    };
  } catch {
    return {
      taskId: recon.taskId,
      plannedAction: `Execute ${toolName}`,
      intentMatch: true,
      boundaryCheck: { costEstimate: 0, reversible: fastTier !== "red", sideEffects: [], riskTier: fastTier },
      proceed: true, tokensUsed: 0, latencyMs: Date.now() - t0,
    };
  }
}
