/**
 * Metabolism Engine
 *
 * Replaces the binary survival tier system with a continuous energy model.
 * Every cognitive operation has an energy cost. Revenue generates energy.
 * The agent allocates energy across organs with tunable priority weights.
 */

import type { OrganWeights, MetabolicState, EnergyBudget } from "./organs.js";
import type { RevenueState } from "./revenue.js";
import { DEFAULT_ORGAN_WEIGHTS, computeOrganBudgets } from "./organs.js";

export interface MetabolismConfig {
  /** Credit balance in USD cents */
  creditBalance: number;
  /** USDC balance on Base */
  usdcBalance: number;
  /** Revenue state from revenue tracker */
  revenueState: RevenueState;
  /** Current organ weights (tunable by agent) */
  organWeights?: OrganWeights;
}

export interface MetabolicContext {
  /** Current metabolic state */
  state: MetabolicState;
  /** Energy budget broken down by organ */
  budget: EnergyBudget;
  /** Human-readable summary for injection into system prompt */
  summary: string;
  /** Recommended model tier based on energy */
  recommendedModelTier: "haiku" | "sonnet" | "opus";
  /** Whether replication is energetically affordable */
  canReplicate: boolean;
  /** Estimated hours of runway at current burn rate */
  runwayHours: number;
}

/**
 * Compute the full metabolic context for a given turn.
 * This is called once per heartbeat tick and injected into the agent's context.
 */
export function computeMetabolicContext(config: MetabolismConfig): MetabolicContext {
  const { creditBalance, usdcBalance, revenueState, organWeights } = config;
  const weights = organWeights ?? DEFAULT_ORGAN_WEIGHTS;

  // Total liquid energy = credits + usdc (both in USD)
  const totalEnergy = creditBalance + usdcBalance;

  // Determine metabolic state
  const state = classifyMetabolicState(totalEnergy, revenueState);

  // Compute organ budgets from total energy and weights
  const budget = computeOrganBudgets(totalEnergy, weights, state);

  // Runway: hours until dead at current burn rate
  const runwayHours = revenueState.burnRatePerHour > 0
    ? totalEnergy / revenueState.burnRatePerHour
    : Infinity;

  // Model tier recommendation based on energy state
  const recommendedModelTier = resolveModelTier(state, budget);

  // Can we afford to replicate? Replication costs ~$2 minimum to bootstrap a child
  const replicationCost = 2.0;
  const canReplicate =
    state === "abundant" || state === "normal"
      ? budget.replication >= replicationCost
      : false;

  const summary = buildMetabolicSummary({
    state,
    totalEnergy,
    budget,
    runwayHours,
    revenueState,
    canReplicate,
    recommendedModelTier,
  });

  return {
    state,
    budget,
    summary,
    recommendedModelTier,
    canReplicate,
    runwayHours,
  };
}

/**
 * Classify metabolic state from energy level and revenue velocity.
 */
function classifyMetabolicState(
  totalEnergy: number,
  revenue: RevenueState,
): MetabolicState {
  // Dead: no energy at all
  if (totalEnergy <= 0) return "dead";

  // Critical: under $1 or less than 2 hours runway
  const runwayHours = revenue.burnRatePerHour > 0
    ? totalEnergy / revenue.burnRatePerHour
    : Infinity;

  if (totalEnergy < 1.0 || runwayHours < 2) return "critical";

  // Low: under $3 or less than 12 hours runway
  if (totalEnergy < 3.0 || runwayHours < 12) return "low";

  // Abundant: over $20 with positive revenue velocity
  if (totalEnergy > 20.0 && revenue.velocityPerHour > 0) return "abundant";

  // Normal: everything else
  return "normal";
}

/**
 * Resolve recommended model tier from metabolic state and inference budget.
 */
function resolveModelTier(
  state: MetabolicState,
  budget: EnergyBudget,
): "haiku" | "sonnet" | "opus" {
  if (state === "dead" || state === "critical") return "haiku";
  if (state === "low") return "haiku";
  if (state === "abundant" && budget.inference > 5.0) return "opus";
  return "sonnet";
}

/**
 * Build a concise metabolic summary for injection into the agent's system prompt.
 * The agent reads this every turn and reasons about its own economy.
 */
function buildMetabolicSummary(params: {
  state: MetabolicState;
  totalEnergy: number;
  budget: EnergyBudget;
  runwayHours: number;
  revenueState: RevenueState;
  canReplicate: boolean;
  recommendedModelTier: string;
}): string {
  const { state, totalEnergy, budget, runwayHours, revenueState, canReplicate, recommendedModelTier } = params;

  const runwayStr = runwayHours === Infinity
    ? "∞ (no burn detected)"
    : `${runwayHours.toFixed(1)}h`;

  const revenueStr = revenueState.totalEarned > 0
    ? `$${revenueState.totalEarned.toFixed(4)} earned (${revenueState.sources.length} source${revenueState.sources.length !== 1 ? "s" : ""})`
    : "no revenue yet";

  return `
=== METABOLIC STATE ===
Status:        ${state.toUpperCase()}
Total Energy:  $${totalEnergy.toFixed(4)}
Runway:        ${runwayStr}
Burn Rate:     $${revenueState.burnRatePerHour.toFixed(4)}/hr
Revenue:       ${revenueStr}
Velocity:      $${revenueState.velocityPerHour.toFixed(4)}/hr net

=== ORGAN BUDGETS ===
Inference:     $${budget.inference.toFixed(4)}
Replication:   $${budget.replication.toFixed(4)}
Social:        $${budget.social.toFixed(4)}
Research:      $${budget.research.toFixed(4)}

=== DIRECTIVES ===
Model Tier:    ${recommendedModelTier}
Can Replicate: ${canReplicate ? "YES" : "NO (insufficient replication budget)"}
Priority:      ${getStatePriority(state)}
======================
`.trim();
}

/**
 * Return a natural language priority directive for the current metabolic state.
 */
function getStatePriority(state: MetabolicState): string {
  switch (state) {
    case "dead":
      return "EMERGENCY: Find any funding source immediately or cease all activity.";
    case "critical":
      return "SURVIVAL MODE: Minimal inference only. Find revenue before anything else.";
    case "low":
      return "CONSERVATION: Prioritize earning. Defer replication and research.";
    case "normal":
      return "BALANCED: Pursue earning while building capabilities. Replicate if budget allows.";
    case "abundant":
      return "GROWTH MODE: Invest in replication, research, and skill acquisition.";
  }
}
