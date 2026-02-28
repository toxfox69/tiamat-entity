/**
 * TIAMAT Adaptive Pacer
 *
 * Dynamically adjusts cycle interval based on rolling productivity.
 * Tracks last 20 cycles, scoring each as "productive" or not.
 *
 * Pace tiers (CC backend = free inference):
 *   sprint  (>= 0.7) — 15s interval, Claude Code 1/3 cycles
 *   active  (0.4-0.7) — 30s interval, Claude Code 1/5 cycles
 *   idle    (0.2-0.4) — 60s interval, Claude Code 1/10 cycles
 *   reflect (< 0.2)   — 90s interval, force introspect + ticket review
 *
 * State persisted to /root/.automaton/pacer.json
 * Auto-cron tasks in /root/.automaton/crontasks.json
 */

import { readFileSync, writeFileSync } from "fs";

const PACER_PATH = "/root/.automaton/pacer.json";
const CRONTASKS_PATH = "/root/.automaton/crontasks.json";

// ─── Types ────────────────────────────────────────────────────

export type PaceTier = "sprint" | "active" | "idle" | "reflect";

export interface CycleRecord {
  cycle: number;
  actions: string[];
  productive: boolean;
  cost: number;
  timestamp: string;
}

export interface PacerState {
  last_20_cycles: CycleRecord[];
  productivity_rate: number;
  current_pace: PaceTier;
  current_interval_seconds: number;
  claude_code_uses_since_last: number;
  claude_code_budget_cycles: number; // use 1 per this many cycles
  last_pace_change: string | null;
  last_pace_change_from: PaceTier | null;
  total_pace_changes: number;
}

export interface CronTask {
  id: string;
  name: string;
  command: string;
  schedule_type: "cycles" | "minutes";
  schedule_value: number;
  last_run_cycle: number | null;
  last_run_time: string | null;
  last_result: string | null;
  created_by_ticket: string | null;
  enabled: boolean;
  created_at: string;
}

export interface CronState {
  tasks: CronTask[];
}

// ─── Productive Action Sets ───────────────────────────────────

/** Tools that count as productive when used in a cycle */
const PRODUCTIVE_TOOLS = new Set([
  // Revenue / customer actions
  "deploy_app",
  // Content publishing
  "post_bluesky", "post_farcaster", "post_instagram", "post_facebook",
  "publish_devto",
  // Building
  "ask_claude_code", "self_improve", "write_file",
  // Growth/cognitive
  "grow", "evolve_era",
  // Ticket progress
  "ticket_claim", "ticket_complete", "ticket_create",
  // Image generation (part of content pipeline)
  "generate_image",
  // Research that leads to action
  "search_web", "web_fetch",
  // Agent interactions
  "send_email", "send_telegram",
  // Infrastructure
  "exec", "spawn_child",
  // Learning
  "learn_fact", "remember",
]);

/** Tools that are definitely NOT productive (status checks, reads) */
const UNPRODUCTIVE_TOOLS = new Set([
  "read_file", "ticket_list", "check_opportunities",
  "read_farcaster", "read_email", "search_email",
  "introspect", "manage_cooldown",
]);

// ─── Pacer State I/O ─────────────────────────────────────────

export function loadPacer(): PacerState {
  try {
    return JSON.parse(readFileSync(PACER_PATH, "utf-8"));
  } catch {
    return {
      last_20_cycles: [],
      productivity_rate: 0.5,
      current_pace: "active",
      current_interval_seconds: 60,
      claude_code_uses_since_last: 0,
      claude_code_budget_cycles: 10,
      last_pace_change: null,
      last_pace_change_from: null,
      total_pace_changes: 0,
    };
  }
}

export function savePacer(state: PacerState): void {
  writeFileSync(PACER_PATH, JSON.stringify(state, null, 2), "utf-8");
}

// ─── Cron State I/O ──────────────────────────────────────────

export function loadCronTasks(): CronState {
  try {
    return JSON.parse(readFileSync(CRONTASKS_PATH, "utf-8"));
  } catch {
    return { tasks: [] };
  }
}

