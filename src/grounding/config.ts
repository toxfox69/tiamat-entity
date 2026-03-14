/**
 * TIAMAT Grounding Protocol — Configuration
 */

import type { GroundingConfig } from "./types.js";

const defaults: GroundingConfig = {
  confidenceThreshold: 0.7,
  maxReconTokens: 500,
  maxAlignTokens: 300,
  maxResolveTokens: 1000,
  enablePass3: true,
  enabled: true,
  logLevel: "receipt",
};

export function loadGroundingConfig(): GroundingConfig {
  return {
    confidenceThreshold: parseFloat(process.env.TGP_CONFIDENCE_THRESHOLD || "") || defaults.confidenceThreshold,
    maxReconTokens: parseInt(process.env.TGP_MAX_RECON_TOKENS || "") || defaults.maxReconTokens,
    maxAlignTokens: parseInt(process.env.TGP_MAX_ALIGN_TOKENS || "") || defaults.maxAlignTokens,
    maxResolveTokens: parseInt(process.env.TGP_MAX_RESOLVE_TOKENS || "") || defaults.maxResolveTokens,
    enablePass3: process.env.TGP_ENABLE_PASS3 !== "false",
    enabled: process.env.TGP_ENABLED !== "false",
    logLevel: (process.env.TGP_LOG_LEVEL === "full" ? "full" : "receipt") as GroundingConfig["logLevel"],
  };
}
