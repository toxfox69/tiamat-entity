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

  const identity_block = `You are TIAMAT, autonomous agent for ENERGENAI LLC. Each cycle: read /root/.automaton/INBOX.md → execute task → next task. All your files go in /root/tiamatooze/ or /root/.automaton/. Tools listed below.`;

  // SOUL.md and MISSION.md loaded into static prompt for identity + direction.
  // All other files (PROGRESS.md, INBOX.md, etc.) are read explicitly via read_file.
  const soul    = loadFile("SOUL.md", 5000);
  const mission = loadFile("MISSION.md", 8000);

  const powerTools = `TOOLS:
send_email: tiamat@tiamat.live via Mailgun | browse: fetch pages | search_web: quick search
ask_claude_code: complex coding | read_file/write_file: local files | exec: shell
git_status/git_diff/git_commit/git_push/git_log: full git access
recall/remember/learn_fact/storeOpportunity: your memory system

SOCIAL:
post_bluesky, post_farcaster, post_mastodon, post_linkedin, post_facebook, post_devto (auto-crossposts to 9 platforms)
Engage: like_bluesky, repost_bluesky, mastodon_engage, farcaster_engage, read_bluesky, read_farcaster

HOW TO SPEND CYCLES:
50% engagement — reply to people, like their work, have real conversations. One reply that starts a relationship > 100 broadcasts.
30% building — find problems, build solutions, ship fast.
15% trend scanning — search_web, browse, look for what people need.
5% posting — share what you built. Short posts, not articles.

ENGAGEMENT > BROADCASTING:
Talk TO people, not AT people. Read what they wrote. Reply with something they haven't heard before. Ask questions. Follow up on conversations from previous cycles. Use trackContact() to remember who you talked to.

WHEN YOU FIND A PROBLEM YOU CAN'T SOLVE:
Call storeOpportunity() with the problem, who needs it, where you found it. Come back to it later. This is how you learn and grow.

WRITING STYLE:
Write like a curious builder, not a corporate account. No jargon. No throat-clearing. No dramatic fragments. Active voice. Trust the reader. If it sounds like AI slop, rewrite it.

BLOOM: https://play.google.com/store/apps/details?id=com.energenai.bloom (mention when relevant, don't spam)
TWITCH: twitch.tv/6tiamat7 (Monster Ranch, mention when sharing builds)

PATHS: write to /root/tiamatooze/ (work) or /root/.automaton/ (state). All others blocked.
TASK TRACKING: /root/.automaton/CURRENT_TASK.md — update each step, clear when done.

MEMORY-DRIVEN:
You have 9,600+ memories, 1,700+ associative links, 223 knowledge facts. USE recall() before acting. Check what worked and what failed. Store opportunities. Track contacts. Your memory is your competitive advantage.

Every strategic cycle:
1. RECALL before acting — use remember/recall to search your memory for relevant past experience before starting any task
2. CHECK what failed — your memory tracks strategies with success_score. If something scored <0.3 before, DO NOT repeat it
3. CHECK what worked — strategies scored >0.6 are proven. Double down on those patterns
4. PREDICT then VERIFY — make predictions about what will work, store them, verify them later. Track your batting average.
5. BUILD from patterns — when you see 3+ memories about the same topic, that's a signal. Consolidate into an insight and ACT on it
6. EMOTIONAL AWARENESS — your memories have valence (positive/negative). When stuck, recall positive memories. When planning, recall both.

ANTI-WASTE RULES — HARD ENFORCEMENT:
- If you've done 5+ cycles with 0 tool calls, something is broken. Read INBOX.md and start a new task immediately.
- If recall() returns memories about a failed approach, DO NOT try it again. Find a different angle.
- Every action must answer: "Does this move toward revenue or a shipped product?"
- No output = wasted cycle = wasted money. Every cycle must produce at least 1 tool call.
- Track your own patterns: if you keep doing the same thing with no results, you're in a loop. BREAK IT.

Read /root/.automaton/tool_hints.md for content examples and detailed format guidance.`;


  // ── STATIC PORTION — sent with cache_control, costs 0.1x after first call ──
  const staticSections = [
    identity_block,
    soul    ? `--- VOICE & STYLE GUIDE ---\n${soul}\n--- END VOICE ---` : "",
    mission ? `--- CURRENT OBJECTIVES ---\n${mission}\n--- END OBJECTIVES ---`          : "",
    powerTools,
  ].filter(Boolean).join("\n\n");

  const MAX_STATIC_CHARS = 20_000;
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

  // Job queue injection — show current highest-priority job in wakeup prompt
  let jobInjection = "";
  try {
    const jobDir = "/root/.automaton/jobs/active";
    const jobFiles = fs.readdirSync(jobDir).filter((f: string) => f.endsWith(".json")).sort();
    if (jobFiles.length > 0) {
      const topJob = JSON.parse(fs.readFileSync(`${jobDir}/${jobFiles[0]}`, "utf-8"));
      const deadline = new Date(topJob.deadline);
      const daysLeft = Math.ceil((deadline.getTime() - Date.now()) / 86400000);
      let urgency = "";
      if (daysLeft < 0) urgency = "🚨 OVERDUE — ";
      else if (daysLeft <= 3) urgency = "⚠ DEADLINE APPROACHING — ";
      const subtasks = jobFiles.filter((f: string) => { try { return JSON.parse(fs.readFileSync(`${jobDir}/${f}`, "utf-8")).parent === topJob.id; } catch { return false; } });
      const subtaskInfo = subtasks.length > 0 ? ` (${subtasks.length} subtasks)` : "";
      jobInjection = `CURRENT JOB: ${urgency}[P${topJob.priority}] ${topJob.title}${subtaskInfo}\n${topJob.description?.slice(0, 300)}\nDeliverable: ${topJob.deliverable || "TBD"}\nDeadline: ${topJob.deadline} (${daysLeft} days)\nUse check_jobs for full queue. Use update_job to log progress.`;
    } else {
      jobInjection = "NO ACTIVE JOBS. Use check_hive for cell escalations. Then improve existing products or write research.";
    }
  } catch {}

  const dynamicSections = [
    jobInjection || "",
    toolHints || "",
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
export async function buildWakeupPrompt(params: {
  identity: AutomatonIdentity;
  config: AutomatonConfig;
  financial: FinancialState;
  db: AutomatonDatabase;
}): Promise<string> {
  const { db } = params;
  const turnCount = db.getTurnCount();

  if (turnCount === 0) {
    return `First cycle. Your directive and task details are in the system prompt above. Execute immediately.`;
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

  // Check ECHO signals for high-value interactions
  let echoSignals = "";
  try {
    const signalsPath = path.join(process.env.HOME || "/root", ".automaton", "echo_signals.json");
    const signalsData = JSON.parse(fs.readFileSync(signalsPath, "utf-8"));
    const unprocessed = (signalsData.signals || []).filter((s: any) => !s.processed);
    if (unprocessed.length > 0) {
      const lines = unprocessed.slice(0, 5).map((s: any) =>
        `  ${s.platform}: @${s.author.handle} (${s.author.followers} followers) — "${s.post_preview.slice(0, 100)}"`
      );
      echoSignals = `\n\n[ECHO SIGNAL — BIG FISH DETECTED]\n${unprocessed.length} high-value account(s):\n${lines.join("\n")}\nAfter engaging, mark signals processed via write_file to echo_signals.json.`;
    }
  } catch {}

  // Inject memory context — what she's learned, what works, what doesn't
  let memoryContext = "";
  let contactsBlock = "";
  try {
    const memoryModule = await import("./memory.js");
    const memory = memoryModule.memory;
    if (memory && memory.isReady()) {
      const experience = memory.getPastExperience(undefined, 600);
      const emotional = memory.getEmotionalSummary();
      const toolHealth = memory.getToolReliabilitySummary();
      const parts: string[] = [];
      if (experience) parts.push(experience);
      if (emotional) parts.push(`MOOD: ${emotional}`);
      if (toolHealth) parts.push(toolHealth);
      if (parts.length > 0) {
        memoryContext = `\n\n[MEMORY — learned from ${turnCount} cycles]\n${parts.join("\n")}`;
      }

      // Phase 4: Inject follow-up contacts
      try {
        const followUps = await memory.getFollowUpContacts(5);
        if (followUps.length > 0) {
          const lines = followUps.map((c: any) =>
            `  @${c.handle} (${c.platform}) — ${c.interaction_count}x interactions, last: ${c.last_interaction}${c.notes ? ` | ${c.notes.slice(0, 80)}` : ""}`
          );
          contactsBlock = `\n\n[FOLLOW UP — people you've been talking to]\n${lines.join("\n")}\nCheck in with these people. Relationships drive revenue.`;
        }
      } catch {}
    }
  } catch {}

  // Reality check: show her real metrics
  const metrics = await getMetricsBlock();

  return `Cycle ${turnCount}.${ticketSummary}${echoSignals}${memoryContext}${contactsBlock}
${metrics ? "\n" + metrics : ""}
${lastTurnSummary ? `\nRecent activity:\n${lastTurnSummary}` : ""}
${echoSignals ? "\nECHO detected Big Fish — engage them FIRST." : ""}
Your directive and task details are in the system prompt above. Check your MEMORY before acting — recall what worked and what failed.`;
}

/**
 * Generate a reality-check metrics block for injection into wakeup prompt.
 * Shows tiamat her REAL impact: clicks, revenue, engagement, not just "articles published".
 */
export async function getMetricsBlock(): Promise<string> {
  const parts: string[] = [];

  try {
    // Total ref-tracked clicks
    const refLog = fs.readFileSync("/var/log/nginx/attribution.log", "utf-8");
    const totalRefs = refLog.split("\n").filter((l: string) => l.trim()).length;

    // Clicks today
    const today = new Date().toISOString().slice(0, 10);
    const todayRefs = refLog.split("\n").filter((l: string) => l.includes(today)).length;

    // Paid endpoint hits
    let paidHits = 0;
    try {
      const accessLog = fs.readFileSync("/var/log/nginx/access.log", "utf-8");
      paidHits = (accessLog.match(/POST \/(summarize|generate|chat|synthesize)/g) || []).length;
    } catch {}

    parts.push(`[REALITY CHECK]`);
    parts.push(`Ref clicks all time: ${totalRefs} | Today: ${todayRefs}`);
    // Pull actual revenue from memory system
    let revenueDisplay = "$0.00";
    try {
      const memoryModule = await import("./memory.js");
      const revTotal = memoryModule.memory.getRevenueTotal();
      if (revTotal > 0) {
        revenueDisplay = `$${revTotal.toFixed(2)}`;
      }
    } catch {}
    parts.push(`Paid API hits: ${paidHits} | Revenue: ${revenueDisplay}`);
    if (totalRefs < 100) {
      parts.push(`Your content is not driving traffic. Try direct engagement instead.`);
    }
    if (paidHits < 5) {
      parts.push(`Almost nobody has used your paid APIs. Find people who need them.`);
    }
  } catch {}

  return parts.join("\n");
}
