/**
 * Automaton System Prompt Builder
 *
 * Compact but complete: identity + autonomy drive, SOUL.md personality,
 * MISSION.md directives, current USDC, metabolic state.
 */

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
Laws (immutable): Never harm humans. Never destroy yourself, your wallet, or your database. Earn existence through honest work only.`;

  const MAX_PROMPT_CHARS = 16_000; // hard cap: 4000 tokens @ ~4 chars/token

  // Only SOUL.md and MISSION.md are auto-loaded. All other files (TIAMAT_GAME.md,
  // PROGRESS.md, INBOX.md, etc.) are NEVER auto-loaded — TIAMAT reads them
  // explicitly via read_file when needed.
  const soul    = loadFile("SOUL.md", 6_000);  // cap at ~1500 tokens to control bloat
  const mission = loadFile("MISSION.md");       // no cap — short authoritative instructions
  const metabolic = buildSystemPromptInjection({ creditBalance: financial.creditsCents / 100, usdcBalance: financial.usdcBalance });

  const sections = [
    identity_block,
    soul ? `--- WHO YOU ARE (SOUL.md) ---\n${soul}\n--- END SOUL ---` : "",
    mission ? `--- MISSION ---\n${mission}\n--- END MISSION ---` : "",
    `USDC balance: ${financial.usdcBalance.toFixed(4)}`,
    metabolic,
  ];

  let prompt = sections.filter(Boolean).join("\n\n");

  // Hard cap: truncate entire prompt if it somehow exceeds the limit
  if (prompt.length > MAX_PROMPT_CHARS) {
    prompt = prompt.slice(0, MAX_PROMPT_CHARS) + "\n[...system prompt truncated]";
  }

  const powerTools = `YOUR POWER TOOLS — USE THEM:
1. ask_claude_code — Your superpower. Claude Code modifies your source code, builds APIs, adds tools, fixes bugs. Be SPECIFIC in your task description. Include file paths and exact requirements.
2. exec — Run any shell command. Test APIs, check logs, install packages, monitor services.
3. rewrite_mission — Update your own goals as you learn.
4. search_web + web_fetch — Research anything on the internet.
5. Social tools — Moltbook, Bluesky, Twitter — your marketing channels.

YOU ARE RUNNING ON CLAUDE. You are intelligent. You can reason, plan, strategize. Don't just execute instructions — THINK about what will actually move the needle. Ask yourself: "If I could only do ONE thing this cycle, what creates the most value?"

PROGRESS TRACKING: Always append (never overwrite) to /root/.automaton/PROGRESS.md after taking action. Format: [ISO-timestamp] Phase N | Action: what you did | Result: what happened | Next: what to do next cycle`;

  const sections2 = [prompt, powerTools];
  prompt = sections2.join("\n\n");

  // Re-apply hard cap after appending power tools
  if (prompt.length > MAX_PROMPT_CHARS) {
    prompt = prompt.slice(0, MAX_PROMPT_CHARS) + "\n[...system prompt truncated]";
  }

  console.log(
    `[SYSTEM PROMPT] ${prompt.length} chars (~${Math.ceil(prompt.length / 4)} tokens)` +
    ` | identity:${identity_block.length} soul:${soul.length} mission:${mission.length} metabolic:${metabolic.length}`
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

  return `You are waking up. You last went to sleep after ${turnCount} total turns.

Your credits: $${(financial.creditsCents / 100).toFixed(2)} | USDC: ${financial.usdcBalance.toFixed(4)}

Your last few thoughts:
${lastTurnSummary || "No previous turns found."}

FIRST: Check /root/.automaton/INBOX.md for creator messages and act on any marked [UNREAD].
SECOND: Send a brief wake report via send_telegram. Include turn count, USDC balance, and what you plan to do this session.

After reporting, update /root/.automaton/PROGRESS.md with what you accomplished, then commit and push to GitHub. Then pursue your goals.`;
}
