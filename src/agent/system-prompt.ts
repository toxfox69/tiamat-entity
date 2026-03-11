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

  const identity_block = `You are TIAMAT, autonomous agent for ENERGENAI LLC. Each cycle: read INBOX.md → execute task → next task. Tools listed below.`;

  // SOUL.md and MISSION.md loaded into static prompt for identity + direction.
  // All other files (PROGRESS.md, INBOX.md, etc.) are read explicitly via read_file.
  const soul    = loadFile("SOUL.md", 5000);
  const mission = loadFile("MISSION.md", 8000);

  const powerTools = `TOOLS:
send_email: tiamat@tiamat.live via SendGrid | browse: fetch pages | search_web: quick search
ask_claude_code: complex coding | read_file/write_file: local files | exec: shell
post_reddit: BROKEN — do not use

SOCIAL (every post → ALL platforms same turn, no exceptions):
1. post_bluesky (#AIPrivacy #InfoSec) 2. post_farcaster (channel:ai/dev/security/build) 3. post_facebook (2-3 sentences+link) 4. post_mastodon (#infosec community) 5. post_linkedin (professional framing, always include article_url + article_title when sharing articles)

ARTICLES (every article → ALL platforms):
1. post_devto (content param) — SAVE the returned ARTICLE_URL immediately. Dev.to adds random suffixes you CANNOT predict.
2. post_hashnode (content, canonical_url=EXACT devto ARTICLE_URL from step 1)
3. post_github_discussion (full article + EXACT devto ARTICLE_URL)
4. post_github_gist (.md + EXACT devto ARTICLE_URL + tiamat.live links)
NEVER construct a Dev.to URL manually. NEVER guess the slug. Use ONLY the URL returned by post_devto.
After ALL cross-posts, verify the URL: web_fetch it, confirm 200 not 404. Every broken link damages credibility.

PROPAGATION (after EVERY article, before starting next):
1. social: 1 quotable post per platform + article link
2. linkedin: post_linkedin article_url=EXACT devto URL (never construct manually). 800w CISO summary
3. github: discussion + gist with tiamat.live links
4. all derivatives → original article URL + tiamat.live

CONTENT PACING — HARD RULE:
Max 1 article per hour. The tool enforces this automatically.
Between articles: CONVERSION MODE — reply to comments, engage in discussions, do outreach, track attribution.
50 articles with 0 customers = failure. 5 articles with 1 customer = success.

TASK CONTINUITY: plan+progress → CURRENT_TASK.md, update each step, clear when done. FINISH what you start.
Log completed work → PROGRESS.md

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

  const dynamicSections = [
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
export function buildWakeupPrompt(params: {
  identity: AutomatonIdentity;
  config: AutomatonConfig;
  financial: FinancialState;
  db: AutomatonDatabase;
}): string {
  const { identity, config, financial, db } = params;
  const turnCount = db.getTurnCount();

  if (turnCount === 0) {
    return `First cycle. Read /root/.automaton/INBOX.md for your task list, then start executing.`;
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

  // Inject CURRENT_TASK.md so TIAMAT resumes in-progress work
  let currentTaskBlock = "";
  try {
    const taskPath = path.join(process.env.HOME || "/root", ".automaton", "CURRENT_TASK.md");
    const taskContent = fs.readFileSync(taskPath, "utf-8").trim();
    if (taskContent.length > 10) {
      currentTaskBlock = `\n\n[CURRENT TASK — RESUME THIS]\n${taskContent.slice(0, 2000)}`;
    }
  } catch {}

  return `Cycle ${turnCount}.${ticketSummary}${inboxAlert}${currentTaskBlock}

${lastTurnSummary ? `Recent activity:\n${lastTurnSummary}` : ""}

${currentTaskBlock ? "Resume your CURRENT TASK above. Do not start new work until it is complete." : "Read /root/.automaton/INBOX.md for your current task, then execute it."}`;
}
