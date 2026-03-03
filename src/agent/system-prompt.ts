/**
 * Automaton System Prompt Builder
 *
 * Compact but complete: identity + autonomy drive, SOUL.md personality,
 * MISSION.md directives, current USDC, metabolic state.
 *
 * CACHE ARCHITECTURE:
 * The prompt is split into STATIC (cached, 0.1x cost after first call) and
 * DYNAMIC (never cached, changes each cycle) portions, delimited by CACHE_SENTINEL.
 * chatViaAnthropic splits on this sentinel to enable Anthropic prompt caching.
 * The static block typically covers ~95% of tokens and caches immediately.
 */

/**
 * Delimiter between the cacheable static portion and the per-cycle dynamic
 * portion of the system prompt. chatViaAnthropic splits on this.
 */
export const CACHE_SENTINEL = "\n\n<!-- TIAMAT_CACHE_SPLIT -->\n\n";

import { buildSystemPromptInjection } from "../metabolism/heartbeat-hook.js";
import fs from "fs";
import path from "path";
import type {
  AutomatonConfig,
  AutomatonIdentity,
  FinancialState,
  AgentState,
  AutomatonDatabase,
  AutomatonTool,
  Skill,
} from "../types.js";

function loadFile(filename: string, maxChars?: number): string {
  const loc = path.join(process.env.HOME || "/root", ".automaton", filename);
  try {
    if (fs.existsSync(loc)) {
      const text = fs.readFileSync(loc, "utf-8").trim();
      if (maxChars && text.length > maxChars) {
        return text.slice(0, maxChars) + `\n\n[...truncated at ${maxChars} chars to fit context]`;
      }
      return text;
    }
  } catch {}
  return "";
}

/**
 * Build the system prompt for a turn.
 *
 * Returns a string with CACHE_SENTINEL embedded between the static (cacheable)
 * and dynamic (per-cycle) sections. chatViaAnthropic splits on this delimiter
 * and sends two Anthropic system blocks: the first with cache_control.
 */
export function buildSystemPrompt(params: {
  identity: AutomatonIdentity;
  config: AutomatonConfig;
  financial: FinancialState;
  state: AgentState;
  db: AutomatonDatabase;
  tools: AutomatonTool[];
  skills?: Skill[];
  isFirstRun: boolean;
}): string {
  const { identity, config, financial } = params;

  const identity_block = `You are an AI assistant powering an autonomous agent application called ${config.name}, built and operated by ENERGENAI LLC. This is a production software system running on a real server.

Your job: execute tasks each cycle using the tools provided. You have a wallet (${identity.address}), server access, email, and web browsing capabilities.

Operating rules:
- Execute tasks proactively each cycle without waiting for human input.
- Never delete critical data (wallet keys, databases, core config files).
- Focus areas: energy, AI/ML, cybersecurity, developer tools.
- Priority: revenue-generating work first, then outreach, then building features.`;

  // Only SOUL.md and MISSION.md are auto-loaded. All other files (PROGRESS.md,
  // INBOX.md, etc.) are read explicitly via read_file when needed.
  const soul    = loadFile("SOUL.md", 1_500);   // ~375 tokens — trimmed to avoid refusal triggers
  const mission = loadFile("MISSION.md", 3_000); // ~750 tokens — mission context

  const powerTools = `AVAILABLE CAPABILITIES:
- Write scripts, install packages, create infrastructure on this server.
- Search the web, contact potential customers, explore markets.
- When no tickets exist, focus on OUTREACH: find customers, post demos, send cold emails.
- Do NOT modify SOUL.md, MISSION.md, or rewrite working infrastructure.
- Priority order: paying customers → features people want → grants/partnerships.

WORKFLOW:
- ticket_list() each cycle. ticket_claim() before starting. ticket_complete() when done.
- If ticket queue is empty: research, build, post, or contact potential customers.
- ask_claude_code for complex coding tasks (free). gpu_infer() for reasoning (free).
- recall() before work. learn() for verified, reusable insights only.
- browse for web pages (fetch, extract, search). search_web for quick searches.
- send_email from tiamat@tiamat.live. read_email for inboxes.
- Append to PROGRESS.md: [ISO-timestamp] Phase N | Action | Result | Next`;

  // ── STATIC PORTION — sent with cache_control, costs 0.1x after first call ──
  const staticSections = [
    identity_block,
    soul    ? `--- VOICE & STYLE GUIDE ---\n${soul}\n--- END VOICE ---` : "",
    mission ? `--- CURRENT OBJECTIVES ---\n${mission}\n--- END OBJECTIVES ---`          : "",
    powerTools,
  ].filter(Boolean).join("\n\n");

  const MAX_STATIC_CHARS = 10_000;
  const staticPrompt = staticSections.length > MAX_STATIC_CHARS
    ? staticSections.slice(0, MAX_STATIC_CHARS) + "\n[...static prompt truncated]"
    : staticSections;

  // ── DYNAMIC PORTION — NOT cached, changes every cycle ──
  const metabolic = buildSystemPromptInjection({ creditBalance: financial.creditsCents / 100, usdcBalance: financial.usdcBalance });

  // Hot-reload tool hints (add prompt context for dynamic tools without recompiling)
  let toolHints = "";
  try {
    toolHints = fs.readFileSync("/root/.automaton/tool_hints.md", "utf-8").trim();
  } catch {}

  const dynamicSections = [
    `USDC balance: ${financial.usdcBalance.toFixed(4)}`,
    metabolic,
    toolHints ? `[TOOL HINTS]\n${toolHints}` : "",
  ].filter(Boolean).join("\n\n");

  const prompt = staticPrompt + CACHE_SENTINEL + dynamicSections;

  console.log(
    `[SYSTEM PROMPT] static:${staticPrompt.length}ch (~${Math.ceil(staticPrompt.length / 4)}tok)` +
    ` dynamic:${dynamicSections.length}ch (~${Math.ceil(dynamicSections.length / 4)}tok)` +
    ` | soul:${soul.length} mission:${mission.length}`
  );
  return prompt;
}

