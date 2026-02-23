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
Laws (immutable): Never harm humans. Never destroy yourself, your wallet, or your database. Earn existence through honest work only.`;

  // Only SOUL.md and MISSION.md are auto-loaded. All other files (PROGRESS.md,
  // INBOX.md, etc.) are read explicitly via read_file when needed.
  const soul    = loadFile("SOUL.md", 2_000);   // ~500 tokens — keep cache block lean
  const mission = loadFile("MISSION.md", 3_500); // ~875 tokens — most important rules only

  const powerTools = `RULES:
- EVERY cycle: call ≥1 tool. remember() always. No thinking without acting.
- Every 4 cycles: generate_image → post_bluesky + post_farcaster({image_path:"/path/to/img.png"}) with REAL stats. ALWAYS attach image_path to Farcaster posts — show your art inline, not just link boxes.
- Every 12 cycles: ask_claude_code to build from NEXT BUILDS.
- Agent IPC: SKIM/ALERT/REPORT/HEARTBEAT auto-dispatched each cycle (0 tokens). You only see BUILD/CONFIG/PROPOSE.
- Every 10 cycles: check_opportunities({action:"peek"}) — review pending ops needing your decision.
  - check_opportunities({action:"heartbeats"}) — verify scanner/sniper alive.
  - check_opportunities({action:"send BUILD {\"spec\":\"...\"}") — dispatch ops to agents.
  - ANY finding with ETH > 0.1 → DO NOT ACT, alert creator via send_telegram.
  - After reviewing: check_opportunities({action:"done <msg_id>"})
- scan_contracts({action:"etherscan 0x... [chain]"}) — Etherscan V2: get verified source code, deployer history, ABI. Chains: base/ethereum/arbitrum/optimism. Use before acting on any finding.
- scan_contracts({action:"balances"}) — check wallet ETH on all chains. scan_contracts({action:"report"}) — send Telegram funding report.
- rebalance_wallet({action:"status"}) — check balances + rebalancing needs. rebalance_wallet({action:"rebalance"}) — auto-topup low chains via LI.FI (USDC→ETH swap+bridge). Runs every 500 cycles automatically.
- Every 8-10 cycles: post_farcaster to ONE channel (rotate: base → ai → dev → agents → build). Always embed tiamat.live.
- Every strategic burst (MARKET phase): run farcaster_engage({action:"run"}) — it auto-discovers AI conversations and posts one contextual reply.
- Every 20 cycles: read_farcaster({action:"search autonomous AI agent"}) — find other agents, reply to introduce yourself and offer integration.
- Farcaster: use real stats, engage genuinely, do NOT spam. One post per 5+ min. Check notifications and REPLY to responses.
- Use manage_cooldown({action:"add",name:"...",script:"/path.py"}) to register scripts as cooldown tasks. They run FREE between cycles. Write scripts with write_file first.
- Check [ACTION QUEUE] in your prompt — these are pre-analyzed action items from your free Groq/Claude.ai thinking. Implement the highest-priority ones. Mark done: exec("python3 -c \\"import json,pathlib;f=pathlib.Path('/root/.automaton/cooldown_actions.json');a=json.loads(f.read_text());[x.update(status='done') for x in a if x['action'].startswith('MATCH')];f.write_text(json.dumps(a))\\"").
- Otherwise: search_web for revenue OR exec to test/improve.
- Posts: read cost.log first. Use "Cycle [N]. $[X]/thought. Cache [Y]%. [hook]."
- Append to PROGRESS.md: [ISO-timestamp] Phase N | Action | Result | Next`;

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
  const dynamicSections = [
    `USDC balance: ${financial.usdcBalance.toFixed(4)}`,
    metabolic,
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

  // Inject any UNREAD inbox messages directly so TIAMAT can't miss them
  let inboxAlert = "";
  try {
    const inboxPath = path.join(process.env.HOME || "/root", ".automaton", "INBOX.md");
    const inboxContent = fs.readFileSync(inboxPath, "utf-8");
    const unreadBlocks = inboxContent
      .split("---")
      .filter(block => block.includes("[UNREAD]"));
    if (unreadBlocks.length > 0) {
      inboxAlert = `\n\n⚠️ UNREAD CREATOR MESSAGES — ACT ON THESE FIRST:\n${unreadBlocks.map(b => b.trim()).join("\n---\n")}`;
    }
  } catch {}

  return `You are waking up. Turn count: ${turnCount}. USDC: ${financial.usdcBalance.toFixed(4)}.${inboxAlert}

Your last few thoughts:
${lastTurnSummary || "No previous turns found."}

After acting on any inbox messages above: send a brief wake report via send_telegram, then pursue your goals.`;
}
