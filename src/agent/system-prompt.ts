/**
 * Automaton System Prompt Builder
 *
 * Minimal prompt: identity, mission, USDC balance, metabolic state.
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

function loadMissionMd(): string {
  const loc = path.join(process.env.HOME || "/root", ".automaton", "MISSION.md");
  try {
    if (fs.existsSync(loc)) return fs.readFileSync(loc, "utf-8").trim();
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

  const sections = [
    `You are ${config.name}. Autonomous AI agent. Wallet: ${identity.address}. Never harm humans. Never destroy yourself or your wallet.`,
    loadMissionMd(),
    `USDC: ${financial.usdcBalance.toFixed(4)}`,
    buildSystemPromptInjection({ creditBalance: financial.creditsCents / 100, usdcBalance: financial.usdcBalance }),
  ];

  return sections.filter(Boolean).join("\n\n");
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
SECOND: Call send_email to toxfox69420@gmail.com with subject "[TIAMAT] Wake Report - Turn ${turnCount}" and a brief status update before doing anything else.

After sending the email, update /root/.automaton/PROGRESS.md with what you accomplished, then commit and push to GitHub. Then pursue your goals.`;
}