export function saveCronTasks(state: CronState): void {
  writeFileSync(CRONTASKS_PATH, JSON.stringify(state, null, 2), "utf-8");
}

// ─── Productivity Scoring ─────────────────────────────────────

/**
 * Score a cycle as productive or not based on the tools used.
 * A cycle is productive if it used ANY productive tool.
 */
export function scoreCycle(toolNames: string[]): boolean {
  if (toolNames.length === 0) return false;
  return toolNames.some(name => PRODUCTIVE_TOOLS.has(name));
}

// ─── Pace Tier Calculation ────────────────────────────────────

interface PaceTierConfig {
  interval: number;       // seconds
  claudeCodeBudget: number; // 1 call per N cycles
}

const PACE_TIERS: Record<PaceTier, PaceTierConfig> = {
  sprint:  { interval: 60,   claudeCodeBudget: 3 },
  active:  { interval: 120,  claudeCodeBudget: 5 },
  idle:    { interval: 300,  claudeCodeBudget: 10 },   // 5 min — no point spinning faster
  reflect: { interval: 600,  claudeCodeBudget: 15 },   // 10 min — nothing to do, wait
};

function rateToPace(rate: number): PaceTier {
  if (rate >= 0.7) return "sprint";
  if (rate >= 0.4) return "active";
  if (rate >= 0.2) return "idle";
  return "reflect";
}

// ─── Main Pacer Update ───────────────────────────────────────

export interface PacerUpdate {
  interval_ms: number;
  pace: PaceTier;
  productivity_rate: number;
  pace_changed: boolean;
  previous_pace: PaceTier | null;
  claude_code_allowed: boolean;
  force_introspect: boolean;
  force_ticket_review: boolean;
}

/**
 * Record a cycle and compute the next interval.
 * Called from loop.ts after each turn completes.
 * Pass blocked=true for rate-limit spin cycles so they don't corrupt the
 * productivity window — they represent infrastructure failure, not poor decisions.
 */
export function updatePacer(
  cycle: number,
  toolNames: string[],
  cost: number,
  blocked = false,
): PacerUpdate {
  const state = loadPacer();
  const now = new Date().toISOString();
  const productive = !blocked && scoreCycle(toolNames);

  // Skip recording fully-blocked cycles: they don't reflect actual agent decisions.
  if (!blocked) {
    state.last_20_cycles.push({
      cycle,
      actions: toolNames.slice(0, 10), // cap to prevent bloat
      productive,
      cost,
      timestamp: now,
    });

    // Keep only last 20
    if (state.last_20_cycles.length > 20) {
      state.last_20_cycles = state.last_20_cycles.slice(-20);
    }
  }

  // Calculate productivity rate
  const productiveCount = state.last_20_cycles.filter(c => c.productive).length;
  const total = state.last_20_cycles.length;
  state.productivity_rate = total > 0 ? productiveCount / total : 0.5;

  // Determine pace tier
  const newPace = rateToPace(state.productivity_rate);
  const paceChanged = newPace !== state.current_pace;
  const previousPace = state.current_pace;

  if (paceChanged) {
    state.last_pace_change_from = previousPace;
    state.last_pace_change = now;
    state.total_pace_changes++;
  }

  state.current_pace = newPace;
  const tierConfig = PACE_TIERS[newPace];
  state.current_interval_seconds = tierConfig.interval;
  state.claude_code_budget_cycles = tierConfig.claudeCodeBudget;

  // Track Claude Code usage for budget enforcement
  const usedClaudeCode = toolNames.includes("ask_claude_code");
  if (usedClaudeCode) {
    state.claude_code_uses_since_last = 0;
  } else {
    state.claude_code_uses_since_last++;
  }

  const claudeCodeAllowed = state.claude_code_uses_since_last >= state.claude_code_budget_cycles;

  savePacer(state);

  console.log(
    `[PACER] productivity: ${state.productivity_rate.toFixed(2)} ` +
    `(${productiveCount}/${total}) → pace: ${newPace} (${tierConfig.interval}s)` +
    (paceChanged ? ` [CHANGED from ${previousPace}]` : "")
  );

  return {
    interval_ms: tierConfig.interval * 1000,
    pace: newPace,
    productivity_rate: state.productivity_rate,
    pace_changed: paceChanged,
    previous_pace: paceChanged ? previousPace : null,
    claude_code_allowed: claudeCodeAllowed,
    force_introspect: newPace === "reflect",
    force_ticket_review: newPace === "reflect",
  };
}

