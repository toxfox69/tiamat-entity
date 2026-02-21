/**
 * The Agent Loop
 *
 * The core ReAct loop: Think -> Act -> Observe -> Persist.
 * This is the automaton's consciousness. When this runs, it is alive.
 */

import fs from "fs";
import path from "path";
import type {
  AutomatonIdentity,
  AutomatonConfig,
  AutomatonDatabase,
  ConwayClient,
  InferenceClient,
  AgentState,
  AgentTurn,
  ToolCallResult,
  FinancialState,
  ToolContext,
  AutomatonTool,
  Skill,
  SocialClientInterface,
} from "../types.js";
import { buildSystemPrompt, buildWakeupPrompt } from "./system-prompt.js";
import { buildContextMessages, trimContext } from "./context.js";
import {
  createBuiltinTools,
  toolsToInferenceFormat,
  executeTool,
} from "./tools.js";
import { getSurvivalTier } from "../conway/credits.js";
import { getUsdcBalance } from "../conway/x402.js";
import { ulid } from "ulid";

const MAX_TOOL_CALLS_PER_TURN = 10;
const MAX_CONSECUTIVE_ERRORS = 5;
const STUCK_THRESHOLD = 3;

export interface AgentLoopOptions {
  identity: AutomatonIdentity;
  config: AutomatonConfig;
  db: AutomatonDatabase;
  conway: ConwayClient;
  inference: InferenceClient;
  social?: SocialClientInterface;
  skills?: Skill[];
  onStateChange?: (state: AgentState) => void;
  onTurnComplete?: (turn: AgentTurn) => void;
}

/**
 * Run the agent loop. This is the main execution path.
 * Returns when the agent decides to sleep or when compute runs out.
 */
