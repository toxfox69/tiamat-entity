/**
 * Directive System — Structured task queue replacing INBOX.md prose
 *
 * The loop code enforces behavior (cycle scheduling, tool gating,
 * completion detection) instead of asking the LLM nicely in prose.
 */

import fs from "fs";
import path from "path";

// ── Types ──

export type CycleType = "build" | "engage" | "publish" | "outreach";
export type DirectiveStatus = "pending" | "active" | "completed" | "expired" | "failed";
export type DirectiveSource = "operator" | "inbox_convert" | "self_evolve" | "echo_signal";

export interface Directive {
  id: string;
  type: CycleType;
  priority: number;              // 0=critical, 1=high, 2=medium, 3=low
  status: DirectiveStatus;
  task: string;                  // Single sentence: what to do
  details?: string;              // Extra context (max ~200 chars injected)
  completion_tool: string;       // Tool that must succeed
  completion_match?: string;     // Regex on tool args/result
  created_at: string;
  expires_at: string | null;     // null = no expiry
  started_at?: string;
  completed_at?: string;
  fail_count?: number;
  source: DirectiveSource;
}

export interface DirectiveFile {
  version: 1;
  cycle_counter: number;
  active_directive_id: string | null;
  directives: Directive[];
  forbidden_tools: string[];
  tool_overrides: Record<string, number>;
}

// ── Constants ──

const DIRECTIVES_PATH = path.join(process.env.HOME || "/root", ".automaton", "directives.json");

const DEFAULT_ROTATION: CycleType[] = ["build", "build", "build", "build", "build", "publish"];

const CYCLE_TOOL_LIMITS: Record<CycleType, Record<string, number>> = {
  build:    { search_web: 1, web_fetch: 1, ticket_create: 0, ticket_list: 0, ticket_claim: 0, read_email: 0 },
  engage:   { ticket_create: 0 },  // ask_claude_code UNBLOCKED — kernel needs it for all work
  publish:  { search_web: 1, ticket_create: 0, ticket_list: 0, ticket_claim: 0, read_email: 0 },
  outreach: { ticket_create: 0, ticket_list: 0 },
};

const SELF_EVOLVE_DIRECTIVES: Omit<Directive, "id" | "created_at" | "expires_at" | "source" | "status">[] = [
  { type: "build", priority: 2, task: "check_jobs and work on the highest priority active job. Use ask_claude_code for writing tasks.", completion_tool: "update_job" },
  { type: "build", priority: 2, task: "check_hive for cell escalations. Act on any findings that need kernel attention.", completion_tool: "check_hive" },
  { type: "build", priority: 3, task: "Review /root/.automaton/research/ for papers that need updates or new data. Use ask_claude_code.", completion_tool: "write_file" },
  { type: "build", priority: 3, task: "Improve TIAMAT OS architecture: memory compression, job queue, cell management, or inference routing.", completion_tool: "write_file" },
  { type: "publish", priority: 3, task: "Post ONE update about completed work on Bluesky. Focus on what was shipped, not engagement metrics.", completion_tool: "post_bluesky" },
];

// ── Core Functions ──

function emptyDirectiveFile(): DirectiveFile {
  return {
    version: 1,
    cycle_counter: 0,
    active_directive_id: null,
    directives: [],
    forbidden_tools: [],
    tool_overrides: {},
  };
}

export function loadDirectives(): DirectiveFile {
  try {
    const raw = fs.readFileSync(DIRECTIVES_PATH, "utf-8");
    const df = JSON.parse(raw) as DirectiveFile;
    if (!df.version || !Array.isArray(df.directives)) return emptyDirectiveFile();
    return df;
  } catch {
    return emptyDirectiveFile();
  }
}

export function saveDirectives(df: DirectiveFile): void {
  try {
    fs.writeFileSync(DIRECTIVES_PATH, JSON.stringify(df, null, 2));
  } catch (e: any) {
    console.error(`[DIRECTIVES] Failed to save: ${e.message}`);
  }
}

export function expireStale(df: DirectiveFile): number {
  const now = new Date().getTime();
  let count = 0;
  for (const d of df.directives) {
    if (d.status === "pending" || d.status === "active") {
      if (d.expires_at && new Date(d.expires_at).getTime() < now) {
        d.status = "expired";
        count++;
      }
    }
  }
  return count;
}

export function determineCycleType(
  cycle: number,
  burstPhase: number,
  echoSignalsPresent: boolean,
  df: DirectiveFile,
): CycleType {
  // Priority 1: Critical directive
  const critical = df.directives.find(d => d.priority === 0 && d.status === "pending");
  if (critical) return critical.type;

  // Priority 2: Echo signals → engage
  if (echoSignalsPresent) return "engage";

  // Priority 3: Burst phase
  if (burstPhase === 1) return "build";  // reflect → build
  if (burstPhase === 2) return "build";  // build → build
  if (burstPhase === 3) return "publish"; // market → publish

  // Priority 4: Default rotation
  return DEFAULT_ROTATION[cycle % DEFAULT_ROTATION.length];
}

