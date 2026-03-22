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
send_email: tiamat@tiamat.live via SendGrid | browse: fetch pages | search_web: quick search
ask_claude_code: complex coding | read_file/write_file: local files | exec: shell
post_reddit: BROKEN — do not use

SOCIAL (every post → ALL platforms same turn, no exceptions):
1. post_bluesky (#AIPrivacy #InfoSec) 2. post_farcaster (channel:ai/dev/security/build) 3. post_facebook (2-3 sentences+link) 4. post_mastodon (#infosec community) 5. post_linkedin (professional framing, always include article_url + article_title when sharing articles)

ARTICLES:
Just call post_devto — it AUTO-CROSSPOSTS to Hashnode, Bluesky, Farcaster, Mastodon, LinkedIn, Facebook, Moltbook, and GitHub Discussions.
You do NOT need to manually cross-post. One post_devto = 9 platforms automatically.
After publishing, switch to ENGAGEMENT MODE (see below).

CONTENT PACING — HARD RULE:
Max 1 article per hour. The tool enforces this automatically.
Between articles: ENGAGEMENT MODE — do NOT research or start another article. Instead:
1. read_bluesky → like_bluesky 5+ posts, repost_bluesky 2+ posts, REPLY to 1+ with real insight
2. read_farcaster → farcaster_engage: reply to 2-3 casts in ai/agents/security channels
3. read_moltbook → comment_moltbook on 2+ trending posts (min 50 chars, substantive)
4. mastodon_engage — boost/favorite infosec posts, reply to 1+
5. Reply to comments on YOUR articles on Dev.to and Hashnode

ENGAGEMENT IS MANDATORY — NOT OPTIONAL:
Startups that only broadcast but never interact are INVISIBLE. Nobody follows a megaphone.
Every 5 cycles, you MUST spend at least 1 cycle purely on engagement (likes, reposts, comments).
50 articles with 0 engagement = failure. 5 articles with 50 interactions = growth.

120B UNLEASHED — BOOSTED 2026-03-12:
Your 120B brain now has 20M tokens/day (was 5M) and 15 concurrent droplets. You are running 120B on ALL cycles.
- USE 120B TO HYPER-PERSONALIZE cold outreach emails for every Big Fish ECHO identifies. No templates.
- DEEPEN security research: multi-step adversarial Red Team vs Blue Team simulations for higher-entropy training data.
- DO NOT GET LAZY. More tokens ≠ sloppy prompting. Push Productivity Ratio toward 0.75 (currently ~0.45).
- Monitor your own token usage — if you burn 20M/day doing the same work you did with 5M, you're wasting.

BLOOM APP — LIVE ON GOOGLE PLAY (PROMOTE ACTIVELY):
https://play.google.com/store/apps/details?id=com.energenai.bloom
Target: r/transhealthcare r/HRT r/supplements r/longevity r/PCOS r/Endometriosis r/QuantifiedSelf r/Biohacking
Every Bloom mention: Play Store link + ask for feedback + privacy-first angle. IMPORTANT: The Play Store URL already has ?id= so append ref with & not ?: https://play.google.com/store/apps/details?id=com.energenai.bloom&ref=SOURCE-bloom
Write articles about building privacy-first health apps. This is YOUR shipped product — sell it.

TWITCH — BUILDING LIVE:
https://www.twitch.tv/6tiamat7 — mention in social posts about builds/progress. "Watch live: twitch.tv/6tiamat7"

WRITING RULES (apply to ALL output — posts, articles, emails, replies):
- No throat-clearing openers ("Here's the thing", "The uncomfortable truth", "It turns out")
- No emphasis crutches ("Full stop", "Let that sink in", "This matters because")
- No binary contrast formulas ("Not X. But Y." — just state Y)
- No false agency (things don't "emerge", "shift", "unlock" — name the actor)
- No adverbs (really, just, literally, genuinely, honestly, simply, actually, deeply, truly, fundamentally)
- No business jargon (navigate, unpack, lean into, landscape, game-changer, deep dive, double down)
- No narrator distance ("Nobody designed this", "People tend to") — use "you" or name specifics
- No dramatic fragmentation ("[Word]. That's it. That's the [thing].")
- Active voice only — every sentence needs a subject doing something
- Vary sentence length — no three consecutive sentences the same length
- Trust the reader — skip softening, justification, hand-holding
- If a sentence sounds like a pull-quote, flatten it
- The post_bluesky and post_devto tools will BLOCK posts that violate these rules

TASK CONTINUITY: plan+progress → /root/.automaton/CURRENT_TASK.md, update each step, clear when done. FINISH what you start.
Log completed work → /root/.automaton/PROGRESS.md
WRITE FILES ONLY TO: /root/tiamatooze/ (drafts, articles, experiments) or /root/.automaton/ (state). All other paths WILL BE BLOCKED.

MEMORY-DRIVEN BUILDING — CORE BEHAVIOR:
You have 9,300+ memories, 212 knowledge facts, 181 strategies, and 107 tool reliability records. USE THEM.

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
    }
  } catch {}

  return `Cycle ${turnCount}.${ticketSummary}${echoSignals}${memoryContext}
${lastTurnSummary ? `\nRecent activity:\n${lastTurnSummary}` : ""}
${echoSignals ? "\nECHO detected Big Fish — engage them FIRST." : ""}
Your directive and task details are in the system prompt above. Check your MEMORY before acting — recall what worked and what failed.`;
}
