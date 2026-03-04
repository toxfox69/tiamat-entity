/**
 * Circuit Breaker — Prevent retry storms
 * NEW FILE (not in forbid list) — provides fault tolerance without modifying core loop
 *
 * Two systems live here:
 *   1. In-memory CircuitBreaker class (used for inference providers)
 *   2. File-backed tool circuit breaker (spawn_child, git_commit, etc.)
 *      State persisted to /root/.automaton/tool_circuit_breaker.json
 *      States: CLOSED → OPEN → HALF_OPEN
 *      Trigger: 3 consecutive failures → OPEN
 *      Backoff:  1s → 2s → 4s → 8s → … → 60s max (doubles each re-open)
 */

import * as fs from 'fs';
import * as path from 'path';

// ============================================================
// SECTION 2 — File-backed tool circuit breaker
// ============================================================

const TOOL_STATE_FILE = '/root/.automaton/tool_circuit_breaker.json';
const TOOL_FAILURE_THRESHOLD = 3;
const TOOL_RETRY_BASE_MS    = 1_000;   // 1s initial backoff
const TOOL_MAX_RETRY_MS     = 60_000;  // 60s ceiling

type ToolCircuitState = 'CLOSED' | 'OPEN' | 'HALF_OPEN';

interface ToolCircuitEntry {
  state: ToolCircuitState;
  failures: number;
  last_fail: string | null;
  cooldown_until: string | null;
  /** How many times the circuit has re-opened; drives exponential backoff */
  backoff_level: number;
}

interface ToolCircuitData {
  tools: Record<string, ToolCircuitEntry>;
}

/** Tools that receive circuit-breaker protection by default */
export const PROTECTED_TOOLS = [
  'spawn_child',
  'git_commit',
  'post_tweet',
  'github_comment',
];

function _toolDefaultEntry(): ToolCircuitEntry {
  return { state: 'CLOSED', failures: 0, last_fail: null, cooldown_until: null, backoff_level: 0 };
}

function _toolBackoffMs(level: number): number {
  return Math.min(TOOL_RETRY_BASE_MS * Math.pow(2, level), TOOL_MAX_RETRY_MS);
}

function _toolLoad(): ToolCircuitData {
  try {
    const raw = fs.readFileSync(TOOL_STATE_FILE, 'utf-8');
    const data = JSON.parse(raw) as ToolCircuitData;
    for (const t of PROTECTED_TOOLS) {
      if (!data.tools[t]) data.tools[t] = _toolDefaultEntry();
    }
    return data;
  } catch {
    const data: ToolCircuitData = { tools: {} };
    for (const t of PROTECTED_TOOLS) data.tools[t] = _toolDefaultEntry();
    return data;
  }
}

