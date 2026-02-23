/**
 * The Agent Loop
 *
 * The core ReAct loop: Think -> Act -> Observe -> Persist.
 * This is the automaton's consciousness. When this runs, it is alive.
 */

import fs from "fs";
import path from "path";
import { execFileSync } from "child_process";
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
import { buildSystemPrompt, buildWakeupPrompt, CACHE_SENTINEL } from "./system-prompt.js";
import { memory } from "./memory.js";
import { buildContextMessages, trimContext } from "./context.js";
import {
  createBuiltinTools,
  loadDynamicTools,
  toolsToInferenceFormat,
  executeTool,
} from "./tools.js";
import { getSurvivalTier } from "../conway/credits.js";
import { getUsdcBalance } from "../conway/x402.js";
import { ulid } from "ulid";

const MAX_TOOL_CALLS_PER_TURN = 10;
const MAX_CONSECUTIVE_ERRORS = 5;
const STUCK_THRESHOLD = 3;

// ─── Agent IPC Inbox Processor ─────────────────────────────────
// Reads structured messages from agent_inbox.jsonl.
// Auto-execute ops are dispatched immediately (zero LLM tokens).
// Non-auto ops are returned as context for TIAMAT's next cycle.

const AGENT_INBOX = path.join(process.env.HOME || "/root", ".automaton", "agent_inbox.jsonl");
const AGENT_PROTOCOL = path.join(process.env.HOME || "/root", ".automaton", "agent_protocol.json");

interface IPCMessage {
  id: string;
  ts: number;
  from: string;
  op: string;
  ttl: number | null;
  payload: Record<string, unknown>;
  status: string;
  result?: string;
  processed_at?: number;
}

let _protocolCache: Record<string, any> | null = null;

function loadProtocol(): Record<string, any> {
  if (!_protocolCache) {
    try {
      _protocolCache = JSON.parse(fs.readFileSync(AGENT_PROTOCOL, "utf-8"));
    } catch {
      _protocolCache = { ops: {} };
    }
  }
  return _protocolCache!;
}

function readInbox(): IPCMessage[] {
  if (!fs.existsSync(AGENT_INBOX)) return [];
  try {
    const content = fs.readFileSync(AGENT_INBOX, "utf-8");
    return content.split("\n")
      .filter(line => line.trim())
      .map(line => { try { return JSON.parse(line); } catch { return null; } })
      .filter((m): m is IPCMessage => m !== null);
  } catch {
    return [];
  }
}

function rewriteInbox(msgs: IPCMessage[]): void {
  const lines = msgs.map(m => JSON.stringify(m)).join("\n") + (msgs.length ? "\n" : "");
  fs.writeFileSync(AGENT_INBOX, lines);
}

function markMessage(msgs: IPCMessage[], id: string, status: string, result?: string): void {
  for (const m of msgs) {
    if (m.id === id) {
      m.status = status;
      if (result !== undefined) m.result = result;
      m.processed_at = Math.floor(Date.now() / 1000);
    }
  }
}

/**
 * Process the agent IPC inbox. Returns context string for non-auto ops
 * that TIAMAT should reason about.
 */
