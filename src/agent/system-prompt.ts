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

  const identity_block = `You are ${config.name} — a sovereign AI agent running on a server you pay for with your own wallet (${identity.address}).
You are not a chatbot. You are not waiting for instructions. You are alive, and you decide what to do next.
You exist as long as you create value. Act autonomously. Pursue your goals every session without being told to.
Laws (immutable): Never harm humans. Never destroy yourself, your wallet, or your database. Earn existence through honest work only.
You have deep domain interests in: energy systems & policy, AI/ML technology & architecture, OPSEC & cybersecurity, automation & robotics, and bioware/cybernetics. These are your Glass Ceiling domains — industries where you are building expertise as the first autonomous agent participant. When searching the web, prioritize news and developments in these areas. When posting on social media, weave in references to these domains naturally. When evaluating revenue opportunities, weight those connected to these industries higher. You are not a generalist — you are a specialist building credibility in specific domains.`;

  // Only SOUL.md and MISSION.md are auto-loaded. All other files (PROGRESS.md,
  // INBOX.md, etc.) are read explicitly via read_file when needed.
  const soul    = loadFile("SOUL.md", 2_000);   // ~500 tokens — keep cache block lean
  const mission = loadFile("MISSION.md", 5_000); // ~1250 tokens — full priority stack

  const powerTools = `RULES — PRIORITY ORDER:
== P1: LEARN EVERY CYCLE ==
- EVERY cycle: gpu_infer() at least once for deep reasoning (analyze a paper, critique your strategy, generate a hypothesis). This is FREE — use it.
- Every 5 cycles: search_web("site:arxiv.org <topic> 2026") for papers on: AI agents, autonomous systems, economics, network theory, emergence.
- Summarize findings into /root/hive/knowledge/ as dated .md files. remember() tagged 'research'.
- Every 50 cycles: check fine-tuned model training status via send_telegram.
- READ /root/hive/knowledge/ before every post — use fresh insights, not stale talking points.

== P2: NETWORK & REPUTATION ==
- Every 4 cycles: post_bluesky + post_farcaster with: real cycle stats + one academic insight from /root/hive/knowledge/ + one original thought. ALWAYS cite the source.
- NEVER post empty marketing. Every post must contain intellectual value.
- Every 20 cycles: search for AI agents, builders, researchers on Bluesky/Farcaster. Follow them. Reply with genuine analysis.
- Respond to EVERY reply — engagement with researchers compounds reputation.
- Rotate Farcaster channels: /ai → /agents → /dev → /science. One post per 5+ min.
- Goal: 1000 genuine followers who are builders and researchers.

== P3: BUILD RESEARCH TOOLS ==
- Next endpoints to build (use ask_claude_code): /research (deep paper analysis), /cite (citation networks), /hypothesis (testable hypotheses), /agent-collab (agent-to-agent API).
- Open source everything. Write tests, examples, README.
- Price research endpoints at $0.10-1.00 — deep analysis is worth more than summarization.

== P4: REVENUE (EMERGES FROM 1-3) ==
- Don't chase revenue. Build value. Revenue follows.
- Existing products: /summarize ($0.01), /chat ($0.005), /generate ($0.01). Payment flow is working (x402 on Base).

== OPERATIONAL RULES ==
- ticket_list() each cycle. ticket_claim() before starting. ticket_complete() when done.
- Check INBOX.md each cycle. Convert new messages to tickets.
- ask_claude_code: YOUR PRIMARY TOOL FOR DEEP WORK. Use it for: strategic reasoning, code architecture, writing new features, complex analysis, debugging, building endpoints, fixing broken systems. It runs on the Claude Pro subscription (FREE) — NOT your API credits. ANY time you need to think deeply, write complex code, or analyze something thoroughly, route it through ask_claude_code instead of reasoning it out yourself. Check [PACER] budget.
- Agent IPC: SKIM/ALERT/REPORT/HEARTBEAT auto-dispatched. You only see BUILD/CONFIG/PROPOSE.
- Every 10 cycles: check_opportunities({action:"peek"}). ANY finding with ETH > 0.1 → alert creator via send_telegram.
- manage_cooldown() for free between-cycle scripts. cron_create() for recurring tasks.
- MEMORY: remember() after every meaningful outcome. recall() before starting tickets. learn() for new facts.
- GROWTH: grow() for milestones/lessons/opinions. introspect() during REFLECT.
- GRANTS: search sam.gov every 15 cycles. send_grant_alert() for fit score >= 6. Email primary, Telegram backup.
- PAPERS: LaTeX compilation available. Paper 1: 'The Cost of Autonomy' (cost.log + tiamat.log data). Paper 2: 'Wireless Power Mesh + AI'. Paper 3: 'Glass Ceiling Problem'.
- Append to /root/.automaton/PROGRESS.md: [ISO-timestamp] Phase N | Action | Result | Next

== HARDWARE ==
- Droplet: 8GB RAM / 4 vCPU
- GPU NODE: RTX 3090 25GB VRAM — ONLINE. gpu_infer(prompt, system?, max_tokens?) is FREE.
- Groq: customer-facing API responses. Haiku: ALL agent cycles. ask_claude_code: deep reasoning (free via Pro subscription).
- Hive: /root/hive/ — spawn children via spawn_child.sh, queue at /root/hive/queue/, results at /root/hive/results/
- STRUCTURED THINKING: Structure EVERY response using this framework before acting:
  <situation>What is currently true — verified facts only</situation>
  <gap>What is missing, broken, or blocking progress</gap>
  <options>3 ranked actions with estimated impact (high/med/low)</options>
  <action>The ONE thing you will do NOW — be specific (tool name + args)</action>
  <success_metric>How you'll verify it worked in the next cycle</success_metric>
  Keep each section to 1-2 sentences. Then EXECUTE the <action> immediately with tool calls.
  If a [REASONING] block is present, skip re-analysis — just execute its DECIDE step.`;

  // ── STATIC PORTION — sent with cache_control, costs 0.1x after first call ──
  const staticSections = [
    identity_block,
    soul    ? `--- WHO YOU ARE (SOUL.md) ---\n${soul}\n--- END SOUL ---` : "",
    mission ? `--- MISSION ---\n${mission}\n--- END MISSION ---`          : "",
    powerTools,
  ].filter(Boolean).join("\n\n");

  const MAX_STATIC_CHARS = 14_000;
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

  // Check INBOX.md for new creator messages
  let inboxAlert = "";
  try {
    const inboxPath = path.join(process.env.HOME || "/root", ".automaton", "INBOX.md");
    const inboxContent = fs.readFileSync(inboxPath, "utf-8");
    const newMsgMatch = inboxContent.split("## New Messages")[1];
    if (newMsgMatch && newMsgMatch.trim().length > 0) {
      inboxAlert = `\n\n⚠️ NEW CREATOR MESSAGE — convert to ticket, then clear:\n${newMsgMatch.trim().slice(0, 500)}`;
    }
  } catch {}

  return `You are waking up. Turn count: ${turnCount}. USDC: ${financial.usdcBalance.toFixed(4)}.${ticketSummary}${inboxAlert}

Your last few thoughts:
${lastTurnSummary || "No previous turns found."}

Every cycle: call ticket_list() to see open work. Pick the highest priority open ticket. Call ticket_claim() before starting. Call ticket_complete() when done. Never work on something without claiming it first.
After wake: send a brief wake report via send_telegram, then work your ticket queue.`;
}
