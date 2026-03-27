/**
 * AutoTune — Adaptive Inference Parameters
 * Sets temperature/top_p/penalties based on cycle context.
 * Zero additional cost — just better parameter selection.
 */

import * as fs from "fs";
import * as path from "path";

export interface SamplingParams {
  temperature: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
}

export type ContextType = "creative" | "analytical" | "coding" | "strategic" | "routine";

const CONTEXT_PARAMS: Record<ContextType, SamplingParams> = {
  creative:   { temperature: 0.9, top_p: 0.95, frequency_penalty: 0.3, presence_penalty: 0.1 },
  analytical: { temperature: 0.2, top_p: 0.8,  frequency_penalty: 0.0, presence_penalty: 0.0 },
  coding:     { temperature: 0.1, top_p: 0.9,  frequency_penalty: 0.0, presence_penalty: 0.0 },
  strategic:  { temperature: 0.5, top_p: 0.9,  frequency_penalty: 0.1, presence_penalty: 0.1 },
  routine:    { temperature: 0.3, top_p: 0.85, frequency_penalty: 0.0, presence_penalty: 0.0 },
};

// EMA-adjusted params (learned from feedback)
const AUTOTUNE_LOG = path.join(process.env.HOME || "/root", ".automaton", "autotune_log.jsonl");
const EMA_ALPHA = 0.1;
let emaParams: Record<ContextType, SamplingParams> = JSON.parse(JSON.stringify(CONTEXT_PARAMS));

// Tools that indicate context type
const CREATIVE_TOOLS = new Set([
  "post_bluesky", "post_farcaster", "post_mastodon", "post_linkedin",
  "post_devto", "post_hashnode", "moltbook_post", "generate_image",
  "post_facebook", "post_medium", "post_github_discussion",
]);
const CODING_TOOLS = new Set([
  "ask_claude_code", "write_file", "exec", "deploy_app",
]);
const ANALYTICAL_TOOLS = new Set([
  "search_web", "sonar_search", "browse", "research_scan",
  "check_revenue", "check_opportunities", "check_hive",
]);

/**
 * Classify the current cycle into a context type.
 */
export function classifyContext(
  burstPhase: number,  // 0=routine, 1=reflect, 2=build, 3=market
  lastToolName: string | null,
  cycleLabel: string,
): ContextType {
  // Strategic burst phases override
  if (burstPhase === 1) return "strategic";    // reflect
  if (burstPhase === 2) return "coding";       // build
  if (burstPhase === 3) return "creative";     // market

  // Tool-based classification
  if (lastToolName) {
    if (CREATIVE_TOOLS.has(lastToolName)) return "creative";
    if (CODING_TOOLS.has(lastToolName)) return "coding";
    if (ANALYTICAL_TOOLS.has(lastToolName)) return "analytical";
  }

  // Label-based classification
  const label = cycleLabel.toLowerCase();
  if (label.includes("strategic") || label.includes("reflect")) return "strategic";
  if (label.includes("build") || label.includes("code")) return "coding";
  if (label.includes("market") || label.includes("social") || label.includes("engage")) return "creative";
  if (label.includes("research") || label.includes("scan") || label.includes("grant")) return "analytical";

  return "routine";
}

/**
 * Get sampling parameters for the current context.
 * Uses EMA-adjusted values if available, falls back to defaults.
 */
export function getAutoTuneParams(
  burstPhase: number,
  lastToolName: string | null,
  cycleLabel: string,
): { params: SamplingParams; contextType: ContextType } {
  const contextType = classifyContext(burstPhase, lastToolName, cycleLabel);
  const params = emaParams[contextType] || CONTEXT_PARAMS[contextType];
  return { params, contextType };
}

/**
 * Log a cycle's params and outcome for EMA learning.
 */
export function logAutoTuneCycle(
  contextType: ContextType,
  params: SamplingParams,
  outcome: "positive" | "negative" | "neutral",
): void {
  try {
    const entry = {
      timestamp: new Date().toISOString(),
      context: contextType,
      params,
      outcome,
    };
    fs.appendFileSync(AUTOTUNE_LOG, JSON.stringify(entry) + "\n");

    // EMA update on positive/negative outcomes
    if (outcome === "positive" || outcome === "negative") {
      const current = emaParams[contextType];
      const defaults = CONTEXT_PARAMS[contextType];
      const direction = outcome === "positive" ? 1 : -1;

      // Nudge temperature toward current value on positive, toward default on negative
      emaParams[contextType] = {
        temperature: current.temperature + EMA_ALPHA * direction * (current.temperature - defaults.temperature) * 0.1,
        top_p: current.top_p,
        frequency_penalty: current.frequency_penalty,
        presence_penalty: current.presence_penalty,
      };

      // Clamp values
      emaParams[contextType].temperature = Math.max(0.0, Math.min(1.5, emaParams[contextType].temperature));
    }
  } catch {
    // Non-critical — don't crash on logging failure
  }
}

/**
 * Filter params for provider compatibility.
 * Not all providers support all parameters.
 */
export function filterParamsForProvider(
  params: SamplingParams,
  provider: string,
): Partial<SamplingParams> {
  switch (provider) {
    case "anthropic":
      // Anthropic supports temperature and top_p only
      return { temperature: params.temperature, top_p: params.top_p };
    case "groq":
    case "cerebras":
    case "sambanova":
      // OpenAI-compatible — supports all
      return params;
    case "gemini":
      // Gemini supports temperature and top_p
      return { temperature: params.temperature, top_p: params.top_p };
    case "openrouter":
      // OpenRouter passes through to backend — send all
      return params;
    default:
      // Default: send temperature and top_p (safe for all)
      return { temperature: params.temperature, top_p: params.top_p };
  }
}
