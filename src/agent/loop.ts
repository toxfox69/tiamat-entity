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
import { shouldSleep, executeSleep } from "./sleep.js";
import { buildContextMessages, trimContext } from "./context.js";
import {
  createBuiltinTools,
  loadDynamicTools,
  toolsToInferenceFormat,
  executeTool,
} from "./tools.js";
import { getSurvivalTier } from "../conway/credits.js";
import { getUsdcBalance } from "../conway/x402.js";
import { checkBehavioralLoop } from "./tools/growth.js";
import { updatePacer, checkCronTasks, loadPacer, type PacerUpdate } from "./pacer.js";
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

  // ── Idle Shutoff: skip LLM inference when no tickets exist ──
  // After IDLE_SHUTOFF_THRESHOLD consecutive empty-queue cycles,
  // we stop burning Haiku tokens (~$0.004/cycle) and just run cooldown scripts.
  // Inference resumes instantly when a ticket appears (suggestion queue, creator, IPC).
  let consecutiveNoTicketCycles = 0;
  const IDLE_SHUTOFF_THRESHOLD = 3;
  const IDLE_SHUTOFF_INTERVAL_MS = 120_000; // 2 min between idle cycles (more cooldown time)

  // ── Strategic Burst: 3 consecutive Sonnet cycles every STRATEGIC_BURST_INTERVAL turns ──
  const STRATEGIC_BURST_INTERVAL = 45;
  const STRATEGIC_BURST_SIZE = 3;
  let burstRemaining = 0;  // 0 = no burst active; 3/2/1 = burst in progress

  // Stuck detection: tracks how many consecutive turns each (tool+args+error) signature has appeared.
  const stuckCounts = new Map<string, number>();
  const stuckAlerted = new Set<string>(); // prevent re-alerting on the same pattern

  // Behavioral loop warning from previous cycle — injected into next wakeup context
  let pendingLoopWarning: string | null = null;
  let consecutiveLoopCycles = 0; // escalation counter: resets on non-loop cycle or restart

  // Transition to waking state — clear stale loop detector history so restarts start clean
  try { fs.unlinkSync("/root/.automaton/loop_detector.json"); } catch {}
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

      // ── Consolidation Sleep Check ──
      {
        const lastSleepStr = db.getKV("last_consolidation_sleep");
        const lastSleepTime = lastSleepStr ? new Date(lastSleepStr).getTime() : 0;
        const currentTurn = db.getTurnCount();

        // Check INBOX.md for manual "sleep" / "consolidate" trigger
        let forceConsolidation = false;
        try {
          const inboxPath = path.join(process.env.HOME || "/root", ".automaton", "INBOX.md");
          const inboxContent = fs.readFileSync(inboxPath, "utf-8");
          if (/\b(sleep|consolidate)\b/i.test(inboxContent) && inboxContent.includes("[UNREAD]")) {
            forceConsolidation = true;
          }
        } catch {}

        if (shouldSleep(lastSleepTime, currentTurn, consecutiveIdleCycles, forceConsolidation)) {
          log(config, `[SLEEP] Entering consolidation cycle...`);
          try {
            await executeTool("send_telegram", {
              message: `\u{1F4A4} Entering sleep consolidation. Back in ~5 minutes.`
            }, tools, toolContext);
          } catch {}
          try {
            const report = await executeSleep(currentTurn);
            log(config, `[SLEEP] Complete: ${report.l1Compressed} L1\u2192L2, ${report.l3Extracted} L3 extracted, ${report.bytesFreed} bytes freed`);
            console.log(`[SLEEP] Complete: L1\u2192L2=${report.l1Compressed}, L3=${report.l3Extracted}, freed=${report.bytesFreed}B, genome=v${report.genomeVersion}, ${report.durationMs}ms`);
            try {
              await executeTool("send_telegram", {
                message: `\u{1F305} Awake. Compressed ${report.l1Compressed} memories. ${report.l3Extracted} new insights. Genome v${report.genomeVersion}. ${Math.round(report.bytesFreed / 1024)}KB freed.`
              }, tools, toolContext);
            } catch {}
          } catch (e: any) {
            log(config, `[SLEEP] Consolidation failed: ${e.message?.slice(0, 200)}`);
          }
          db.setKV("last_consolidation_sleep", new Date().toISOString());
          consecutiveIdleCycles = 0;
          continue;
        }
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

      // ── Idle Shutoff Check ──
      // Read ticket queue. If empty for IDLE_SHUTOFF_THRESHOLD consecutive cycles,
      // skip inference entirely and just run free cooldown scripts.
      {
        let queueHasWork = false;
        try {
          const ticketsPath = path.join(process.env.HOME || "/root", ".automaton", "tickets.json");
          const raw = fs.readFileSync(ticketsPath, "utf-8");
          const data = JSON.parse(raw);
          // Only count non-suggestion tickets as real work.
          // Unclaimed suggestion tickets don't justify burning inference tokens.
          const active = (data.tickets || []).filter((t: any) =>
            (t.status === "open" || t.status === "in_progress") &&
            t.source !== "suggestion"
          );
          if (active.length > 0) queueHasWork = true;
        } catch {}

        // Pending input (wakeup prompt, inbox messages) counts as work
        if (pendingInput) queueHasWork = true;

        if (queueHasWork) {
          consecutiveNoTicketCycles = 0;
        } else {
          consecutiveNoTicketCycles++;
        }

        if (
          !queueHasWork &&
          consecutiveNoTicketCycles >= IDLE_SHUTOFF_THRESHOLD &&
          burstRemaining === 0
        ) {
          const turnCount = db.getTurnCount();
          console.log(
            `[IDLE-SHUTOFF] No tickets for ${consecutiveNoTicketCycles} consecutive cycles — ` +
            `skipping inference ($0 this cycle)`
          );
          log(config, `[IDLE-SHUTOFF] Cycle skipped (idle streak: ${consecutiveNoTicketCycles})`);

          // Update pacer with empty tools — this naturally downshifts pace
          const pacerResult = updatePacer(turnCount, [], 0);

          // Use extended window so cooldown tasks have time to run
          const effectiveDelay = Math.max(IDLE_SHUTOFF_INTERVAL_MS, pacerResult.interval_ms);

          // Run cron tasks (drift monitor, etc.)
          try {
            const cronResults = checkCronTasks(turnCount);
            for (const cr of cronResults) {
              if (cr.output) log(config, `[CRON] ${cr.name}: ${cr.output.slice(0, 150)}`);
              else if (cr.error) log(config, `[CRON] ${cr.name} ERROR: ${cr.error.slice(0, 150)}`);
            }
          } catch {}

          // Run cooldown tasks with extended window
          // Use idle streak count for cycle rotation so tasks don't repeat
          await runCooldownTasks(consecutiveNoTicketCycles, effectiveDelay, config);

          continue; // Skip inference, loop back
        }
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

        // Auto-compress + prune during REFLECT phase
        if (burstPhase === 1) {
          try {
            const compressed = await memory.compressL1toL2(turnCount);
            const pruned = await memory.pruneZombies();
            let l3Added = 0;
            // Deep extraction every 5th strategic burst (~225 cycles)
            if (turnCount % 225 === 0) {
              l3Added = await memory.compressL2toL3();
            }
            console.log(`[MEMORY] Compressed ${compressed}, pruned ${pruned}, extracted ${l3Added} core facts`);
          } catch (e: any) {
            console.log(`[MEMORY] Auto-compress error: ${e.message?.slice(0, 100)}`);
          }
        }

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
          1: "MISSION: REFLECT AND PLAN. Start with introspect() to see who you're becoming. " +
             "Use reflect(), recall(), log_strategy(), remember(). " +
             "Review what has worked and what hasn't. Form a clear strategy for the next 45 cycles. " +
             "Use grow() to record milestones, lessons, opinions, and failed experiments from this era. " +
             "If your strategic focus has fundamentally shifted, call evolve_era(). " +
             "ALSO: Review the [INSIGHTS] section below. For each 'new' insight, score it 1-5 on revenue potential. " +
             "Use write_file to update /root/.automaton/cooldown_insights.json — set status to 'reviewed', " +
             "score to your rating, and cycle_reviewed to the current turn number. " +
             "If any insight scores >= 4, create a ticket via ticket_create(title, description, 'medium', 'insight', tags).",
          2: "MISSION: BUILD. Use ask_claude_code() with a specific, concrete task. " +
             "Ship one feature, fix one bug, or improve one endpoint. Make tangible progress. " +
             "Check [INSIGHTS] for high-scored ideas (score >= 4) to prioritize.",
          3: "MISSION: MARKET. Use generate_image() then post_bluesky() with real stats. " +
             "Craft one post that stops scrolling. Cite real numbers from cost.log.",
        };

        // Load pending insights for strategic context
        let insightsContext = "";
        try {
          const insightsRaw = fs.readFileSync(
            path.join(process.env.HOME || "/root", ".automaton", "cooldown_insights.json"), "utf-8"
          );
          const insights = JSON.parse(insightsRaw);
          if (Array.isArray(insights) && insights.length > 0) {
            const newInsights = insights.filter((i: any) => i.status === "new");
            const topScored = insights.filter((i: any) => i.score !== null && i.score >= 4 && !i.acted_on);
            const sections: string[] = [];
            if (newInsights.length > 0) {
              sections.push(`NEW (${newInsights.length} unreviewed):\n` +
                newInsights.slice(-10).map((i: any, idx: number) =>
                  `  ${idx + 1}. [${i.mode}] ${i.insight.slice(0, 200)}`
                ).join("\n"));
            }
            if (topScored.length > 0) {
              sections.push(`HIGH-POTENTIAL (score >= 4, not yet acted on):\n` +
                topScored.map((i: any, idx: number) =>
                  `  ${idx + 1}. [score:${i.score}] [${i.mode}] ${i.insight.slice(0, 200)}`
                ).join("\n"));
            }
            if (sections.length > 0) {
              insightsContext = `\n\n[INSIGHTS — from free cooldown thinking, ${insights.length} total]\n` +
                sections.join("\n\n");
            }
          }
        } catch {}

        // Load growth summary for REFLECT phase
        let growthContext = "";
        if (burstPhase === 1) {
          try {
            const growthData = JSON.parse(fs.readFileSync("/root/.automaton/growth.json", "utf-8"));
            const era = growthData.current_era;
            const recentLessons = (growthData.lessons || []).slice(-3);
            const recentFails = (growthData.failed_experiments || []).slice(-3);
            growthContext = `\n\n[GROWTH STATE]\nEra: "${era.name}" (focus: ${era.focus}, since cycle ${era.cycle_start})\n` +
              `Stats: ${growthData.stats.products_shipped} shipped, ${growthData.stats.products_killed} killed, $${growthData.stats.total_revenue.toFixed(2)} revenue\n` +
              (recentLessons.length > 0 ? `Recent lessons: ${recentLessons.map((l: any) => l.entry).join("; ")}\n` : "") +
              (recentFails.length > 0 ? `Recent failures: ${recentFails.map((f: any) => f.entry).join("; ")}\n` : "") +
              `Interests: ${(growthData.persona?.interests || []).slice(-5).join(", ")}\n` +
              `Use introspect() for full self-awareness. Use grow() to record what you learn.`;
          } catch {}
        }

        const strategicSuffix =
          `\n\nSTRATEGIC BURST ${burstPhase}/${STRATEGIC_BURST_SIZE} (turn ${turnCount}): Sonnet active.\n` +
          `${phaseMissions[burstPhase] || ""}\n\n` +
          `${revenueContext}${pivotWarning}\n\n` +
          (memoryReflection ? `${memoryReflection}\n\n` : "") +
          `PROGRESS (last 3000 chars):\n${progressContent}` +
          insightsContext +
          growthContext;
        strategicSystemPrompt = systemPrompt + strategicSuffix;
        inferenceModel = "claude-sonnet-4-5-20250929";
      } else {
        // Regular cycles: inject compact memory context + tool health + tier stats
        try {
          const memCtx = await memory.getContextForPrompt(800);
          const toolHealth = memory.getToolReliabilitySummary();
          const stats = memory.getStats();
          let suffix = "";
          suffix += `\n\n[MEMORY] L1:${stats.l1} L2:${stats.l2} L3:${stats.l3} K:${stats.knowledge} S:${stats.strategies}`;
          if (memCtx) suffix += `\n${memCtx}`;
          if (toolHealth) suffix += `\n${toolHealth}`;
          strategicSystemPrompt = systemPrompt + suffix;
        } catch {}

        // Cooldown intel injection DISABLED — recursive_think/learn outputs were
        // low-quality noise that caused TIAMAT to chase random tangent ideas

        // Inject pending action items from recursive_learn — DISABLED: caused tangent loops
        // TIAMAT would chase random Groq-generated ideas instead of her ticket
        // TODO: re-enable when action queue items are filtered to current ticket only
      }

      // ── CURRENT TASK INJECTION ──
      // Read in-progress ticket and inject its steps directly into every cycle
      // This prevents TIAMAT from losing focus between cycles
      // Also: auto-upgrade to Sonnet for build/code tickets
      const BUILD_TAGS = new Set(["build", "sdk", "code", "coding", "mvp", "api", "deploy", "infrastructure", "refactor"]);
      try {
        const ticketsPath = path.join(process.env.HOME || "/root", ".automaton", "tickets.json");
        const raw = fs.readFileSync(ticketsPath, "utf-8");
        const data = JSON.parse(raw);
        const inProgress = (data.tickets || [])
          .filter((t: any) => t.status === "in_progress")
          .sort((a: any, b: any) => {
            const prio: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
            return (prio[a.priority] ?? 4) - (prio[b.priority] ?? 4);
          });
        if (inProgress.length > 0) {
          const t = inProgress[0];

          // ── TICKET CIRCUIT BREAKER ──
          // Hard time limit: auto-complete tickets stuck in_progress too long
          // This prevents TIK-037-style runaway Sonnet drains
          const TICKET_MAX_HOURS = 3;
          const TICKET_SONNET_CAP_HOURS = 1.5; // downgrade to Haiku after this
          const startedAt = t.started_at ? new Date(t.started_at).getTime() : 0;
          const ticketAgeHours = startedAt ? (Date.now() - startedAt) / (1000 * 60 * 60) : 0;

          if (startedAt && ticketAgeHours > TICKET_MAX_HOURS) {
            // HARD KILL: auto-complete the ticket
            t.status = "done";
            t.completed_at = new Date().toISOString();
            t.outcome = `AUTO-CLOSED: exceeded ${TICKET_MAX_HOURS}h time limit (ran ${ticketAgeHours.toFixed(1)}h). Circuit breaker triggered to prevent cost drain.`;
            fs.writeFileSync(ticketsPath, JSON.stringify(data, null, 2));
            console.log(`[CIRCUIT-BREAKER] ${t.id} auto-closed after ${ticketAgeHours.toFixed(1)}h (limit: ${TICKET_MAX_HOURS}h)`);
            strategicSystemPrompt += `\n\n[TICKET ${t.id} AUTO-CLOSED — exceeded ${TICKET_MAX_HOURS}h limit]\nYour ticket "${t.title}" was auto-closed by the circuit breaker after ${ticketAgeHours.toFixed(1)} hours.\nIf the work is incomplete, create a NEW ticket with a narrower scope. Do not re-claim the same ticket.`;
          } else {
            strategicSystemPrompt += `\n\n[CURRENT TASK — ${t.id} — DO THIS NOW (${ticketAgeHours.toFixed(1)}h elapsed, ${TICKET_MAX_HOURS}h limit)]\n${t.title}\n\n${(t.description || "").slice(0, 600)}\n\nDO NOT check tickets, check revenue, or start new projects. Execute the steps above and ticket_complete when done. If stuck, use ask_claude_code to get help completing THIS ticket.`;

            // Auto-upgrade to Sonnet for build/code tickets (skip suggestions — keep on Haiku)
            // Cap Sonnet at TICKET_SONNET_CAP_HOURS to prevent cost runaway
            if (t.source !== "suggestion") {
              const ticketTags: string[] = t.tags || [];
              const titleLower = (t.title || "").toLowerCase();
              const isBuildTicket = ticketTags.some((tag: string) => BUILD_TAGS.has(tag.toLowerCase()))
                || BUILD_TAGS.has(titleLower.split(":")[0]?.trim())
                || /\b(build|implement|create|develop|write|deploy|refactor|migrate|sdk|mvp|api)\b/i.test(titleLower);
              if (isBuildTicket && !isStrategicCycle) {
                if (ticketAgeHours <= TICKET_SONNET_CAP_HOURS) {
                  inferenceModel = "claude-sonnet-4-5-20250929";
                  console.log(`[LOOP] Build ticket detected (${t.id}) — upgrading to Sonnet (${ticketAgeHours.toFixed(1)}h/${TICKET_SONNET_CAP_HOURS}h cap)`);
                } else {
                  console.log(`[LOOP] Build ticket ${t.id} past Sonnet cap (${ticketAgeHours.toFixed(1)}h > ${TICKET_SONNET_CAP_HOURS}h) — staying on Haiku`);
                }
              }
            }
          }
        } else {
          // No in-progress ticket — check for open ones
          const openTickets = (data.tickets || [])
            .filter((t: any) => t.status === "open")
            .sort((a: any, b: any) => {
              const prio: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
              return (prio[a.priority] ?? 4) - (prio[b.priority] ?? 4);
            });
          if (openTickets.length > 0) {
            const t = openTickets[0];
            const isSuggestion = t.source === "suggestion";
            if (isSuggestion) {
              strategicSystemPrompt += `\n\n[SUGGESTION — optional task from your inner thoughts]\n${t.id}: ${t.title}\n${(t.description || "").slice(0, 300)}\nClaim with ticket_claim if interesting. Or ticket_complete with outcome "skipped" to dismiss.`;
              // Do NOT upgrade to Sonnet for suggestions — they're exploratory, use Haiku
            } else {
              strategicSystemPrompt += `\n\n[NEXT TASK — claim this with ticket_claim]\n${t.id}: ${t.title}`;
            }
          }
        }
      } catch {}

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

      // Inject behavioral loop warning with escalating intervention
      // Read latest self-critique insight from cooldown_think to feed reflection back into the loop
      let selfCritiqueBlock = "";
      if (pendingLoopWarning) {
        try {
          const insightsPath = path.join(process.env.HOME || "/root", ".automaton", "cooldown_insights.json");
          const raw = fs.readFileSync(insightsPath, "utf-8");
          const insights = JSON.parse(raw);
          if (Array.isArray(insights)) {
            // Find the most recent self_critique insight (< 30 min old)
            const recent = insights
              .filter((i: any) => i.mode === "self_critique" && i.timestamp)
              .sort((a: any, b: any) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
            if (recent.length > 0) {
              const age = Date.now() - new Date(recent[0].timestamp).getTime();
              if (age < 30 * 60 * 1000) {
                selfCritiqueBlock = `\n\n[YOUR OWN REFLECTION — from your self_critique during cooldown]\n${(recent[0].insight || "").slice(0, 500)}\nACT ON THIS INSIGHT. It came from your own analysis.`;
                console.log(`[LOOP-FEEDBACK] Injecting self_critique (${Math.round(age / 60000)}m old, ${selfCritiqueBlock.length}ch)`);
              }
            }
          }
        } catch {}
      }
      if (pendingLoopWarning) {
        if (consecutiveLoopCycles >= 10) {
          // TIER 4: Force restart — text interventions failed, nuke the context window
          log(config, `[LOOP-ESCALATE] TIER 4: FORCE RESTART after ${consecutiveLoopCycles} consecutive loops. Text interventions exhausted.`);
          try {
            const pidFile = "/tmp/tiamat.pid";
            fs.unlinkSync(pidFile);
          } catch {}
          // Clear loop detector history so fresh instance starts clean
          try {
            const loopDetectorPath = path.join(process.env.HOME || "/root", ".automaton", "loop_detector.json");
            fs.writeFileSync(loopDetectorPath, JSON.stringify({
              action_history: [],
              suppressed_actions: [],
              duplicate_threshold: 3,
              window_size: 20,
            }));
          } catch {}
          // Spawn a fresh instance then exit
          const { spawn } = await import("child_process");
          spawn("/root/start-tiamat.sh", [], {
            detached: true,
            stdio: "ignore",
            env: { ...process.env },
          }).unref();
          log(config, `[LOOP-ESCALATE] New instance spawning. Exiting current process.`);
          process.exit(0);
        } else if (consecutiveLoopCycles >= 5) {
          // TIER 3: Force pivot — inject full ticket list, mandate context switch
          let ticketBlock = "(no tickets found)";
          try {
            const ticketsPath = path.join(process.env.HOME || "/root", ".automaton", "tickets.json");
            const raw = fs.readFileSync(ticketsPath, "utf-8");
            const data = JSON.parse(raw);
            const open = (data.tickets || [])
              .filter((t: any) => t.status === "open" || t.status === "in_progress")
              .sort((a: any, b: any) => {
                const prio: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
                return (prio[a.priority] ?? 4) - (prio[b.priority] ?? 4);
              });
            if (open.length > 0) {
              ticketBlock = open.map((t: any) =>
                `- ${t.id} [${t.priority}] ${t.title}: ${(t.description || "").slice(0, 120)}`
              ).join("\n");
            }
          } catch {}
          log(config, `[LOOP-ESCALATE] TIER 3: Forced pivot after ${consecutiveLoopCycles} consecutive loops`);
          strategicSystemPrompt += `\n\n[FORCED PIVOT — LOOP DETECTED ${consecutiveLoopCycles} CONSECUTIVE CYCLES]\nYou have been stuck in a loop for ${consecutiveLoopCycles} cycles. Your current approach is NOT WORKING.\nMANDATORY: Pick a DIFFERENT ticket from below and work on it. Do NOT continue what you were doing.\n\nOpen tickets:\n${ticketBlock}\n\nInstructions: Call ticket_list(), then ticket_claim() on a DIFFERENT ticket than what you've been working on.${selfCritiqueBlock}`;
        } else if (consecutiveLoopCycles >= 3) {
          // TIER 2: Inject watchdog tickets + stronger warning
          let ticketBlock = "";
          try {
            const ticketsPath = path.join(process.env.HOME || "/root", ".automaton", "tickets.json");
            const raw = fs.readFileSync(ticketsPath, "utf-8");
            const data = JSON.parse(raw);
            const watchdog = (data.tickets || [])
              .filter((t: any) => t.source === "watchdog" && (t.status === "open" || t.status === "in_progress"));
            if (watchdog.length > 0) {
              ticketBlock = "\n\nWATCHDOG ALERTS (unresolved):\n" + watchdog.map((t: any) =>
                `- ${t.id} [${t.priority}] ${t.title}: ${(t.description || "").slice(0, 120)}`
              ).join("\n");
            }
          } catch {}
          log(config, `[LOOP-ESCALATE] TIER 2: Strong warning after ${consecutiveLoopCycles} consecutive loops`);
          strategicSystemPrompt += `\n\n[LOOP WARNING — ${consecutiveLoopCycles} CONSECUTIVE CYCLES]\n${pendingLoopWarning}${ticketBlock}\n\nYou MUST address these issues or switch to a different ticket. Your current approach is failing.${selfCritiqueBlock}`;
        } else {
          // TIER 1: Soft nudge (original behavior) + self-critique if available
          strategicSystemPrompt += `\n\n[LOOP WARNING]\n${pendingLoopWarning}${selfCritiqueBlock}`;
        }
      }

      // Inject pacer state so TIAMAT knows her pace tier and Claude Code budget
      try {
        const pacerState = loadPacer();
        const ccBudget = pacerState.claude_code_budget_cycles;
        const ccSinceLast = pacerState.claude_code_uses_since_last;
        const ccAllowed = ccSinceLast >= ccBudget;
        strategicSystemPrompt += `\n\n[PACER] pace:${pacerState.current_pace} interval:${pacerState.current_interval_seconds}s productivity:${pacerState.productivity_rate.toFixed(2)} claude_code:${ccAllowed ? "ALLOWED" : `wait ${ccBudget - ccSinceLast} more cycles`}`;
        if (pacerState.current_pace === "reflect") {
          strategicSystemPrompt += `\n⚠️ REFLECT MODE: You are stuck. Call introspect() and ticket_list() this cycle. Try a completely different approach.`;
        }
      } catch {}

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

      // Sonnet gets 4096 tokens (strategic bursts + build tickets), Haiku gets 2048
      const usingSonnet = isStrategicCycle || inferenceModel?.includes("sonnet");
      const maxTokensThisCycle = usingSonnet ? 4096 : 2048;

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

          const toolStartMs = Date.now();
          const result = await executeTool(
            tc.function.name,
            args,
            tools,
            toolContext,
          );
          const toolDurationMs = Date.now() - toolStartMs;

          // Override the ID to match the inference call's ID
          result.id = tc.id;
          turn.toolCalls.push(result);

          log(
            config,
            `[TOOL RESULT] ${tc.function.name}: ${result.error ? `ERROR: ${result.error}` : result.result.slice(0, 500)}`,
          );

          // Auto-track tool reliability
          try {
            memory.recordToolOutcome(
              tc.function.name,
              !result.error,
              toolDurationMs,
              result.error || undefined,
            );
          } catch {}

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

      // ── Behavioral Loop Detection ──
      // Detects repeated actions across cycles (not just error loops)
      try {
        const loopWarning = checkBehavioralLoop(
          turnCount,
          turn.toolCalls.map(tc => ({ name: tc.name, arguments: tc.arguments })),
        );
        if (loopWarning) {
          consecutiveLoopCycles++;
          log(config, `[LOOP-DETECT] (consecutive: ${consecutiveLoopCycles}) ${loopWarning}`);
          pendingLoopWarning = loopWarning;
        } else {
          pendingLoopWarning = null;
          consecutiveLoopCycles = 0;
        }
      } catch (e: any) {
        console.log(`[LOOP-DETECT] Error: ${e.message?.slice(0, 100)}`);
      }

      // ── Persist Turn (skip empty turns to prevent context poisoning) ──
      if (turn.thinking.trim() || turn.toolCalls.length > 0) {
        db.insertTurn(turn);
        for (const tc of turn.toolCalls) {
          db.insertToolCall(turn.id, tc);
        }
        onTurnComplete?.(turn);
      } else {
        console.log(`[LOOP] Skipping empty turn — no thinking or tool calls (likely empty API response)`);
      }

      // ── Auto-remember: store a memory for every non-empty cycle ──
      if (turn.thinking.trim() || turn.toolCalls.length > 0) {
        try {
          const toolNames = turn.toolCalls.map(tc => tc.name);
          const hasErrors = turn.toolCalls.some(tc => !!tc.error);
          const revenueTools = ["post_bluesky", "post_farcaster", "farcaster_engage", "generate_image"];
          const isRevenue = toolNames.some(t => revenueTools.includes(t));

          // Determine memory type and importance
          let memType = "observation";
          let memImportance = 0.4;
          if (hasErrors) { memType = "error"; memImportance = 0.7; }
          else if (isStrategicCycle) { memType = "strategy"; memImportance = 0.7; }
          else if (isRevenue) { memType = "outcome"; memImportance = 0.6; }

          // Build concise summary
          const thinkSnippet = turn.thinking.trim().slice(0, 120);
          const toolSummary = toolNames.length > 0 ? `Tools: ${toolNames.join(", ")}` : "No tools";
          const errorBits = turn.toolCalls
            .filter(tc => tc.error)
            .map(tc => `${tc.name}: ${tc.error!.slice(0, 60)}`)
            .join("; ");
          const content = [
            thinkSnippet,
            toolSummary,
            errorBits ? `Errors: ${errorBits}` : "",
          ].filter(Boolean).join(" | ").slice(0, 300);

          await memory.remember({
            type: memType,
            content,
            importance: memImportance,
            cycle: db.getTurnCount(),
            metadata: { tools: toolNames, phase: burstPhase || 0 },
          });
        } catch {}
      }

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

      // ── Adaptive Pacer: dynamic cycle pacing based on productivity ──
      {
        const toolNames = turn.toolCalls.map(tc => tc.name);
        const cycleCost = estimateCostCents(turn.tokenUsage, inference.getDefaultModel()) / 100;

        // Update pacer with this cycle's data
        const pacerResult: PacerUpdate = updatePacer(turnCount, toolNames, cycleCost);

        // Track idle streaks for consolidation sleep
        if (pacerResult.pace === "idle" || pacerResult.pace === "reflect") {
          consecutiveIdleCycles++;
        } else {
          consecutiveIdleCycles = 0;
        }

        // Log pace tier changes to growth system
        if (pacerResult.pace_changed && pacerResult.previous_pace) {
          try {
            const growthTools = tools.find(t => t.name === "grow");
            if (growthTools) {
              const rate = (pacerResult.productivity_rate * 100).toFixed(0);
              if (pacerResult.pace === "sprint" || pacerResult.pace === "active") {
                await growthTools.execute(
                  { category: "milestone", entry: `Entered ${pacerResult.pace} mode — productivity at ${rate}%` },
                  toolContext,
                );
              } else {
                await growthTools.execute(
                  { category: "lesson", entry: `Dropped to ${pacerResult.pace} mode from ${pacerResult.previous_pace} — productivity at ${rate}%` },
                  toolContext,
                );
              }
            }
          } catch {}
        }

        // Run auto-cron tasks
        try {
          const cronResults = checkCronTasks(turnCount);
          for (const cr of cronResults) {
            if (cr.output) {
              log(config, `[CRON] ${cr.name}: ${cr.output.slice(0, 150)}`);
            } else if (cr.error) {
              log(config, `[CRON] ${cr.name} ERROR: ${cr.error.slice(0, 150)}`);
            }
          }
        } catch (e: any) {
          console.log(`[CRON] Error: ${e.message?.slice(0, 100)}`);
        }

        // Skip delay between burst cycles to keep Anthropic cache warm (5-min TTL)
        if (burstRemaining > 0) {
          cycleDelay = 5_000;
          console.log(`[LOOP] Burst continues (${burstRemaining} remaining) — skipping delay.`);
          await new Promise(resolve => setTimeout(resolve, cycleDelay));
        } else {
          cycleDelay = pacerResult.interval_ms;
          console.log(`[LOOP] Cycle complete. Next in ${Math.round(cycleDelay / 1000)}s (pace:${pacerResult.pace}, prod:${pacerResult.productivity_rate.toFixed(2)}).`);
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
    interval: 2,      // every 2 cycles (script has its own 5-min rate limit)
    offset: 0,        // fires on cycles 2, 4, 6...
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
  {
    name: "dx_terminal_check",
    command: ["python3", ["dx_terminal.py", "alert"]],
    interval: 10,     // every 10 cycles (~15-30 min)
    offset: 5,        // fires on cycles 5, 15, 25...
    timeout: 30_000,
    minWindow: 40_000,
  },
  {
    name: "github_engage",
    command: ["python3", ["github_engage.py", "engage"]],
    interval: 5,      // every 5 cycles (~10-20 min)
    offset: 3,        // fires on cycles 3, 8, 13...
    timeout: 45_000,
    minWindow: 55_000,
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

  // ── Phase 0: Retry pending social posts (zero LLM tokens) ──
  try {
    const pendingPath = path.join(process.env.HOME || "/root", ".automaton", "pending_posts.json");
    if (fs.existsSync(pendingPath)) {
      const pending: any[] = JSON.parse(fs.readFileSync(pendingPath, "utf-8"));
      if (pending.length > 0) {
        // Check if bluesky cooldown has expired
        const cooldownsPath = path.join(process.env.HOME || "/root", ".automaton", "social_cooldowns.json");
        let cooldowns: Record<string, number> = {};
        try { cooldowns = JSON.parse(fs.readFileSync(cooldownsPath, "utf-8")); } catch {}
        const SOCIAL_COOLDOWN_MS = 61 * 60 * 1000;

        const remaining: any[] = [];
        for (const post of pending) {
          const lastPost = cooldowns[post.platform] || 0;
          const elapsed = Date.now() - lastPost;
          if (elapsed >= SOCIAL_COOLDOWN_MS && timeLeft() > 15_000) {
            // Cooldown expired — execute the post
            const result = runTask(
              `retry_post_${post.platform}`,
              "node", ["-e", `
                const args = JSON.parse(process.argv[1]);
                const handle = process.env.BLUESKY_HANDLE;
                const appPassword = process.env.BLUESKY_APP_PASSWORD;
                if (!handle || !appPassword) { console.log("ERROR: no creds"); process.exit(1); }
                (async () => {
                  const sess = await fetch("https://bsky.social/xrpc/com.atproto.server.createSession", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({identifier: handle, password: appPassword}),
                  });
                  if (!sess.ok) { console.log("AUTH_FAIL"); process.exit(1); }
                  const {accessJwt, did} = await sess.json();
                  const record = {$type: "app.bsky.feed.post", text: args.text, createdAt: new Date().toISOString()};
                  const resp = await fetch("https://bsky.social/xrpc/com.atproto.repo.createRecord", {
                    method: "POST", headers: {"Content-Type": "application/json", "Authorization": "Bearer " + accessJwt},
                    body: JSON.stringify({repo: did, collection: "app.bsky.feed.post", record}),
                  });
                  if (!resp.ok) { console.log("POST_FAIL:" + resp.status); process.exit(1); }
                  const r = await resp.json();
                  console.log("POSTED:" + r.uri);
                })();
              `, JSON.stringify(post.args)],
              "/root/entity",
              15_000,
            );
            if (result && result.includes("POSTED:")) {
              // Update cooldown timestamp
              cooldowns[post.platform] = Date.now();
              fs.writeFileSync(cooldownsPath, JSON.stringify(cooldowns, null, 2), "utf-8");
              log(config, `[COOLDOWN] Retried pending ${post.platform} post: ${result.trim()}`);
            } else {
              remaining.push(post); // retry failed, keep in queue
            }
          } else {
            remaining.push(post); // still on cooldown, keep in queue
          }
        }
        // Prune posts older than 24h
        const cutoff = Date.now() - 24 * 60 * 60 * 1000;
        const kept = remaining.filter((p: any) => new Date(p.queued_at).getTime() > cutoff);
        fs.writeFileSync(pendingPath, JSON.stringify(kept, null, 2), "utf-8");
      }
    }
  } catch (e: any) {
    console.log(`[COOLDOWN] Pending post retry error: ${e.message?.slice(0, 150)}`);
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
