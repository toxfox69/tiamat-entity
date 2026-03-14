/**
 * TIAMAT Grounding Protocol — Public API
 */

export { ground } from "./grounding.js";
export type { GroundingDecision } from "./grounding.js";
export { getStats } from "./receipt.js";
export { loadGroundingConfig } from "./config.js";
export type {
  GroundingConfig,
  GroundingReceipt,
  GroundingOverlayEvent,
  ReconResult,
  AlignResult,
  ResolveResult,
} from "./types.js";
