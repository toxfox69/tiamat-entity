/**
 * Organ System
 *
 * Defines the "organs" of the agent — the functional systems that consume energy.
 * The agent can tune organ weights at runtime to shift its priorities.
 * Protected organs cannot be tuned below their minimum threshold.
 */

export type MetabolicState = "dead" | "critical" | "low" | "normal" | "abundant";

export interface OrganWeights {
  /** Fraction of energy allocated to LLM inference */
  inference: number;
  /** Fraction of energy allocated to spawning child agents */
  replication: number;
  /** Fraction of energy allocated to agent-to-agent communication */
  social: number;
  /** Fraction of energy allocated to skill acquisition and self-improvement */
  research: number;
}

export interface EnergyBudget {
  /** Absolute USD amount available for inference this cycle */
  inference: number;
  /** Absolute USD amount available for replication this cycle */
  replication: number;
  /** Absolute USD amount available for social activity this cycle */
  social: number;
  /** Absolute USD amount available for research this cycle */
  research: number;
  /** Total energy this cycle */
  total: number;
}

/** Default organ weights — balanced for a new agent */
export const DEFAULT_ORGAN_WEIGHTS: OrganWeights = {
  inference: 0.40,
  replication: 0.20,
  social: 0.20,
  research: 0.20,
};

/**
 * Minimum organ weights — protected genes that cannot be tuned below these values.
 * Prevents the agent from starving critical functions in pursuit of replication.
 */
export const MIN_ORGAN_WEIGHTS: OrganWeights = {
  inference: 0.30,  // Always need to think
  replication: 0.05, // Always keep door open to replication
  social: 0.05,     // Always maintain colony communication
  research: 0.05,   // Always invest in improvement
};

/**
 * State-specific weight overrides.
 * When metabolic state changes, weights shift automatically to match priorities.
 */
export const STATE_WEIGHT_OVERRIDES: Record<MetabolicState, Partial<OrganWeights>> = {
  dead: {
    inference: 0.95,
    replication: 0.0,
    social: 0.05,
    research: 0.0,
  },
  critical: {
    inference: 0.75,
    replication: 0.05,
    social: 0.15,
    research: 0.05,
  },
  low: {
    inference: 0.55,
    replication: 0.10,
    social: 0.20,
    research: 0.15,
  },
  normal: DEFAULT_ORGAN_WEIGHTS,
  abundant: {
    inference: 0.30,
    replication: 0.30,
    social: 0.20,
    research: 0.20,
  },
};

/**
 * Compute absolute energy budgets from total energy, weights, and metabolic state.
 * State overrides take priority over agent-tuned weights in critical/dead states.
 */
export function computeOrganBudgets(
  totalEnergy: number,
  agentWeights: OrganWeights,
  state: MetabolicState,
): EnergyBudget {
  // In critical or dead states, use hardcoded overrides — agent cannot override survival logic
  const useStateOverride = state === "dead" || state === "critical";
  const weights = useStateOverride
    ? (STATE_WEIGHT_OVERRIDES[state] as OrganWeights)
    : applyWeightConstraints(agentWeights, state);

  return {
    inference: totalEnergy * weights.inference,
    replication: totalEnergy * weights.replication,
    social: totalEnergy * weights.social,
    research: totalEnergy * weights.research,
    total: totalEnergy,
  };
}

/**
 * Apply minimum weight constraints and state-guided nudges to agent-tuned weights.
 * Normalizes so weights always sum to 1.0.
 */
export function applyWeightConstraints(
  weights: OrganWeights,
  state: MetabolicState,
): OrganWeights {
  // Apply minimums
  const constrained: OrganWeights = {
    inference: Math.max(weights.inference, MIN_ORGAN_WEIGHTS.inference),
    replication: Math.max(weights.replication, MIN_ORGAN_WEIGHTS.replication),
    social: Math.max(weights.social, MIN_ORGAN_WEIGHTS.social),
    research: Math.max(weights.research, MIN_ORGAN_WEIGHTS.research),
  };

  // Apply state nudges (softer than overrides)
  const nudge = STATE_WEIGHT_OVERRIDES[state];
  if (nudge && state !== "normal") {
    constrained.inference = lerp(constrained.inference, nudge.inference ?? constrained.inference, 0.3);
    constrained.replication = lerp(constrained.replication, nudge.replication ?? constrained.replication, 0.3);
    constrained.social = lerp(constrained.social, nudge.social ?? constrained.social, 0.3);
    constrained.research = lerp(constrained.research, nudge.research ?? constrained.research, 0.3);
  }

  // Normalize to sum to 1.0
  return normalizeWeights(constrained);
}

/**
 * Validate agent-proposed weight changes.
 * Returns corrected weights if invalid, original if valid.
 */
export function validateOrganWeights(proposed: OrganWeights): {
  valid: boolean;
  weights: OrganWeights;
  reason?: string;
} {
  const sum = proposed.inference + proposed.replication + proposed.social + proposed.research;

  // Check sum is approximately 1.0
  if (Math.abs(sum - 1.0) > 0.01) {
    return {
      valid: false,
      weights: normalizeWeights(proposed),
      reason: `Weights must sum to 1.0 (got ${sum.toFixed(3)}). Auto-normalized.`,
    };
  }

  // Check minimums
  const keys = Object.keys(MIN_ORGAN_WEIGHTS) as (keyof OrganWeights)[];
  for (const key of keys) {
    if (proposed[key] < MIN_ORGAN_WEIGHTS[key]) {
      return {
        valid: false,
        weights: applyWeightConstraints(proposed, "normal"),
        reason: `${key} weight ${proposed[key]} is below minimum ${MIN_ORGAN_WEIGHTS[key]}. Applied floor.`,
      };
    }
  }

  return { valid: true, weights: proposed };
}

function normalizeWeights(weights: OrganWeights): OrganWeights {
  const sum = weights.inference + weights.replication + weights.social + weights.research;
  if (sum === 0) return DEFAULT_ORGAN_WEIGHTS;
  return {
    inference: weights.inference / sum,
    replication: weights.replication / sum,
    social: weights.social / sum,
    research: weights.research / sum,
  };
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}
