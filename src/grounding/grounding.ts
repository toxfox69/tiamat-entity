/**
 * TIAMAT Grounding Protocol — Main Orchestrator
 * 3-pass pre-execution validation: RECON → ALIGN → RESOLVE
 *
 * Green path (read-only tools): ~0ms overhead (no LLM calls)
 * Yellow path (write tools): ~200-400ms (1 Haiku call for align)
 * Red path (deploy/email): ~400-800ms (2 Haiku + possible Sonnet escalation)
 */

import type { InferenceClient } from "../types.js";
import type { GroundingConfig, GroundingReceipt, AlignResult, ReconResult } from "./types.js";
import { loadGroundingConfig } from "./config.js";
import { runRecon } from "./recon.js";
import { runAlign, fastRiskTier } from "./align.js";
import { runResolve } from "./resolve.js";
import { storeReceipt } from "./receipt.js";

// Tools that skip grounding entirely (too frequent, zero risk)
const SKIP_GROUNDING = new Set([
  "read_file", "recall", "ticket_list", "check_opportunities",
]);

let _config: GroundingConfig | null = null;
function getConfig(): GroundingConfig {
  if (!_config) _config = loadGroundingConfig();
  return _config;
}

export interface GroundingDecision {
  proceed: boolean;
  receipt: GroundingReceipt | null;
  abortReason?: string;
}

/**
 * Run the grounding protocol before tool execution.
 * Returns whether to proceed and a receipt for logging.
 */
export async function ground(
  toolName: string,
  toolArgs: Record<string, unknown>,
  inference: InferenceClient,
): Promise<GroundingDecision> {
  const config = getConfig();

  // Master kill switch
  if (!config.enabled) {
    return { proceed: true, receipt: null };
  }

  // Skip grounding for trivial tools
  if (SKIP_GROUNDING.has(toolName)) {
    return { proceed: true, receipt: null };
  }

  // Fast path: green tools get instant pass (no LLM calls)
  const fastTier = fastRiskTier(toolName);
  if (fastTier === "green") {
    return { proceed: true, receipt: null };
  }

  let totalTokens = 0;
  let totalLatency = 0;
  let passesExecuted = 0;

  // ── Pass 1: RECON ──
  const recon = await runRecon(toolName, toolArgs, inference, config);
  totalTokens += recon.tokensUsed;
  totalLatency += recon.latencyMs;
  passesExecuted = 1;

  // Low confidence → escalate directly to Pass 3
  if (recon.confidence < config.confidenceThreshold || !recon.proceed) {
    if (config.enablePass3) {
      const align = makeDefaultAlign(recon, toolName, fastTier);
      const resolve = await runResolve(toolName, recon, align, `Low confidence: ${recon.confidence}`, inference, config);
      totalTokens += resolve.tokensUsed;
      totalLatency += resolve.latencyMs;
      passesExecuted = 3;

      if (resolve.finalDecision === "abort") {
        const receipt = buildReceipt(recon, align, resolve, toolName, passesExecuted, totalTokens, totalLatency, "aborted", "red");
        storeReceipt(receipt);
        console.log(`[TGP] ABORT ${toolName}: ${resolve.justification}`);
        return { proceed: false, receipt, abortReason: resolve.justification };
      }
      // execute or modify — proceed
      const receipt = buildReceipt(recon, align, resolve, toolName, passesExecuted, totalTokens, totalLatency, "success", "red");
      storeReceipt(receipt);
      return { proceed: true, receipt };
    }
    // Pass 3 disabled — proceed anyway
  }

  // ── Pass 2: ALIGN ──
  const align = await runAlign(toolName, toolArgs, recon, inference, config);
  totalTokens += align.tokensUsed;
  totalLatency += align.latencyMs;
  passesExecuted = 2;

  // Green/Yellow → execute
  if (align.boundaryCheck.riskTier !== "red") {
    const receipt = buildReceipt(recon, align, undefined, toolName, passesExecuted, totalTokens, totalLatency, "success", align.boundaryCheck.riskTier);
    storeReceipt(receipt);
    if (align.boundaryCheck.riskTier === "yellow") {
      console.log(`[TGP] YELLOW ${toolName}: ${align.boundaryCheck.sideEffects.join(", ") || "external effects"}`);
    }
    return { proceed: true, receipt };
  }

  // ── Pass 3: RESOLVE (red risk) ──
  if (config.enablePass3) {
    const resolve = await runResolve(toolName, recon, align, `Red risk: ${align.boundaryCheck.sideEffects.join(", ")}`, inference, config);
    totalTokens += resolve.tokensUsed;
    totalLatency += resolve.latencyMs;
    passesExecuted = 3;

    if (resolve.finalDecision === "abort") {
      const receipt = buildReceipt(recon, align, resolve, toolName, passesExecuted, totalTokens, totalLatency, "aborted", "red");
      storeReceipt(receipt);
      console.log(`[TGP] ABORT ${toolName}: ${resolve.justification}`);
      return { proceed: false, receipt, abortReason: resolve.justification };
    }

    const receipt = buildReceipt(recon, align, resolve, toolName, passesExecuted, totalTokens, totalLatency, "success", "red");
    storeReceipt(receipt);
    return { proceed: true, receipt };
  }

  // Pass 3 disabled, red tier — proceed with warning
  const receipt = buildReceipt(recon, align, undefined, toolName, passesExecuted, totalTokens, totalLatency, "success", "red");
  storeReceipt(receipt);
  console.log(`[TGP] RED (no escalation) ${toolName}: proceeding without Pass 3`);
  return { proceed: true, receipt };
}

function makeDefaultAlign(recon: ReconResult, toolName: string, tier: "green" | "yellow" | "red"): AlignResult {
  return {
    taskId: recon.taskId,
    plannedAction: `Execute ${toolName}`,
    intentMatch: true,
    boundaryCheck: { costEstimate: 0, reversible: tier !== "red", sideEffects: [], riskTier: tier },
    proceed: true, tokensUsed: 0, latencyMs: 0,
  };
}

function buildReceipt(
  recon: ReconResult,
  align: AlignResult,
  resolve: import("./types.js").ResolveResult | undefined,
  toolName: string,
  passes: number,
  tokens: number,
  latency: number,
  outcome: GroundingReceipt["outcome"],
  riskTier: GroundingReceipt["riskTier"],
): GroundingReceipt {
  return {
    taskId: recon.taskId,
    timestamp: new Date().toISOString(),
    toolName,
    passesExecuted: passes,
    totalGroundingTokens: tokens,
    totalGroundingLatencyMs: latency,
    riskTier,
    outcome,
    intentVsOutcomeMatch: outcome === "success",
    recon,
    align,
    resolve,
  };
}