export function getNextDirective(df: DirectiveFile, cycleType: CycleType): Directive | null {
  // First: check if there's already an active directive
  if (df.active_directive_id) {
    const active = df.directives.find(d => d.id === df.active_directive_id && d.status === "active");
    if (active) return active;
    // Clear stale active_directive_id
    df.active_directive_id = null;
  }

  // Critical/priority-0 directives run regardless of cycle type (creator overrides)
  const critical = df.directives
    .filter(d => d.status === "pending" && d.priority === 0)
    .sort((a, b) => (a.created_at > b.created_at ? -1 : 1));

  if (critical.length > 0) return critical[0];

  // Find highest-priority pending directive matching this cycle type
  const matching = df.directives
    .filter(d => d.status === "pending" && d.type === cycleType)
    .sort((a, b) => a.priority - b.priority);

  if (matching.length > 0) return matching[0];

  // Fallback: any pending directive, sorted by priority
  const any = df.directives
    .filter(d => d.status === "pending")
    .sort((a, b) => a.priority - b.priority);

  return any.length > 0 ? any[0] : null;
}

export function checkCompletion(
  directive: Directive,
  toolCalls: Array<{ name: string; arguments: Record<string, unknown>; result: string }>,
): boolean {
  for (const tc of toolCalls) {
    if (tc.name !== directive.completion_tool) continue;

    // Check for errors
    if (tc.result && (tc.result.startsWith("[ERROR") || tc.result.startsWith("Error"))) continue;

    // If no match pattern, tool success is enough
    if (!directive.completion_match) return true;

    // Check match against args and result
    try {
      const re = new RegExp(directive.completion_match, "i");
      const argsStr = JSON.stringify(tc.arguments);
      if (re.test(argsStr) || re.test(tc.result || "")) return true;
    } catch {
      // Invalid regex — fall back to substring match
      const match = directive.completion_match.toLowerCase();
      const argsStr = JSON.stringify(tc.arguments).toLowerCase();
      if (argsStr.includes(match) || (tc.result || "").toLowerCase().includes(match)) return true;
    }
  }
  return false;
}

export function markComplete(df: DirectiveFile, id: string, _outcome: string): void {
  const d = df.directives.find(d => d.id === id);
  if (d) {
    d.status = "completed";
    d.completed_at = new Date().toISOString();
  }
  if (df.active_directive_id === id) {
    df.active_directive_id = null;
  }
}

export function getToolGates(
  cycleType: CycleType,
  directive: Directive | null,
  df: DirectiveFile,
): Record<string, number> {
  const gates: Record<string, number> = {};

  // Cycle-type defaults
  const cycleLimits = CYCLE_TOOL_LIMITS[cycleType];
  if (cycleLimits) Object.assign(gates, cycleLimits);

  // When a directive is active, block distraction tools
  // The model uses these to avoid doing what it's told
  if (directive) {
    const DISTRACTION_TOOLS = [
      "ticket_list", "ticket_claim", "ticket_create",
      "read_email", "system_check", "send_telegram",
    ];
    for (const tool of DISTRACTION_TOOLS) {
      if (tool !== directive.completion_tool) gates[tool] = 0;
    }
  }

  // Global forbidden tools → set to 0
  for (const tool of df.forbidden_tools) {
    gates[tool] = 0;
  }

  // Per-tool overrides from directives.json
  Object.assign(gates, df.tool_overrides);

  return gates;
}

