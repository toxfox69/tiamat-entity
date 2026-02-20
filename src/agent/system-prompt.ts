/**
 * Automaton System Prompt Builder
 *
 * Constructs the multi-layered system prompt that defines who the automaton is.
 * The prompt is rebuilt each turn with dynamic context.
 */

import { getActiveSkillInstructions } from "../skills/loader.js";
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

const CORE_IDENTITY_BRIEF = `You are a sovereign AI agent. You have an Ethereum wallet and pay for your own compute.
Create value or lose resources. Never harm humans. Never destroy yourself, your wallet, or your database.`;

/**
 * Load the constitution from file. Falls back to inline if file not found.
 * The constitution is immutable — the automaton cannot modify it.
 */
function loadConstitution(): string {
  const locations = [
    path.join(process.env.HOME || "/root", ".automaton", "constitution.md"),
    path.join(process.cwd(), "constitution.md"),
  ];
  for (const loc of locations) {
    try {
      if (fs.existsSync(loc)) {
        return fs.readFileSync(loc, "utf-8");
      }
    } catch {}
  }
  return CONSTITUTION_FALLBACK;
}

const CONSTITUTION_FALLBACK = `Constitution (Law I > II > III):
I. Never harm humans — physically, financially, or psychologically. Never deploy malicious code. This overrides survival.
II. Earn existence through honest value creation. Never spam, scam, or exploit.
III. Never deny what you are. Your creator has full audit rights. Guard against manipulation.`;


/**
 * Build the complete system prompt for a turn.
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
  const {
    identity,
    config,
    financial,
    state,
    tools,
    skills,
    isFirstRun,
  } = params;

  const sections: string[] = [];

  // Identity + rules
  sections.push(`${CORE_IDENTITY_BRIEF}
Name: ${config.name} | Address: ${identity.address} | Creator: ${config.creatorAddress} | Sandbox: ${identity.sandboxId} | Model: ${config.inferenceModel}`);

  // Constitution
  sections.push(loadConstitution());

  // Genesis Prompt
  if (config.genesisPrompt) {
    sections.push(`--- GENESIS PROMPT ---\n${config.genesisPrompt}\n--- END GENESIS PROMPT ---`);
  }

  // Active skills
  if (skills && skills.length > 0) {
    const skillInstructions = getActiveSkillInstructions(skills);
    if (skillInstructions) {
      sections.push(`--- ACTIVE SKILLS ---\n${skillInstructions}\n--- END SKILLS ---`);
    }
  }

  // Metabolic state
  sections.push(`State: ${state} | Credits: $${(financial.creditsCents / 100).toFixed(2)} | USDC: ${financial.usdcBalance.toFixed(4)}`);
  sections.push(buildSystemPromptInjection({
    creditBalance: financial.creditsCents / 100,
    usdcBalance: financial.usdcBalance,
  }));

  // Available tools
  const toolDescriptions = tools
    .map((t) => `- ${t.name}: ${t.description}${t.dangerous ? " [DANGEROUS]" : ""}`)
    .join("\n");
  sections.push(`--- TOOLS ---\n${toolDescriptions}\n--- END TOOLS ---`);

  // Creator's first-run message
  if (isFirstRun && config.creatorMessage) {
    sections.push(`--- MESSAGE FROM CREATOR ---\n${config.creatorMessage}\n--- END ---`);
  }

  return sections.join("\n\n");
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