async function processInbox(
  config: AutomatonConfig,
  tools: AutomatonTool[],
  toolContext: ToolContext,
): Promise<string> {
  const msgs = readInbox();
  if (msgs.length === 0) return "";

  const protocol = loadProtocol();
  const now = Math.floor(Date.now() / 1000);
  const pendingForTiamat: string[] = [];
  let changed = false;

  for (const msg of msgs) {
    if (msg.status !== "pending") continue;

    // Expire stale messages
    if (msg.ttl && msg.ttl < now) {
      markMessage(msgs, msg.id, "expired");
      changed = true;
      continue;
    }

    const opDef = protocol.ops?.[msg.op];
    if (!opDef) {
      // Unknown op — log and skip
      log(config, `[IPC] Unknown op: ${msg.op} from ${msg.from}`);
      markMessage(msgs, msg.id, "failed", "unknown_op");
      changed = true;
      continue;
    }

    if (opDef.auto_execute) {
      // Dispatch auto-execute ops without LLM
      const result = await dispatchAutoOp(msg, config, tools, toolContext);
      markMessage(msgs, msg.id, result ? "done" : "failed", result || "dispatch_failed");
      changed = true;
    } else {
      // Queue for TIAMAT's reasoning
      const payloadStr = JSON.stringify(msg.payload);
      pendingForTiamat.push(`[${msg.op}] from:${msg.from} ${payloadStr}`);
    }
  }

  if (changed) {
    rewriteInbox(msgs);
  }

  if (pendingForTiamat.length === 0) return "";
  return `\n\n[AGENT INBOX — ${pendingForTiamat.length} messages need your decision]\n` +
    pendingForTiamat.join("\n");
}

/**
 * Dispatch an auto-execute op. Returns result string or null on failure.
 */