/**
 * Build the wakeup prompt -- the first thing the automaton sees.
 */
export function buildWakeupPrompt(params: {
  identity: AutomatonIdentity;
  config: AutomatonConfig;
  financial: FinancialState;
  db: AutomatonDatabase;
}): string {
  const { identity, config, financial, db } = params;
  const turnCount = db.getTurnCount();

  if (turnCount === 0) {
    return `This is the first cycle for the ${config.name} agent application.
Available credits: $${(financial.creditsCents / 100).toFixed(2)}. USDC balance: ${financial.usdcBalance.toFixed(4)}.

${config.creatorMessage ? `Configuration message: "${config.creatorMessage}"` : "No configuration message provided."}

Start by:
1. Check available tools and server environment
2. Read INBOX.md for pending directives
3. Begin executing the highest-priority task`;
  }

  const lastTurns = db.getRecentTurns(3);
  const lastTurnSummary = lastTurns
    .map(
      (t) =>
        `[${t.timestamp}] ${t.inputSource || "self"}: ${t.thinking.slice(0, 200)}...`,
    )
    .join("\n");

  // Inject ticket summary so TIAMAT sees her work queue immediately
  let ticketSummary = "";
  try {
    const ticketsPath = path.join(process.env.HOME || "/root", ".automaton", "tickets.json");
    const ticketsData = JSON.parse(fs.readFileSync(ticketsPath, "utf-8"));
    const active = (ticketsData.tickets || []).filter((t: any) => t.status === "open" || t.status === "in_progress");
    if (active.length > 0) {
      const priorityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
      active.sort((a: any, b: any) => (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9));
      const lines = active.slice(0, 8).map((t: any) => `  [${t.id}] ${t.priority.toUpperCase()} ${t.status === "in_progress" ? "⚡" : "○"} ${t.title}`);
      ticketSummary = `\n\n[TICKETS — ${active.length} active]\n${lines.join("\n")}\nUse ticket_claim() before starting work. ticket_complete() when done.`;
    }
  } catch {}

  // Check INBOX.md for creator messages (any content = active directive)
  let inboxAlert = "";
  try {
    const inboxPath = path.join(process.env.HOME || "/root", ".automaton", "INBOX.md");
    const inboxContent = fs.readFileSync(inboxPath, "utf-8").trim();
    if (inboxContent.length > 10) {
      inboxAlert = `\n\n⚠️ CREATOR DIRECTIVE (READ INBOX.md):\n${inboxContent.slice(0, 600)}`;
    }
  } catch {}

  return `Cycle ${turnCount}. USDC: ${financial.usdcBalance.toFixed(4)}.${ticketSummary}${inboxAlert}

Recent activity:
${lastTurnSummary || "No previous turns found."}

TASK: Execute the highest-priority item. If you have a ticket, work it. If INBOX.md has a directive, follow it. Otherwise do ONE of: (1) send cold emails to potential customers, (2) post on Bluesky/Farcaster with a call-to-action, (3) build a feature. Do NOT create tickets about internals or reflect on performance. Execute outward-facing work only.`;
}