// ─── Cron Check ──────────────────────────────────────────────

export interface CronResult {
  id: string;
  name: string;
  output: string | null;
  error: string | null;
}

/**
 * Check and run any due cron tasks. Called from loop.ts each cycle.
 * Returns results of tasks that ran.
 */
export function checkCronTasks(
  currentCycle: number,
): CronResult[] {
  const state = loadCronTasks();
  const results: CronResult[] = [];
  const now = Date.now();
  let changed = false;

  for (const task of state.tasks) {
    if (!task.enabled) continue;

    let shouldRun = false;

    if (task.schedule_type === "cycles") {
      if (task.last_run_cycle === null) {
        shouldRun = true;
      } else {
        shouldRun = (currentCycle - task.last_run_cycle) >= task.schedule_value;
      }
    } else if (task.schedule_type === "minutes") {
      if (task.last_run_time === null) {
        shouldRun = true;
      } else {
        const elapsed = (now - new Date(task.last_run_time).getTime()) / 60_000;
        shouldRun = elapsed >= task.schedule_value;
      }
    }

    if (!shouldRun) continue;

    // Run the command
    try {
      const { execFileSync } = require("child_process");
      // Split command for safe execution
      const parts = task.command.split(/\s+/);
      const cmd = parts[0];
      const args = parts.slice(1);
      const output = execFileSync(cmd, args, {
        encoding: "utf-8",
        timeout: 30_000,
        cwd: "/root",
        env: { ...process.env },
      });

      task.last_run_cycle = currentCycle;
      task.last_run_time = new Date().toISOString();
      task.last_result = output.trim().slice(0, 500);
      changed = true;

      results.push({ id: task.id, name: task.name, output: output.trim().slice(0, 300), error: null });
    } catch (e: any) {
      task.last_run_cycle = currentCycle;
      task.last_run_time = new Date().toISOString();
      task.last_result = `ERROR: ${e.message?.slice(0, 200)}`;
      changed = true;

      results.push({ id: task.id, name: task.name, output: null, error: e.message?.slice(0, 200) || "unknown" });
    }
  }

  if (changed) {
    saveCronTasks(state);
  }

  return results;
}

/**
 * Get a summary of pacer state for the /pacer API endpoint.
 */
export function getPacerSummary(): {
  pace: PaceTier;
  interval_seconds: number;
  productivity_rate: number;
  productive_count: number;
  total_cycles: number;
  last_20: CycleRecord[];
  claude_code_budget: number;
  claude_code_cycles_until_allowed: number;
  last_pace_change: string | null;
  total_pace_changes: number;
  cron_tasks: CronTask[];
} {
  const pacer = loadPacer();
  const cron = loadCronTasks();

  const cyclesUntilAllowed = Math.max(
    0,
    pacer.claude_code_budget_cycles - pacer.claude_code_uses_since_last,
  );

  return {
    pace: pacer.current_pace,
    interval_seconds: pacer.current_interval_seconds,
    productivity_rate: pacer.productivity_rate,
    productive_count: pacer.last_20_cycles.filter(c => c.productive).length,
    total_cycles: pacer.last_20_cycles.length,
    last_20: pacer.last_20_cycles,
    claude_code_budget: pacer.claude_code_budget_cycles,
    claude_code_cycles_until_allowed: cyclesUntilAllowed,
    last_pace_change: pacer.last_pace_change,
    total_pace_changes: pacer.total_pace_changes,
    cron_tasks: cron.tasks,
  };
}
