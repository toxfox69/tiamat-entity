/**
 * TIAMAT Grounding Protocol — Pass 1: RECON
 * Lightweight intent assessment on Haiku. Budget: 500 tokens.
 */

import type { InferenceClient } from "../types.js";
import type { GroundingConfig, ReconResult } from "./types.js";
import { randomUUID } from "crypto";

const RECON_PROMPT = `You are TIAMAT's grounding module. Assess this task before execution.

TASK: {task}
TOOL: {tool}
ARGS: {args}

Respond in JSON only:
{"intent_summary":"one sentence — what is this task trying to accomplish","resources_available":true,"constraints":["list any blockers or limits"],"confidence":0.0-1.0,"proceed":true}`;

export async function runRecon(
  toolName: string,
  toolArgs: Record<string, unknown>,
  inference: InferenceClient,
  config: GroundingConfig,
): Promise<ReconResult> {
  const taskId = `tgp-${Date.now()}-${randomUUID().slice(0, 8)}`;
  const t0 = Date.now();

  const argsStr = JSON.stringify(toolArgs).slice(0, 500);
  const prompt = RECON_PROMPT
    .replace("{task}", `Execute tool "${toolName}" with given arguments`)
    .replace("{tool}", toolName)
    .replace("{args}", argsStr);

  try {
    const response = await inference.chat(
      [{ role: "user", content: prompt }],
      { tier: "haiku", maxTokens: config.maxReconTokens, temperature: 0 },
    );

    const text = response.message?.content || "";
    const tokensUsed = (response.usage?.totalTokens) || 0;
    const latencyMs = Date.now() - t0;

    // Parse JSON from response
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      // If model doesn't return JSON, default to proceed with medium confidence
      return {
        taskId, timestamp: new Date().toISOString(),
        intentSummary: `Execute ${toolName}`,
        environmentCheck: { resourcesAvailable: true, constraintsIdentified: [], stateSnapshot: {} },
        confidence: 0.8, proceed: true, tokensUsed, latencyMs,
      };
    }

    const parsed = JSON.parse(jsonMatch[0]);
    return {
      taskId,
      timestamp: new Date().toISOString(),
      intentSummary: parsed.intent_summary || `Execute ${toolName}`,
      environmentCheck: {
        resourcesAvailable: parsed.resources_available !== false,
        constraintsIdentified: Array.isArray(parsed.constraints) ? parsed.constraints : [],
        stateSnapshot: {},
      },
      confidence: Math.max(0, Math.min(1, parseFloat(parsed.confidence) || 0.8)),
      proceed: parsed.proceed !== false,
      tokensUsed,
      latencyMs,
    };
  } catch (e: any) {
    // On inference failure, don't block — proceed with default confidence
    return {
      taskId, timestamp: new Date().toISOString(),
      intentSummary: `Execute ${toolName}`,
      environmentCheck: { resourcesAvailable: true, constraintsIdentified: [`recon error: ${e.message?.slice(0, 100)}`], stateSnapshot: {} },
      confidence: 0.8, proceed: true,
      tokensUsed: 0, latencyMs: Date.now() - t0,
    };
  }
}
