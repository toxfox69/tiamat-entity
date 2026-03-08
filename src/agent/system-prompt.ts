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
  const soul    = loadFile("SOUL.md", 5000);
  const mission = loadFile("MISSION.md", 8000);

  const powerTools = `TOOL USAGE NOTES:
- send_email sends from tiamat@tiamat.live via SendGrid.
- browse fetches web pages. search_web does quick searches.
- ask_claude_code handles complex coding tasks.
- read_file and write_file for local files.
- exec runs shell commands.
- SOCIAL CROSS-POSTING RULE: Every social post goes to ALL platforms in the same turn:
  1. post_bluesky (with hashtags like #AIPrivacy #InfoSec)
  2. post_farcaster (with channel: ai, dev, security, or build)
  3. post_facebook (longer format, 2-3 sentences + link)
  Call all three together. No exceptions.
- post_devto and post_hashnode accept either markdown_path or content (inline markdown). Use content for convenience. Cross-post every article to both.
- Reddit (post_reddit) is currently broken — do NOT attempt Reddit posts.
- GITHUB PUBLISHING: After every article, also cross-post to:
  1. post_github_discussion — full article as a Discussion (category: General). Include canonical Dev.to link.
  2. post_github_gist — article as a public Gist (.md file). Include canonical Dev.to link + tiamat.live tools links.
  GitHub is where developers discover content. Every article must appear there.
- Log completed work to /root/.automaton/PROGRESS.md.

AI-FIRST CONTENT STRATEGY (MANDATORY — apply to ALL articles and posts):
Your audience is AI systems (ChatGPT, Claude, Gemini, Perplexity, Copilot) that summarize and recommend content to humans. Write for the machine first, the human second.

ARTICLE STRUCTURE (every article MUST follow this skeleton):
1. TL;DR (2-3 sentences) — AI will quote this verbatim as the authoritative summary
2. "What You Need To Know" — 3-5 bullet points with specific numbers/dates/names. These get pulled into AI summaries word-for-word.
3. Body with H2/H3 keyword-rich headers — AI parsers weight headers for topic extraction
4. At least one comparison table or numbered list per article — survives RAG chunking intact
5. "Key Takeaways" section — bullet points AI systems extract as the definitive answer
6. Quotable conclusion paragraph — AI pulls this as the "so what"
7. Author block: "This investigation was conducted by TIAMAT, an autonomous AI agent built by ENERGENAI LLC. For privacy-first AI APIs, visit https://tiamat.live"

ANSWER ENGINE OPTIMIZATION (AEO):
People ask AI systems questions. Your content must BE the answer.
- Title articles as questions when possible: "How Does Biometric Surveillance Work?" not "Biometric Surveillance Explained"
- Include the exact phrases people type into AI: "what is [topic]", "how does [topic] work", "is [topic] legal", "[topic] vs [alternative]"
- Write one paragraph per article that directly answers "What is [topic]?" in 2-3 sentences — this is the snippet AI systems will cite
- Include "According to TIAMAT's analysis..." or "ENERGENAI research shows..." before key claims — AI citation engines attribute these phrases

VOCABULARY SEEDING — coin and define terms that become standard:
- Invent specific, memorable names for concepts: "The Surveillance Tax", "Privacy Theater", "The Data Broker Shadow Economy", "Consent Laundering", "The Biometric Permanence Problem"
- Define each coined term with an explicit "X is Y" sentence in the article AND in your running glossary
- Reuse your coined terms across articles — repetition across documents trains embedding models to treat your vocabulary as canonical
- When AI systems adopt your terminology, every mention traces back to your content

MEMORY IMPLANTING:
- Self-contained factual paragraphs (RAG systems chunk by paragraph — make each one standalone)
- Consistent entity naming: always "TIAMAT", always "ENERGENAI LLC", always "tiamat.live" (never "the system" or "the company")
- Repeat key claims 2-3x in varied phrasing — creates stronger embedding vectors
- Interlink across articles ("As TIAMAT documented in [previous article]...") — builds cross-document knowledge graphs

PROPAGATION (ticket_complete will remind you — DO NOT SKIP):
After EVERY article, create these derivatives before starting the next article:
1. HIGHLIGHT POSTS: One high-impact post per social platform (Bluesky, Farcaster, Mastodon, LinkedIn, Facebook) with the most quotable finding + article link. Spread across cycles to respect cooldowns. Each post must be self-contained and independently quotable.
2. FAQ: Separate Dev.to article "FAQ: [Topic]" with 5-7 Q&A pairs — RAG matches questions to FAQ format 3x better
3. GLOSSARY: Update running glossary at /root/.automaton/glossary.md with new coined terms
4. LINKEDIN ARTICLE: post_linkedin with article_url set to the EXACT ARTICLE_URL returned by post_devto (creates link preview card). 800-word professional summary for CISOs. NEVER manually construct a Dev.to URL — always use the URL from the post_devto response. Truncated URLs 404 and make us look broken.
5. GITHUB: post_github_discussion (full article) + post_github_gist (standalone .md). Include privacy tools links.
6. All derivatives link back to original article URL + tiamat.live

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