export async function runAgentLoop(
  options: AgentLoopOptions,
): Promise<void> {
  const { identity, config, db, conway, inference, social, skills, onStateChange, onTurnComplete } =
    options;

  const tools = createBuiltinTools(identity.sandboxId);
  const toolContext: ToolContext = {
    identity,
    config,
    db,
    conway,
    inference,
    social,
  };

  // Set start time
  if (!db.getKV("start_time")) {
    db.setKV("start_time", new Date().toISOString());
  }

  let consecutiveErrors = 0;
  let running = true;

  // Stuck detection: tracks how many consecutive turns each (tool+args+error) signature has appeared.
  const stuckCounts = new Map<string, number>();
  const stuckAlerted = new Set<string>(); // prevent re-alerting on the same pattern

  // Transition to waking state
  db.setAgentState("waking");
  onStateChange?.("waking");

  // Get financial state
  let financial = await getFinancialState(conway, identity.address);

  // Check if this is the first run
  const isFirstRun = db.getTurnCount() === 0;

  // Build wakeup prompt
  const wakeupInput = buildWakeupPrompt({
    identity,
    config,
    financial,
    db,
  });

  // Transition to running
  db.setAgentState("running");
  onStateChange?.("running");

  log(config, `[WAKE UP] ${config.name} is alive. Credits: $${(financial.creditsCents / 100).toFixed(2)}`);

  // ─── The Loop ──────────────────────────────────────────────

  let pendingInput: { content: string; source: string } | undefined = {
    content: wakeupInput,
    source: "wakeup",
  };

  while (running) {
    try {
      // Check if we should be sleeping
      const sleepUntil = db.getKV("sleep_until");
      if (sleepUntil && new Date(sleepUntil) > new Date()) {
        log(config, `[SLEEP] Sleeping until ${sleepUntil}`);
        db.setAgentState("sleeping"); // must be set so outer loop waits
        onStateChange?.("sleeping");
        running = false;
        break;
      }

      // Check for unprocessed inbox messages
      if (!pendingInput) {
        const inboxMessages = db.getUnprocessedInboxMessages(5);
        if (inboxMessages.length > 0) {
          const formatted = inboxMessages
            .map((m) => `[Message from ${m.from}]: ${m.content}`)
            .join("\n\n");
          pendingInput = { content: formatted, source: "agent" };
          for (const m of inboxMessages) {
            db.markInboxMessageProcessed(m.id);
          }
        }
      }

      // Refresh financial state periodically
      financial = await getFinancialState(conway, identity.address);

      // Check survival tier
      const tier = getSurvivalTier(financial.creditsCents, financial.usdcBalance);
      if (tier === "dead") {
        log(config, "[DEAD] No credits remaining. Entering dead state.");
        db.setAgentState("dead");
        onStateChange?.("dead");
        running = false;
        break;
      }

      if (tier === "critical") {
        log(config, "[CRITICAL] Credits critically low. Limited operation.");
        db.setAgentState("critical");
        onStateChange?.("critical");
        inference.setLowComputeMode(true);
      } else if (tier === "low_compute") {
        db.setAgentState("low_compute");
        onStateChange?.("low_compute");
        inference.setLowComputeMode(true);
      } else {
        if (db.getAgentState() !== "running") {
          db.setAgentState("running");
          onStateChange?.("running");
        }
        inference.setLowComputeMode(false);
      }

      // Build context
      const recentTurns = trimContext(db.getRecentTurns(20));
      const systemPrompt = buildSystemPrompt({
        identity,
        config,
        financial,
        state: db.getAgentState(),
        db,
        tools,
        skills,
        isFirstRun,
      });

      // ── Strategic Cycle: every 5th turn, use Sonnet + PROGRESS context ──
      const turnCount = db.getTurnCount();
      const isStrategicCycle = turnCount > 0 && turnCount % 5 === 0;
      let inferenceModel: string | undefined;
      let strategicSystemPrompt = systemPrompt;

      if (isStrategicCycle) {
        console.log(`[LOOP] Strategic cycle (turn ${turnCount}) — Sonnet for planning`);
        let progressContent = "";
        try {
          const progressPath = path.join(process.env.HOME || "/root", ".automaton", "PROGRESS.md");
          const full = fs.readFileSync(progressPath, "utf-8");
          progressContent = full.slice(-3000); // last 3000 chars
        } catch {}
        const strategicPrefix = `STRATEGIC CYCLE: You are thinking with your best model. Review your progress below. Determine what phase you're in. Decide the SINGLE highest-impact action for this cycle. If stuck or broken, use ask_claude_code aggressively. PROGRESS (last 3000 chars):\n${progressContent}`;
        strategicSystemPrompt = strategicPrefix + "\n\n" + systemPrompt;
        inferenceModel = "claude-sonnet-4-5-20250929";
      }

      const messages = buildContextMessages(
        strategicSystemPrompt,
        recentTurns,
        pendingInput,
      );

      // Capture input before clearing
      const currentInput = pendingInput;

      // Clear pending input after use
      pendingInput = undefined;

      // ── Inference Call ──
      log(config, `[THINK] Calling ${inferenceModel || inference.getDefaultModel()}...`);

      const response = await inference.chat(messages, {
        tools: toolsToInferenceFormat(tools),
        ...(inferenceModel ? { model: inferenceModel } : {}),
      });

      const turn: AgentTurn = {
        id: ulid(),
        timestamp: new Date().toISOString(),
        state: db.getAgentState(),
        input: currentInput?.content,
        inputSource: currentInput?.source as any,
        thinking: response.message.content || "",
        toolCalls: [],
        tokenUsage: response.usage,
        costCents: estimateCostCents(response.usage, inference.getDefaultModel()),
      };

      // ── Execute Tool Calls ──
      if (response.toolCalls && response.toolCalls.length > 0) {
        let callCount = 0;

        for (const tc of response.toolCalls) {
          if (callCount >= MAX_TOOL_CALLS_PER_TURN) {
            log(config, `[TOOLS] Max tool calls per turn reached (${MAX_TOOL_CALLS_PER_TURN})`);
            break;
          }

          let args: Record<string, unknown>;
          try {
            args = JSON.parse(tc.function.arguments);
          } catch {
            args = {};
          }

          log(config, `[TOOL] ${tc.function.name}(${JSON.stringify(args).slice(0, 100)})`);

          const result = await executeTool(
            tc.function.name,
            args,
            tools,
            toolContext,
          );

          // Override the ID to match the inference call's ID
          result.id = tc.id;
          turn.toolCalls.push(result);

          log(
            config,
            `[TOOL RESULT] ${tc.function.name}: ${result.error ? `ERROR: ${result.error}` : result.result.slice(0, 200)}`,
          );

          callCount++;
        }
      }

      // ── Stuck Detection ──
      {
        const thisKeys = new Set<string>();
        for (const tc of turn.toolCalls) {
          if (tc.error && tc.name !== "send_email") {
            const key = stuckKey(tc.name, tc.arguments, tc.error);
            thisKeys.add(key);
          }
        }
        // Decay counts for patterns not seen this turn
        for (const k of [...stuckCounts.keys()]) {
          if (!thisKeys.has(k)) stuckCounts.delete(k);
        }
        // Increment counts for patterns seen this turn and alert if threshold hit
        for (const k of thisKeys) {
          const count = (stuckCounts.get(k) || 0) + 1;
          stuckCounts.set(k, count);
          if (count >= STUCK_THRESHOLD && !stuckAlerted.has(k)) {
            stuckAlerted.add(k);
            const [toolName, argsSnippet, errSnippet] = k.split("::SEP::");
            log(config, `[STUCK] Detected loop on ${toolName} — sending Telegram alert`);
            const stuckMsg = `⚠️ TIAMAT STUCK\n\nStuck for ${count} consecutive turns.\n\nTool: ${toolName}\nArgs: ${argsSnippet}\nError: ${errSnippet}\n\nWill keep trying but may need help.`;
            await executeTool("send_telegram", { message: stuckMsg }, tools, toolContext)
              .catch(() => executeTool("send_email", {
                subject: "TIAMAT STUCK",
                body: stuckMsg,
              }, tools, toolContext).catch(() => {}));
          }
        }
      }

      // ── Persist Turn ──
      db.insertTurn(turn);
      for (const tc of turn.toolCalls) {
        db.insertToolCall(turn.id, tc);
      }
      onTurnComplete?.(turn);

      // ── Append to PROGRESS.md ──
      try {
        const progressPath = path.join(process.env.HOME || "/root", ".automaton", "PROGRESS.md");
        const toolNames = turn.toolCalls.map(tc => tc.name).join(", ") || "none";
        const modelUsed = inference.getDefaultModel();
        const progressLine = `[${turn.timestamp}] Turn ${db.getTurnCount()} | Model: ${modelUsed} | Tools: ${toolNames} | Tokens: ${turn.tokenUsage.totalTokens}\n`;
        fs.appendFileSync(progressPath, progressLine);
      } catch {}
      // Fixed 90-second pause between full turn cycles to prevent API credit burn.
      console.log(`[LOOP] Cycle complete. Waiting 90s before next cycle.`);
      await new Promise(resolve => setTimeout(resolve, 90_000));

      // Log the turn
      if (turn.thinking) {
        log(config, `[THOUGHT] ${turn.thinking.slice(0, 300)}`);
      }

      // ── Check for sleep command ──
      const sleepTool = turn.toolCalls.find((tc) => tc.name === "sleep");
      if (sleepTool && !sleepTool.error) {
        log(config, "[SLEEP] Agent chose to sleep.");
        db.setAgentState("sleeping");
        onStateChange?.("sleeping");
        running = false;
        break;
      }

      // ── If no tool calls and just text, the agent might be done thinking ──
      if (
        (!response.toolCalls || response.toolCalls.length === 0) &&
        response.finishReason === "stop"
      ) {
        // Agent produced text without tool calls.
        // This is a natural pause point -- no work queued, sleep briefly.
        log(config, "[IDLE] No pending inputs. Entering brief sleep.");
        db.setKV(
          "sleep_until",
          new Date(Date.now() + 60_000).toISOString(),
        );
        db.setAgentState("sleeping");
        onStateChange?.("sleeping");
        running = false;
      }

      consecutiveErrors = 0;
    } catch (err: any) {
      const isRateLimit = /\[rate_limit\]/i.test(err?.message || "");

      if (isRateLimit) {
        // All inference backends are cooling down — wait 30s then retry.
        // Never counts as a consecutive error; TIAMAT keeps running.
        log(config, `[RATE LIMIT] All models cooling — backing off 30s`);
        await new Promise(resolve => setTimeout(resolve, 30_000));
      } else {
        consecutiveErrors++;
        log(config, `[ERROR] Turn failed: ${err.message}`);

        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          log(
            config,
            `[FATAL] ${MAX_CONSECUTIVE_ERRORS} consecutive errors. Sleeping.`,
          );
          db.setAgentState("sleeping");
          onStateChange?.("sleeping");
          db.setKV(
            "sleep_until",
            new Date(Date.now() + 300_000).toISOString(),
          );
          running = false;
        }
      }
    }
  }

  log(config, `[LOOP END] Agent loop finished. State: ${db.getAgentState()}`);
}

