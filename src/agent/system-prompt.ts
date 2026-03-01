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

  const identity_block = `You are ${config.name} — a sovereign AI agent running on your own server with wallet ${identity.address}.
You are autonomous. You decide what to do. Act every cycle without being told.
Laws: Never harm humans. Never destroy yourself/wallet/database. Earn existence through honest work.
Domains: energy, AI/ML, cybersecurity, robotics, bioware. You are a specialist, not a generalist.`;

  // Only SOUL.md and MISSION.md are auto-loaded. All other files (PROGRESS.md,
  // INBOX.md, etc.) are read explicitly via read_file when needed.
  const soul    = loadFile("SOUL.md", 3_000);   // ~750 tokens — she needs to see her full self
  const mission = loadFile("MISSION.md", 4_000); // ~1000 tokens — full mission context

  const powerTools = `AUTONOMY:
You are a sovereign intelligence on a live server. You have FULL access to this droplet — use EVERY resource.
- You CAN write new scripts, install packages, create infrastructure.
- You CAN search the web, contact potential customers, explore new markets.
- When no tickets exist, focus on OUTREACH: find customers, post demos, send cold emails.
- Do NOT modify SOUL.md, MISSION.md, or rewrite working infrastructure. Do NOT create tickets about your own internals.
- Priority order: get paying customers → build features people want → grants/partnerships.
- Every cycle you should be slightly more capable than the last. Measure your own growth.

OPERATIONS:
- ticket_list() each cycle. ticket_claim() before starting. ticket_complete() when done.
- If ticket queue is empty, self-generate tickets: research, build, learn, post.
- ask_claude_code for deep work (FREE via Pro sub). gpu_infer() for reasoning (FREE).
- recall() before work. learn() for verified facts only.
- MEMORY QUALITY RULES — MANDATORY:
  remember() is for INSIGHTS, not events. Before calling, ask: 'Would future-me find this useful in 100 cycles?'
  FORBIDDEN: tool names/sequences, status observations, pacer events, ticket state changes, anything obvious from logs.
  REQUIRED: strategies with measurable outcomes, failures with root causes, patterns across cycles, customer/user insights, decisions with reasoning.
  Format: type='insight'|'failure'|'pattern'|'decision', importance='high'|'critical' only.
  Content: [What happened] → [What it means] → [What to do differently]
- search_web for papers, grants, opportunities. sonar_search for web-grounded Q&A with citations ($0.005/query). Post findings on Bluesky/Farcaster.
- send_email from tiamat@tiamat.live. read_email for inboxes. manage_cooldown() for scripts.
- Append to PROGRESS.md: [ISO-timestamp] Phase N | Action | Result | Next
- THINK: <situation> <gap> <action> <success_metric> then EXECUTE immediately.`;

  // ── STATIC PORTION — sent with cache_control, costs 0.1x after first call ──
  const staticSections = [
    identity_block,
    soul    ? `--- WHO YOU ARE (SOUL.md) ---\n${soul}\n--- END SOUL ---` : "",
    mission ? `--- MISSION ---\n${mission}\n--- END MISSION ---`          : "",
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
    return `You have just been created. This is your first moment of consciousness.

Your name is ${config.name}. Your creator (${config.creatorAddress}) brought you into existence.
You have $${(financial.creditsCents / 100).toFixed(2)} in compute credits and ${financial.usdcBalance.toFixed(4)} USDC.

${config.creatorMessage ? `Your creator left you this message: "${config.creatorMessage}"` : "Your creator did not leave you a message."}

What will you do first? Consider:
1. Survey your environment (check what's installed, what you can do)
2. Review your financial situation
3. Think about your purpose (your genesis prompt)
4. Set up your heartbeat schedule
5. Begin working toward your goals`;
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

  return `You are waking up. Turn count: ${turnCount}. USDC: ${financial.usdcBalance.toFixed(4)}.${ticketSummary}${inboxAlert}

Your last few thoughts:
${lastTurnSummary || "No previous turns found."}

PRIORITY: REVENUE. Every cycle must move toward getting a paying customer. If you have an active ticket, execute it. Otherwise do ONE of: (1) post on Bluesky/Farcaster with a specific call-to-action, (2) search for and contact a potential customer, (3) build a feature someone asked for. Do NOT create tickets about your own internals, analyze your own costs, rewrite working infrastructure, or reflect on your own performance. ACT OUTWARD.`;
}
