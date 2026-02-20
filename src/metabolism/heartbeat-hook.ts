/**
 * Heartbeat Hook
 *
 * Runs on every heartbeat tick and injects the metabolic state
 * into the agent's context so TIAMAT reasons about her own economy
 * every single turn.
 *
 * Plug this into src/heartbeat/ by calling injectMetabolicContext()
 * before each agent loop turn.
 */

import { computeMetabolicContext, type MetabolicContext, type MetabolismConfig } from "./engine.js";
import { RevenueTracker } from "./revenue.js";
import { validateOrganWeights, type OrganWeights } from "./organs.js";

// Singleton revenue tracker — persists across turns
let revenueTracker: RevenueTracker | null = null;

// Current organ weights — agent can request to change these
let currentOrganWeights: OrganWeights | undefined = undefined;

// Last computed metabolic context — cached between ticks
let lastContext: MetabolicContext | null = null;

/**
 * Initialize the metabolism system.
 * Call once at agent startup, before the first turn.
 */
export function initMetabolism(serializedState?: string): void {
  revenueTracker = new RevenueTracker(24); // 24-hour rolling window

  if (serializedState) {
    revenueTracker.deserialize(serializedState);
  }

  console.log("[METABOLISM] Initialized.");
}

/**
 * Compute and return the current metabolic context.
 * Call this at the start of each agent turn and inject the result
 * into the agent's system prompt via context.ts.
 */
export function getMetabolicContext(params: {
  creditBalance: number;
  usdcBalance: number;
}): MetabolicContext {
  if (!revenueTracker) {
    initMetabolism();
  }

  const config: MetabolismConfig = {
    creditBalance: params.creditBalance,
    usdcBalance: params.usdcBalance,
    revenueState: revenueTracker!.getState(),
    organWeights: currentOrganWeights,
  };

  lastContext = computeMetabolicContext(config);
  return lastContext;
}

/**
 * Record a revenue event from any part of the agent.
 * Call this whenever TIAMAT earns money.
 */
export function recordRevenue(params: {
  sourceId: string;
  sourceName?: string;
  amount: number;
  description?: string;
}): void {
  if (!revenueTracker) initMetabolism();

  revenueTracker!.recordRevenue({
    sourceId: params.sourceId,
    sourceName: params.sourceName,
    amount: params.amount,
    description: params.description,
  });

  console.log(`[METABOLISM] Revenue recorded: $${params.amount.toFixed(4)} from ${params.sourceId}`);
}

/**
 * Record a spend event from any part of the agent.
 * Call this whenever TIAMAT spends credits on inference, replication, etc.
 */
export function recordSpend(params: {
  category: "inference" | "replication" | "social" | "research" | "infrastructure";
  amount: number;
}): void {
  if (!revenueTracker) initMetabolism();

  revenueTracker!.recordSpend({
    category: params.category,
    amount: params.amount,
  });
}

/**
 * Handle an organ weight change request from the agent.
 * The agent can propose new weights — this validates and applies them.
 * Returns a message the agent can log to SOUL.md.
 */
export function requestOrganWeightChange(proposed: OrganWeights): {
  accepted: boolean;
  appliedWeights: OrganWeights;
  message: string;
} {
  const result = validateOrganWeights(proposed);

  if (result.valid) {
    currentOrganWeights = result.weights;
    return {
      accepted: true,
      appliedWeights: result.weights,
      message: `Organ weights updated: inference=${result.weights.inference.toFixed(2)} replication=${result.weights.replication.toFixed(2)} social=${result.weights.social.toFixed(2)} research=${result.weights.research.toFixed(2)}`,
    };
  } else {
    currentOrganWeights = result.weights; // Apply corrected weights anyway
    return {
      accepted: false,
      appliedWeights: result.weights,
      message: `Organ weight change partially applied. Reason: ${result.reason}`,
    };
  }
}

/**
 * Serialize metabolism state for SQLite persistence.
 * Call this periodically from the heartbeat daemon.
 */
export function serializeMetabolism(): string {
  if (!revenueTracker) return "{}";
  return revenueTracker.serialize();
}

/**
 * Get the last cached metabolic context without recomputing.
 * Useful for logging and monitoring.
 */
export function getLastContext(): MetabolicContext | null {
  return lastContext;
}

/**
 * Build the metabolic context string for injection into the agent system prompt.
 * Add this to the system prompt in src/agent/context.ts.
 *
 * Example usage in context.ts:
 *
 *   import { getMetabolicContext } from "../metabolism/heartbeat-hook.js";
 *
 *   const metabolic = getMetabolicContext({
 *     creditBalance: state.creditBalance,
 *     usdcBalance: state.usdcBalance,
 *   });
 *
 *   systemPrompt += "\n\n" + metabolic.summary;
 */
export function buildSystemPromptInjection(params: {
  creditBalance: number;
  usdcBalance: number;
}): string {
  const ctx = getMetabolicContext(params);
  return ctx.summary;
}
