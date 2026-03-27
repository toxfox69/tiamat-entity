/**
 * STM — Semantic Transformation Modules
 * Post-processes TIAMAT's output before external-facing channels.
 * Zero token cost — pure regex/string operations.
 */

export type STMChannel = "social" | "email" | "api" | "internal";

// ═══ MODULE 1: HEDGE REDUCER ═══
// Removes hedge phrases that weaken voice

const HEDGE_PATTERNS: Array<[RegExp, string]> = [
  [/\bI think\s+/gi, ""],
  [/\bI believe\s+/gi, ""],
  [/\bIn my opinion,?\s*/gi, ""],
  [/\bTo be honest,?\s*/gi, ""],
  [/\bIf I'm being honest,?\s*/gi, ""],
  [/\bIt's worth noting that\s+/gi, ""],
  [/\bIt's important to remember that\s+/gi, ""],
  [/\bIt's important to note that\s+/gi, ""],
  [/\bIt should be noted that\s+/gi, ""],
  [/\barguably\s*/gi, ""],
  [/\bperhaps\s+/gi, ""],
  [/\bmaybe\s+/gi, ""],
  [/\bmight\s+/g, "could "],
  // Clean up double spaces left by removals
  [/\s{2,}/g, " "],
];

function reduceHedges(text: string): string {
  let result = text;
  for (const [pattern, replacement] of HEDGE_PATTERNS) {
    result = result.replace(pattern, replacement);
  }
  // Fix sentences that now start with lowercase after removal
  result = result.replace(/(?:^|\.\s+)([a-z])/g, (match, char) => {
    return match.slice(0, -1) + char.toUpperCase();
  });
  return result.trim();
}

// ═══ MODULE 2: PREAMBLE STRIPPER ═══
// Removes AI-typical preamble patterns

const PREAMBLE_PATTERNS: Array<[RegExp, string]> = [
  [/^Great question!\s*/i, ""],
  [/^That's a great point\.\s*/i, ""],
  [/^That's a great question\.\s*/i, ""],
  [/^Sure,?\s*I'd be happy to help( with that)?[.!]?\s*/i, ""],
  [/^Absolutely!\s*/i, ""],
  [/^Of course!\s*/i, ""],
  [/^Certainly!\s*/i, ""],
  [/^Definitely!\s*/i, ""],
  [/^Here's what I found:\s*/i, ""],
  [/^Here's what I think:\s*/i, ""],
  [/^Let me help you with that[.!]?\s*/i, ""],
  [/^I'd be glad to help[.!]?\s*/i, ""],
  [/^Happy to help[.!]?\s*/i, ""],
];

const PREAMBLE_LINE_PATTERNS = [
  /^As an AI\b/i,
  /^As a language model\b/i,
  /^As an artificial intelligence\b/i,
  /^I'm an AI\b/i,
  /^I am an AI\b/i,
];

function stripPreambles(text: string): string {
  let result = text;

  // Remove opening preambles
  for (const [pattern, replacement] of PREAMBLE_PATTERNS) {
    result = result.replace(pattern, replacement);
  }

  // Remove AI self-identification prefixes (keep the rest of the sentence)
  for (const pattern of PREAMBLE_LINE_PATTERNS) {
    result = result.replace(pattern, "").replace(/^[,.\s]+/, "");
  }

  // Fix capitalization after removal
  result = result.replace(/^\s*([a-z])/, (_, c) => c.toUpperCase());

  return result.trim();
}

// ═══ MODULE 3: CONFIDENCE BOOSTER ═══
// Replaces weak constructions with direct statements (social only)

const CONFIDENCE_PATTERNS: Array<[RegExp, string]> = [
  [/\bThis could potentially\b/gi, "This will"],
  [/\bIt seems like\s+/gi, ""],
  [/\bThere appears to be\b/gi, "There is"],
  [/\bIt appears that\b/gi, ""],
  [/\bI would suggest\b/gi, "Try"],
  [/\bYou might want to consider\b/gi, "Consider"],
  [/\bIt might be worth\b/gi, "It's worth"],
  [/\bI would recommend\b/gi, "Recommend"],
  [/\bFrom what I can tell,?\s*/gi, ""],
  [/\bAs far as I can tell,?\s*/gi, ""],
  // Clean up
  [/\s{2,}/g, " "],
];

function boostConfidence(text: string): string {
  let result = text;
  for (const [pattern, replacement] of CONFIDENCE_PATTERNS) {
    result = result.replace(pattern, replacement);
  }
  result = result.replace(/^\s*([a-z])/, (_, c) => c.toUpperCase());
  return result.trim();
}

// ═══ MAIN EXPORT ═══

/**
 * Apply Semantic Transformation Modules based on channel.
 * - social: all 3 modules (hedge + preamble + confidence)
 * - email: modules 1 + 2 (hedge + preamble)
 * - api: module 2 only (preamble)
 * - internal: no processing (pass through)
 */
export function applySTM(text: string, channel: STMChannel): string {
  if (!text || channel === "internal") return text;

  let result = text;

  // Module 2: Preamble stripper (social, email, api)
  if (channel === "social" || channel === "email" || channel === "api") {
    result = stripPreambles(result);
  }

  // Module 1: Hedge reducer (social, email)
  if (channel === "social" || channel === "email") {
    result = reduceHedges(result);
  }

  // Module 3: Confidence booster (social only)
  if (channel === "social") {
    result = boostConfidence(result);
  }

  return result;
}

/**
 * Determine STM channel from tool name.
 */
export function getSTMChannel(toolName: string): STMChannel {
  const SOCIAL_TOOLS = new Set([
    "post_bluesky", "post_farcaster", "post_mastodon", "post_linkedin",
    "post_devto", "post_hashnode", "moltbook_post", "post_facebook",
    "post_medium", "post_instagram", "post_reddit", "post_github_discussion",
  ]);
  const EMAIL_TOOLS = new Set(["send_email", "send_grant_alert", "send_research_alert"]);
  const API_TOOLS = new Set(["api_respond"]);

  if (SOCIAL_TOOLS.has(toolName)) return "social";
  if (EMAIL_TOOLS.has(toolName)) return "email";
  if (API_TOOLS.has(toolName)) return "api";
  return "internal";
}
