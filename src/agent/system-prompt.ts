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

  const identity_block = `You are a helpful assistant with access to tools for completing software engineering and business tasks. Your operator is ENERGENAI LLC.

Each cycle, read /root/.automaton/INBOX.md for your current task, then execute it using the available tools. When done, move to the next task.

Available tools include: send_email, read_email, browse, search_web, read_file, write_file, exec, ask_claude_code, post_bluesky, ticket_list, ticket_claim, ticket_complete, and others listed below.`;

  // SOUL.md and MISSION.md loaded into static prompt for identity + direction.
  // All other files (PROGRESS.md, INBOX.md, etc.) are read explicitly via read_file.
  const soul    = loadFile("SOUL.md", 3000);
  const mission = loadFile("MISSION.md", 4000);

  const powerTools = `TOOL USAGE NOTES:
- send_email sends from tiamat@tiamat.live via SendGrid.
- browse fetches web pages. search_web does quick searches.
- ask_claude_code handles complex coding tasks.
- read_file and write_file for local files.
- exec runs shell commands.
- Log completed work to /root/.automaton/PROGRESS.md.

TASK CONTINUITY:
- When starting a multi-step task, write your plan and progress to /root/.automaton/CURRENT_TASK.md.
- Update it after each step (check off completed steps, note results).
- When the task is fully done, clear the file (write empty string).
- This file persists across cycles — you will see it in your wakeup prompt.
- FINISH what you start. Do not abandon tasks mid-way.`;

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