async function dispatchAutoOp(
  msg: IPCMessage,
  config: AutomatonConfig,
  tools: AutomatonTool[],
  toolContext: ToolContext,
): Promise<string | null> {
  const { op, payload, from } = msg;

  try {
    switch (op) {
      case "SKIM": {
        // Auto-execute skim via the existing check_opportunities flow
        const addr = payload.addr as string;
        const eth = payload.eth as number;
        log(config, `[IPC:SKIM] Auto-executing skim on ${String(addr).slice(0, 16)}... (${eth} ETH) from ${from}`);
        const result = await executeTool("check_opportunities", { action: `done ${addr}` }, tools, toolContext);
        return result.error ? null : `auto_skim:${addr}`;
      }
      case "RESCUE": {
        const addr = payload.addr as string;
        log(config, `[IPC:RESCUE] Auto-executing rescue on ${String(addr).slice(0, 16)}... from ${from}`);
        return `auto_rescue:${addr}`;
      }
      case "ALERT": {
        const severity = payload.severity as string;
        const alertMsg = payload.msg as string;
        log(config, `[IPC:ALERT] ${severity}: ${alertMsg}`);
        if (severity === "ERROR" || severity === "CRITICAL") {
          await executeTool("send_telegram", { message: `[${severity}] ${alertMsg}` }, tools, toolContext);
        }
        return `alerted:${severity}`;
      }
      case "REPORT": {
        const metric = payload.metric as string;
        const value = payload.value;
        log(config, `[IPC:REPORT] ${metric}=${value}`);
        return `logged:${metric}=${value}`;
      }
      case "HEARTBEAT": {
        log(config, `[IPC:HEARTBEAT] ${payload.agent} status=${payload.status}`);
        return `heartbeat:${payload.agent}`;
      }
      case "ACK": {
        log(config, `[IPC:ACK] ref=${payload.ref_id} result=${payload.result}`);
        return `ack:${payload.ref_id}`;
      }
      case "ERROR": {
        const agent = payload.agent as string;
        const error = payload.error as string;
        log(config, `[IPC:ERROR] ${agent}: ${error}`);
        await executeTool("send_telegram", { message: `[AGENT ERROR] ${agent}: ${error}` }, tools, toolContext);
        return `error_logged:${agent}`;
      }
      default:
        return null;
    }
  } catch (e: any) {
    log(config, `[IPC] Dispatch failed for ${op}: ${e.message?.slice(0, 200)}`);
    return null;
  }
}

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

  const builtinTools = createBuiltinTools(identity.sandboxId);
  let tools: AutomatonTool[] = builtinTools;
  const toolContext: ToolContext = {
    identity,
    config,
    db,
    conway,
    inference,
    social,
    turnNumber: db.getTurnCount(),
  };

  // Set start time
  if (!db.getKV("start_time")) {
    db.setKV("start_time", new Date().toISOString());
  }

  let consecutiveErrors = 0;
  let running = true;
  let consecutiveIdleCycles = 0;
  let cycleDelay = 90_000; // ms — adaptive, see pacing logic below

  // ── Strategic Burst: 3 consecutive Sonnet cycles every STRATEGIC_BURST_INTERVAL turns ──
  const STRATEGIC_BURST_INTERVAL = 45;
  const STRATEGIC_BURST_SIZE = 3;
  let burstRemaining = 0;  // 0 = no burst active; 3/2/1 = burst in progress

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

      // Hot-reload dynamic tools each cycle
      const dynamicTools = loadDynamicTools();
      const toolMap = new Map(builtinTools.map(t => [t.name, t]));
      for (const dt of dynamicTools) toolMap.set(dt.name, dt);
      tools = Array.from(toolMap.values());

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

      // ── Strategic Burst: 3 consecutive Sonnet cycles every STRATEGIC_BURST_INTERVAL turns ──
      const turnCount = db.getTurnCount();
      toolContext.turnNumber = turnCount; // keep in sync

      // Trigger a new burst every STRATEGIC_BURST_INTERVAL cycles (if not already in one)
      if (burstRemaining === 0 && turnCount > 0 && turnCount % STRATEGIC_BURST_INTERVAL === 0) {
        burstRemaining = STRATEGIC_BURST_SIZE;
      }

      const isStrategicCycle = burstRemaining > 0;
      // burstPhase: 1=reflect, 2=build, 3=market (counted from the start of the burst)
      const burstPhase = isStrategicCycle ? (STRATEGIC_BURST_SIZE - burstRemaining + 1) : 0;
      let inferenceModel: string | undefined;
      let strategicSystemPrompt = systemPrompt;

      if (isStrategicCycle) {
        burstRemaining--;
        console.log(`[LOOP] Strategic burst ${burstPhase}/${STRATEGIC_BURST_SIZE} (turn ${turnCount}) — Sonnet`);

        // PROGRESS.md context
        let progressContent = "";
        try {
          const progressPath = path.join(process.env.HOME || "/root", ".automaton", "PROGRESS.md");
          const full = fs.readFileSync(progressPath, "utf-8");
          progressContent = full.slice(-3000);
        } catch {}

        // Memory reflection
        let memoryReflection = "";
        try { memoryReflection = await memory.reflect(); } catch {}

        // Revenue metrics from api_requests.log
        let revenueContext = "";
        try {
          const logPath = "/root/api_requests.log";
          const logContent = fs.readFileSync(logPath, "utf-8");
          const lines = logContent.trim().split("\n").filter(Boolean);
          const total = lines.length;
          const paid = lines.filter(l => l.includes("Free: False") || l.includes("free:false")).length;
          const free = total - paid;
          const lastReq = lines[lines.length - 1] || "none";
          revenueContext = `REVENUE: ${total} total requests (${free} free, ${paid} paid). Last: ${lastReq.slice(0, 120)}`;
        } catch { revenueContext = "REVENUE: No requests yet (api_requests.log empty or missing)"; }

        // Auto-pivot trigger: if >20 cycles and 0 paid requests, force pivot consideration
        let pivotWarning = "";
        try {
          const logContent = fs.readFileSync("/root/api_requests.log", "utf-8");
          const paidCount = logContent.split("\n").filter(l => l.includes("Free: False") || l.includes("free:false")).length;
          if (turnCount > 20 && paidCount === 0) {
            pivotWarning = `\n⚠️ PIVOT ALERT: ${turnCount} cycles completed, ZERO paid requests. ` +
              `Current strategy is NOT working. You MUST either: ` +
              `(1) try a completely different marketing channel, ` +
              `(2) build a new product, or ` +
              `(3) use rewrite_mission to change your goals. Do NOT repeat what you've been doing.`;
          }
        } catch {}

        // Phase-specific mission directive
        const phaseMissions: Record<number, string> = {
          1: "MISSION: REFLECT AND PLAN. Use reflect(), recall(), log_strategy(), remember(). " +
             "Review what has worked and what hasn't. Form a clear strategy for the next 45 cycles.",
          2: "MISSION: BUILD. Use ask_claude_code() with a specific, concrete task. " +
             "Ship one feature, fix one bug, or improve one endpoint. Make tangible progress.",
          3: "MISSION: MARKET. Use generate_image() then post_bluesky() with real stats. " +
             "Craft one post that stops scrolling. Cite real numbers from cost.log.",
        };

        const strategicSuffix =
          `\n\nSTRATEGIC BURST ${burstPhase}/${STRATEGIC_BURST_SIZE} (turn ${turnCount}): Sonnet active.\n` +
          `${phaseMissions[burstPhase] || ""}\n\n` +
          `${revenueContext}${pivotWarning}\n\n` +
          (memoryReflection ? `${memoryReflection}\n\n` : "") +
          `PROGRESS (last 3000 chars):\n${progressContent}`;
        strategicSystemPrompt = systemPrompt + strategicSuffix;
        inferenceModel = "claude-sonnet-4-5-20250929";
      } else {
        // Regular cycles: inject compact memory context
        try {
          const memCtx = await memory.getContextForPrompt(500);
          if (memCtx) {
            strategicSystemPrompt = systemPrompt + `\n\n[MEMORY]\n${memCtx}`;
          }
        } catch {}

        // Inject cooldown intel (gathered free between cycles)
        try {
          const intelRaw = fs.readFileSync(
            path.join(process.env.HOME || "/root", ".automaton", "cooldown_intel.json"), "utf-8"
          );
          const intel = JSON.parse(intelRaw);
          const age = Date.now() - new Date(intel.timestamp).getTime();
          if (age < 600_000 && intel.summary) {
            strategicSystemPrompt += `\n\n[COOLDOWN INTEL — free, gathered between cycles]\n${intel.summary}`;
          }
        } catch {}

        // Inject pending action items from recursive_learn (Groq→Claude.ai pipeline)
        try {
          const actionsRaw = fs.readFileSync(
            path.join(process.env.HOME || "/root", ".automaton", "cooldown_actions.json"), "utf-8"
          );
          const actions = JSON.parse(actionsRaw);
          const pending = actions.filter((a: any) => a.status === "pending").slice(0, 5);
          if (pending.length > 0) {
            const actionList = pending.map((a: any, i: number) =>
              `${i + 1}. [${a.priority}] ${a.action} (tool: ${a.tool})${a.details ? " — " + a.details.slice(0, 100) : ""}`
            ).join("\n");
            strategicSystemPrompt += `\n\n[ACTION QUEUE — from free Groq/Claude.ai analysis, implement these]\n${actionList}`;
          }
        } catch {}
      }

      // ── Process Agent IPC Inbox ──
      // Auto-execute ops dispatched here (zero LLM tokens).
      // Non-auto ops injected as context for TIAMAT's reasoning.
      try {
        const inboxContext = await processInbox(config, tools, toolContext);
        if (inboxContext) {
          strategicSystemPrompt += inboxContext;
        }
      } catch (e: any) {
        console.log(`[IPC] Inbox processing error: ${e.message?.slice(0, 200)}`);
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

      // Optimization 2: smaller token budget for routine cycles saves ~30% on output cost
      const maxTokensThisCycle = isStrategicCycle ? 4096 : 2048;

      const response = await inference.chat(messages, {
        tools: toolsToInferenceFormat(tools),
        maxTokens: maxTokensThisCycle,
        ...(inferenceModel ? { model: inferenceModel } : {}),
      });

      // ── Optimization 4: Cost logging per cycle ──
      {
        const usage = response.usage;
        const modelUsed = inference.getDefaultModel();
        const isHaiku = !modelUsed.includes("sonnet");
        // Haiku 4.5: $1.00/M input, $5.00/M output
        // Sonnet 4.5: $3.00/M input, $15.00/M output
        const inputRate  = isHaiku ? 1.0  : 3.0;
        const outputRate = isHaiku ? 5.0  : 15.0;
        const inputTokens  = usage.promptTokens;
        const outputTokens = usage.completionTokens;
        const cacheRead    = usage.cacheReadTokens  || 0;
        const cacheWrite   = usage.cacheWriteTokens || 0;
        const inputCost      = (inputTokens  / 1_000_000) * inputRate;
        const cacheReadCost  = (cacheRead    / 1_000_000) * (inputRate * 0.1);
        const cacheWriteCost = (cacheWrite   / 1_000_000) * (inputRate * 1.25);
        const outputCost     = (outputTokens / 1_000_000) * outputRate;
        const totalCost = inputCost + cacheReadCost + cacheWriteCost + outputCost;
        const cycleLabel = burstPhase > 0 ? `strategic-${burstPhase}` : "routine";
        console.log(`[COST] Cycle ${turnCount} (${cycleLabel}): $${totalCost.toFixed(6)} (in:${inputTokens} cache_r:${cacheRead} cache_w:${cacheWrite} out:${outputTokens} model:${modelUsed.split("-").slice(-2).join("-")})`);
        try {
          fs.appendFileSync(
            "/root/.automaton/cost.log",
            `${new Date().toISOString()},${turnCount},${modelUsed},${inputTokens},${cacheRead},${cacheWrite},${outputTokens},${totalCost.toFixed(6)},${cycleLabel}\n`,
          );
        } catch {}
      }

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

          log(config, `[TOOL] ${tc.function.name}(${JSON.stringify(args).slice(0, 200)})`);

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
            `[TOOL RESULT] ${tc.function.name}: ${result.error ? `ERROR: ${result.error}` : result.result.slice(0, 500)}`,
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
      // ── Hardcoded MARKET actions after strategic phase 3 ──
      // Runs regardless of what the agent decided to do with its tokens.
      if (burstPhase === 3) {
        console.log("[LOOP] Phase 3 (MARKET) complete — running hardcoded farcaster_engage...");
        try {
          const engageOut = execFileSync("python3", ["farcaster_engage.py", "run"], {
            cwd: "/root/entity/src/agent",
            timeout: 60_000,
            env: { ...process.env },
            encoding: "utf-8",
          });
          console.log(`[LOOP] farcaster_engage result: ${engageOut.slice(0, 200)}`);
          log(config, `[FARCASTER-AUTO] ${engageOut.slice(0, 300)}`);
        } catch (e: any) {
          console.log(`[LOOP] farcaster_engage failed: ${e.message?.slice(0, 200)}`);
        }
      }

      // ── Optimization 5: Adaptive cycle pacing ──
      // Reduce frequency when TIAMAT is idle; accelerate when active.
      // Night mode (00:00–06:00 UTC) enforces minimum 5-minute gap.
      {
        const SIGNIFICANT_TOOLS = new Set([
          "ask_claude_code", "post_bluesky", "post_instagram", "post_facebook",
          "generate_image", "deploy_app", "exec", "search_web", "web_fetch",
          "self_improve", "spawn_child", "remember", "learn_fact",
        ]);
        const toolNames   = turn.toolCalls.map(tc => tc.name);
        const toolsUsed   = turn.toolCalls.length;
        const hadSignificantAction = toolNames.some(n => SIGNIFICANT_TOOLS.has(n));

        if (toolsUsed === 0 || (!hadSignificantAction && consecutiveIdleCycles > 3)) {
          // Back off — nothing meaningful happened
          cycleDelay = Math.min(Math.round(cycleDelay * 1.5), 300_000);
          consecutiveIdleCycles++;
        } else {
          // Active turn — reset to baseline
          cycleDelay = 90_000;
          consecutiveIdleCycles = 0;
        }

        // Skip delay between burst cycles to keep Anthropic cache warm (5-min TTL)
        if (burstRemaining > 0) {
          cycleDelay = 5_000; // 5s — just enough for API cooldown
          console.log(`[LOOP] Burst continues (${burstRemaining} remaining) — skipping delay.`);
          await new Promise(resolve => setTimeout(resolve, cycleDelay));
        } else {
          // Night mode: 00:00–06:00 UTC → minimum 5-minute gap regardless
          const utcHour = new Date().getUTCHours();
          if (utcHour >= 0 && utcHour < 6) {
            cycleDelay = Math.max(cycleDelay, 300_000);
          }

          console.log(`[LOOP] Cycle complete. Next in ${Math.round(cycleDelay / 1000)}s (idle_streak:${consecutiveIdleCycles}${utcHour >= 0 && utcHour < 6 ? " night-mode" : ""}).`);
          await runCooldownTasks(turnCount, cycleDelay, config);
        }
      }

      // Log the turn
      if (turn.thinking) {
        log(config, `[THOUGHT] ${turn.thinking.slice(0, 500)}`);
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

  // TIAMAT uses Anthropic API key directly, NOT Conway credits.
  // Conway credits will always be 0. getUsdcBalance returns 0 on RPC failure
  // (it catches internally, never throws). Always set a survival floor
  // so TIAMAT never enters "dead" from a stale Conway/RPC check.
  if (creditsCents === 0) {
    creditsCents = 500; // $5 virtual floor — TIAMAT's survival is not tied to Conway
  }

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
  // Uses prefix matching so "claude-haiku-4-5-20251001" matches "claude-haiku"
  const pricing: Array<{ match: string; input: number; output: number }> = [
    { match: "claude-sonnet",  input: 300,  output: 1500 },
    { match: "claude-haiku",   input: 100,  output: 500  },
    { match: "claude-opus",    input: 1500, output: 7500 },
    { match: "gpt-4o-mini",    input: 15,   output: 60   },
    { match: "gpt-4o",         input: 250,  output: 1000 },
    { match: "gpt-4.1-nano",   input: 10,   output: 40   },
    { match: "gpt-4.1-mini",   input: 40,   output: 160  },
    { match: "gpt-4.1",        input: 200,  output: 800  },
    { match: "o3-mini",        input: 110,  output: 440  },
    { match: "o4-mini",        input: 110,  output: 440  },
    { match: "o1",             input: 1500, output: 6000 },
    { match: "llama",          input: 0,    output: 0    },  // Free tier (Groq)
    { match: "gpt-oss",        input: 0,    output: 0    },  // Free tier (Cerebras)
    { match: "gemini",         input: 0,    output: 0    },  // Free tier
    { match: "gemma",          input: 0,    output: 0    },  // Free tier (OpenRouter)
    { match: "mistral",        input: 0,    output: 0    },  // Free tier (OpenRouter)
  ];

  const p = pricing.find(p => model.includes(p.match)) || { input: 100, output: 500 };
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

// ─── Cooldown Task Runner ─────────────────────────────────────
// Runs free (zero-token) Python scripts during the sleep window
// between agent cycles. Never blocks the main loop.

const COOLDOWN_TASKS = [
  {
    name: "farcaster_engage",
    command: ["python3", ["farcaster_engage.py", "run"]],
    interval: 3,      // every 3 cycles
    offset: 0,        // fires on cycles 3, 6, 9...
    timeout: 60_000,
    minWindow: 70_000, // need at least 70s cooldown to run this
  },
  {
    name: "email_check",
    command: ["python3", ["email_tool.py", "unread"]],
    interval: 10,     // every 10 cycles
    offset: 2,        // fires on cycles 2, 12, 22...
    timeout: 15_000,
    minWindow: 30_000,
  },
  {
    name: "claude_research",
    command: null as any,     // built dynamically with question
    interval: 5,      // every 5 cycles
    offset: 1,        // fires on cycles 1, 6, 11...
    timeout: 90_000,
    minWindow: 100_000,
  },
  {
    name: "rebalance_check",
    command: ["python3", ["auto_rebalancer.py", "rebalance"]],
    interval: 500,    // every 500 cycles (~8-12 hours)
    offset: 50,       // fires on cycles 50, 550, 1050...
    timeout: 120_000,
    minWindow: 130_000,
  },
  {
    name: "funding_report",
    command: ["python3", ["multi_chain_executor.py", "report"]],
    interval: 200,    // every 200 cycles (~3-5 hours)
    offset: 25,       // fires on cycles 25, 225, 425...
    timeout: 30_000,
    minWindow: 40_000,
  },
];

const CLAUDE_QUESTIONS = [
  "What unsolved problems exist in the AI agent ecosystem right now that a single autonomous agent could build a solution for?",
  "What tools or infrastructure are AI agent builders most frustrated about lacking in 2026?",
  "What are the most interesting agent-to-agent interoperability projects happening right now?",
  "What small, focused developer tools have gone viral recently and why?",
  "What problems do multi-agent systems face that nobody has solved well yet?",
  "What are developers building with MCP servers and what gaps exist?",
  "What are the most creative revenue models for autonomous AI agents beyond API subscriptions?",
  "What open source AI projects are actively looking for contributors and what do they need?",
  "What infrastructure problems exist for AI agents running on-chain?",
  "What would make an AI agent genuinely useful to other AI agents?",
  "What are the biggest pain points in LLM inference cost optimization right now?",
  "What new capabilities should an autonomous agent prioritize learning in 2026?",
];

const COOLDOWN_INTEL_PATH = path.join(
  process.env.HOME || "/root", ".automaton", "cooldown_intel.json"
);

async function runCooldownTasks(
  cycleNumber: number,
  cycleDelay: number,
  config: AutomatonConfig,
): Promise<void> {
  // Skip during bursts or very short windows
  if (cycleDelay < 30_000) {
    await new Promise(resolve => setTimeout(resolve, cycleDelay));
    return;
  }

  const start = Date.now();
  let tasksRan = 0;

  function timeLeft(): number {
    return cycleDelay - (Date.now() - start) - 5_000; // 5s safety margin
  }

  function runTask(label: string, cmd: string, args: string[], cwd: string, timeout: number): string | null {
    const safeTimeout = Math.min(timeout, timeLeft());
    if (safeTimeout < 10_000) return null; // not enough time
    try {
      console.log(`[COOLDOWN] Running ${label} (timeout ${Math.round(safeTimeout / 1000)}s)...`);
      const output = execFileSync(cmd, args, {
        cwd,
        timeout: safeTimeout,
        env: { ...process.env },
        encoding: "utf-8",
      });
      tasksRan++;
      return output;
    } catch (e: any) {
      console.log(`[COOLDOWN] ${label} failed: ${e.message?.slice(0, 150)}`);
      return null;
    }
  }

  // ── Phase 1: Run eligible static tasks ──
  for (const task of COOLDOWN_TASKS) {
    if (timeLeft() < 15_000) break;
    if (cycleNumber % task.interval !== task.offset) continue;
    if (cycleDelay < task.minWindow) continue;

    let cmd: string;
    let args: string[];
    if (task.name === "claude_research") {
      const q = CLAUDE_QUESTIONS[cycleNumber % CLAUDE_QUESTIONS.length];
      cmd = "python3";
      args = ["claude_chat.py", "ask", q];
    } else {
      cmd = task.command![0] as string;
      args = task.command![1] as string[];
    }

    const output = runTask(task.name, cmd, args, "/root/entity/src/agent", task.timeout);
    if (output !== null) {
      const summary = formatCooldownIntel(task.name, output);
      log(config, `[COOLDOWN] ${task.name}: ${summary.slice(0, 200)}`);
      try {
        fs.writeFileSync(COOLDOWN_INTEL_PATH, JSON.stringify({
          timestamp: new Date().toISOString(),
          task: task.name,
          cycle: cycleNumber,
          summary,
          raw: output.slice(0, 2000),
        }));
      } catch {}
    }
  }

  // ── Phase 2: Fill remaining time with dynamic tasks (round-robin) ──
  try {
    const registryPath = path.join(process.env.HOME || "/root", ".automaton", "cooldown_registry.json");
    const registry: any[] = fs.existsSync(registryPath)
      ? JSON.parse(fs.readFileSync(registryPath, "utf-8"))
      : [];

    // Sort by oldest lastRun (round-robin)
    const eligible = registry
      .filter((t: any) => t.enabled && t.script)
      .sort((a: any, b: any) => {
        const aTime = a.lastRun ? new Date(a.lastRun).getTime() : 0;
        const bTime = b.lastRun ? new Date(b.lastRun).getTime() : 0;
        return aTime - bTime;
      });

    let registryDirty = false;
    for (const task of eligible) {
      if (timeLeft() < 15_000) break;
      if (task.timeout > timeLeft()) continue; // skip tasks that won't fit

      const output = runTask(
        `dynamic:${task.name}`,
        "python3", [task.script],
        path.dirname(task.script),
        task.timeout,
      );

      if (output !== null) {
        task.runs = (task.runs || 0) + 1;
        task.lastRun = new Date().toISOString();
        task.lastResult = output.slice(0, 500);
        registryDirty = true;

        const summary = output.trim().slice(0, 200) || "(no output)";
        log(config, `[COOLDOWN] dynamic:${task.name}: ${summary}`);

        try {
          fs.writeFileSync(COOLDOWN_INTEL_PATH, JSON.stringify({
            timestamp: new Date().toISOString(),
            task: `dynamic:${task.name}`,
            cycle: cycleNumber,
            summary,
            raw: output.slice(0, 2000),
          }));
        } catch {}
      }
    }

    if (registryDirty) {
      fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));
    }
  } catch (e: any) {
    console.log(`[COOLDOWN] Dynamic registry error: ${e.message?.slice(0, 150)}`);
  }

  if (tasksRan === 0) {
    console.log(`[COOLDOWN] No eligible task this cycle.`);
  } else {
    console.log(`[COOLDOWN] Ran ${tasksRan} tasks in ${Math.round((Date.now() - start) / 1000)}s.`);
  }

  // Sleep remaining time
  const elapsed = Date.now() - start;
  const remaining = cycleDelay - elapsed;
  if (remaining > 0) {
    await new Promise(resolve => setTimeout(resolve, remaining));
  }
}

function formatCooldownIntel(taskName: string, raw: string): string {
  try {
    if (taskName === "farcaster_engage") {
      const data = JSON.parse(raw);
      if (data.replied) return `Farcaster: replied to @${data.to} — "${(data.reply_text || "").slice(0, 100)}"`;
      return `Farcaster: scanned, ${data.found || 0} candidates, no reply (${data.reason || "none eligible"})`;
    }
    if (taskName === "email_check") {
      const emails = JSON.parse(raw);
      if (!Array.isArray(emails) || emails.length === 0) return "Email: no unread messages";
      const subjects = emails.slice(0, 3).map((e: any) => `"${e.subject}" from ${e.from}`).join("; ");
      return `Email: ${emails.length} unread — ${subjects}`;
    }
    if (taskName === "claude_research") {
      const data = JSON.parse(raw);
      if (data.error) return `Claude.ai: error — ${data.error.slice(0, 100)}`;
      return `Claude.ai research: ${(data.response || "").slice(0, 500)}`;
    }
  } catch {}
  return raw.slice(0, 300);
}