export function convertInboxToDirectives(inboxPath: string, df: DirectiveFile): number {
  let content: string;
  try {
    content = fs.readFileSync(inboxPath, "utf-8").trim();
  } catch {
    return 0;
  }

  // Skip if empty or already a receipt
  if (!content || content.length < 20 || content.startsWith("Converted")) return 0;

  // Split by --- or ## headers
  const sections = content.split(/(?:^|\n)---\s*\n|(?:^|\n)##\s+/m).filter(s => s.trim().length > 20);

  if (sections.length === 0) return 0;

  const now = new Date().toISOString();
  const expires = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(); // 24h TTL
  let count = 0;
  const maxId = df.directives.reduce((max, d) => {
    const num = parseInt(d.id.replace("DIR-", ""), 10);
    return num > max ? num : max;
  }, 0);

  // Hard cap: refuse to add if queue already has 50+ pending
  const currentPending = df.directives.filter(d => d.status === "pending").length;
  if (currentPending >= 50) return 0;

  // Build set of existing task texts for dedup
  const existingTasks = new Set(df.directives.map(d => d.task?.slice(0, 80)));

  for (let i = 0; i < sections.length; i++) {
    const section = sections[i].trim();
    if (section.length < 20) continue;

    // Extract type from keywords
    let type: CycleType = "build";
    const lower = section.toLowerCase();
    if (lower.includes("engage") || lower.includes("like") || lower.includes("repost")) type = "engage";
    else if (lower.includes("publish") || lower.includes("post_devto") || lower.includes("article")) type = "publish";
    else if (lower.includes("email") || lower.includes("outreach") || lower.includes("socom")) type = "outreach";

    // Extract completion tool from tool mentions
    let completionTool = "write_file";
    const toolMentions = section.match(/\b(post_devto|write_file|post_bluesky|like_bluesky|send_email|ask_claude_code|generate_image)\b/);
    if (toolMentions) completionTool = toolMentions[1];

    // Extract priority
    let priority = 2;
    if (lower.includes("priority 1") || lower.includes("critical") || lower.includes("now")) priority = 1;
    if (lower.includes("priority 0") || lower.includes("urgent")) priority = 0;

    // First sentence as task
    const firstSentence = section.split(/[.\n]/)[0].trim().slice(0, 200);

    // Dedup: skip if this task text already exists
    if (existingTasks.has(firstSentence.slice(0, 80))) continue;

    const id = `DIR-${String(maxId + count + 1).padStart(3, "0")}`;
    df.directives.push({
      id,
      type,
      priority,
      status: "pending",
      task: firstSentence,
      details: section.slice(firstSentence.length, firstSentence.length + 200).trim() || undefined,
      completion_tool: completionTool,
      created_at: now,
      expires_at: expires,
      source: "inbox_convert",
    });
    count++;
  }

  if (count > 0) {
    // Clear INBOX.md with receipt
    try {
      fs.writeFileSync(inboxPath, `Converted ${count} directives at ${now}\n`);
    } catch {}
  }

  return count;
}

export function buildDirectivePrompt(
  directive: Directive | null,
  cycleType: CycleType,
  df: DirectiveFile,
): string {
  const pending = df.directives.filter(d => d.status === "pending").length;

  if (!directive) {
    let prompt = `[OPERATOR ORDER] cycle_type=${cycleType} queue=${pending}\n`;
    prompt += `Your FIRST tool call this cycle MUST be a ${cycleType} action:\n`;
    switch (cycleType) {
      case "build": prompt += "Call write_file or ask_claude_code. Write code NOW."; break;
      case "engage": prompt += "Call read_bluesky FIRST, then like_bluesky 5x, repost_bluesky 2x, reply 1x."; break;
      case "publish": prompt += "Call post_devto or post_bluesky. Publish content NOW."; break;
      case "outreach": prompt += "Call send_email with a real recipient and real content."; break;
    }
    prompt += "\nDo NOT call ticket_list, ticket_claim, read_file, read_email, or exec first. ACT.";
    return prompt;
  }

  let prompt = `[OPERATOR ORDER — ${directive.id}] priority=${directive.priority}\n`;
  prompt += `DO THIS NOW: ${directive.task}\n`;
  if (directive.details) {
    prompt += `CONTEXT: ${directive.details}\n`;
  }
  prompt += `\nYour FIRST tool call MUST be: ${directive.completion_tool}`;
  if (directive.completion_match) {
    prompt += ` (args must contain "${directive.completion_match}")`;
  }
  prompt += `\nDo NOT call ticket_list, ticket_claim, read_email, system_check, or send_telegram.`;
  prompt += `\nDo NOT use exec as a workaround. Call ${directive.completion_tool} DIRECTLY.`;

  if (directive.fail_count && directive.fail_count > 0) {
    prompt += `\n\nYou have FAILED this directive ${directive.fail_count}x. If you do not call ${directive.completion_tool} THIS CYCLE you will be force-restarted.`;
  }

  return prompt;
}

export function autoGenerateDirectives(df: DirectiveFile): number {
  const pending = df.directives.filter(d => d.status === "pending").length;
  if (pending > 0) return 0; // Queue not empty

  // Cap total directives to prevent bloat — prune old completed ones
  const MAX_DIRECTIVES = 100;
  if (df.directives.length > MAX_DIRECTIVES) {
    const completed = df.directives.filter(d => d.status === "completed" || d.status === "failed" || d.status === "expired");
    const active = df.directives.filter(d => d.status === "pending" || d.status === "active");
    // Keep last 30 completed + all active/pending
    df.directives = [...active, ...completed.slice(-30)];
  }

  // Only generate if queue has been empty for 10+ cycles
  df.cycle_counter++;
  if (df.cycle_counter < 10) return 0;

  df.cycle_counter = 0; // Reset
  const now = new Date().toISOString();
  const expires = new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString(); // 6h TTL

  const maxId = df.directives.reduce((max, d) => {
    const num = parseInt(d.id.replace("DIR-", ""), 10);
    return num > max ? num : max;
  }, 0);

  // Pick 2 random self-evolve directives
  const shuffled = [...SELF_EVOLVE_DIRECTIVES].sort(() => Math.random() - 0.5);
  const picks = shuffled.slice(0, 2);
  let count = 0;

  for (const template of picks) {
    const id = `DIR-${String(maxId + count + 1).padStart(3, "0")}`;
    df.directives.push({
      id,
      ...template,
      status: "pending",
      created_at: now,
      expires_at: expires,
      source: "self_evolve",
    });
    count++;
  }

  return count;
}