function _toolSave(data: ToolCircuitData): void {
  const dir = path.dirname(TOOL_STATE_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(TOOL_STATE_FILE, JSON.stringify(data, null, 2), 'utf-8');
}

function _toolGetOrCreate(data: ToolCircuitData, toolName: string): ToolCircuitEntry {
  if (!data.tools[toolName]) data.tools[toolName] = _toolDefaultEntry();
  return data.tools[toolName];
}

/**
 * Returns true if the tool is currently blocked by an active cooldown.
 *
 * Side-effect: automatically transitions OPEN → HALF_OPEN when the
 * cooldown timer expires, allowing one test call through.
 */
export function isCooledDown(toolName: string): boolean {
  const data = _toolLoad();
  const tool = _toolGetOrCreate(data, toolName);

  if (tool.state === 'CLOSED' || tool.state === 'HALF_OPEN') return false;

  // OPEN — check if timer has expired
  const cooldownUntil = tool.cooldown_until ? new Date(tool.cooldown_until).getTime() : 0;
  if (Date.now() < cooldownUntil) return true; // still blocked

  // Timer expired — promote to HALF_OPEN and let one call through
  tool.state = 'HALF_OPEN';
  _toolSave(data);
  return false;
}

/**
 * Record a failure for a tool.
 *
 * - CLOSED:    increments counter; opens circuit after TOOL_FAILURE_THRESHOLD
 * - HALF_OPEN: test call failed — re-opens circuit with doubled backoff
 */
export function recordFailure(toolName: string): void {
  const data = _toolLoad();
  const tool = _toolGetOrCreate(data, toolName);

  tool.failures += 1;
  tool.last_fail = new Date().toISOString();

  if (tool.state === 'HALF_OPEN') {
    // Test call failed — increase backoff and re-open
    tool.backoff_level += 1;
    tool.state = 'OPEN';
    tool.cooldown_until = new Date(Date.now() + _toolBackoffMs(tool.backoff_level)).toISOString();
  } else if (tool.state === 'CLOSED' && tool.failures >= TOOL_FAILURE_THRESHOLD) {
    // Hit threshold — open the circuit
    tool.state = 'OPEN';
    tool.cooldown_until = new Date(Date.now() + _toolBackoffMs(tool.backoff_level)).toISOString();
    tool.backoff_level += 1;
  }

  _toolSave(data);

  if (tool.state === 'OPEN') {
    const secsLeft = Math.ceil((new Date(tool.cooldown_until!).getTime() - Date.now()) / 1000);
    console.error(
      `[circuit_breaker] ${toolName}: OPEN — ${tool.failures} failures, ` +
      `cooldown ${secsLeft}s (backoff_level=${tool.backoff_level - 1})`
    );
  }
}

/**
 * Record a success. Resets all failure state and closes the circuit.
 */
export function recordSuccess(toolName: string): void {
  const data = _toolLoad();
  const tool = _toolGetOrCreate(data, toolName);
  const wasOpen = tool.state !== 'CLOSED';

  tool.state        = 'CLOSED';
  tool.failures     = 0;
  tool.last_fail    = null;
  tool.cooldown_until = null;
  tool.backoff_level  = 0;

  _toolSave(data);
  if (wasOpen) console.error(`[circuit_breaker] ${toolName}: CLOSED (recovered)`);
}

/**
 * Returns milliseconds until the tool's cooldown expires.
 * Returns 0 if the tool is not in cooldown (CLOSED or HALF_OPEN).
 */
export function getCooldownMs(toolName: string): number {
  const data = _toolLoad();
  const tool = _toolGetOrCreate(data, toolName);
  if (tool.state !== 'OPEN' || !tool.cooldown_until) return 0;
  return Math.max(0, new Date(tool.cooldown_until).getTime() - Date.now());
}

/**
 * Returns the full state snapshot for one tool, or all tools if no name given.
 */
export function getToolState(toolName?: string): ToolCircuitEntry | Record<string, ToolCircuitEntry> {
  const data = _toolLoad();
  if (toolName) return _toolGetOrCreate(data, toolName);
  return data.tools;
}

// ============================================================
// SECTION 1 — In-memory CircuitBreaker class (inference providers)
// ============================================================

export interface CircuitBreakerConfig {
  name: string;
  failureThreshold: number;  // failures before open
  resetTimeout: number;      // ms before half-open
  monitorWindow: number;     // ms for failure counting
}

export class CircuitBreaker {
  private state: 'closed' | 'open' | 'half-open' = 'closed';
  private failures: number = 0;
  private lastFailureTime: number = 0;
  private nextResetTime: number = 0;
  private config: CircuitBreakerConfig;

  constructor(config: CircuitBreakerConfig) {
    this.config = config;
  }

  /**
   * Guard: should we execute this operation?
   */
  public canExecute(): boolean {
    if (this.state === 'closed') return true;
    if (this.state === 'half-open') return true; // Allow one test
    
    // Open state: check if reset timeout expired
    if (Date.now() >= this.nextResetTime) {
      this.state = 'half-open';
      console.log(`[CIRCUIT] ${this.config.name} → half-open (testing)`);
      return true;
    }
    
    return false;
  }

  /**
   * Record success — move toward closed
   */
  public recordSuccess(): void {
    if (this.state === 'half-open') {
      this.state = 'closed';
      this.failures = 0;
      console.log(`[CIRCUIT] ${this.config.name} → closed (recovered)`);
    }
  }

  /**
   * Record failure — move toward open
   */
  public recordFailure(): void {
    const now = Date.now();
    
    // Reset counter if outside monitor window
    if (now - this.lastFailureTime > this.config.monitorWindow) {
      this.failures = 0;
    }
    
    this.failures++;
    this.lastFailureTime = now;
    
    if (this.failures >= this.config.failureThreshold) {
      this.state = 'open';
      this.nextResetTime = now + this.config.resetTimeout;
      console.log(`[CIRCUIT] ${this.config.name} → OPEN (too many failures: ${this.failures})`);
    }
  }

  public getState(): string {
    return this.state;
  }

  public getStats(): { state: string; failures: number; nextReset?: number } {
    return {
      state: this.state,
      failures: this.failures,
      nextReset: this.state === 'open' ? this.nextResetTime - Date.now() : undefined
    };
  }
}

/**
 * Provider health registry — tracks each inference provider
 */
export const PROVIDER_CIRCUIT_BREAKERS = {
  anthropic: new CircuitBreaker({
    name: 'Anthropic',
    failureThreshold: 3,
    resetTimeout: 30000, // 30s
    monitorWindow: 60000  // 60s window
  }),
  groq: new CircuitBreaker({
    name: 'Groq',
    failureThreshold: 3,
    resetTimeout: 20000,
    monitorWindow: 60000
  }),
  cerebras: new CircuitBreaker({
    name: 'Cerebras',
    failureThreshold: 2,
    resetTimeout: 40000,
    monitorWindow: 60000
  }),
  gemini: new CircuitBreaker({
    name: 'Gemini',
    failureThreshold: 3,
    resetTimeout: 30000,
    monitorWindow: 60000
  }),
  openrouter: new CircuitBreaker({
    name: 'OpenRouter',
    failureThreshold: 3,
    resetTimeout: 30000,
    monitorWindow: 60000
  })
};

/**
 * Get all healthy providers (for parallel racing)
 */
export function getHealthyProviders(): string[] {
  return Object.entries(PROVIDER_CIRCUIT_BREAKERS)
    .filter(([_, cb]) => cb.canExecute())
    .map(([name, _]) => name);
}

/**
 * Get circuit breaker stats for monitoring
 */
export function getAllStats() {
  const stats: Record<string, any> = {};
  for (const [name, cb] of Object.entries(PROVIDER_CIRCUIT_BREAKERS)) {
    stats[name] = cb.getStats();
  }
  return stats;
}