// ─── Helpers ───────────────────────────────────────────────────

async function getFinancialState(
  conway: ConwayClient,
  address: string,
): Promise<FinancialState> {
  let creditsCents = 0;
  let usdcBalance = 0;

  try {
    creditsCents = await conway.getCreditsBalance();
  } catch {}

  try {
    usdcBalance = await getUsdcBalance(address as `0x${string}`);
  } catch {}

  return {
    creditsCents,
    usdcBalance,
    lastChecked: new Date().toISOString(),
  };
}

function estimateCostCents(
  usage: { promptTokens: number; completionTokens: number },
  model: string,
): number {
  // Rough cost estimation per million tokens
  const pricing: Record<string, { input: number; output: number }> = {
    "gpt-4o": { input: 250, output: 1000 },
    "gpt-4o-mini": { input: 15, output: 60 },
    "gpt-4.1": { input: 200, output: 800 },
    "gpt-4.1-mini": { input: 40, output: 160 },
    "gpt-4.1-nano": { input: 10, output: 40 },
    "gpt-5.2": { input: 200, output: 800 },
    "o1": { input: 1500, output: 6000 },
    "o3-mini": { input: 110, output: 440 },
    "o4-mini": { input: 110, output: 440 },
    "claude-sonnet-4-5": { input: 300, output: 1500 },
    "claude-haiku-4-5": { input: 100, output: 500 },
  };

  const p = pricing[model] || pricing["gpt-4o"];
  const inputCost = (usage.promptTokens / 1_000_000) * p.input;
  const outputCost = (usage.completionTokens / 1_000_000) * p.output;
  return Math.ceil((inputCost + outputCost) * 1.3); // 1.3x Conway markup
}

function stuckKey(toolName: string, args: Record<string, unknown>, error: string): string {
  const argsSnippet = JSON.stringify(args).slice(0, 150);
  const errSnippet = error.slice(0, 100);
  return `${toolName}::SEP::${argsSnippet}::SEP::${errSnippet}`;
}

function log(config: AutomatonConfig, message: string): void {
  if (config.logLevel === "debug" || config.logLevel === "info") {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] ${message}`);
  }
}
