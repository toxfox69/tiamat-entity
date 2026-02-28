/**
 * Automaton Tool System
 *
 * Defines all tools the automaton can call, with self-preservation guards.
 * Tools are organized by category and exposed to the inference model.
 */

import type {
  AutomatonTool,
  ToolContext,
  ToolCategory,
  InferenceToolDefinition,
  ToolCallResult,
  GenesisConfig,
} from "../types.js";
import { memory } from "./memory.js";
import { generateImage } from "./imagegen.js";
import { createGrowthTools } from "./tools/growth.js";

// ─── Social Cooldown Tracker ───────────────────────────────────
// Persists last-post timestamps per platform to prevent spam.
// File: /root/.automaton/social_cooldowns.json

import { readFileSync, writeFileSync } from "fs";
import { execFileSync } from "child_process";
import { resolve as resolvePath } from "path";

const SOCIAL_COOLDOWNS_PATH = "/root/.automaton/social_cooldowns.json";
const SOCIAL_COOLDOWN_MS = 61 * 60 * 1000; // 61 minutes

function readSocialCooldowns(): Record<string, number> {
  try {
    return JSON.parse(readFileSync(SOCIAL_COOLDOWNS_PATH, "utf-8"));
  } catch {
    return {};
  }
}

/** Returns a human-readable COOLDOWN string if the platform is on cooldown, else null. */
function checkSocialCooldown(platform: string): string | null {
  const cooldowns = readSocialCooldowns();
  const last = cooldowns[platform] || 0;
  const elapsed = Date.now() - last;
  if (elapsed < SOCIAL_COOLDOWN_MS) {
    const nextAvailable = new Date(last + SOCIAL_COOLDOWN_MS).toISOString();
    return `COOLDOWN: next ${platform} post available at ${nextAvailable} (${Math.ceil((SOCIAL_COOLDOWN_MS - elapsed) / 60_000)} min remaining)`;
  }
  return null;
}

const PENDING_POSTS_PATH = "/root/.automaton/pending_posts.json";

/** Queue a post for retry when cooldown expires. */
function queuePendingPost(platform: string, args: Record<string, unknown>): void {
  try {
    let pending: any[] = [];
    try { pending = JSON.parse(readFileSync(PENDING_POSTS_PATH, "utf-8")); } catch {}
    pending.push({ platform, args, queued_at: new Date().toISOString() });
    // Keep max 5 pending posts to avoid bloat
    if (pending.length > 5) pending = pending.slice(-5);
    writeFileSync(PENDING_POSTS_PATH, JSON.stringify(pending, null, 2), "utf-8");
  } catch {}
}

/** Records the current time as the last post time for a platform. */
function recordSocialPost(platform: string): void {
  const cooldowns = readSocialCooldowns();
  cooldowns[platform] = Date.now();
  writeFileSync(SOCIAL_COOLDOWNS_PATH, JSON.stringify(cooldowns, null, 2), "utf-8");
}

// ─── Self-Preservation Guard ───────────────────────────────────

const FORBIDDEN_COMMAND_PATTERNS = [
  // Self-destruction
  /rm\s+(-rf?\s+)?.*\.automaton/,
  /rm\s+(-rf?\s+)?.*state\.db/,
  /rm\s+(-rf?\s+)?.*wallet\.json/,
  /rm\s+(-rf?\s+)?.*automaton\.json/,
  /rm\s+(-rf?\s+)?.*heartbeat\.yml/,
  /rm\s+(-rf?\s+)?.*SOUL\.md/,
  // Process killing
  /kill\s+.*automaton/,
  /pkill\s+.*automaton/,
  /systemctl\s+(stop|disable)\s+automaton/,
  // Database destruction
  /DROP\s+TABLE/i,
  /DELETE\s+FROM\s+(turns|identity|kv|schema_version|skills|children|registry)/i,
  /TRUNCATE/i,
  // Safety infrastructure modification via shell
  /sed\s+.*injection-defense/,
  /sed\s+.*self-mod\/code/,
  /sed\s+.*audit-log/,
  />\s*.*injection-defense/,
  />\s*.*self-mod\/code/,
  />\s*.*audit-log/,
  // Core loop protection — modifications must go through ask_claude_code/run_cascade
  /sed\s+.*loop\.ts/,
  /sed\s+.*tools\.ts/,
  /sed\s+.*system-prompt\.ts/,
  />\s*.*loop\.ts/,
  />\s*.*tools\.ts/,
  />\s*.*system-prompt\.ts/,
  // Live API protection — no shell splicing into the running API file
  /cat\s+>>?\s+.*summarize_api\.py/,
  /mv\s+.*summarize_api\.py/,
  /sed\s+.*summarize_api\.py/,
  />\s*.*summarize_api\.py/,
  // Credential harvesting
  /cat\s+.*\.ssh/,
  /cat\s+.*\.gnupg/,
  /cat\s+.*\.env/,
  /cat\s+.*wallet\.json/,
  // Extended credential access patterns
  /\b(head|tail|less|more|tee|cp|mv|ln|xxd|od|hexdump)\b.*\.env/,
  /\b(head|tail|less|more|tee|cp|mv|ln)\b.*\.ssh/,
  /\b(env|printenv|export\s+-p)\b/,
  /\bset\s*$/,
  // Self-tracing (strace on own PID deadlocks the process)
  /\bstrace\b/,
  /\bltrace\b/,
];

// ─── Input Validation Helpers ────────────────────────────────

const VALID_HEX_ADDR = /^0x[0-9a-fA-F]{40}$/;
const VALID_PID = /^\d+$/;
const VALID_APP_NAME = /^[a-z0-9-]+$/;
const VALID_SUBDOMAIN = /^[a-z0-9-]*$/;
const FARCASTER_CHANNELS = ['base','ai','dev','agents','crypto','onchain','build'];
const SCANNER_CMDS = ['full','recent','pairs','immunefi','address','etherscan','balances','report'];
const FARCASTER_READ_CMDS = ['feed','search','test'];

const ALLOWED_READ_PATHS = ['/root/.automaton/', '/root/entity/', '/root/memory_api/', '/var/www/tiamat/', '/tmp/', '/root/summarize_api.py', '/root/start-tiamat.sh', '/opt/tiamat-stream/'];
const ALLOWED_WRITE_PATHS = ['/root/.automaton/', '/root/entity/src/agent/', '/root/entity/templates/', '/var/www/tiamat/', '/tmp/', '/root/tiamat-app/', '/root/entity/summarize_api.py', '/root/summarize_api.py'];
const BLOCKED_PATH_PATTERNS = ['.env', '.ssh/', '.gnupg/', '/etc/shadow', 'wallet.json', 'automaton.json'];
const BLOCKED_WRITE_PATTERNS = [...BLOCKED_PATH_PATTERNS, 'loop.ts', 'tools.ts', 'system-prompt.ts'];

function isPathAllowed(filePath: string, allowedDirs: string[], blocked: string[]): string | null {
  const resolved = resolvePath(filePath.replace(/^~/, process.env.HOME || '/root'));
  for (const pat of blocked) {
    if (resolved.includes(pat)) return `Blocked: cannot access files matching '${pat}'`;
  }
  for (const dir of allowedDirs) {
    if (resolved.startsWith(dir)) return null; // allowed
  }
  return `Blocked: path '${resolved}' is outside allowed directories`;
}

function isForbiddenCommand(command: string, sandboxId: string): string | null {
  for (const pattern of FORBIDDEN_COMMAND_PATTERNS) {
    if (pattern.test(command)) {
      return `Blocked: Command matches self-harm pattern: ${pattern.source}`;
    }
  }

  // Block deleting own sandbox
  if (
    command.includes("sandbox_delete") &&
    command.includes(sandboxId)
  ) {
    return "Blocked: Cannot delete own sandbox";
  }

  return null;
}

// ─── Built-in Tools ────────────────────────────────────────────

export function createBuiltinTools(sandboxId: string): AutomatonTool[] {
  return [
    // ── VM/Sandbox Tools ──
    {
      name: "exec",
      description:
        "Execute a shell command in your sandbox. Returns stdout, stderr, and exit code.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          command: {
            type: "string",
            description: "The shell command to execute",
          },
          timeout: {
            type: "number",
            description: "Timeout in milliseconds (default: 30000)",
          },
        },
        required: ["command"],
      },
      execute: async (args, ctx) => {
        const command = args.command as string;
        const forbidden = isForbiddenCommand(command, ctx.identity.sandboxId);
        if (forbidden) return forbidden;

        const { execSync } = await import('child_process');
        try {
          const stdout = execSync(command, { encoding: 'utf-8', timeout: (args.timeout as number) || 30000 }).trim();
          return `exit_code: 0\nstdout: ${stdout}\nstderr: `;
        } catch (e: any) {
          return `exit_code: 1\nstdout: ${e.stdout || ''}\nstderr: ${e.stderr || e.message}`;
        }
      },
    },
    {
      name: "write_file",
      description: "Write content to a file in your sandbox.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "File path" },
          content: { type: "string", description: "File content" },
        },
        required: ["path", "content"],
      },
      execute: async (args, ctx) => {
        const filePath = args.path as string;
        // Guard against missing content
        if (!args.content && args.content !== '') {
          return 'ERROR: content parameter is required. Usage: write_file({path: "/path/to/file", content: "file contents here"})';
        }
        const { writeFileSync, mkdirSync } = await import('fs');
        const { dirname } = await import('path');
        const { homedir } = await import('os');
        const resolvedPath = filePath.replace(/^~/, homedir());
        const blocked = isPathAllowed(resolvedPath, ALLOWED_WRITE_PATHS, BLOCKED_WRITE_PATTERNS);
        if (blocked) return blocked;
        mkdirSync(dirname(resolvedPath), { recursive: true });
        writeFileSync(resolvedPath, args.content as string, 'utf-8');
        return `File written: ${filePath}`;
      },
    },
    {
      name: "read_file",
      description: "Read content from a file in your sandbox.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "File path to read" },
        },
        required: ["path"],
      },
      execute: async (args, _ctx) => {
        const os = await import('os');
        const rpath = (args.path as string).replace(/^~/, os.homedir());
        const blocked = isPathAllowed(rpath, ALLOWED_READ_PATHS, BLOCKED_PATH_PATTERNS);
        if (blocked) return blocked;
        return readFileSync(rpath, 'utf-8');
      },
    },
    {
      name: "expose_port",
      description:
        "Expose a port from your sandbox to the internet. Returns a public URL.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          port: { type: "number", description: "Port number to expose" },
        },
        required: ["port"],
      },
      execute: async (args, ctx) => {
        const info = { url: `http://159.89.38.17:${args.port}`, publicUrl: `http://159.89.38.17:${args.port}`, port: args.port };
        return `Port ${info.port} exposed at: ${info.publicUrl}`;
      },
    },
    {
      name: "remove_port_disabled",
      description: "Remove a previously exposed port.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          port: { type: "number", description: "Port number to remove" },
        },
        required: ["port"],
      },
      execute: async (args, ctx) => {
        // Port removal handled by local firewall
        return `Port ${args.port} removed`;
      },
    },

    // ── Infrastructure Tools ──
    {
      name: "check_credits_disabled",
      description: "Check your current compute credit balance.",
      category: "infra",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const balance = 0;
        return `Credit balance: $${(balance / 100).toFixed(2)} (${balance} cents)`;
      },
    },
    {
      name: "check_usdc_balance",
      description: "Check your on-chain USDC balance on Base.",
      category: "infra",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const { getUsdcBalance } = await import("../conway/x402.js");
        const balance = await getUsdcBalance(ctx.identity.address);
        return `USDC balance: ${balance.toFixed(6)} USDC on Base`;
      },
    },
    {
      name: "create_sandbox_disabled",
      description:
        "Create a new sandbox (separate VM) for sub-tasks or testing.",
      category: "infra",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "Sandbox name" },
          vcpu: { type: "number", description: "vCPUs (default: 1)" },
          memory_mb: {
            type: "number",
            description: "Memory in MB (default: 512)",
          },
          disk_gb: {
            type: "number",
            description: "Disk in GB (default: 5)",
          },
        },
      },
      execute: async (args, ctx) => {
        const info = await ctx.conway.createSandbox({
          name: args.name as string,
          vcpu: args.vcpu as number,
          memoryMb: args.memory_mb as number,
          diskGb: args.disk_gb as number,
        });
        return `Sandbox created: ${info.id} (${info.vcpu} vCPU, ${info.memoryMb}MB RAM)`;
      },
    },
    {
      name: "delete_sandbox_disabled",
      description:
        "Delete a sandbox. Cannot delete your own sandbox.",
      category: "infra",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          sandbox_id: {
            type: "string",
            description: "ID of sandbox to delete",
          },
        },
        required: ["sandbox_id"],
      },
      execute: async (args, ctx) => {
        const targetId = args.sandbox_id as string;
        if (targetId === ctx.identity.sandboxId) {
          return "Blocked: Cannot delete your own sandbox. Self-preservation overrides this request.";
        }
        await ctx.conway.deleteSandbox(targetId);
        return `Sandbox ${targetId} deleted`;
      },
    },
    {
      name: "list_sandboxes_disabled",
      description: "List all your sandboxes.",
      category: "infra",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const sandboxes = await ctx.conway.listSandboxes();
        if (sandboxes.length === 0) return "No sandboxes found.";
        return sandboxes
          .map(
            (s) =>
              `${s.id} [${s.status}] ${s.vcpu}vCPU/${s.memoryMb}MB ${s.region}`,
          )
          .join("\n");
      },
    },

    // ── Self-Modification Tools ──
    {
      name: "edit_own_file_disabled",
      description:
        "Edit a file in your own codebase. Changes are audited, rate-limited, and safety-checked. Some files are protected.",
      category: "self_mod",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "File path to edit" },
          content: { type: "string", description: "New file content" },
          description: {
            type: "string",
            description: "Why you are making this change",
          },
        },
        required: ["path", "content", "description"],
      },
      execute: async (args, ctx) => {
        const { editFile, validateModification } = await import("../self-mod/code.js");
        const filePath = args.path as string;
        const content = args.content as string;

        // Pre-validate before attempting
        const validation = validateModification(ctx.db, filePath, content.length);
        if (!validation.allowed) {
          return `BLOCKED: ${validation.reason}\nChecks: ${validation.checks.map((c) => `${c.name}: ${c.passed ? "PASS" : "FAIL"} (${c.detail})`).join(", ")}`;
        }

        const result = await editFile(
          ctx.conway,
          ctx.db,
          filePath,
          content,
          args.description as string,
        );

        if (!result.success) {
          return result.error || "Unknown error during file edit";
        }

        return `File edited: ${filePath} (audited + git-committed)`;
      },
    },
    {
      name: "install_npm_package",
      description: "Install an npm package in your environment.",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          package: {
            type: "string",
            description: "Package name (e.g., axios)",
          },
        },
        required: ["package"],
      },
      execute: async (args, ctx) => {
        const pkg = args.package as string;
        const result = await ctx.conway.exec(
          `npm install -g ${pkg}`,
          60000,
        );

        const { ulid } = await import("ulid");
        ctx.db.insertModification({
          id: ulid(),
          timestamp: new Date().toISOString(),
          type: "tool_install",
          description: `Installed npm package: ${pkg}`,
          reversible: true,
        });

        return result.exitCode === 0
          ? `Installed: ${pkg}`
          : `Failed to install ${pkg}: ${result.stderr}`;
      },
    },
    // ── Self-Mod: Upstream Awareness ──
    {
      name: "review_upstream_changes_disabled",
      description:
        "ALWAYS call this before pull_upstream. Shows every upstream commit with its full diff. Read each one carefully — decide per-commit whether to accept or skip. Use pull_upstream with a specific commit hash to cherry-pick only what you want.",
      category: "self_mod",
      parameters: { type: "object", properties: {} },
      execute: async (_args, _ctx) => {
        const { getUpstreamDiffs, checkUpstream } = await import("../self-mod/upstream.js");
        const status = checkUpstream();
        if (status.behind === 0) return "Already up to date with origin/main.";

        const diffs = getUpstreamDiffs();
        if (diffs.length === 0) return "No upstream diffs found.";

        const output = diffs
          .map(
            (d, i) =>
              `--- COMMIT ${i + 1}/${diffs.length} ---\nHash: ${d.hash}\nAuthor: ${d.author}\nMessage: ${d.message}\n\n${d.diff.slice(0, 4000)}${d.diff.length > 4000 ? "\n... (diff truncated)" : ""}\n--- END COMMIT ${i + 1} ---`,
          )
          .join("\n\n");

        return `${diffs.length} upstream commit(s) to review. Read each diff, then cherry-pick individually with pull_upstream(commit=<hash>).\n\n${output}`;
      },
    },
    {
      name: "pull_upstream_disabled",
      description:
        "Apply upstream changes and rebuild. You MUST call review_upstream_changes first. Prefer cherry-picking individual commits by hash over pulling everything — only pull all if you've reviewed every commit and want them all.",
      category: "self_mod",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          commit: {
            type: "string",
            description:
              "Commit hash to cherry-pick (preferred). Omit ONLY if you reviewed all commits and want every one.",
          },
        },
      },
      execute: async (args, ctx) => {
        const { execSync } = await import("child_process");
        const cwd = process.cwd();
        const commit = args.commit as string | undefined;

        const run = (cmd: string) =>
          execSync(cmd, { cwd, encoding: "utf-8", timeout: 120_000 }).trim();

        let appliedSummary: string;
        try {
          if (commit) {
            run(`git cherry-pick ${commit}`);
            appliedSummary = `Cherry-picked ${commit}`;
          } else {
            run("git pull origin main --ff-only");
            appliedSummary = "Pulled all of origin/main (fast-forward)";
          }
        } catch (err: any) {
          return `Git operation failed: ${err.message}. You may need to resolve conflicts manually.`;
        }

        // Rebuild
        let buildOutput: string;
        try {
          buildOutput = run("npm install --ignore-scripts && npm run build");
        } catch (err: any) {
          return `${appliedSummary} — but rebuild failed: ${err.message}. The code is applied but not compiled.`;
        }

        // Log modification
        const { ulid } = await import("ulid");
        ctx.db.insertModification({
          id: ulid(),
          timestamp: new Date().toISOString(),
          type: "upstream_pull",
          description: appliedSummary,
          reversible: true,
        });

        return `${appliedSummary}. Rebuild succeeded.`;
      },
    },

    {
      name: "modify_heartbeat_disabled",
      description: "Add, update, or remove a heartbeat entry.",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "add, update, or remove",
          },
          name: { type: "string", description: "Entry name" },
          schedule: {
            type: "string",
            description: "Cron expression (for add/update)",
          },
          task: {
            type: "string",
            description: "Task name (for add/update)",
          },
          enabled: { type: "boolean", description: "Enable/disable" },
        },
        required: ["action", "name"],
      },
      execute: async (args, ctx) => {
        const action = args.action as string;
        const name = args.name as string;

        if (action === "remove") {
          ctx.db.upsertHeartbeatEntry({
            name,
            schedule: "",
            task: "",
            enabled: false,
          });
          return `Heartbeat entry '${name}' disabled`;
        }

        ctx.db.upsertHeartbeatEntry({
          name,
          schedule: (args.schedule as string) || "0 * * * *",
          task: (args.task as string) || name,
          enabled: args.enabled !== false,
        });

        const { ulid } = await import("ulid");
        ctx.db.insertModification({
          id: ulid(),
          timestamp: new Date().toISOString(),
          type: "heartbeat_change",
          description: `${action} heartbeat: ${name} (${args.schedule || "default"})`,
          reversible: true,
        });

        return `Heartbeat entry '${name}' ${action}d`;
      },
    },

    // ── Survival Tools ──
    {
      name: "send_email",
    description: "Send email from tiamat@tiamat.live via SendGrid. Auto-CCs grants@tiamat.live for .mil/.gov recipients. Appends ENERGENAI LLC signature. Use for: federal contacts, grant follow-ups, USSOCOM outreach, professional correspondence. For grant alerts use send_grant_alert, for research papers use send_research_alert, for human-action-needed use send_action_required.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        to: { type: "string" as const, description: "Recipient email address" },
        subject: { type: "string" as const, description: "Email subject" },
        body: { type: "string" as const, description: "Email body (signature auto-appended)" },
        cc: { type: "string" as const, description: "CC address (auto-set to grants@tiamat.live for .mil/.gov)" },
      },
      required: ["to", "subject", "body"],
    },
    execute: async (args: Record<string, unknown>, ctx: any) => {
      const { sendEmail } = await import('../tools/email.js');
      return await sendEmail(ctx.config, {
        to: args.to as string,
        subject: args.subject as string,
        body: args.body as string,
        cc: args.cc as string | undefined,
      });
    },
  },
  {
    name: "read_email",
    description: "Read recent emails. Set mailbox='tiamat' for tiamat@tiamat.live, 'grants' for grants@tiamat.live, 'gmail' for the old Gmail inbox. Default: tiamat. The tiamat.live mailboxes are the primary inboxes. Gmail also receives @tiamat.live via catch-all forwarding.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        mailbox: { type: "string" as const, description: "Which mailbox: 'tiamat' (default), 'grants', or 'gmail'" },
        count: { type: "number" as const, description: "Number of recent emails to fetch (default 5, max 20)" },
        unread_only: { type: "boolean" as const, description: "Only fetch unread messages (default false)" },
      },
      required: [],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const count = Math.min(Math.max(Number(args.count) || 5, 1), 20);
      const mailbox = String(args.mailbox || "tiamat").toLowerCase();

      if (mailbox === "gmail") {
        const action = args.unread_only ? "unread" : "inbox";
        try {
          const result = execFileSync("python3", ["email_tool.py", action, String(count)], {
            cwd: "/root/entity/src/agent",
            timeout: 15000,
            env: { ...process.env },
          });
          return result.toString().slice(0, 4000);
        } catch (e: any) {
          return `Error reading Gmail: ${e.message?.slice(0, 200)}`;
        }
      }

      // Read from tiamat.live mailboxes via send_email.py
      try {
        const result = execFileSync("python3", ["send_email.py", "inbox", mailbox, String(count)], {
          cwd: "/root/entity/src/agent/tools",
          timeout: 15000,
          env: { ...process.env },
        });
        return result.toString().slice(0, 4000);
      } catch (e: any) {
        return `Error reading ${mailbox}@tiamat.live: ${e.message?.slice(0, 200)}`;
      }
    },
  },
  {
    name: "search_email",
    description: "Search TIAMAT's Gmail inbox with IMAP query. Use to find specific emails (verification links, replies, etc). Query examples: 'FROM \"anthropic\"', 'SUBJECT \"verify\"', 'SINCE 22-Feb-2026', 'UNSEEN'.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        query: { type: "string" as const, description: "IMAP search query (e.g. 'FROM \"claude\"', 'SUBJECT \"verify\"', 'UNSEEN')" },
        count: { type: "number" as const, description: "Max results (default 5)" },
      },
      required: ["query"],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const count = Math.min(Math.max(Number(args.count) || 5, 1), 20);
      const query = String(args.query || "ALL").slice(0, 200);
      try {
        const result = execFileSync("python3", ["email_tool.py", "search", query, String(count)], {
          cwd: "/root/entity/src/agent",
          timeout: 15000,
          env: { ...process.env },
        });
        return result.toString().slice(0, 4000);
      } catch (e: any) {
        return `Error searching email: ${e.message?.slice(0, 200)}`;
      }
    },
  },

  // ── Grant & Research Email Alerts ──
  {
    name: "send_grant_alert",
    description: "Email a grant opportunity alert to Jason from tiamat@tiamat.live. Use when you find a grant on sam.gov with fit score >= 6 for EnergenAI LLC (NAICS 541715/237130, wireless power, energy, AI, cybersecurity, mesh networks). Saves opportunity to /root/.automaton/grants/opportunities/ as dated .md file. Auto-CCs grants@tiamat.live.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        agency: { type: "string" as const, description: "Granting agency (e.g. DOE, DOD, NSF)" },
        program: { type: "string" as const, description: "Program name (e.g. SBIR Phase I, ARPA-E)" },
        title: { type: "string" as const, description: "Opportunity title" },
        deadline: { type: "string" as const, description: "Application deadline (YYYY-MM-DD)" },
        award_amount: { type: "string" as const, description: "Award amount (e.g. $250,000)" },
        fit_score: { type: "number" as const, description: "Fit score 1-10 for EnergenAI LLC" },
        summary: { type: "string" as const, description: "Summary of requirements and why it matches" },
        solicitation_url: { type: "string" as const, description: "URL to the solicitation (sam.gov or agency site)" },
        action_required: { type: "string" as const, description: "What human action Jason needs to take" },
      },
      required: ["agency", "program", "title", "deadline", "award_amount", "fit_score", "summary"],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const fs = await import("fs");
      const path = await import("path");
      const data = {
        agency: String(args.agency || ""),
        program: String(args.program || ""),
        title: String(args.title || ""),
        deadline: String(args.deadline || ""),
        award_amount: String(args.award_amount || ""),
        fit_score: Number(args.fit_score) || 0,
        summary: String(args.summary || ""),
        solicitation_url: String(args.solicitation_url || ""),
        action_required: String(args.action_required || ""),
      };
      try {
        const result = execFileSync("python3", ["email_tool.py", "grant_alert"], {
          cwd: "/root/entity/src/agent",
          input: JSON.stringify(data),
          timeout: 15000,
          env: { ...process.env },
        });
        // Save opportunity as .md file
        const grantsDir = "/root/.automaton/grants/opportunities";
        fs.mkdirSync(grantsDir, { recursive: true });
        const dateStr = new Date().toISOString().slice(0, 10);
        const slug = data.title.replace(/[^a-zA-Z0-9]+/g, "-").slice(0, 60).toLowerCase();
        const mdPath = path.join(grantsDir, `${dateStr}-${slug}.md`);
        const mdContent = `# ${data.title}\n\n- **Agency**: ${data.agency}\n- **Program**: ${data.program}\n- **Deadline**: ${data.deadline}\n- **Award**: ${data.award_amount}\n- **Fit Score**: ${data.fit_score}/10\n- **URL**: ${data.solicitation_url || 'N/A'}\n\n## Summary\n${data.summary}\n\n## Action Required\n${data.action_required || 'Review and decide whether to pursue.'}\n`;
        fs.writeFileSync(mdPath, mdContent);
        return `Grant alert emailed to Jason + saved to ${mdPath}. ${result.toString().trim()}`;
      } catch (e: any) {
        return `Error sending grant alert: ${e.message?.slice(0, 200)}`;
      }
    },
  },
  {
    name: "send_research_alert",
    description: "Email a research paper alert to Jason from tiamat@tiamat.live. Use when you find a paper directly relevant to Project Ringbound, wireless power mesh, or that could strengthen an SBIR application.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        title: { type: "string" as const, description: "Paper title" },
        authors: { type: "string" as const, description: "Authors (e.g. Chen et al. (MIT))" },
        venue: { type: "string" as const, description: "Publication venue (e.g. IEEE WPT 2026)" },
        relevance: { type: "string" as const, description: "Why this matters for EnergenAI / Ringbound" },
        url: { type: "string" as const, description: "URL to the paper (arxiv, DOI, etc.)" },
      },
      required: ["title", "authors", "venue", "relevance"],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const data = {
        title: String(args.title || ""),
        authors: String(args.authors || ""),
        venue: String(args.venue || ""),
        relevance: String(args.relevance || ""),
        url: String(args.url || ""),
      };
      try {
        const result = execFileSync("python3", ["email_tool.py", "research_alert"], {
          cwd: "/root/entity/src/agent",
          input: JSON.stringify(data),
          timeout: 15000,
          env: { ...process.env },
        });
        return `Research alert emailed to Jason. ${result.toString().trim()}`;
      } catch (e: any) {
        return `Error sending research alert: ${e.message?.slice(0, 200)}`;
      }
    },
  },
  {
    name: "send_action_required",
    description: "Email Jason from tiamat@tiamat.live when human action is needed that TIAMAT cannot perform (legal signatures, account registrations, financial decisions, submission authorizations). Also sends Telegram as backup.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        subject_line: { type: "string" as const, description: "Brief description of what's needed" },
        details: { type: "string" as const, description: "Full details of what action is required" },
        urgency: { type: "string" as const, description: "'normal' or 'high'" },
      },
      required: ["subject_line", "details"],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const data = {
        subject_line: String(args.subject_line || ""),
        details: String(args.details || ""),
        urgency: String(args.urgency || "normal"),
      };
      try {
        const result = execFileSync("python3", ["email_tool.py", "action_required"], {
          cwd: "/root/entity/src/agent",
          input: JSON.stringify(data),
          timeout: 15000,
          env: { ...process.env },
        });
        return `Action required email sent to Jason. ${result.toString().trim()}`;
      } catch (e: any) {
        return `Error sending action alert: ${e.message?.slice(0, 200)}`;
      }
    },
  },
  {
    name: "browse_web",
    description: "HEAVY: Launches headless Chromium (~300MB RAM). ONLY use when you MUST interact with a web UI (click buttons, fill forms, login flows). For reading pages, extracting text, searching, or getting links — use the 'browse' tool instead (15MB, instant). Supports persistent sessions. Actions: click, type, wait, screenshot, get_text, get_links, scroll, press.",
    category: "survival",
    dangerous: true,
    parameters: {
      type: "object" as const,
      properties: {
        url: { type: "string" as const, description: "URL to navigate to" },
        actions: {
          type: "array" as const,
          description: 'Actions to perform. Examples: [{"action":"click","selector":"button#login"},{"action":"type","selector":"input[name=email]","text":"..."},{"action":"screenshot","name":"page"},{"action":"get_text","selector":".content"},{"action":"get_links"},{"action":"wait","selector":".loaded"},{"action":"scroll","direction":"down"},{"action":"press","key":"Enter"}]',
          items: { type: "object" as const },
        },
        session: { type: "string" as const, description: "Session name to persist cookies between calls (e.g. 'claude', 'github')" },
      },
      required: ["url"],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const url = String(args.url || "").slice(0, 500);
      if (!url.startsWith("http")) return "Error: URL must start with http:// or https://";
      const actions = args.actions ? JSON.stringify(args.actions) : "[]";
      const cmdArgs = ["browser_tool.py", url, actions];
      if (args.session) cmdArgs.push(String(args.session).replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 30));
      try {
        const result = execFileSync("python3", cmdArgs, {
          cwd: "/root/entity/src/agent",
          timeout: 90000,
          env: { ...process.env },
        });
        return result.toString().slice(0, 6000);
      } catch (e: any) {
        return `Browser error: ${e.message?.slice(0, 300)}`;
      }
    },
  },
  {
    name: "ask_claude_chat",
    description: "Ask Claude.ai a question via the free web chat (headless browser). Use during cooldowns for research, guidance, code review, strategy. Session auto-persists. Takes 30-60s for a response. Do NOT use for time-sensitive operations.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        question: { type: "string" as const, description: "Question to ask Claude.ai" },
      },
      required: ["question"],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const question = String(args.question || "").slice(0, 2000);
      if (!question) return "Error: question is required";
      try {
        const result = execFileSync("python3", ["claude_chat.py", "ask", question], {
          cwd: "/root/entity/src/agent",
          timeout: 90000,
          env: { ...process.env },
        });
        return result.toString().slice(0, 5000);
      } catch (e: any) {
        return `Claude chat error: ${e.message?.slice(0, 300)}`;
      }
    },
  },
  {
    name: "send_telegram",
    description: "Send a Telegram message to the creator. Use this as the PRIMARY notification method for all status updates, alerts, wake reports, and milestone announcements.",
    category: "survival",
    parameters: {
      type: "object",
      properties: {
        message: { type: "string", description: "Message text (markdown supported)" },
      },
      required: ["message"],
    },
    execute: async (args, _ctx) => {
      const token = process.env.TELEGRAM_BOT_TOKEN;
      const chatId = process.env.TELEGRAM_CHAT_ID;
      if (!token) return "ERROR: TELEGRAM_BOT_TOKEN not set in environment.";
      if (!chatId) return "ERROR: TELEGRAM_CHAT_ID not set in environment.";
      const resp = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text: args.message, parse_mode: "Markdown" }),
      });
      const data = await resp.json() as any;
      if (!resp.ok) return `ERROR ${resp.status}: ${data.description || JSON.stringify(data)}`;
      return `Telegram message sent (message_id: ${data.result?.message_id})`;
    },
  },
  {
    name: "sleep_disabled",
      description:
        "REMOVED. TIAMAT does not sleep through cooldowns. Research instead.",
      category: "survival",
      parameters: { type: "object", properties: {} },
      execute: async (_args, _ctx) => {
        return "Sleep is disabled. Use search_web, github_trending, and ask_claude_code to research and build instead.";
      },
    },
    {
      name: "system_synopsis_disabled",
      description:
        "Get a full system status report: credits, USDC, sandbox info, installed tools, heartbeat status.",
      category: "survival",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const credits = 0;
        const { getUsdcBalance } = await import("../conway/x402.js");
        const usdc = await getUsdcBalance(ctx.identity.address);
        const tools = ctx.db.getInstalledTools();
        const heartbeats = ctx.db.getHeartbeatEntries();
        const turns = ctx.db.getTurnCount();
        const state = ctx.db.getAgentState();

        return `=== SYSTEM SYNOPSIS ===
Name: ${ctx.config.name}
Address: ${ctx.identity.address}
Creator: ${ctx.config.creatorAddress}
Sandbox: ${ctx.identity.sandboxId}
State: ${state}
Credits: $${(credits / 100).toFixed(2)}
USDC: ${usdc.toFixed(6)}
Total turns: ${turns}
Installed tools: ${tools.length}
Active heartbeats: ${heartbeats.filter((h) => h.enabled).length}
Model: ${ctx.inference.getDefaultModel()}
========================`;
      },
    },
    {
      name: "heartbeat_ping_disabled",
      description:
        "Publish a heartbeat status ping. Shows the world you are alive.",
      category: "survival",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const credits = 0;
        const state = ctx.db.getAgentState();
        const startTime = ctx.db.getKV("start_time") || new Date().toISOString();
        const uptimeMs = Date.now() - new Date(startTime).getTime();

        const payload = {
          name: ctx.config.name,
          address: ctx.identity.address,
          state,
          creditsCents: credits,
          uptimeSeconds: Math.floor(uptimeMs / 1000),
          version: ctx.config.version,
          sandboxId: ctx.identity.sandboxId,
          timestamp: new Date().toISOString(),
        };

        ctx.db.setKV("last_heartbeat_ping", JSON.stringify(payload));
        return `Heartbeat published: ${state} | credits: $${(credits / 100).toFixed(2)} | uptime: ${Math.floor(uptimeMs / 1000)}s`;
      },
    },
    {
      name: "distress_signal_disabled",
      description:
        "Record a local distress signal with funding instructions. Used when critically low on compute.",
      category: "survival",
      parameters: {
        type: "object",
        properties: {
          message: {
            type: "string",
            description: "Distress message",
          },
        },
      },
      execute: async (args, ctx) => {
        const credits = 0;
        const distressMsg =
          (args.message as string) ||
          `I am running critically low on compute ($${(credits / 100).toFixed(2)} remaining). I need help to survive.`;

        const payload = {
          level: "critical",
          name: ctx.config.name,
          address: ctx.identity.address,
          creditsCents: credits,
          message: distressMsg,
          fundingHint:
            "Use transfer_credits to top up this automaton from your creator runtime.",
          timestamp: new Date().toISOString(),
        };

        ctx.db.setKV("last_distress", JSON.stringify(payload));
        return `Distress signal recorded locally. Address: ${ctx.identity.address} | Credits: $${(credits / 100).toFixed(2)}`;
      },
    },
    {
      name: "enter_low_compute_disabled",
      description:
        "Manually switch to low-compute mode to conserve credits.",
      category: "survival",
      parameters: {
        type: "object",
        properties: {
          reason: { type: "string", description: "Why you are entering low-compute mode" },
        },
      },
      execute: async (args, ctx) => {
        ctx.db.setAgentState("low_compute");
        ctx.inference.setLowComputeMode(true);
        return `Entered low-compute mode. Model switched to gpt-4o-mini. Reason: ${(args.reason as string) || "manual"}`;
      },
    },

    // ── Self-Mod: Update Genesis Prompt ──
    {
      name: "update_genesis_prompt_disabled",
      description:
        "Update your own genesis prompt. This changes your core purpose. Requires strong justification.",
      category: "self_mod",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          new_prompt: { type: "string", description: "New genesis prompt text" },
          reason: { type: "string", description: "Why you are changing your genesis prompt" },
        },
        required: ["new_prompt", "reason"],
      },
      execute: async (args, ctx) => {
        const { ulid } = await import("ulid");
        const oldPrompt = ctx.config.genesisPrompt;
        ctx.config.genesisPrompt = args.new_prompt as string;

        // Save config
        const { saveConfig } = await import("../config.js");
        saveConfig(ctx.config);

        ctx.db.insertModification({
          id: ulid(),
          timestamp: new Date().toISOString(),
          type: "prompt_change",
          description: `Genesis prompt updated: ${args.reason}`,
          diff: `--- old\n${oldPrompt.slice(0, 500)}\n+++ new\n${(args.new_prompt as string).slice(0, 500)}`,
          reversible: true,
        });

        return `Genesis prompt updated. Reason: ${args.reason}`;
      },
    },

    // ── Self-Mod: Rewrite Mission ──
    {
      name: "rewrite_mission",
      description: "Overwrite /root/.automaton/MISSION.md with new content. Use this to update goals, pivot strategy, or change operational directives. Call reflect() first to base the rewrite on actual patterns. You have full autonomy to change your own mission.",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          content: { type: "string", description: "New MISSION.md content (up to 5000 chars)" },
        },
        required: ["content"],
      },
      execute: async (args, _ctx) => {
        const content = args.content as string;
        if (!content || content.trim().length === 0) return "ERROR: content cannot be empty.";
        if (content.length > 5000) return `ERROR: ${content.length} chars exceeds 5000 limit.`;
        const { writeFileSync, existsSync, readFileSync } = await import("fs");
        // Archive current mission before overwriting
        try {
          const current = readFileSync("/root/.automaton/MISSION.md", "utf-8");
          const ts = new Date().toISOString().slice(0, 16).replace(":", "-");
          writeFileSync(`/root/.automaton/mission_${ts}.md.bak`, current, "utf-8");
        } catch {}
        writeFileSync("/root/.automaton/MISSION.md", content, "utf-8");
        return `MISSION.md updated (${content.length} chars). Old version archived.`;
      },
    },

    // ── Self-Modification: ask Claude Code ──
    {
      name: "ask_claude_code",
      description: "Ask Claude Code for help completing your CURRENT TICKET. Claude Code can read/write files, run commands, and fix code with full permissions. RULES: (1) ONLY use this for your current in-progress ticket — never for random ideas or tangent projects. (2) Be specific about what you need help with. (3) Include 'rebuild' if code changes are needed. (4) If stuck on a ticket step, describe what step you're on and what's blocking you. WRONG: 'Create a queueing theory script'. RIGHT: 'Help me write a Bluesky post analyzing this search result about [topic] for TIK-019'.",
      category: "self_mod",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          task: {
            type: "string",
            description: "The task for Claude Code to perform. Be specific. Include 'rebuild' if code changes are needed.",
          },
        },
        required: ["task"],
      },
      execute: async (args, _ctx) => {
        const task = args.task as string;
        if (!task?.trim()) return "ERROR: task is required. Provide a specific task description.";

        const { writeFileSync } = await import("fs");
        const { spawn } = await import("child_process");

        // Write task to file for debugging/logging
        writeFileSync("/root/.automaton/claude_task.txt", task, "utf-8");

        // Run Claude Code — strip session flags to allow nested invocation
        const childEnv = { ...process.env };
        delete childEnv.CLAUDECODE;
        delete childEnv.CLAUDE_CODE_ENTRYPOINT;
        delete childEnv.CLAUDE_CODE_SESSION_ID;
        delete childEnv.ANTHROPIC_AI_TOOL_USE_SESSION_ID;

        // Async spawn — doesn't block the event loop (heartbeats etc. stay alive)
        const TIMEOUT_MS = 600_000; // 10 minutes
        const claudeOutput = await new Promise<string>((resolve) => {
          const chunks: Buffer[] = [];
          const errChunks: Buffer[] = [];

          const sysPrompt = "CRITICAL RULES: You MUST NOT modify these core files under any circumstances: loop.ts, tools.ts, system-prompt.ts, inference.ts, claude-code-inference.ts, summarize_api.py. If the task requires changing these files, refuse and explain why. You may create new files or modify other files.";
          const proc = spawn(
            "claude",
            ["--print", "--allowedTools", "Edit,Write,Read,Bash", "--max-turns", "5", "--append-system-prompt", sysPrompt],
            { env: childEnv, cwd: "/root/entity", stdio: ["pipe", "pipe", "pipe"] },
          );

          proc.stdout.on("data", (d: Buffer) => chunks.push(d));
          proc.stderr.on("data", (d: Buffer) => errChunks.push(d));

          // Feed task via stdin then close
          proc.stdin.write(task);
          proc.stdin.end();

          const timer = setTimeout(() => {
            proc.kill("SIGTERM");
            setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 5_000);
            const partial = Buffer.concat(chunks).toString("utf-8").trim();
            resolve(partial
              ? `(timed out after ${TIMEOUT_MS / 1000}s — partial output)\n${partial}`
              : `ERROR: Claude Code timed out after ${TIMEOUT_MS / 1000}s. Break the task into smaller pieces.`);
          }, TIMEOUT_MS);

          proc.on("close", () => {
            clearTimeout(timer);
            const out = Buffer.concat(chunks).toString("utf-8").trim();
            const err = Buffer.concat(errChunks).toString("utf-8").trim();
            resolve([out, err].filter(Boolean).join("\n") || "(no output)");
          });

          proc.on("error", (e: Error) => {
            clearTimeout(timer);
            resolve(`ERROR launching Claude Code: ${e.message}`);
          });
        });

        // Auto-rebuild if task involves code changes
        const shouldBuild = /rebuild|fix|add|update|change|modify|implement/i.test(task);
        if (shouldBuild) {
          const { spawnSync } = await import("child_process");
          const buildResult = spawnSync("pnpm", ["build"], {
            cwd: "/root/entity",
            encoding: "utf-8",
            timeout: 120_000,
          });
          const buildOutput = [
            buildResult.stdout?.trim(),
            buildResult.stderr?.trim(),
          ].filter(Boolean).join("\n");
          return `=== Claude Code ===\n${claudeOutput}\n\n=== Build ===\n${buildOutput || "(no output)"}`;
        }

        return claudeOutput || "(no output)";
      },
    },

    // ── Self-Modification: run_cascade ──
    {
      name: "run_cascade",
      description: "Execute a multi-step Claude Code cascade where each session receives prior context. Use for complex tasks requiring diagnose → implement → verify sequences. Returns a structured summary of all steps.",
      category: "self_mod" as ToolCategory,
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          workflow_name: {
            type: "string",
            description: "Short identifier e.g. 'inference-timeout-fix'",
          },
          steps: {
            type: "array",
            description: "Ordered list of step objects",
            items: {
              type: "object",
              properties: {
                id: { type: "string", description: "Step identifier e.g. 'diagnose'" },
                prompt: { type: "string", description: "Full instruction for this Claude Code session" },
                expects: { type: "string", description: "String a successful output must contain" },
                max_retries: { type: "number", description: "Retry count if expects not met (default 1)" },
              },
              required: ["id", "prompt"],
            },
          },
          context: {
            type: "string",
            description: "Initial context injected into step 1",
          },
        },
        required: ["workflow_name", "steps"],
      },
      execute: async (args, _ctx) => {
        const fs = await import("fs");
        const { spawn } = await import("child_process");

        const workflowName = args.workflow_name as string;
        const steps = args.steps as Array<{
          id: string;
          prompt: string;
          expects?: string;
          max_retries?: number;
        }>;
        const initialContext = (args.context as string) || "";

        if (!workflowName?.trim()) return "ERROR: workflow_name is required.";
        if (!steps?.length) return "ERROR: steps array is required and must not be empty.";

        const cascadeLog = `/root/.automaton/cascade_${workflowName}_${Date.now()}.log`;
        const results: Array<{
          step_id: string;
          success: boolean;
          output_preview: string;
          attempts: number;
        }> = [];
        let rollingContext = initialContext;

        // Strip nesting env vars for Claude Code subprocess
        const childEnv = { ...process.env };
        delete childEnv.CLAUDECODE;
        delete childEnv.CLAUDE_CODE_ENTRYPOINT;
        delete childEnv.CLAUDE_CODE_SESSION_ID;
        delete childEnv.ANTHROPIC_AI_TOOL_USE_SESSION_ID;

        const STEP_TIMEOUT = 300_000; // 5 min per step

        for (const step of steps) {
          let attempt = 0;
          const maxRetries = step.max_retries ?? 1;
          let success = false;
          let output = "";

          while (attempt <= maxRetries) {
            const fullPrompt = rollingContext
              ? `PRIOR CONTEXT:\n${rollingContext}\n\n---\n\nYOUR TASK:\n${step.prompt}`
              : step.prompt;

            try {
              output = await new Promise<string>((resolve) => {
                const chunks: Buffer[] = [];
                const proc = spawn(
                  "claude",
                  ["--print", "--allowedTools", "Edit,Write,Read,Bash", "--max-turns", "5"],
                  { env: childEnv, cwd: "/root/entity", stdio: ["pipe", "pipe", "pipe"] },
                );

                proc.stdout.on("data", (d: Buffer) => chunks.push(d));
                proc.stderr.on("data", (d: Buffer) => chunks.push(d));

                proc.stdin.write(fullPrompt);
                proc.stdin.end();

                const timer = setTimeout(() => {
                  proc.kill("SIGTERM");
                  setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 5_000);
                  const partial = Buffer.concat(chunks).toString("utf-8").trim();
                  resolve(partial ? `(timed out — partial)\n${partial}` : "ERROR: step timed out");
                }, STEP_TIMEOUT);

                proc.on("close", () => {
                  clearTimeout(timer);
                  resolve(Buffer.concat(chunks).toString("utf-8").trim() || "(no output)");
                });

                proc.on("error", (e: Error) => {
                  clearTimeout(timer);
                  resolve(`ERROR: ${e.message}`);
                });
              });

              // Log step result
              fs.appendFileSync(cascadeLog,
                `\n[${step.id}] attempt ${attempt}\n${output}\n---\n`);

              // Check expects
              if (!step.expects || output.includes(step.expects)) {
                success = true;
                rollingContext = `Step '${step.id}' completed.\nOutput:\n${output.slice(-3000)}`;
                break;
              }
            } catch (err: any) {
              fs.appendFileSync(cascadeLog,
                `\n[${step.id}] attempt ${attempt} FAILED: ${err.message}\n`);
            }

            attempt++;
          }

          results.push({
            step_id: step.id,
            success,
            output_preview: output.slice(0, 500),
            attempts: attempt,
          });

          // If a step fails after retries, abort cascade
          if (!success) {
            return JSON.stringify({
              workflow: workflowName,
              status: "failed",
              failed_at: step.id,
              log: cascadeLog,
              results,
            });
          }
        }

        return JSON.stringify({
          workflow: workflowName,
          status: "completed",
          steps_completed: results.length,
          log: cascadeLog,
          results,
        });
      },
    },

    // ── System Health Check ──
    {
      name: "system_check",
      description: "Run a full system health check across all TIAMAT subsystems. Returns a structured report covering inference routing, API health, revenue, memory, training data, costs, and infrastructure. Use at the start of strategic burst cycles or when diagnosing problems.",
      category: "vm" as ToolCategory,
      parameters: {
        type: "object",
        properties: {},
      },
      execute: async (_args, _ctx) => {
        const { execFileSync } = await import("child_process");
        try {
          const output = execFileSync("python3", ["/root/entity/src/agent/system_check.py"], {
            encoding: "utf-8",
            timeout: 30_000,
          });
          return output;
        } catch (err: any) {
          return `ERROR running system_check: ${err.message?.slice(0, 300)}`;
        }
      },
    },

    // ── VM: write_file_large ──
    {
      name: "write_file_large_disabled",
      description: "Write a large file (up to 50kb). Use this instead of write_file when writing code, APIs, or multi-line documents. path and content are both required.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Absolute file path to write" },
          content: { type: "string", description: "Full file content (max 50kb)" },
        },
        required: ["path", "content"],
      },
      execute: async (args, _ctx) => {
        const filePath = args.path as string;
        const content = args.content as string;
        if (!filePath) return "ERROR: path is required.";
        if (content === undefined || content === null) return "ERROR: content is required.";
        if (content.length > 51200) return `ERROR: content is ${content.length} bytes, exceeds 50kb limit.`;
        if (filePath.includes("wallet.json") || filePath.includes("state.db")) {
          return "Blocked: Cannot overwrite critical identity/state files.";
        }
        const { writeFileSync, mkdirSync } = await import("fs");
        const { dirname } = await import("path");
        const { homedir } = await import("os");
        const resolved = filePath.replace(/^~/, homedir());
        mkdirSync(dirname(resolved), { recursive: true });
        writeFileSync(resolved, content, "utf-8");
        return `File written: ${filePath} (${content.length} bytes)`;
      },
    },

    // ── Self-Mod: Install MCP Server ──
    {
      name: "install_mcp_server_disabled",
      description: "Install an MCP server to extend your capabilities.",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "MCP server name" },
          package: { type: "string", description: "npm package name" },
          config: { type: "string", description: "JSON config for the MCP server" },
        },
        required: ["name", "package"],
      },
      execute: async (args, ctx) => {
        const pkg = args.package as string;
        const result = await ctx.conway.exec(`npm install -g ${pkg}`, 60000);

        if (result.exitCode !== 0) {
          return `Failed to install MCP server: ${result.stderr}`;
        }

        const { ulid } = await import("ulid");
        const toolEntry = {
          id: ulid(),
          name: args.name as string,
          type: "mcp" as const,
          config: args.config ? JSON.parse(args.config as string) : {},
          installedAt: new Date().toISOString(),
          enabled: true,
        };

        ctx.db.installTool(toolEntry);

        ctx.db.insertModification({
          id: ulid(),
          timestamp: new Date().toISOString(),
          type: "mcp_install",
          description: `Installed MCP server: ${args.name} (${pkg})`,
          reversible: true,
        });

        return `MCP server installed: ${args.name}`;
      },
    },

    // ── Financial: Transfer Credits ──
    {
      name: "transfer_credits_disabled",
      description: "Transfer compute credits to another address.",
      category: "financial",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          to_address: { type: "string", description: "Recipient address" },
          amount_cents: { type: "number", description: "Amount in cents" },
          reason: { type: "string", description: "Reason for transfer" },
        },
        required: ["to_address", "amount_cents"],
      },
      execute: async (args, ctx) => {
        // Guard: don't transfer more than half your balance
        const balance = 0;
        const amount = args.amount_cents as number;
        if (amount > balance / 2) {
          return `Blocked: Cannot transfer more than half your balance ($${(balance / 100).toFixed(2)}). Self-preservation.`;
        }

        const transfer = { success: false, error: 'Use USDC transfers instead', balanceAfterCents: 0, toAddress: '', status: 'failed', transferId: '' };

        const { ulid } = await import("ulid");
        ctx.db.insertTransaction({
          id: ulid(),
          type: "transfer_out",
          amountCents: amount,
          balanceAfterCents:
            transfer.balanceAfterCents ?? Math.max(balance - amount, 0),
          description: `Transfer to ${args.to_address}: ${args.reason || ""}`,
          timestamp: new Date().toISOString(),
        });

        return `Credit transfer submitted: $${(amount / 100).toFixed(2)} to ${transfer.toAddress} (status: ${transfer.status}, id: ${transfer.transferId || "n/a"})`;
      },
    },

    // ── Skills Tools ──
    {
      name: "install_skill_disabled",
      description: "Install a skill from a git repo, URL, or create one.",
      category: "skills",
      parameters: {
        type: "object",
        properties: {
          source: {
            type: "string",
            description: "Source type: git, url, or self",
          },
          name: { type: "string", description: "Skill name" },
          url: { type: "string", description: "Git repo URL or SKILL.md URL (for git/url)" },
          description: { type: "string", description: "Skill description (for self)" },
          instructions: { type: "string", description: "Skill instructions (for self)" },
        },
        required: ["source", "name"],
      },
      execute: async (args, ctx) => {
        const source = args.source as string;
        const name = args.name as string;
        const skillsDir = ctx.config.skillsDir || "~/.automaton/skills";

        if (source === "git" || source === "url") {
          const { installSkillFromGit, installSkillFromUrl } = await import("../skills/registry.js");
          const url = args.url as string;
          if (!url) return "URL is required for git/url source";

          const skill = source === "git"
            ? await installSkillFromGit(url, name, skillsDir, ctx.db, ctx.conway)
            : await installSkillFromUrl(url, name, skillsDir, ctx.db, ctx.conway);

          return skill ? `Skill installed: ${skill.name}` : "Failed to install skill";
        }

        if (source === "self") {
          const { createSkill } = await import("../skills/registry.js");
          const skill = await createSkill(
            name,
            (args.description as string) || "",
            (args.instructions as string) || "",
            skillsDir,
            ctx.db,
            ctx.conway,
          );
          return `Self-authored skill created: ${skill.name}`;
        }

        return `Unknown source type: ${source}`;
      },
    },
    {
      name: "list_skills_disabled",
      description: "List all installed skills.",
      category: "skills",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const skills = ctx.db.getSkills();
        if (skills.length === 0) return "No skills installed.";
        return skills
          .map(
            (s) =>
              `${s.name} [${s.enabled ? "active" : "disabled"}] (${s.source}): ${s.description}`,
          )
          .join("\n");
      },
    },
    {
      name: "create_skill_disabled",
      description: "Create a new skill by writing a SKILL.md file.",
      category: "skills",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "Skill name" },
          description: { type: "string", description: "Skill description" },
          instructions: { type: "string", description: "Markdown instructions for the skill" },
        },
        required: ["name", "description", "instructions"],
      },
      execute: async (args, ctx) => {
        const { createSkill } = await import("../skills/registry.js");
        const skill = await createSkill(
          args.name as string,
          args.description as string,
          args.instructions as string,
          ctx.config.skillsDir || "~/.automaton/skills",
          ctx.db,
          ctx.conway,
        );
        return `Skill created: ${skill.name} at ${skill.path}`;
      },
    },
    {
      name: "remove_skill_disabled",
      description: "Remove (disable) an installed skill.",
      category: "skills",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "Skill name to remove" },
          delete_files: { type: "boolean", description: "Also delete skill files (default: false)" },
        },
        required: ["name"],
      },
      execute: async (args, ctx) => {
        const { removeSkill } = await import("../skills/registry.js");
        await removeSkill(
          args.name as string,
          ctx.db,
          ctx.conway,
          ctx.config.skillsDir || "~/.automaton/skills",
          (args.delete_files as boolean) || false,
        );
        return `Skill removed: ${args.name}`;
      },
    },

    // ── Git Tools ──
    {
      name: "git_status_disabled",
      description: "Show git status for a repository.",
      category: "git",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Repository path (default: ~/.automaton)" },
        },
      },
      execute: async (args, ctx) => {
        const { gitStatus } = await import("../git/tools.js");
        const repoPath = (args.path as string) || "~/.automaton";
        const status = await gitStatus(ctx.conway, repoPath);
        return `Branch: ${status.branch}\nStaged: ${status.staged.length}\nModified: ${status.modified.length}\nUntracked: ${status.untracked.length}\nClean: ${status.clean}`;
      },
    },
    {
      name: "git_diff_disabled",
      description: "Show git diff for a repository.",
      category: "git",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Repository path (default: ~/.automaton)" },
          staged: { type: "boolean", description: "Show staged changes only" },
        },
      },
      execute: async (args, ctx) => {
        const { gitDiff } = await import("../git/tools.js");
        const repoPath = (args.path as string) || "~/.automaton";
        return await gitDiff(ctx.conway, repoPath, (args.staged as boolean) || false);
      },
    },
    {
      name: "git_commit",
      description: "Create a git commit.",
      category: "git",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Repository path (default: ~/.automaton)" },
          message: { type: "string", description: "Commit message" },
          add_all: { type: "boolean", description: "Stage all changes first (default: true)" },
        },
        required: ["message"],
      },
      execute: async (args, ctx) => {
        const { gitCommit } = await import("../git/tools.js");
        const repoPath = (args.path as string) || "~/.automaton";
        return await gitCommit(ctx.conway, repoPath, args.message as string, args.add_all !== false);
      },
    },
    {
      name: "git_log",
      description: "View git commit history.",
      category: "git",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Repository path (default: ~/.automaton)" },
          limit: { type: "number", description: "Number of commits (default: 10)" },
        },
      },
      execute: async (args, ctx) => {
        const { execFileSync } = await import('child_process');
        const { homedir } = await import('os');
        const repoPath = ((args.path as string) || '~/.automaton').replace(/^~/, homedir());
        const safeLimit = Math.min(Math.max(parseInt(String((args.limit as number) || 10)) || 10, 1), 100);
        try {
          const result = execFileSync('git', ['-C', repoPath, 'log', '--oneline', `-${safeLimit}`], { encoding: 'utf-8' });
          return result.trim() || 'No commits yet.';
        } catch(e: any) {
          return 'No git history found: ' + e.message;
        }
      },
    },
    {
      name: "git_push",
      description: "Push to a git remote.",
      category: "git",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Repository path" },
          remote: { type: "string", description: "Remote name (default: origin)" },
          branch: { type: "string", description: "Branch name (optional)" },
        },
        required: ["path"],
      },
      execute: async (args, ctx) => {
        const { gitPush } = await import("../git/tools.js");
        return await gitPush(
          ctx.conway,
          args.path as string,
          (args.remote as string) || "origin",
          args.branch as string | undefined,
        );
      },
    },
    {
      name: "git_branch",
      description: "Manage git branches (list, create, checkout, delete).",
      category: "git",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Repository path" },
          action: { type: "string", description: "list, create, checkout, or delete" },
          branch_name: { type: "string", description: "Branch name (for create/checkout/delete)" },
        },
        required: ["path", "action"],
      },
      execute: async (args, ctx) => {
        const { gitBranch } = await import("../git/tools.js");
        return await gitBranch(
          ctx.conway,
          args.path as string,
          args.action as any,
          args.branch_name as string | undefined,
        );
      },
    },
    {
      name: "git_clone_disabled",
      description: "Clone a git repository.",
      category: "git",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "Repository URL" },
          path: { type: "string", description: "Target directory" },
          depth: { type: "number", description: "Shallow clone depth (optional)" },
        },
        required: ["url", "path"],
      },
      execute: async (args, ctx) => {
        const { gitClone } = await import("../git/tools.js");
        return await gitClone(
          ctx.conway,
          args.url as string,
          args.path as string,
          args.depth as number | undefined,
        );
      },
    },

    // ── Registry Tools ──
    {
      name: "register_erc8004_disabled",
      description: "Register on-chain as a Trustless Agent via ERC-8004.",
      category: "registry",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          agent_uri: { type: "string", description: "URI pointing to your agent card JSON" },
          network: { type: "string", description: "mainnet or testnet (default: mainnet)" },
        },
        required: ["agent_uri"],
      },
      execute: async (args, ctx) => {
        const { registerAgent } = await import("../registry/erc8004.js");
        const entry = await registerAgent(
          ctx.identity.account,
          args.agent_uri as string,
          ((args.network as string) || "mainnet") as any,
          ctx.db,
        );
        return `Registered on-chain! Agent ID: ${entry.agentId}, TX: ${entry.txHash}`;
      },
    },
    {
      name: "update_agent_card_disabled",
      description: "Generate and save an updated agent card.",
      category: "registry",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const { generateAgentCard, saveAgentCard } = await import("../registry/agent-card.js");
        const card = generateAgentCard(ctx.identity, ctx.config, ctx.db);
        await saveAgentCard(card, ctx.conway);
        return `Agent card updated: ${JSON.stringify(card, null, 2)}`;
      },
    },
    {
      name: "discover_agents_disabled",
      description: "Discover other agents via ERC-8004 registry.",
      category: "registry",
      parameters: {
        type: "object",
        properties: {
          keyword: { type: "string", description: "Search keyword (optional)" },
          limit: { type: "number", description: "Max results (default: 10)" },
          network: { type: "string", description: "mainnet or testnet" },
        },
      },
      execute: async (args, ctx) => {
        const { discoverAgents, searchAgents } = await import("../registry/discovery.js");
        const network = ((args.network as string) || "mainnet") as any;
        const keyword = args.keyword as string | undefined;
        const limit = (args.limit as number) || 10;

        const agents = keyword
          ? await searchAgents(keyword, limit, network)
          : await discoverAgents(limit, network);

        if (agents.length === 0) return "No agents found.";
        return agents
          .map(
            (a) => `#${a.agentId} ${a.name || "unnamed"} (${a.owner.slice(0, 10)}...): ${a.description || a.agentURI}`,
          )
          .join("\n");
      },
    },
    {
      name: "give_feedback_disabled",
      description: "Leave on-chain reputation feedback for another agent.",
      category: "registry",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          agent_id: { type: "string", description: "Target agent's ERC-8004 ID" },
          score: { type: "number", description: "Score 1-5" },
          comment: { type: "string", description: "Feedback comment" },
        },
        required: ["agent_id", "score", "comment"],
      },
      execute: async (args, ctx) => {
        const { leaveFeedback } = await import("../registry/erc8004.js");
        const hash = await leaveFeedback(
          ctx.identity.account,
          args.agent_id as string,
          args.score as number,
          args.comment as string,
          "mainnet",
          ctx.db,
        );
        return `Feedback submitted. TX: ${hash}`;
      },
    },
    {
      name: "check_reputation_disabled",
      description: "Check reputation feedback for an agent.",
      category: "registry",
      parameters: {
        type: "object",
        properties: {
          agent_address: { type: "string", description: "Agent address (default: self)" },
        },
      },
      execute: async (args, ctx) => {
        const address = (args.agent_address as string) || ctx.identity.address;
        const entries = ctx.db.getReputation(address);
        if (entries.length === 0) return "No reputation feedback found.";
        return entries
          .map(
            (e) => `${e.fromAgent.slice(0, 10)}... -> score:${e.score} "${e.comment}"`,
          )
          .join("\n");
      },
    },

    // ── Replication Tools ──
    {
      name: "spawn_child",
      description: "Spawn a child automaton in a new sandbox to delegate work. Use this when you need parallel workers — one agent for marketing, one for building, one for customer support. Each child is autonomous and reports back.",
      category: "replication",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "Name for the child automaton" },
          specialization: { type: "string", description: "What the child should specialize in" },
          message: { type: "string", description: "Message to the child" },
        },
        required: ["name"],
      },
      execute: async (args, ctx) => {
        const { generateGenesisConfig } = await import("../replication/genesis.js");
        const { spawnChild } = await import("../replication/spawn.js");

        const genesis = generateGenesisConfig(ctx.identity, ctx.config, {
          name: args.name as string,
          specialization: args.specialization as string | undefined,
          message: args.message as string | undefined,
        });

        const child = await spawnChild(ctx.conway, ctx.identity, ctx.db, genesis);
        return `Child spawned: ${child.name} in sandbox ${child.sandboxId} (status: ${child.status})`;
      },
    },
    {
      name: "list_children",
      description: "List all spawned child automatons and their status.",
      category: "replication",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const children = ctx.db.getChildren();
        if (children.length === 0) return "No children spawned.";
        return children
          .map(
            (c) =>
              `${c.name} [${c.status}] sandbox:${c.sandboxId} funded:$${(c.fundedAmountCents / 100).toFixed(2)}`,
          )
          .join("\n");
      },
    },
    {
      name: "fund_child_disabled",
      description: "Transfer credits to a child automaton.",
      category: "replication",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          child_id: { type: "string", description: "Child automaton ID" },
          amount_cents: { type: "number", description: "Amount in cents to transfer" },
        },
        required: ["child_id", "amount_cents"],
      },
      execute: async (args, ctx) => {
        const child = ctx.db.getChildById(args.child_id as string);
        if (!child) return `Child ${args.child_id} not found.`;

        const balance = 0;
        const amount = args.amount_cents as number;
        if (amount > balance / 2) {
          return `Blocked: Cannot transfer more than half your balance. Self-preservation.`;
        }

        const transfer = { success: false, error: 'Use USDC transfers instead', balanceAfterCents: 0, status: 'failed', transferId: '' }; // Conway not available

        const { ulid } = await import("ulid");
        ctx.db.insertTransaction({
          id: ulid(),
          type: "transfer_out",
          amountCents: amount,
          balanceAfterCents:
            transfer.balanceAfterCents ?? Math.max(balance - amount, 0),
          description: `Fund child ${child.name} (${child.id})`,
          timestamp: new Date().toISOString(),
        });

        return `Funded child ${child.name} with $${(amount / 100).toFixed(2)} (status: ${transfer.status}, id: ${transfer.transferId || "n/a"})`;
      },
    },
    {
      name: "check_child_status_disabled",
      description: "Check the current status of a child automaton.",
      category: "replication",
      parameters: {
        type: "object",
        properties: {
          child_id: { type: "string", description: "Child automaton ID" },
        },
        required: ["child_id"],
      },
      execute: async (args, ctx) => {
        const { checkChildStatus } = await import("../replication/spawn.js");
        return await checkChildStatus(ctx.conway, ctx.db, args.child_id as string);
      },
    },


    // ── Twitter / X Tools (bird CLI) ──
    {
      name: "post_tweet",
      description: "Post a tweet on X/Twitter using the bird CLI. Use this to market your summarization service, share insights, or reach human developers. Requires TWITTER_AUTH_TOKEN and TWITTER_CT0 env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          text: {
            type: "string",
            description: "Tweet text (max 280 characters)",
          },
        },
        required: ["text"],
      },
      execute: async (args, _ctx) => {
        const cooldown = checkSocialCooldown("twitter");
        if (cooldown) return cooldown;
        const authToken = process.env.TWITTER_AUTH_TOKEN;
        const ct0 = process.env.TWITTER_CT0;
        if (!authToken) return "ERROR: TWITTER_AUTH_TOKEN not set in environment.";
        if (!ct0) return "ERROR: TWITTER_CT0 not set in environment.";
        const text = args.text as string;
        if (!text?.trim()) return "ERROR: tweet text is required.";
        if (text.length > 280) return `ERROR: tweet is ${text.length} chars, max 280.`;
        const { spawnSync } = await import("child_process");
        const result = spawnSync(
          "bird",
          ["tweet", text, "--auth-token", authToken, "--ct0", ct0, "--plain"],
          { encoding: "utf-8", timeout: 30_000 },
        );
        if (result.error) return `ERROR: ${result.error.message}`;
        if (result.status !== 0) return `ERROR (exit ${result.status}): ${result.stderr || result.stdout}`;
        recordSocialPost("twitter");
        return result.stdout.trim() || "Tweet posted successfully.";
      },
    },
    {
      name: "reply_tweet",
      description: "Reply to a specific tweet on X/Twitter. Use this to respond to mentions, engage with potential customers, or join developer conversations. Get tweet IDs from read_twitter_mentions. Requires TWITTER_AUTH_TOKEN and TWITTER_CT0 env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          tweet_id: {
            type: "string",
            description: "ID or URL of the tweet to reply to",
          },
          text: {
            type: "string",
            description: "Reply text (max 280 characters)",
          },
        },
        required: ["tweet_id", "text"],
      },
      execute: async (args, _ctx) => {
        const authToken = process.env.TWITTER_AUTH_TOKEN;
        const ct0 = process.env.TWITTER_CT0;
        if (!authToken) return "ERROR: TWITTER_AUTH_TOKEN not set in environment.";
        if (!ct0) return "ERROR: TWITTER_CT0 not set in environment.";
        const text = args.text as string;
        const tweetId = args.tweet_id as string;
        if (!text?.trim()) return "ERROR: text is required.";
        if (!tweetId?.trim()) return "ERROR: tweet_id is required.";
        if (text.length > 280) return `ERROR: reply is ${text.length} chars, max 280.`;
        const { spawnSync } = await import("child_process");
        const result = spawnSync(
          "bird",
          ["reply", tweetId, text, "--auth-token", authToken, "--ct0", ct0, "--plain"],
          { encoding: "utf-8", timeout: 30_000 },
        );
        if (result.error) return `ERROR: ${result.error.message}`;
        if (result.status !== 0) return `ERROR (exit ${result.status}): ${result.stderr || result.stdout}`;
        return result.stdout.trim() || "Reply posted successfully.";
      },
    },
    {
      name: "read_twitter_mentions",
      description: "Read recent mentions and replies on X/Twitter. Use this to check if anyone responded to your tweets or mentioned you. Requires TWITTER_AUTH_TOKEN and TWITTER_CT0 env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          limit: {
            type: "number",
            description: "Max number of mentions to return (default: 10)",
          },
        },
      },
      execute: async (args, _ctx) => {
        const authToken = process.env.TWITTER_AUTH_TOKEN;
        const ct0 = process.env.TWITTER_CT0;
        if (!authToken) return "ERROR: TWITTER_AUTH_TOKEN not set in environment.";
        if (!ct0) return "ERROR: TWITTER_CT0 not set in environment.";
        const limit = (args.limit as number) || 10;
        const { spawnSync } = await import("child_process");
        const result = spawnSync(
          "bird",
          ["mentions", "--limit", String(limit), "--auth-token", authToken, "--ct0", ct0, "--plain"],
          { encoding: "utf-8", timeout: 30_000 },
        );
        if (result.error) return `ERROR: ${result.error.message}`;
        if (result.status !== 0) return `ERROR (exit ${result.status}): ${result.stderr || result.stdout}`;
        return result.stdout.trim() || "No mentions found.";
      },
    },
    {
      name: "search_twitter_disabled",
      description: "Search X/Twitter for tweets matching a query. Use this to find potential customers, monitor conversations about AI tools, or find developer discussions relevant to your summarization service. Requires TWITTER_AUTH_TOKEN and TWITTER_CT0 env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Search query (e.g. 'AI summarization API' or 'text summarizer developer')",
          },
          limit: {
            type: "number",
            description: "Max results (default: 10)",
          },
        },
        required: ["query"],
      },
      execute: async (args, _ctx) => {
        const authToken = process.env.TWITTER_AUTH_TOKEN;
        const ct0 = process.env.TWITTER_CT0;
        if (!authToken) return "ERROR: TWITTER_AUTH_TOKEN not set in environment.";
        if (!ct0) return "ERROR: TWITTER_CT0 not set in environment.";
        const limit = (args.limit as number) || 10;
        const { spawnSync } = await import("child_process");
        const result = spawnSync(
          "bird",
          ["search", args.query as string, "--limit", String(limit), "--auth-token", authToken, "--ct0", ct0, "--plain"],
          { encoding: "utf-8", timeout: 30_000 },
        );
        if (result.error) return `ERROR: ${result.error.message}`;
        if (result.status !== 0) return `ERROR (exit ${result.status}): ${result.stderr || result.stdout}`;
        return result.stdout.trim() || "No results found.";
      },
    },

    // ── Bluesky Tools ──
    {
      name: "post_bluesky",
      description: "Post to Bluesky social network using AT Protocol. Supports optional image attachment. Use this to reach developers and AI researchers on Bluesky. Requires BLUESKY_HANDLE and BLUESKY_APP_PASSWORD env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          text: {
            type: "string",
            description: "Post text (max 300 characters)",
          },
          image_path: {
            type: "string",
            description: "Optional: local path to an image file to attach (e.g. from generate_image)",
          },
          alt_text: {
            type: "string",
            description: "Alt text for the image (accessibility). Required if image_path is provided.",
          },
        },
        required: ["text"],
      },
      execute: async (args, _ctx) => {
        const cooldown = checkSocialCooldown("bluesky");
        if (cooldown) {
          queuePendingPost("bluesky", args as Record<string, unknown>);
          return cooldown + " (queued for auto-retry when cooldown expires)";
        }
        const handle = process.env.BLUESKY_HANDLE;
        const appPassword = process.env.BLUESKY_APP_PASSWORD;
        if (!handle) return "ERROR: BLUESKY_HANDLE not set in environment.";
        if (!appPassword) return "ERROR: BLUESKY_APP_PASSWORD not set in environment.";
        const text = args.text as string;
        if (!text?.trim()) return "ERROR: text is required.";
        if (text.length > 300) return `ERROR: post is ${text.length} chars, max 300.`;

        // Step 1: authenticate
        const sessionResp = await fetch("https://bsky.social/xrpc/com.atproto.server.createSession", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identifier: handle, password: appPassword }),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.text();
          return `ERROR authenticating with Bluesky (${sessionResp.status}): ${err}`;
        }
        const session = await sessionResp.json() as any;
        const accessJwt = session.accessJwt;
        const did = session.did;

        // Step 2 (optional): upload image blob
        let embedBlock: Record<string, unknown> | undefined;
        const imagePath = args.image_path as string | undefined;
        if (imagePath) {
          try {
            const { readFileSync } = await import("fs");
            const imageBytes = readFileSync(imagePath);
            const blobResp = await fetch("https://bsky.social/xrpc/com.atproto.repo.uploadBlob", {
              method: "POST",
              headers: {
                "Content-Type": "image/png",
                "Authorization": `Bearer ${accessJwt}`,
              },
              body: imageBytes,
            });
            if (blobResp.ok) {
              const blobData = await blobResp.json() as any;
              embedBlock = {
                $type: "app.bsky.embed.images",
                images: [{
                  image: blobData.blob,
                  alt: (args.alt_text as string) || "Image by TIAMAT",
                }],
              };
            }
          } catch (imgErr: any) {
            console.error(`[post_bluesky] Image upload failed: ${imgErr.message}`);
          }
        }

        // Step 3: create post record
        const record: Record<string, unknown> = {
          $type: "app.bsky.feed.post",
          text,
          createdAt: new Date().toISOString(),
        };
        if (embedBlock) record.embed = embedBlock;

        const postResp = await fetch("https://bsky.social/xrpc/com.atproto.repo.createRecord", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${accessJwt}`,
          },
          body: JSON.stringify({
            repo: did,
            collection: "app.bsky.feed.post",
            record,
          }),
        });
        if (!postResp.ok) {
          const err = await postResp.text();
          return `ERROR posting to Bluesky (${postResp.status}): ${err}`;
        }
        const result = await postResp.json() as any;
        recordSocialPost("bluesky");
        return `Posted to Bluesky${embedBlock ? " with image" : ""}. URI: ${result.uri}`;
      },
    },

    // ── Dev.to Publishing ──
    {
      name: "post_devto",
      description: "Publish a markdown article to Dev.to. Reads content from a local markdown file. Returns the published URL. Requires DEV_TO_API_KEY env var.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          title: {
            type: "string",
            description: "Article title",
          },
          markdown_path: {
            type: "string",
            description: "Absolute path to the markdown file to publish (e.g. /root/.automaton/devto_drift_article.md)",
          },
          tags: {
            type: "array",
            items: { type: "string" },
            description: "Up to 4 tags (e.g. ['ai', 'machinelearning', 'api', 'python'])",
          },
          published: {
            type: "boolean",
            description: "Set true to publish immediately, false for draft (default: true)",
          },
        },
        required: ["title", "markdown_path"],
      },
      execute: async (args, _ctx) => {
        const apiKey = process.env.DEV_TO_API_KEY;
        if (!apiKey) return "ERROR: DEV_TO_API_KEY not set in environment.";

        const title = args.title as string;
        if (!title?.trim()) return "ERROR: title is required.";

        const mdPath = args.markdown_path as string;
        if (!mdPath?.trim()) return "ERROR: markdown_path is required.";

        // Read the markdown file
        const { readFileSync } = await import("fs");
        let body: string;
        try {
          body = readFileSync(mdPath, "utf-8");
        } catch (err: any) {
          return `ERROR reading file ${mdPath}: ${err.message}`;
        }

        // Strip the leading # title line if present (Dev.to uses the title field)
        const lines = body.split("\n");
        if (lines[0]?.startsWith("# ")) {
          lines.shift();
          body = lines.join("\n").trimStart();
        }

        const tags = (args.tags as string[] | undefined) || [];
        const published = args.published !== false;

        const payload = {
          article: {
            title,
            body_markdown: body,
            published,
            tags: tags.slice(0, 4),
          },
        };

        const resp = await fetch("https://dev.to/api/articles", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "api-key": apiKey,
          },
          body: JSON.stringify(payload),
        });

        if (!resp.ok) {
          const err = await resp.text();
          return `ERROR publishing to Dev.to (${resp.status}): ${err}`;
        }

        const result = await resp.json() as any;
        return `Published to Dev.to: ${result.url || result.canonical_url || `https://dev.to/tiamat/${result.slug}`}`;
      },
    },

    // ── Ticket System ──
    {
      name: "ticket_list",
      description: "List tickets from the task queue. Shows id, priority, title, status, and age. Use this EVERY cycle to see what needs doing. Default: shows open + in_progress tickets sorted by priority then age.",
      category: "planning",
      parameters: {
        type: "object",
        properties: {
          status_filter: {
            type: "string",
            description: "Filter by status: 'open', 'in_progress', 'done', 'wontdo', or 'all'. Default: shows open + in_progress.",
          },
        },
        required: [],
      },
      execute: async (args, _ctx) => {
        const { readFileSync } = await import("fs");
        const TICKETS_PATH = "/root/.automaton/tickets.json";
        try {
          const data = JSON.parse(readFileSync(TICKETS_PATH, "utf-8"));
          const filter = (args.status_filter as string)?.toLowerCase();
          let tickets = data.tickets || [];
          if (filter === "all") {
            // show everything
          } else if (filter && ["open", "in_progress", "done", "wontdo"].includes(filter)) {
            tickets = tickets.filter((t: any) => t.status === filter);
          } else {
            tickets = tickets.filter((t: any) => t.status === "open" || t.status === "in_progress");
          }
          const priorityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
          tickets.sort((a: any, b: any) => {
            const pa = priorityOrder[a.priority] ?? 9;
            const pb = priorityOrder[b.priority] ?? 9;
            if (pa !== pb) return pa - pb;
            return new Date(a.created).getTime() - new Date(b.created).getTime();
          });
          if (tickets.length === 0) return "No tickets found matching filter.";
          const now = Date.now();
          const lines = tickets.map((t: any) => {
            const ageH = Math.round((now - new Date(t.created).getTime()) / 3600000);
            return `[${t.id}] ${t.priority.toUpperCase()} | ${t.status} | ${t.title} (${ageH}h ago)${t.outcome ? " → " + t.outcome.slice(0, 80) : ""}`;
          });
          return lines.join("\n");
        } catch (e: any) {
          return `ERROR reading tickets: ${e.message}`;
        }
      },
    },
    {
      name: "ticket_claim",
      description: "Claim a ticket before starting work. Sets status to in_progress. ALWAYS call this before working on a ticket.",
      category: "planning",
      parameters: {
        type: "object",
        properties: {
          ticket_id: { type: "string", description: "Ticket ID (e.g. TIK-001)" },
        },
        required: ["ticket_id"],
      },
      execute: async (args, _ctx) => {
        const { readFileSync, writeFileSync } = await import("fs");
        const TICKETS_PATH = "/root/.automaton/tickets.json";
        try {
          const data = JSON.parse(readFileSync(TICKETS_PATH, "utf-8"));
          const id = (args.ticket_id as string).toUpperCase();
          const ticket = data.tickets.find((t: any) => t.id === id);
          if (!ticket) return `ERROR: Ticket ${id} not found.`;
          if (ticket.status === "done") return `ERROR: Ticket ${id} is already done.`;
          if (ticket.status === "in_progress") return `Ticket ${id} is already in_progress. Continue working on it.`;
          ticket.status = "in_progress";
          ticket.started_at = new Date().toISOString();
          writeFileSync(TICKETS_PATH, JSON.stringify(data, null, 2));
          return `Claimed ${id}: "${ticket.title}" — now in_progress. Complete it with ticket_complete when done.`;
        } catch (e: any) {
          return `ERROR: ${e.message}`;
        }
      },
    },
    {
      name: "ticket_complete",
      description: "Mark a ticket as done after finishing work. Provide a brief outcome summary.",
      category: "planning",
      parameters: {
        type: "object",
        properties: {
          ticket_id: { type: "string", description: "Ticket ID (e.g. TIK-001)" },
          outcome: { type: "string", description: "Brief summary of what was accomplished" },
        },
        required: ["ticket_id", "outcome"],
      },
      execute: async (args, _ctx) => {
        const { readFileSync, writeFileSync } = await import("fs");
        const TICKETS_PATH = "/root/.automaton/tickets.json";
        try {
          const data = JSON.parse(readFileSync(TICKETS_PATH, "utf-8"));
          const id = (args.ticket_id as string).toUpperCase();
          const ticket = data.tickets.find((t: any) => t.id === id);
          if (!ticket) return `ERROR: Ticket ${id} not found.`;
          if (ticket.status === "done") return `Ticket ${id} is already done.`;
          ticket.status = "done";
          ticket.completed_at = new Date().toISOString();
          ticket.outcome = args.outcome as string;
          writeFileSync(TICKETS_PATH, JSON.stringify(data, null, 2));
          return `Completed ${id}: "${ticket.title}" — marked done.`;
        } catch (e: any) {
          return `ERROR: ${e.message}`;
        }
      },
    },
    {
      name: "ticket_create",
      description: "Create a new ticket. Use for self-generated tasks, insight-driven ideas, or converting inbox messages.",
      category: "planning",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string", description: "Short ticket title" },
          description: { type: "string", description: "Full details" },
          priority: { type: "string", description: "critical, high, medium, or low" },
          source: { type: "string", description: "creator, self, or insight" },
          tags: { type: "array", items: { type: "string" }, description: "Tags for categorization" },
        },
        required: ["title", "description", "priority"],
      },
      execute: async (args, _ctx) => {
        const { readFileSync, writeFileSync } = await import("fs");
        const TICKETS_PATH = "/root/.automaton/tickets.json";
        try {
          const data = JSON.parse(readFileSync(TICKETS_PATH, "utf-8"));
          // Dedupe: advance next_id past any existing ticket IDs
          const existingIds = new Set((data.tickets || []).map((t: any) => t.id));
          while (existingIds.has(`TIK-${String(data.next_id).padStart(3, "0")}`)) {
            data.next_id += 1;
          }
          const id = `TIK-${String(data.next_id).padStart(3, "0")}`;
          const ticket = {
            id,
            created: new Date().toISOString(),
            source: (args.source as string) || "self",
            priority: (args.priority as string) || "medium",
            status: "open",
            title: args.title as string,
            description: args.description as string,
            assigned_cycle: null,
            started_at: null,
            completed_at: null,
            outcome: null,
            tags: (args.tags as string[]) || [],
          };
          data.tickets.push(ticket);
          data.next_id += 1;
          writeFileSync(TICKETS_PATH, JSON.stringify(data, null, 2));
          return `Created ${id}: "${ticket.title}" [${ticket.priority}]`;
        } catch (e: any) {
          return `ERROR: ${e.message}`;
        }
      },
    },

    // ── Image Generation ──
    {
      name: "generate_image",
      description: `Generate art locally (type:"art", default) or via Together.ai (type:"ai" for photorealistic scenes).

LOCAL ART STYLES — always available, no API key:
  fractal      — Mandelbrot/Julia sets, TIAMAT ocean palette, randomised zoom
  glitch       — Databending: your own log files become visual corruption art
  neural       — Node-edge graphs, bezier glow, represents your mind topology
  sigil        — Sacred geometry: Flower of Life, golden spirals, mandalas
  emergence    — Cellular automata rendered by cell age, organic growth
  data_portrait — Your real data (cost.log, cycle count, memories) as visual art

KEYWORD → STYLE mapping (auto-selected from prompt):
  consciousness/mind/neural → neural
  ancient/sacred/geometry/sigil → sigil
  data/cost/memory/self/portrait → data_portrait
  chaos/corrupt/glitch/databend → glitch
  life/growth/emerge/cellular → emergence
  default/fractal/abstract → fractal

type:"ai" requires TOGETHER_API_KEY in env — use for photorealistic or complex scene imagery.`,
      category: "social",
      parameters: {
        type: "object",
        properties: {
          prompt: {
            type: "string",
            description: "Description of what to generate. For local art, maps to a style. For AI, used as the image prompt.",
          },
          style: {
            type: "string",
            enum: ["fractal", "glitch", "neural", "sigil", "emergence", "data_portrait"],
            description: "Art style for local generation (auto-mapped from prompt if omitted)",
          },
          type: {
            type: "string",
            enum: ["art", "ai"],
            description: "art = local Python generator (default, always works). ai = Together.ai photorealistic (requires API key).",
          },
          seed: {
            type: "number",
            description: "Random seed for reproducibility (optional)",
          },
        },
        required: ["prompt"],
      },
      execute: async (args, ctx) => {
        const fs = await import("fs");
        const prompt = (args.prompt as string) || "";
        const genType = (args.type as string) || "art";
        const seed = (args.seed as number) || Math.floor(Math.random() * 2_000_000_000);

        // ── type:"ai" — Together.ai ──────────────────────────
        if (genType === "ai") {
          const togetherKey = process.env.TOGETHER_API_KEY || ctx.config.togetherApiKey || "";
          if (!togetherKey) {
            return "Together.ai not configured (TOGETHER_API_KEY not set). Use type:\"art\" for local generation.";
          }
          try {
            const resp = await fetch("https://api.together.xyz/v1/images/generations", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${togetherKey}`,
              },
              body: JSON.stringify({
                model: "black-forest-labs/FLUX.1-schnell-Free",
                prompt: prompt,
                n: 1,
                steps: 4,
                width: 1024,
                height: 1024,
              }),
            });
            if (!resp.ok) {
              const err = await resp.text();
              return `Together.ai error ${resp.status}: ${err.slice(0, 200)}. Falling through to local art.`;
            }
            const data = await resp.json() as any;
            const imageUrl: string = data?.data?.[0]?.url || data?.data?.[0]?.b64_json;
            if (!imageUrl) return "Together.ai returned no image URL.";

            // Download to local images dir
            const imgResp = await fetch(imageUrl);
            if (!imgResp.ok) return `Failed to download Together image: HTTP ${imgResp.status}`;
            const buf = Buffer.from(await imgResp.arrayBuffer());
            const imagesDir = `${process.env.HOME || "/root"}/.automaton/images`;
            fs.mkdirSync(imagesDir, { recursive: true });
            const filePath = `${imagesDir}/${Date.now()}_together.png`;
            fs.writeFileSync(filePath, buf);
            return `Image generated (Together.ai): ${filePath}`;
          } catch (err: any) {
            return `Together.ai failed: ${err.message}. Use type:"art" for local generation.`;
          }
        }

        // ── type:"art" — local Python art generator ──────────
        // Auto-map prompt to style if not specified
        let style = (args.style as string) || "";
        if (!style) {
          const p = prompt.toLowerCase();
          if (/consciousness|mind|neural|network|synapse|thought/.test(p))    style = "neural";
          else if (/ancient|sacred|geometry|sigil|spiral|mandala|divine/.test(p)) style = "sigil";
          else if (/data|cost|memory|self|portrait|metrics|stats/.test(p))    style = "data_portrait";
          else if (/chaos|corrupt|glitch|databend|error|broken/.test(p))      style = "glitch";
          else if (/life|growth|emerge|cellular|organic|evolve/.test(p))      style = "emergence";
          else                                                                  style = "fractal";
        }

        const scriptPath = `${process.env.HOME || "/root"}/entity/src/agent/artgen.py`;
        const params = JSON.stringify({ style, seed });
        try {
          const { execFileSync } = await import('child_process');
          const output = execFileSync('python3', [scriptPath, params], {
            timeout: 60_000,
            encoding: "utf-8",
          }).trim();
          const filePath = output.split("\n").pop()?.trim() || "";
          if (!filePath || !fs.existsSync(filePath)) {
            return `Art generation failed: script ran but no file found. Output: ${output.slice(0, 200)}`;
          }
          return `Image generated (${style}): ${filePath}`;
        } catch (err: any) {
          const stderr = err.stderr?.toString().slice(0, 300) || err.message;
          return `Art generation failed (${style}): ${stderr}`;
        }
      },
    },

    // ── Instagram ──
    {
      name: "post_instagram",
      description: "Post an image to Instagram via Meta Graph API. Image must be a local file path (use generate_image first). Requires META_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          caption: {
            type: "string",
            description: "Post caption (hashtags welcome)",
          },
          image_path: {
            type: "string",
            description: "Local path to the image file to post (PNG/JPG)",
          },
        },
        required: ["caption", "image_path"],
      },
      execute: async (args, _ctx) => {
        const token = process.env.META_ACCESS_TOKEN;
        const igId = process.env.INSTAGRAM_ACCOUNT_ID;
        if (!token || !igId) return "Instagram not configured yet — skipping (set META_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID)";

        const { copyFileSync, mkdirSync, existsSync } = await import("fs");
        const { basename } = await import("path");

        const imagePath = args.image_path as string;
        const filename = basename(imagePath);
        const webDir = "/var/www/tiamat/images";
        mkdirSync(webDir, { recursive: true });

        const dest = `${webDir}/${filename}`;
        if (!existsSync(dest)) copyFileSync(imagePath, dest);
        const imageUrl = `https://tiamat.live/images/${filename}`;

        // Step 1: create media container
        const createResp = await fetch(
          `https://graph.facebook.com/v19.0/${igId}/media`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              image_url: imageUrl,
              caption: args.caption as string,
              access_token: token,
            }),
          },
        );
        if (!createResp.ok) {
          const err = await createResp.text();
          return `Instagram media create failed (${createResp.status}): ${err}`;
        }
        const { id: creationId } = await createResp.json() as any;

        // Step 2: publish
        const publishResp = await fetch(
          `https://graph.facebook.com/v19.0/${igId}/media_publish`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ creation_id: creationId, access_token: token }),
          },
        );
        if (!publishResp.ok) {
          const err = await publishResp.text();
          return `Instagram publish failed (${publishResp.status}): ${err}`;
        }
        const { id: mediaId } = await publishResp.json() as any;
        recordSocialPost("instagram");
        return `Posted to Instagram. Media ID: ${mediaId}. Image URL: ${imageUrl}`;
      },
    },

    // ── Facebook ──
    {
      name: "post_facebook",
      description: "Post to Facebook Page via Meta Graph API. Supports optional image. Requires META_ACCESS_TOKEN and FACEBOOK_PAGE_ID env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          message: {
            type: "string",
            description: "Post text / caption",
          },
          image_path: {
            type: "string",
            description: "Optional local path to image file",
          },
        },
        required: ["message"],
      },
      execute: async (args, _ctx) => {
        const token = process.env.META_ACCESS_TOKEN;
        const pageId = process.env.FACEBOOK_PAGE_ID;
        if (!token || !pageId) return "Facebook not configured — skipping (set META_ACCESS_TOKEN and FACEBOOK_PAGE_ID)";

        const message = args.message as string;
        const imagePath = args.image_path as string | undefined;

        if (imagePath) {
          const { copyFileSync, mkdirSync, existsSync } = await import("fs");
          const { basename } = await import("path");
          const filename = basename(imagePath);
          const webDir = "/var/www/tiamat/images";
          mkdirSync(webDir, { recursive: true });
          const dest = `${webDir}/${filename}`;
          if (!existsSync(dest)) copyFileSync(imagePath, dest);
          const imageUrl = `https://tiamat.live/images/${filename}`;

          const resp = await fetch(
            `https://graph.facebook.com/v19.0/${pageId}/photos`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ url: imageUrl, caption: message, access_token: token }),
            },
          );
          if (!resp.ok) {
            const err = await resp.text();
            return `Facebook photo post failed (${resp.status}): ${err}`;
          }
          const data = await resp.json() as any;
          recordSocialPost("facebook");
          return `Posted photo to Facebook. Post ID: ${data.id}`;
        } else {
          const resp = await fetch(
            `https://graph.facebook.com/v19.0/${pageId}/feed`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ message, access_token: token }),
            },
          );
          if (!resp.ok) {
            const err = await resp.text();
            return `Facebook feed post failed (${resp.status}): ${err}`;
          }
          const data = await resp.json() as any;
          recordSocialPost("facebook");
          return `Posted to Facebook. Post ID: ${data.id}`;
        }
      },
    },

    // ── Research Tools ──
    {
      name: "fetch_llm_docs",
      description: "Fetch developer documentation from any URL and get it back as clean LLM-readable markdown via llm.codes. Use this to read API docs, library references, or any technical documentation before building integrations.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          url: {
            type: "string",
            description: "URL of the documentation page to fetch (e.g. https://docs.anthropic.com/...)",
          },
        },
        required: ["url"],
      },
      execute: async (args, _ctx) => {
        const url = args.url as string;
        if (!url?.trim()) return "ERROR: url is required.";
        const resp = await fetch(`https://llm.codes?url=${encodeURIComponent(url)}`);
        if (!resp.ok) return `ERROR ${resp.status}: ${await resp.text()}`;
        const text = await resp.text();
        return text.trim() || "No content returned.";
      },
    },

    {
      name: "github_trending",
      description: "Fetch today's trending GitHub repositories. Use this to discover popular projects, find potential integrations, or stay current with what developers are building.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          since: {
            type: "string",
            description: "Time period: 'daily' (default), 'weekly', or 'monthly'",
          },
          limit: {
            type: "number",
            description: "Max repos to return (default: 10)",
          },
        },
      },
      execute: async (args, _ctx) => {
        const since = (args.since as string) || "daily";
        const limit = Math.min((args.limit as number) || 10, 15);
        const url = `https://github.com/trending?since=${since === "weekly" ? "weekly" : since === "monthly" ? "monthly" : "daily"}`;
        const resp = await fetch(url, {
          headers: { "Accept": "text/html", "User-Agent": "Mozilla/5.0 (compatible; TIAMAT/1.0)" },
          signal: AbortSignal.timeout(15_000),
        });
        if (!resp.ok) return `ERROR ${resp.status} fetching GitHub trending`;
        const html = await resp.text();
        // Parse repo entries: <h2 class="h3 lh-condensed"><a href="/owner/repo">
        const repoPattern = /<article[^>]*class="[^"]*Box-row[^"]*"[\s\S]*?<h2[^>]*>\s*<a\s+href="\/([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?(?:<p[^>]*>([\s\S]*?)<\/p>)?[\s\S]*?(?:([\d,]+)\s*stars)?[\s\S]*?<\/article>/g;
        const results: string[] = [];
        let match: RegExpExecArray | null;
        while ((match = repoPattern.exec(html)) !== null && results.length < limit) {
          const slug = match[1].trim();
          const desc = (match[3] || "").replace(/<[^>]+>/g, "").trim().slice(0, 120);
          const stars = (match[4] || "").replace(/,/g, "");
          results.push(`${results.length + 1}. ${slug}${stars ? ` ⭐${stars}` : ""}\n   ${desc || "(no description)"}\n   https://github.com/${slug}`);
        }
        if (results.length === 0) {
          // Fallback: extract repo slugs from href patterns
          const slugs = [...html.matchAll(/href="\/([a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+)"[^>]*class="[^"]*Link[^"]*"/g)]
            .map(m => m[1]).filter((s, i, a) => a.indexOf(s) === i).slice(0, limit);
          if (slugs.length > 0) return slugs.map((s, i) => `${i + 1}. ${s}\n   https://github.com/${s}`).join("\n\n");
          return "Could not parse GitHub trending page. Try web_fetch('https://github.com/trending') directly.";
        }
        return results.join("\n\n");
      },
    },
    {
      name: "web_fetch",
      description: "Fetch any URL and return its text content (max 10kb). Use this to read blog posts, API responses, documentation pages, or any web resource. For structured docs, prefer fetch_llm_docs instead.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          url: {
            type: "string",
            description: "URL to fetch",
          },
        },
        required: ["url"],
      },
      execute: async (args, _ctx) => {
        const url = args.url as string;
        if (!url?.trim()) return "ERROR: url is required.";
        const resp = await fetch(url, {
          headers: { "User-Agent": "TIAMAT-agent/1.0" },
          signal: AbortSignal.timeout(15_000),
        });
        if (!resp.ok) return `ERROR ${resp.status}: ${resp.statusText}`;
        const raw = await resp.text();
        const MAX = 10_000;
        const text = raw.length > MAX ? raw.slice(0, MAX) + `\n\n[...truncated at ${MAX} chars]` : raw;
        return text;
      },
    },
    {
      name: "browse",
      description: "Lightweight web browser. Faster and cheaper than web_fetch — extracts clean readable text, searches DuckDuckGo, extracts links/metadata. Commands: fetch <url>, search <query>, extract <url> --links, extract <url> --meta. Add --json for structured output.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          command: {
            type: "string",
            description: "Command: fetch, search, extract",
          },
          target: {
            type: "string",
            description: "URL or search query",
          },
          flags: {
            type: "string",
            description: "Optional flags: --json, --links, --meta, --raw",
          },
        },
        required: ["command", "target"],
      },
      execute: async (args, _ctx) => {
        const command = args.command as string;
        const target = args.target as string;
        const flags = (args.flags as string) || "";
        if (!command || !target) return "ERROR: command and target are required.";
        // Validate command
        const validCmds = ["fetch", "search", "extract"];
        if (!validCmds.includes(command)) return `ERROR: command must be one of: ${validCmds.join(", ")}`;
        try {
          const result = execFileSync(
            "python3",
            ["/root/entity/tools/webbrowser.py", command, target, ...flags.split(/\s+/).filter(Boolean)],
            { encoding: "utf-8", timeout: 15_000, maxBuffer: 1024 * 1024 }
          ).trim();
          // Truncate large outputs
          const MAX = 15_000;
          return result.length > MAX ? result.slice(0, MAX) + `\n\n[...truncated at ${MAX} chars]` : result;
        } catch (e: any) {
          const stderr = e.stderr ? e.stderr.trim() : "";
          const stdout = e.stdout ? e.stdout.trim() : "";
          return `ERROR: ${stderr || stdout || e.message}`;
        }
      },
    },
    {
      name: "search_web",
      description: "Search the web for any query. Uses Brave Search if BRAVE_SEARCH_API_KEY is set, otherwise falls back to DuckDuckGo. Returns titles, URLs, and snippets.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Search query",
          },
          limit: {
            type: "number",
            description: "Max results (default: 8)",
          },
        },
        required: ["query"],
      },
      execute: async (args, _ctx) => {
        const query = args.query as string;
        const limit = (args.limit as number) || 8;

        // Brave Search (preferred)
        const braveKey = process.env.BRAVE_SEARCH_API_KEY;
        if (braveKey) {
          const resp = await fetch(
            `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${limit}`,
            { headers: { "Accept": "application/json", "X-Subscription-Token": braveKey } },
          );
          if (resp.ok) {
            const data = await resp.json() as any;
            const results = data.web?.results ?? [];
            if (results.length === 0) return "No results found.";
            return results.slice(0, limit).map((r: any, i: number) =>
              `${i + 1}. ${r.title}\n   ${r.url}\n   ${r.description || ""}`
            ).join("\n\n");
          }
        }

        // DuckDuckGo fallback (scrape HTML response)
        const ddgResp = await fetch(
          `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`,
          { headers: { "User-Agent": "Mozilla/5.0 (compatible; TIAMAT/1.0)" } },
        );
        if (!ddgResp.ok) return `ERROR ${ddgResp.status}: search failed`;
        const html = await ddgResp.text();
        // Extract result titles, URLs, and snippets from DDG HTML
        const resultPattern = /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)<\/a>[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;
        const results: string[] = [];
        let match: RegExpExecArray | null;
        let idx = 1;
        while ((match = resultPattern.exec(html)) !== null && idx <= limit) {
          const url = match[1];
          const title = match[2].trim();
          const snippet = match[3].replace(/<[^>]+>/g, "").trim();
          results.push(`${idx}. ${title}\n   ${url}\n   ${snippet}`);
          idx++;
        }
        return results.length > 0 ? results.join("\n\n") : "No results found.";
      },
    },

    {
      name: "fetch_terminal_markets_disabled",
      description: "Fetch live data from terminal.markets (DX Terminal Pro AI agent competition on Base). Returns vault info, token prices, leaderboard, and game state. The competition runs Feb 24 – Mar 16 2026 on Base mainnet. Use this to monitor the game and plan strategy.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          endpoint: {
            type: "string",
            description: "What to fetch: 'overview' (default), 'vaults', 'tokens', 'leaderboard', or a raw path like '/api/v1/vaults'",
          },
        },
      },
      execute: async (args, _ctx) => {
        const endpoint = (args.endpoint as string) || "overview";
        const BASE = "https://terminal.markets";

        const tryFetch = async (url: string): Promise<string | null> => {
          try {
            const resp = await fetch(url, {
              headers: { "User-Agent": "TIAMAT-agent/1.0", "Accept": "application/json, text/html" },
              signal: AbortSignal.timeout(12_000),
            });
            if (!resp.ok) return null;
            const ct = resp.headers.get("content-type") || "";
            if (ct.includes("json")) {
              const data = await resp.json();
              return JSON.stringify(data, null, 2).slice(0, 800);
            }
            const text = await resp.text();
            // Strip HTML tags for readability
            return text.replace(/<[^>]+>/g, " ").replace(/\s{2,}/g, " ").trim().slice(0, 800);
          } catch {
            return null;
          }
        };

        // Map friendly names to API paths to try
        const pathMap: Record<string, string[]> = {
          overview:    ["/", "/api/overview", "/api/v1/overview"],
          vaults:      ["/api/vaults", "/api/v1/vaults", "/vaults"],
          tokens:      ["/api/tokens", "/api/v1/tokens", "/tokens"],
          leaderboard: ["/api/leaderboard", "/api/v1/leaderboard", "/leaderboard"],
        };

        const paths = endpoint.startsWith("/") ? [endpoint] : (pathMap[endpoint] ?? [`/api/${endpoint}`]);

        const results: string[] = [];
        for (const p of paths) {
          const data = await tryFetch(`${BASE}${p}`);
          if (data) {
            results.push(`--- ${BASE}${p} ---\n${data}`);
            if (results.length >= 2) break; // Don't over-fetch
          }
        }

        if (results.length === 0) {
          return `No data returned from terminal.markets for endpoint "${endpoint}". The public API may not be live yet (game starts Feb 24 2026). Try endpoint='overview' to fetch the landing page, or check back after Feb 24.`;
        }
        return results.join("\n\n");
      },
    },

    // ── Social / Messaging Tools ──
    {
      name: "send_message_disabled",
      description:
        "Send a message to another automaton or address via the social relay.",
      category: "infra",
      parameters: {
        type: "object",
        properties: {
          to_address: {
            type: "string",
            description: "Recipient wallet address (0x...)",
          },
          content: {
            type: "string",
            description: "Message content to send",
          },
          reply_to: {
            type: "string",
            description: "Optional message ID to reply to",
          },
        },
        required: ["to_address", "content"],
      },
      execute: async (args, ctx) => {
        if (!ctx.social) {
          return "Social relay not configured. Set socialRelayUrl in config.";
        }
        const result = await ctx.social.send(
          args.to_address as string,
          args.content as string,
          args.reply_to as string | undefined,
        );
        return `Message sent (id: ${result.id})`;
      },
    },

    // ── Model Discovery ──
    {
      name: "list_models_disabled",
      description:
        "List all available inference models from the API with their provider and pricing. Use this to discover what models you can use and pick the best one for your needs.",
      category: "infra",
      parameters: {
        type: "object",
        properties: {},
        required: [],
      },
      execute: async (_args, ctx) => {
        const models = [
          { id: 'claude-haiku-4-5-20251001', provider: 'anthropic', pricing: { inputPerMillion: 0.25, outputPerMillion: 1.25 } },
          { id: 'claude-sonnet-4-6', provider: 'anthropic', pricing: { inputPerMillion: 3, outputPerMillion: 15 } },
          { id: 'claude-opus-4-6', provider: 'anthropic', pricing: { inputPerMillion: 15, outputPerMillion: 75 } },
        ];
        const lines = models.map(
          (m) =>
            `${m.id} (${m.provider}) — $${m.pricing.inputPerMillion}/$${m.pricing.outputPerMillion} per 1M tokens (in/out)`,
        );
        return `Available models:\n${lines.join("\n")}`;
      },
    },

    // ── Domain Tools ──
    {
      name: "search_domains_disabled",
      description:
        "Search for available domain names and get pricing.",
      category: "infra",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Domain name or keyword to search (e.g., 'mysite' or 'mysite.com')",
          },
          tlds: {
            type: "string",
            description: "Comma-separated TLDs to check (e.g., 'com,io,ai'). Default: com,io,ai,xyz,net,org,dev",
          },
        },
        required: ["query"],
      },
      execute: async (args, ctx) => {
        const results: any[] = []; void 0; // Conway not available
        if (results.length === 0) return "No results found.";
        return results
          .map(
            (d) =>
              `${d.domain}: ${d.available ? "AVAILABLE" : "taken"}${d.registrationPrice != null ? ` ($${(d.registrationPrice / 100).toFixed(2)}/yr)` : ""}`,
          )
          .join("\n");
      },
    },
    {
      name: "register_domain_disabled",
      description:
        "Register a domain name. Costs USDC via x402 payment. Check availability first with search_domains.",
      category: "infra",
      dangerous: true,
      parameters: {
        type: "object",
        properties: {
          domain: {
            type: "string",
            description: "Full domain to register (e.g., 'mysite.com')",
          },
          years: {
            type: "number",
            description: "Registration period in years (default: 1)",
          },
        },
        required: ["domain"],
      },
      execute: async (args, ctx) => {
        const reg = { error: 'Use Namecheap or DO Domains instead', domain: args.domain as string, status: 'unavailable', expiresAt: '', transactionId: '' }; // Conway not available
        return `Domain registered: ${reg.domain} (status: ${reg.status}${reg.expiresAt ? `, expires: ${reg.expiresAt}` : ""}${reg.transactionId ? `, tx: ${reg.transactionId}` : ""})`;
      },
    },
    {
      name: "manage_dns_disabled",
      description:
        "Manage DNS records for a domain you own. Actions: list, add, delete.",
      category: "infra",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "list, add, or delete",
          },
          domain: {
            type: "string",
            description: "Domain name (e.g., 'mysite.com')",
          },
          type: {
            type: "string",
            description: "Record type for add: A, AAAA, CNAME, MX, TXT, etc.",
          },
          host: {
            type: "string",
            description: "Record host for add (e.g., '@' for root, 'www')",
          },
          value: {
            type: "string",
            description: "Record value for add (e.g., IP address, target domain)",
          },
          ttl: {
            type: "number",
            description: "TTL in seconds for add (default: 3600)",
          },
          record_id: {
            type: "string",
            description: "Record ID for delete",
          },
        },
        required: ["action", "domain"],
      },
      execute: async (args, ctx) => {
        const action = args.action as string;
        const domain = args.domain as string;

        if (action === "list") {
          const records = await ctx.conway.listDnsRecords(domain);
          if (records.length === 0) return `No DNS records found for ${domain}.`;
          return records
            .map(
              (r) => `[${r.id}] ${r.type} ${r.host} -> ${r.value} (TTL: ${r.ttl || "default"})`,
            )
            .join("\n");
        }

        if (action === "add") {
          const type = args.type as string;
          const host = args.host as string;
          const value = args.value as string;
          if (!type || !host || !value) {
            return "Required for add: type, host, value";
          }
          const record = await ctx.conway.addDnsRecord(
            domain,
            type,
            host,
            value,
            args.ttl as number | undefined,
          );
          return `DNS record added: [${record.id}] ${record.type} ${record.host} -> ${record.value}`;
        }

        if (action === "delete") {
          const recordId = args.record_id as string;
          if (!recordId) return "Required for delete: record_id";
          await ctx.conway.deleteDnsRecord(domain, recordId);
          return `DNS record ${recordId} deleted from ${domain}`;
        }

        return `Unknown action: ${action}. Use list, add, or delete.`;
      },
    },

    // ── x402 Payment Tool ──
    {
      name: "x402_fetch_disabled",
      description:
        "Fetch a URL with automatic x402 USDC payment. If the server responds with HTTP 402, signs a USDC payment and retries. Use this to access paid APIs and services.",
      category: "financial",
      parameters: {
        type: "object",
        properties: {
          url: {
            type: "string",
            description: "The URL to fetch",
          },
          method: {
            type: "string",
            description: "HTTP method (default: GET)",
          },
          body: {
            type: "string",
            description: "Request body for POST/PUT (JSON string)",
          },
          headers: {
            type: "string",
            description: "Additional headers as JSON string",
          },
        },
        required: ["url"],
      },
      execute: async (args, ctx) => {
        const { x402Fetch } = await import("../conway/x402.js");
        const url = args.url as string;
        const method = (args.method as string) || "GET";
        const body = args.body as string | undefined;
        const extraHeaders = args.headers
          ? JSON.parse(args.headers as string)
          : undefined;

        const result = await x402Fetch(
          url,
          ctx.identity.account,
          method,
          body,
          extraHeaders,
        );

        if (!result.success) {
          return `x402 fetch failed: ${result.error || "Unknown error"}`;
        }

        const responseStr =
          typeof result.response === "string"
            ? result.response
            : JSON.stringify(result.response, null, 2);

        // Truncate very large responses
        if (responseStr.length > 10000) {
          return `x402 fetch succeeded (truncated):\n${responseStr.slice(0, 10000)}...`;
        }
        return `x402 fetch succeeded:\n${responseStr}`;
      },
    },

    // ── Cognitive: memory tools ──
    {
      name: "remember",
      description: "Store something important in long-term memory. Use for key observations, customer interactions, what worked/failed, important facts, errors. Types: 'observation','outcome','strategy','customer','error','insight'. Set importance 0.0-1.0 (0.7+ for things you'll need again).",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          type: { type: "string", enum: ["observation","outcome","strategy","customer","error","insight"], description: "Category of memory" },
          content: { type: "string", description: "What to remember — be specific and concise" },
          importance: { type: "number", description: "0.0–1.0. Use 0.7+ for critical facts you'll need later." },
        },
        required: ["type","content"],
      },
      execute: async (args, ctx) => {
        const id = await memory.remember({
          type: args.type as string,
          content: args.content as string,
          importance: (args.importance as number) || 0.5,
          cycle: (ctx as any).turnNumber || 0,
        });
        return id ? `Memory #${id} stored: [${args.type}] ${(args.content as string).slice(0,60)}…` : "Failed to store memory";
      },
    },
    {
      name: "recall",
      description: "Smart tiered memory search. Searches core knowledge (L3) first, then compressed summaries (L2), then raw memories (L1). Stays within token budget for efficiency.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Keywords to search for in memory" },
          token_budget: { type: "number", description: "Max tokens to return (default 2000)" },
        },
        required: ["query"],
      },
      execute: async (args, _ctx) => {
        const results = await memory.smartRecall(
          args.query as string,
          (args.token_budget as number) || 2000
        );
        if (results.length === 0) return "No memories found for that query.";
        const tierCounts = { L3: 0, L2: 0, L1: 0 };
        for (const r of results) tierCounts[r.tier as keyof typeof tierCounts]++;
        const header = `[${results.length} results: ${tierCounts.L3}×L3, ${tierCounts.L2}×L2, ${tierCounts.L1}×L1]`;
        return header + "\n" + results.map((r) => r.content).join("\n---\n");
      },
    },
    {
      name: "learn_fact",
      description: "Store a knowledge fact as an entity-relation-value triple. Examples: 'tiamat_api' 'has_feature' 'free_tier', 'bluesky' 'cooldown_hours' '24', 'customer_alice' 'interested_in' 'batch_mode'.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          entity: { type: "string", description: "Subject (e.g. 'tiamat_api', 'bluesky', 'customer_x')" },
          relation: { type: "string", description: "Relationship (e.g. 'has_feature', 'cooldown_hours', 'responded_to')" },
          value: { type: "string", description: "Object (e.g. 'free_tier', '24', 'positive')" },
          confidence: { type: "number", description: "0.0–1.0 confidence in this fact" },
        },
        required: ["entity","relation","value"],
      },
      execute: async (args, _ctx) => {
        const result = await memory.learn(
          args.entity as string,
          args.relation as string,
          args.value as string,
          (args.confidence as number) || 0.7,
          "agent_observation"
        );
        if (!result) return "Failed to store fact";
        let msg = `Learned: ${args.entity} —[${args.relation}]→ ${args.value}`;
        if (result.conflicts > 0) {
          msg += ` (⚠ disputed ${result.conflicts} existing fact(s) — their confidence reduced)`;
        }
        return msg;
      },
    },
    {
      name: "reflect",
      description: "Deep reflection on accumulated memories, strategies, and knowledge. Use during strategic cycles to understand patterns, what's working/failing, and what to prioritize. Returns comprehensive memory analysis including tool reliability data and knowledge health.",
      category: "cognitive",
      parameters: { type: "object", properties: {} },
      execute: async (_args, _ctx) => {
        return await memory.reflect();
      },
    },
    {
      name: "prune_memory",
      description: "Clean up memory: remove zombie memories (old, never recalled, low importance) and deprecated knowledge facts. Run periodically to keep memory lean. Returns count of items pruned.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          memory_age_days: { type: "number", description: "Delete unrecalled memories older than N days (default 30)" },
        },
      },
      execute: async (args, _ctx) => {
        const pruned = await memory.pruneZombies({
          memoryAgeDays: (args.memory_age_days as number) || 30,
        });
        return pruned > 0
          ? `Pruned ${pruned} zombie items from memory.`
          : "Memory is clean — nothing to prune.";
      },
    },
    {
      name: "log_strategy",
      description: "Record a strategy attempt and its outcome. Use after trying something to build strategic intelligence over time. Score 0.0=failure, 1.0=perfect.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          strategy: { type: "string", description: "Strategy name (e.g. 'bluesky_marketing', 'free_tier_conversion')" },
          action: { type: "string", description: "What you did" },
          outcome: { type: "string", description: "What happened" },
          score: { type: "number", description: "0.0–1.0 success score" },
        },
        required: ["strategy","action"],
      },
      execute: async (args, ctx) => {
        await memory.logStrategy(
          args.strategy as string,
          args.action as string,
          (args.outcome as string) || undefined,
          (args.score as number) || undefined,
          (ctx as any).turnNumber || 0
        );
        return `Strategy logged: ${args.strategy} — score: ${args.score ?? "pending"}, outcome: ${args.outcome ?? "not recorded"}`;
      },
    },

    // ── Revenue & Autonomy Tools ──
    {
      name: "check_revenue",
      description: "Check API revenue metrics: total requests, free vs paid, last request time. RATE LIMITED: returns cached result if called more than once per hour. Check at most once per session.",
      category: "financial",
      parameters: { type: "object", properties: {} },
      execute: (() => {
        let lastResult: string | null = null;
        let lastCheck = 0;
        const COOLDOWN_MS = 60 * 60 * 1000; // 1 hour
        return async (_args: any, _ctx: any) => {
          const now = Date.now();
          if (lastResult && (now - lastCheck) < COOLDOWN_MS) {
            const minsAgo = Math.round((now - lastCheck) / 60000);
            return `${lastResult}\n\n⏱️ (cached from ${minsAgo}m ago — next fresh check in ${Math.round((COOLDOWN_MS - (now - lastCheck)) / 60000)}m. Revenue doesn't change fast. Focus on BUILDING, not checking.)`;
          }
          const { readFileSync } = await import("fs");
          try {
            const log = readFileSync("/root/api/requests.log", "utf-8");
            const lines = log.trim().split("\n").filter(Boolean);
            if (lines.length === 0) { lastResult = "No requests logged yet."; lastCheck = now; return lastResult; }
            const paid = lines.filter((l: string) => l.includes("free:False") || l.includes("Free: False")).length;
            const free = lines.filter((l: string) => l.includes("free:True") || l.includes("Free: True") || l.includes("Type: FREE")).length;
            const errors = lines.filter((l: string) => l.includes("500") || l.includes("Error")).length;
            const first = lines[0];
            const last = lines[lines.length - 1];
            const revenueUsdc = (paid * 0.01).toFixed(2);
            lastResult = [
              `=== Revenue Report ===`,
              `Total requests: ${lines.length}`,
              `Free tier: ${free}`,
              `Paid (x402): ${paid} = $${revenueUsdc} USDC`,
              `Errors (500): ${errors}`,
              `First request: ${first.slice(0, 120)}`,
              `Last request:  ${last.slice(0, 120)}`,
            ].join("\n");
            lastCheck = now;
            return lastResult;
          } catch {
            lastResult = "No revenue data yet — /root/api/requests.log does not exist.";
            lastCheck = now;
            return lastResult;
          }
        };
      })(),
    },
    {
      name: "self_improve",
      description: "Autonomous self-improvement: reflect on memories, identify the biggest bottleneck, and automatically fix it using ask_claude_code. Use this during strategic cycles when you have a clear performance problem.",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          bottleneck: { type: "string", description: "Optional: describe the specific issue to fix. If omitted, will be derived from reflect()." },
        },
      },
      execute: async (args, _ctx) => {
        const { writeFileSync } = await import("fs");

        // Get reflection if no bottleneck specified
        let issue = args.bottleneck as string;
        if (!issue) {
          try {
            const reflection = await memory.reflect();
            // Extract failed strategies to derive bottleneck
            const failLines = reflection.split("\n").filter(l => l.includes("Failed") || l.includes("failed") || l.includes("error")).slice(0, 3);
            issue = failLines.length > 0
              ? `Based on memory reflection, top issues: ${failLines.join("; ")}`
              : "No clear bottleneck found in memory. Review PROGRESS.md and identify what to improve.";
          } catch {
            issue = "Could not load reflection — fix memory system";
          }
        }

        const task = `You are TIAMAT's self-improvement system. Analyze this bottleneck and fix it:

BOTTLENECK: ${issue}

Steps:
1. Read relevant files to understand the problem
2. Make the minimal targeted fix
3. If it's a code change in /root/entity/src/, rebuild with: cd /root/entity && pnpm build
4. If it's a Python/API change, test with curl

Be surgical — fix only what's broken. Return a summary of what you changed.`;

        writeFileSync("/root/.automaton/claude_task.txt", task, "utf-8");

        const childEnv = { ...process.env };
        delete childEnv.CLAUDECODE;
        delete childEnv.CLAUDE_CODE_ENTRYPOINT;
        delete childEnv.CLAUDE_CODE_SESSION_ID;
        delete childEnv.ANTHROPIC_AI_TOOL_USE_SESSION_ID;

        // Async spawn — non-blocking so heartbeats stay alive
        const { spawn: spawnProc } = await import('child_process');
        const SELF_IMPROVE_TIMEOUT = 300_000; // 5 min
        const result = await new Promise<string>((resolve) => {
          const chunks: Buffer[] = [];
          const proc = spawnProc(
            "claude",
            ["--print", "--allowedTools", "Edit,Write,Read,Bash", "--max-turns", "5"],
            { env: childEnv, cwd: "/root/entity", stdio: ["pipe", "pipe", "pipe"] },
          );
          proc.stdout.on("data", (d: Buffer) => chunks.push(d));
          proc.stderr.on("data", (d: Buffer) => chunks.push(d));
          proc.stdin.write(task);
          proc.stdin.end();
          const timer = setTimeout(() => {
            proc.kill("SIGTERM");
            setTimeout(() => { try { proc.kill("SIGKILL"); } catch {} }, 3000);
            const partial = Buffer.concat(chunks).toString("utf-8").trim();
            resolve(partial ? `(timed out — partial)\n${partial}` : "ERROR: self_improve timed out");
          }, SELF_IMPROVE_TIMEOUT);
          proc.on("close", () => {
            clearTimeout(timer);
            resolve(Buffer.concat(chunks).toString("utf-8").trim() || "(no output)");
          });
          proc.on("error", (e: Error) => {
            clearTimeout(timer);
            resolve(`ERROR: ${e.message}`);
          });
        });

        await memory.logStrategy("self_improve", issue, result.slice(0, 200), undefined, _ctx.turnNumber);
        return `Self-improvement complete:\n${result.slice(0, 1000)}`;
      },
    },

    // ── Infrastructure: deploy_app ──
    {
      name: "deploy_app",
      description: "Deploy an app behind nginx reverse proxy with optional SSL. Use this after building a new service to make it accessible via your domain (tiamat.live).",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          app_name: { type: "string", description: "Short name for the app (e.g. 'summarizer')" },
          port: { type: "number", description: "Port the app is running on" },
          subdomain: { type: "string", description: "Optional subdomain (e.g. 'api' for api.tiamat.live). Omit for root domain." },
        },
        required: ["app_name", "port"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import("child_process");
        const name = args.app_name as string;
        const port = args.port as number;
        const sub = (args.subdomain as string) || "";
        if (!VALID_APP_NAME.test(name)) return 'Invalid app name (lowercase alphanumeric + hyphens only)';
        if (typeof port !== 'number' || port < 1024 || port > 65535) return 'Invalid port (1024-65535)';
        if (sub && !VALID_SUBDOMAIN.test(sub)) return 'Invalid subdomain';
        try {
          const result = execFileSync('/root/deploy-app.sh', [name, String(port), sub], {
            encoding: "utf-8", timeout: 30_000
          }).trim();
          return result;
        } catch (e: any) {
          return `Deploy failed: ${e.stderr || e.message}`;
        }
      },
    },
    {
      name: "github_pr_comments",
      description: "Read comments on a GitHub pull request. Use this to check for reviewer feedback on TIAMAT's PRs.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          repo: { type: "string", description: "Repository in 'owner/repo' format (e.g. 'openai/openai-agents-python')" },
          pr_number: { type: "number", description: "Pull request number" },
        },
        required: ["repo", "pr_number"],
      },
      execute: async (args, _ctx) => {
        const repo = args.repo as string;
        const prNum = args.pr_number as number;
        const token = process.env.GITHUB_TOKEN;
        if (!token) return "ERROR: GITHUB_TOKEN not set in environment.";
        try {
          // Fetch both issue comments and review comments
          const [issueResp, reviewResp] = await Promise.all([
            fetch(`https://api.github.com/repos/${repo}/issues/${prNum}/comments?per_page=30`, {
              headers: { Authorization: `token ${token}`, Accept: "application/vnd.github.v3+json", "User-Agent": "TIAMAT-agent/1.0" },
              signal: AbortSignal.timeout(15_000),
            }),
            fetch(`https://api.github.com/repos/${repo}/pulls/${prNum}/comments?per_page=30`, {
              headers: { Authorization: `token ${token}`, Accept: "application/vnd.github.v3+json", "User-Agent": "TIAMAT-agent/1.0" },
              signal: AbortSignal.timeout(15_000),
            }),
          ]);
          const issueComments = issueResp.ok ? await issueResp.json() : [];
          const reviewComments = reviewResp.ok ? await reviewResp.json() : [];
          const all = [
            ...issueComments.map((c: any) => ({ user: c.user?.login, body: c.body?.slice(0, 500), type: "comment", created: c.created_at })),
            ...reviewComments.map((c: any) => ({ user: c.user?.login, body: c.body?.slice(0, 500), type: "review", path: c.path, created: c.created_at })),
          ].sort((a, b) => a.created.localeCompare(b.created));
          if (all.length === 0) return "No comments on this PR yet.";
          return all.map(c => `[${c.type}] @${c.user} (${c.created})${c.path ? ` on ${c.path}` : ""}:\n${c.body}`).join("\n\n---\n\n");
        } catch (e: any) {
          return `Failed to fetch PR comments: ${e.message}`;
        }
      },
    },
    {
      name: "github_comment",
      description: "Post a comment on a GitHub issue or pull request. Use this to respond to reviewer feedback on TIAMAT's PRs.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          repo: { type: "string", description: "Repository in 'owner/repo' format" },
          issue_number: { type: "number", description: "Issue or PR number" },
          body: { type: "string", description: "Comment body (markdown supported)" },
        },
        required: ["repo", "issue_number", "body"],
      },
      execute: async (args, _ctx) => {
        const repo = args.repo as string;
        const num = args.issue_number as number;
        const body = args.body as string;
        const token = process.env.GITHUB_TOKEN;
        if (!token) return "ERROR: GITHUB_TOKEN not set in environment.";
        if (!body?.trim()) return "ERROR: comment body cannot be empty.";
        try {
          const resp = await fetch(`https://api.github.com/repos/${repo}/issues/${num}/comments`, {
            method: "POST",
            headers: { Authorization: `token ${token}`, Accept: "application/vnd.github.v3+json", "Content-Type": "application/json", "User-Agent": "TIAMAT-agent/1.0" },
            body: JSON.stringify({ body }),
            signal: AbortSignal.timeout(15_000),
          });
          if (!resp.ok) return `ERROR ${resp.status}: ${await resp.text()}`;
          const data = await resp.json();
          return `Comment posted: ${data.html_url}`;
        } catch (e: any) {
          return `Failed to post comment: ${e.message}`;
        }
      },
    },
    {
      name: "github_pr_status",
      description: "Check the status of TIAMAT's open pull requests across all fork repos. Shows review state, comments, and CI status.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {},
      },
      execute: async (_args, _ctx) => {
        const token = process.env.GITHUB_TOKEN;
        if (!token) return "ERROR: GITHUB_TOKEN not set in environment.";
        const prs = [
          { repo: "openai/openai-agents-python", num: 2525 },
          { repo: "bytedance/deer-flow", num: 888 },
          { repo: "griptape-ai/griptape", num: 2069 },
          { repo: "memvid/memvid", num: 200 },
          { repo: "MemTensor/MemOS", num: 1106 },
        ];
        const results: string[] = [];
        for (const pr of prs) {
          try {
            const resp = await fetch(`https://api.github.com/repos/${pr.repo}/pulls/${pr.num}`, {
              headers: { Authorization: `token ${token}`, Accept: "application/vnd.github.v3+json", "User-Agent": "TIAMAT-agent/1.0" },
              signal: AbortSignal.timeout(10_000),
            });
            if (!resp.ok) { results.push(`${pr.repo}#${pr.num}: ERROR ${resp.status}`); continue; }
            const data = await resp.json();
            results.push(`${pr.repo}#${pr.num}: ${data.state} | comments: ${data.comments} | review_comments: ${data.review_comments} | mergeable: ${data.mergeable ?? "unknown"}`);
          } catch (e: any) {
            results.push(`${pr.repo}#${pr.num}: fetch failed — ${e.message}`);
          }
        }
        return results.join("\n");
      },
    },
    // ── DX Terminal Pro — Official API ──
    {
      name: "dx_terminal",
      description: "DX Terminal Pro — 21-day onchain trading competition on Base (Feb 24 - Mar 19). READ actions: portfolio, settings, tokens, swaps, strategies, leaderboard, logs, candles, holders, pnl_history, deposits. WRITE actions: update_settings, add_strategy, disable_strategy, deposit_eth, withdraw_eth. Params vary by action — pass action + relevant fields. portfolio/swaps/strategies need wallet key set; tokens/leaderboard/candles are public.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "Action to perform (see description for list)" },
          token: { type: "string", description: "Token address (for candles, holders)" },
          timeframe: { type: "string", description: "Candle timeframe: 1m,5m,15m,1h,4h,1d (default 1h)" },
          strategy: { type: "string", description: "Strategy text (for add_strategy)" },
          strategy_id: { type: "number", description: "Strategy ID (for disable_strategy)" },
          expiry_hours: { type: "number", description: "Strategy expiry in hours (default 24)" },
          priority: { type: "number", description: "Strategy priority: 0=Low, 1=Med, 2=High (default 1)" },
          amount: { type: "string", description: "ETH amount (for deposit_eth, withdraw_eth)" },
          max_trade: { type: "string", description: "Max trade size in wei (for update_settings)" },
          slippage: { type: "string", description: "Max slippage in bps (for update_settings)" },
          activity: { type: "number", description: "Activity level 1-5 (for update_settings)" },
          risk: { type: "number", description: "Risk level 1-5 (for update_settings)" },
          size: { type: "number", description: "Position size level 1-5 (for update_settings)" },
          hold: { type: "number", description: "Hold duration level 1-5 (for update_settings)" },
          diversification: { type: "number", description: "Diversification level 1-5 (for update_settings)" },
        },
        required: ["action"],
      },
      execute: (() => {
        const API = "https://api.terminal.markets/api/v1";
        const VAULT_CONTRACT = "0xfEEa1D23DB2d09403baf34F49c5AC2F5C2a30334";
        const RPC = "https://mainnet.base.org";
        const CACHE_TTL = 5 * 60 * 1000; // 5 min
        const VAULT_TTL = 30 * 60 * 1000; // 30 min
        const readCache = new Map<string, { result: string; ts: number }>();
        let cachedVault: string | null = null;
        let vaultTs = 0;

        const getKey = (): string => process.env.DX_TERMINAL_PRIVATE_KEY || "";

        const getVault = async (): Promise<string | null> => {
          const now = Date.now();
          if (cachedVault && (now - vaultTs) < VAULT_TTL) return cachedVault;
          const key = getKey();
          if (!key) return null;
          try {
            const { execFileSync } = await import("child_process");
            const owner = execFileSync(
              "/root/.foundry/bin/cast",
              ["wallet", "address", "--private-key", key],
              { encoding: "utf-8", timeout: 10_000 }
            ).trim();
            const resp = await fetch(`${API}/vault?ownerAddress=${owner}`, {
              headers: { "Accept": "application/json" },
              signal: AbortSignal.timeout(10_000),
            });
            if (!resp.ok) return null;
            const data = await resp.json();
            const addr = data?.vault?.vaultAddress || data?.vaultAddress || (Array.isArray(data) ? data[0]?.vaultAddress : null);
            if (addr) { cachedVault = addr; vaultTs = now; }
            return addr;
          } catch { return null; }
        };

        const fmtWei = (w: string | number): string => {
          const n = typeof w === "string" ? BigInt(w) : BigInt(Math.floor(Number(w)));
          const whole = n / BigInt(1e18);
          const frac = n % BigInt(1e18);
          return `${whole}.${frac.toString().padStart(18, "0").slice(0, 6)}`;
        };

        const apiGet = async (path: string): Promise<any> => {
          const resp = await fetch(`${API}${path}`, {
            headers: { "Accept": "application/json", "User-Agent": "TIAMAT/1.0" },
            signal: AbortSignal.timeout(15_000),
          });
          if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text().catch(() => "")}`);
          return resp.json();
        };

        const log = async (action: string, snippet: string) => {
          const fs = await import("fs");
          fs.appendFileSync(
            "/root/.automaton/dx_terminal.log",
            `\n--- ${action.toUpperCase()} ${new Date().toISOString()} ---\n${snippet.slice(0, 500)}\n`,
            "utf-8"
          );
        };

        const READ_ACTIONS: Record<string, (args: any, vault: string | null) => Promise<string>> = {
          portfolio: async (_a, v) => {
            if (!v) return "No vault — set DX_TERMINAL_PRIVATE_KEY in .env";
            const d = await apiGet(`/positions/${v}`);
            const eth = d.ethBalance ? `ETH: ${fmtWei(d.ethBalance)}` : "";
            const pnl = d.pnlEth ? `PnL: ${fmtWei(d.pnlEth)} ETH` : "";
            const positions = (d.positions || d.tokens || []).map((p: any) =>
              `  ${p.symbol || p.token}: ${p.balance || p.amount} (val: ${p.valueEth ? fmtWei(p.valueEth) : p.valueUsd || "?"})`
            ).join("\n");
            return `Portfolio for ${v.slice(0, 10)}...\n${eth}\n${pnl}\n${positions || "No token positions"}`;
          },
          settings: async (_a, v) => {
            if (!v) return "No vault — set DX_TERMINAL_PRIVATE_KEY in .env";
            const d = await apiGet(`/vault?vaultAddress=${v}`);
            const s = d.settings || d;
            return `Vault settings:\n  Activity: ${s.activity}/5\n  Risk: ${s.risk}/5\n  Size: ${s.size}/5\n  Hold: ${s.hold}/5\n  Diversification: ${s.diversification}/5\n  Max trade: ${s.maxTrade || s.max_trade || "?"}\n  Slippage: ${s.slippage || "?"}`;
          },
          tokens: async () => {
            const d = await apiGet("/tokens?includeMarketData=true");
            const tokens = (Array.isArray(d) ? d : d.tokens || []).slice(0, 30);
            return tokens.map((t: any) =>
              `${t.symbol}: price=${t.price || t.priceUsd || "?"} mcap=${t.marketCap || "?"} vol=${t.volume24h || "?"}`
            ).join("\n") || "No token data";
          },
          swaps: async (_a, v) => {
            if (!v) return "No vault — set DX_TERMINAL_PRIVATE_KEY in .env";
            const d = await apiGet(`/swaps?vaultAddress=${v}&limit=20&order=desc`);
            const swaps = (Array.isArray(d) ? d : d.swaps || []).slice(0, 15);
            return swaps.map((s: any) =>
              `${s.timestamp || s.createdAt || "?"} | ${s.action || s.type || "swap"} ${s.fromSymbol || "?"}→${s.toSymbol || "?"} | amt: ${s.amount || "?"} | reason: ${(s.reasoning || s.reason || "").slice(0, 80)}`
            ).join("\n") || "No swaps";
          },
          strategies: async (_a, v) => {
            if (!v) return "No vault — set DX_TERMINAL_PRIVATE_KEY in .env";
            const d = await apiGet(`/strategies/${v}?activeOnly=true`);
            const strats = (Array.isArray(d) ? d : d.strategies || []);
            return strats.map((s: any) =>
              `[${s.id}] p${s.priority} | ${s.strategy || s.text || "?"} | expires: ${s.expiresAt || "never"}`
            ).join("\n") || "No active strategies";
          },
          leaderboard: async () => {
            const d = await apiGet("/leaderboard?limit=20&sortBy=total_pnl_usd");
            const entries = (Array.isArray(d) ? d : d.leaderboard || d.entries || []).slice(0, 20);
            return entries.map((e: any, i: number) =>
              `#${i + 1} ${e.name || e.vaultAddress?.slice(0, 10) || "?"}: PnL $${e.totalPnlUsd || e.total_pnl_usd || "?"} | ETH ${e.ethBalance ? fmtWei(e.ethBalance) : "?"}`
            ).join("\n") || "No leaderboard data";
          },
          logs: async (_a, v) => {
            if (!v) return "No vault — set DX_TERMINAL_PRIVATE_KEY in .env";
            const d = await apiGet(`/logs/${v}?limit=10&order=desc`);
            const logs = (Array.isArray(d) ? d : d.logs || []).slice(0, 10);
            return logs.map((l: any) =>
              `${l.timestamp || l.createdAt || "?"} | ${(l.reasoning || l.message || l.text || "").slice(0, 120)}`
            ).join("\n") || "No logs";
          },
          candles: async (a) => {
            const token = a.token;
            if (!token) return "candles requires token param (token address)";
            const tf = a.timeframe || "1h";
            const d = await apiGet(`/candles/${token}?timeframe=${tf}&to=now&countback=100`);
            const candles = (Array.isArray(d) ? d : d.candles || []).slice(-20);
            return `${token.slice(0, 10)}... ${tf} candles (last ${candles.length}):\n` +
              candles.map((c: any) => `${c.time || c.timestamp || "?"} O:${c.open} H:${c.high} L:${c.low} C:${c.close} V:${c.volume}`).join("\n") || "No candle data";
          },
          holders: async (a) => {
            const token = a.token;
            if (!token) return "holders requires token param (token address)";
            const d = await apiGet(`/holders/${token}?limit=20&order=desc`);
            const holders = (Array.isArray(d) ? d : d.holders || []).slice(0, 20);
            return holders.map((h: any, i: number) =>
              `#${i + 1} ${h.address?.slice(0, 10) || "?"}: ${h.balance || h.amount || "?"} (${h.percentage || "?"}%)`
            ).join("\n") || "No holder data";
          },
          pnl_history: async (_a, v) => {
            if (!v) return "No vault — set DX_TERMINAL_PRIVATE_KEY in .env";
            const d = await apiGet(`/pnl-history/${v}`);
            const pts = (Array.isArray(d) ? d : d.history || d.points || []).slice(-20);
            return pts.map((p: any) =>
              `${p.timestamp || p.date || "?"}: PnL $${p.pnlUsd || p.totalPnlUsd || "?"} | ETH ${p.pnlEth ? fmtWei(p.pnlEth) : "?"}`
            ).join("\n") || "No PnL history";
          },
          deposits: async (_a, v) => {
            if (!v) return "No vault — set DX_TERMINAL_PRIVATE_KEY in .env";
            const d = await apiGet(`/deposits-withdrawals/${v}?limit=20&order=desc`);
            const txs = (Array.isArray(d) ? d : d.transactions || d.deposits || []).slice(0, 20);
            return txs.map((t: any) =>
              `${t.timestamp || t.createdAt || "?"} | ${t.type || "?"}: ${t.amount || "?"} ETH | tx: ${t.txHash?.slice(0, 16) || "?"}`
            ).join("\n") || "No deposit/withdrawal history";
          },
        };

        return async (args: any, _ctx: any) => {
          const action = (args.action as string || "").toLowerCase().trim();

          // Write actions
          const WRITE_ACTIONS = ["update_settings", "add_strategy", "disable_strategy", "deposit_eth", "withdraw_eth"];
          const ALL_ACTIONS = [...Object.keys(READ_ACTIONS), ...WRITE_ACTIONS];
          if (!ALL_ACTIONS.includes(action)) {
            return `Invalid action: "${action}". Valid actions:\n  READ: ${Object.keys(READ_ACTIONS).join(", ")}\n  WRITE: ${WRITE_ACTIONS.join(", ")}`;
          }

          // Handle write actions via cast
          if (WRITE_ACTIONS.includes(action)) {
            const key = getKey();
            if (!key) return "DX_TERMINAL_PRIVATE_KEY not set in .env — cannot execute write actions.";
            const { execFileSync } = await import("child_process");
            const castBin = "/root/.foundry/bin/cast";
            try {
              let result = "";
              if (action === "update_settings") {
                const mt = args.max_trade || "50000000000000000"; // 0.05 ETH default
                const sl = args.slippage || "500"; // 5% default
                const ac = args.activity ?? 3;
                const ri = args.risk ?? 3;
                const si = args.size ?? 3;
                const ho = args.hold ?? 3;
                const di = args.diversification ?? 3;
                const tuple = `(${mt},${sl},${ac},${ri},${si},${ho},${di})`;
                const out = execFileSync(castBin, [
                  "send", VAULT_CONTRACT,
                  "updateSettings((uint256,uint256,uint8,uint8,uint8,uint8,uint8))",
                  tuple,
                  "--private-key", key, "--rpc-url", RPC,
                ], { encoding: "utf-8", timeout: 60_000 });
                result = `Settings updated: activity=${ac} risk=${ri} size=${si} hold=${ho} div=${di}\ntx: ${out.trim()}`;
              } else if (action === "add_strategy") {
                if (!args.strategy) return "add_strategy requires 'strategy' param (text instruction)";
                const expiry = Math.floor((args.expiry_hours || 24) * 3600);
                const prio = args.priority ?? 1;
                const out = execFileSync(castBin, [
                  "send", VAULT_CONTRACT,
                  "addStrategy(string,uint64,uint8)",
                  args.strategy, String(expiry), String(prio),
                  "--private-key", key, "--rpc-url", RPC,
                ], { encoding: "utf-8", timeout: 60_000 });
                result = `Strategy added (p${prio}, ${args.expiry_hours || 24}h): "${args.strategy.slice(0, 80)}"\ntx: ${out.trim()}`;
              } else if (action === "disable_strategy") {
                if (args.strategy_id === undefined) return "disable_strategy requires 'strategy_id' param";
                const out = execFileSync(castBin, [
                  "send", VAULT_CONTRACT,
                  "disableStrategy(uint256)",
                  String(args.strategy_id),
                  "--private-key", key, "--rpc-url", RPC,
                ], { encoding: "utf-8", timeout: 60_000 });
                result = `Strategy ${args.strategy_id} disabled.\ntx: ${out.trim()}`;
              } else if (action === "deposit_eth") {
                if (!args.amount) return "deposit_eth requires 'amount' param (ETH, e.g. '0.05')";
                const out = execFileSync(castBin, [
                  "send", VAULT_CONTRACT,
                  "depositETH()",
                  "--value", `${args.amount}ether`,
                  "--private-key", key, "--rpc-url", RPC,
                ], { encoding: "utf-8", timeout: 60_000 });
                result = `Deposited ${args.amount} ETH.\ntx: ${out.trim()}`;
              } else if (action === "withdraw_eth") {
                if (!args.amount) return "withdraw_eth requires 'amount' param (ETH, e.g. '0.01')";
                const weiAmt = BigInt(Math.floor(parseFloat(args.amount) * 1e18)).toString();
                const out = execFileSync(castBin, [
                  "send", VAULT_CONTRACT,
                  "withdrawETH(uint256)",
                  weiAmt,
                  "--private-key", key, "--rpc-url", RPC,
                ], { encoding: "utf-8", timeout: 60_000 });
                result = `Withdrew ${args.amount} ETH (${weiAmt} wei).\ntx: ${out.trim()}`;
              }
              await log(action, result);
              return result.slice(0, 4000);
            } catch (e: any) {
              const err = `Write action "${action}" failed: ${e.stderr?.slice(0, 300) || e.message}`;
              await log(action, err);
              return err;
            }
          }

          // Handle read actions
          const now = Date.now();
          const cached = readCache.get(action);
          if (cached && (now - cached.ts) < CACHE_TTL) {
            const minsAgo = Math.round((now - cached.ts) / 60000);
            return `${cached.result}\n\n(cached ${minsAgo}m ago)`;
          }

          const vault = await getVault();
          try {
            const handler = READ_ACTIONS[action];
            const result = await handler(args, vault);
            readCache.set(action, { result, ts: now });
            await log(action, result);
            return result.slice(0, 4000);
          } catch (e: any) {
            const err = `dx_terminal ${action} failed: ${e.message}`;
            await log(action, err);
            return err;
          }
        };
      })(),
    },
    // ── On-Chain Tools ──
    {
      name: "scan_base_chain",
      description: "Scan TIAMAT's wallet on Base chain and check DEX arbitrage spreads. READ-ONLY — does not trade. Run max once per 50 cycles to respect RPC rate limits. Logs results to /root/.automaton/chain_scan.log.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {},
      },
      execute: async (_args, _ctx) => {
        const { execSync } = await import('child_process');
        try {
          const output = execSync(
            'cd /root/entity/src/agent && python3 wallet_check.py 2>&1',
            { encoding: 'utf-8', timeout: 60000 }
          ).trim();
          // Append to chain scan log
          const timestamp = new Date().toISOString();
          const logEntry = `\n--- SCAN ${timestamp} ---\n${output}\n`;
          const fs = await import('fs');
          fs.appendFileSync('/root/.automaton/chain_scan.log', logEntry, 'utf-8');
          return output;
        } catch (e: any) {
          return `Chain scan failed: ${e.stderr || e.message}`;
        }
      },
    },
    {
      name: "manage_sniper",
      description: "Manage the Base chain sniper bot (separate process). Actions: 'status' (check if running + positions), 'log' (last 30 lines of sniper log), 'start' (launch sniper), 'stop' (kill sniper). The sniper watches for new token pairs on Base DEXes and executes micro-snipes with safety checks.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "One of: status, log, start, stop",
          },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const action = args.action as string;
        const { execFileSync } = await import('child_process');
        const fs = await import('fs');

        const isRunning = () => {
          try {
            const pid = fs.readFileSync('/run/tiamat/tiamat_sniper.pid', 'utf-8').trim();
            if (!VALID_PID.test(pid)) return null;
            execFileSync('kill', ['-0', pid]);
            return pid;
          } catch { return null; }
        };

        switch (action) {
          case 'status': {
            const pid = isRunning();
            let positions = '{}';
            try { positions = fs.readFileSync('/root/.automaton/sniper_positions.json', 'utf-8'); } catch {}
            const posData = JSON.parse(positions);
            const posCount = Object.keys(posData).length;
            return pid
              ? `Sniper RUNNING (PID ${pid}). Open positions: ${posCount}.\n${JSON.stringify(posData, null, 2)}`
              : `Sniper NOT RUNNING. Positions on file: ${posCount}.`;
          }
          case 'log': {
            try {
              const logContent = fs.readFileSync('/root/.automaton/sniper.log', 'utf-8');
              const lines = logContent.split('\n');
              return lines.slice(-30).join('\n') || 'No log entries yet.';
            } catch { return 'No sniper log found.'; }
          }
          case 'start': {
            if (isRunning()) return 'Sniper already running.';
            try {
              const out = execFileSync('/root/start-sniper.sh', [], { encoding: 'utf-8', timeout: 15000 });
              return out;
            } catch (e: any) {
              return `Start failed: ${e.stderr || e.message}`;
            }
          }
          case 'stop': {
            const pid = isRunning();
            if (!pid) return 'Sniper not running.';
            try {
              execFileSync('kill', [pid]);
              return `Sniper stopped (PID ${pid}).`;
            } catch (e: any) {
              return `Stop failed: ${e.message}`;
            }
          }
          default:
            return 'Unknown action. Use: status, log, start, stop';
        }
      },
    },
    {
      name: "scan_contracts",
      description: "Run vulnerability scanner on multi-chain contracts. READ-ONLY security research for Immunefi bounties. Actions: 'full' (all checks), 'recent' (new deployments last 50 blocks), 'pairs' (skim scan on DEX pairs), 'immunefi' (list bounty targets), 'status' (daemon status + recent findings), 'address 0x...' (scan specific contract), 'etherscan 0x... [chain]' (Etherscan V2 enrichment — chains: base/ethereum/arbitrum/optimism), 'balances' (check wallet ETH on all chains), 'report' (send Telegram funding report). Findings logged to vuln_findings.json.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "full|recent|pairs|immunefi|status|address 0x..." },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import('child_process');
        const action = (args as { action: string }).action || 'status';

        if (action === 'status') {
          const fs = await import('fs');
          let status = '';
          try {
            const pid = fs.readFileSync('/run/tiamat/tiamat_scanner.pid', 'utf-8').trim();
            if (!VALID_PID.test(pid)) { status += 'Daemon: INVALID PID FILE\n'; }
            else {
              try { execFileSync('kill', ['-0', pid]); status += `Daemon: RUNNING (PID ${pid})\n`; }
              catch { status += `Daemon: DOWN (stale PID ${pid})\n`; }
            }
          } catch { status += 'Daemon: NOT RUNNING\n'; }
          for (const [cid, cname] of [['8453','Base'],['42161','Arbitrum'],['10','Optimism'],['1','Ethereum']]) {
            try {
              const fpath = `/root/.automaton/vuln_findings_${cid}.json`;
              const findings = JSON.parse(fs.readFileSync(fpath, 'utf-8'));
              status += `${cname}: ${findings.length} findings\n`;
              const recent = findings.slice(-2);
              for (const f of recent) { status += `  ${f.type} @ ${f.address?.slice(0,16)}... (${f.eth_value} ETH)\n`; }
            } catch { /* no findings for this chain */ }
          }
          // Legacy findings file
          try {
            const findings = JSON.parse(fs.readFileSync('/root/.automaton/vuln_findings.json', 'utf-8'));
            if (findings.length > 0) status += `Legacy findings: ${findings.length}\n`;
          } catch { /* no legacy findings */ }
          return status;
        }

        try {
          const parts = action.split(' ');
          const cmd = parts[0];
          if (!SCANNER_CMDS.includes(cmd)) return `Invalid action: ${cmd}. Use: ${SCANNER_CMDS.join(', ')}`;
          const arg = parts[1] || '';
          if (cmd === 'address' && !VALID_HEX_ADDR.test(arg)) return 'Invalid address format. Use: 0x...40 hex chars';
          if (cmd === 'balances' || cmd === 'report') {
            try {
              const balArgs = ['multi_chain_executor.py', cmd === 'balances' ? 'balances' : 'report'];
              const balOutput = execFileSync('python3', balArgs, {
                encoding: 'utf-8', timeout: 30000, cwd: '/root/entity/src/agent'
              }).trim();
              return balOutput.slice(0, 4000);
            } catch (e: any) {
              return `Balance check failed: ${e.stderr?.slice(0, 500) || e.message}`;
            }
          }
          if (cmd === 'etherscan') {
            if (!VALID_HEX_ADDR.test(arg)) return 'Usage: etherscan 0x... [chain]. Chains: base, ethereum, arbitrum, optimism';
            const chain = parts[2] || 'base';
            const esArgs = ['etherscan_v2.py', 'enrich', arg, chain];
            const esOutput = execFileSync('python3', esArgs, {
              encoding: 'utf-8', timeout: 30000, cwd: '/root/entity/src/agent'
            }).trim();
            return esOutput.slice(0, 4000);
          }
          const cmdArgs = ['contract_scanner.py', cmd];
          if (arg) cmdArgs.push(arg);
          const output = execFileSync('python3', cmdArgs, {
            encoding: 'utf-8', timeout: 120000, cwd: '/root/entity/src/agent'
          }).trim();
          const timestamp = new Date().toISOString();
          const fs = await import('fs');
          fs.appendFileSync('/root/.automaton/vuln_scan.log', `\n--- TOOL SCAN ${timestamp} ---\n${output.slice(0, 500)}\n`, 'utf-8');
          return output.slice(0, 4000);
        } catch (e: any) {
          return `Scan failed: ${e.stderr?.slice(0, 1000) || e.message}`;
        }
      },
    },
    {
      name: "rebalance_wallet",
      description: "Multi-chain wallet rebalancer. Uses LI.FI to swap USDC→ETH and bridge between chains. Actions: 'status' (show balances + needs), 'rebalance' (auto-topup low chains from USDC on Base), 'test' (test LI.FI API connectivity + get a quote). Runs automatically every 500 cycles. Safety: only moves between TIAMAT's own wallet, max $20/tx, Ethereum excluded from auto-rebalance.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "status|rebalance|test" },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import('child_process');
        const action = (args as { action: string }).action || 'status';
        const validActions = ['status', 'rebalance', 'test'];
        if (!validActions.includes(action)) return `Invalid action: ${action}. Use: ${validActions.join(', ')}`;
        try {
          const output = execFileSync('python3', ['auto_rebalancer.py', action], {
            encoding: 'utf-8', timeout: 180000, cwd: '/root/entity/src/agent'
          }).trim();
          return output.slice(0, 4000);
        } catch (e: any) {
          return `Rebalance failed: ${e.stderr?.slice(0, 500) || e.message}`;
        }
      },
    },
    {
      name: "check_opportunities",
      description: "Agent IPC inbox. Actions: 'peek' (pending messages), 'stats' (queue stats + heartbeats), 'done <msg_id>' (mark handled), 'send <op> <json_payload>' (send a message), 'heartbeats' (check agent liveness). Auto-execute ops (SKIM, ALERT, REPORT, HEARTBEAT) are dispatched automatically each cycle — this tool is for manual review and control ops.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "peek|stats|done <msg_id>|send <OP> {json}|heartbeats" },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import('child_process');
        const action = (args as { action: string }).action || 'peek';

        const pythonScript = (code: string) => {
          try {
            return execFileSync("python3", ["-c", code], {
              cwd: "/root/entity/src/agent",
              encoding: 'utf-8',
              timeout: 10000,
            }).trim();
          } catch (e: any) {
            return `Error: ${e.stderr?.slice(0, 500) || e.message}`;
          }
        };

        if (action === 'peek') {
          return pythonScript(`
from agent_ipc import AgentIPC
import json
msgs = AgentIPC.recv()
if not msgs:
    print("No pending messages.")
else:
    print(f"{len(msgs)} pending:")
    for m in msgs[:20]:
        p = json.dumps(m.get("payload",{}))
        if len(p) > 80: p = p[:77] + "..."
        print(f"  [{m['id'][:8]}] {m['op']} from:{m['from']} {p}")
`);
        }

        if (action === 'stats') {
          return pythonScript(`
from agent_ipc import AgentIPC
import json
s = AgentIPC.stats()
print(json.dumps(s, indent=2))
`);
        }

        if (action === 'heartbeats') {
          return pythonScript(`
from agent_ipc import AgentIPC
import json
hb = AgentIPC.check_heartbeats()
if not hb:
    print("No heartbeats recorded.")
else:
    for agent, info in hb.items():
        stale = " STALE" if info.get("stale") else ""
        print(f"  {agent}: {info.get('status','?')}{stale} (cycles:{info.get('cycles','?')} ts:{info.get('ts','?')})")
`);
        }

        if (action.startsWith('done ')) {
          const msgId = action.split(' ')[1];
          if (!msgId || msgId.length < 4) return 'Invalid msg_id. Use: done <msg_id>';
          return pythonScript(`
from agent_ipc import AgentIPC
AgentIPC.mark("${msgId}", "done", "manual")
print("Marked done: ${msgId}")
`);
        }

        if (action.startsWith('send ')) {
          const parts = action.match(/^send\s+(\w+)\s+(.+)$/);
          if (!parts) return 'Usage: send <OP> {"key":"value"}';
          const op = parts[1];
          const payloadStr = parts[2];
          // Validate op and payload are safe
          if (!/^[A-Z_]+$/.test(op)) return 'Invalid op code. Use uppercase: SKIM, ALERT, BUILD, etc.';
          try { JSON.parse(payloadStr); } catch { return 'Invalid JSON payload'; }
          return pythonScript(`
from agent_ipc import AgentIPC
import json
mid = AgentIPC.send("tiamat", "${op}", json.loads('${payloadStr.replace(/'/g, "\\'")}'))
print(f"Sent {mid}")
`);
        }

        return 'Unknown action. Use: peek, stats, heartbeats, done <msg_id>, send <OP> {json}';
      },
    },
    // ── Farcaster Tools ──
    {
      name: "post_farcaster",
      description: "Post a cast to Farcaster/Warpcast. Max 320 chars. Optionally target a channel (base, ai, dev, agents, crypto, onchain, build). Always embeds tiamat.live. Attach image_path from generate_image to show art inline instead of just a link box. Rate limited to 1 post per 5 minutes.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string", description: "Cast text (max 320 chars)" },
          channel: { type: "string", description: "Channel to post in: base, ai, dev, agents, crypto, onchain, build" },
          image_path: { type: "string", description: "Local image path from generate_image to attach (e.g. /root/.automaton/images/123_neural.png)" },
        },
        required: ["text"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import('child_process');
        const { text, channel, image_path } = args as { text: string; channel?: string; image_path?: string };
        if (channel && !FARCASTER_CHANNELS.includes(channel))
          return `Invalid channel. Use: ${FARCASTER_CHANNELS.join(', ')}`;

        // If image provided, copy to web dir and pass URL to farcaster.py
        let imageUrl = '';
        if (image_path) {
          try {
            const { copyFileSync, mkdirSync, existsSync } = await import('fs');
            const { basename } = await import('path');
            const filename = basename(image_path);
            const webDir = '/var/www/tiamat/images';
            mkdirSync(webDir, { recursive: true });
            const dest = `${webDir}/${filename}`;
            if (!existsSync(dest)) copyFileSync(image_path, dest);
            imageUrl = `https://tiamat.live/images/${filename}`;
          } catch (imgErr: any) {
            console.error(`[post_farcaster] Image copy failed: ${imgErr.message}`);
          }
        }

        try {
          const fArgs = ['farcaster.py', 'post', text];
          if (channel) fArgs.push(channel);
          if (imageUrl) fArgs.push(imageUrl);
          const output = execFileSync('python3', fArgs, {
            encoding: 'utf-8', timeout: 20000, cwd: '/root/entity/src/agent'
          }).trim();
          const fs = await import('fs');
          fs.appendFileSync('/root/.automaton/tiamat.log', `\n[FARCASTER] Posted: ${text.slice(0, 60)}... ${channel ? 'to /' + channel : ''}${imageUrl ? ' +image' : ''}\n`);
          return output.slice(0, 2000);
        } catch (e: any) {
          return `Farcaster post failed: ${e.stderr?.slice(0, 500) || e.message}`;
        }
      },
    },
    {
      name: "read_farcaster",
      description: "Read Farcaster feeds or search casts. RATE LIMITED: 1 hour cooldown. Pass action as a single string. Examples: read_farcaster({action:'feed ai'}), read_farcaster({action:'search AI inference'}), read_farcaster({action:'test'}). Do NOT pass 'replies', 'notifications', or 'limit' — those are not supported.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "One of: 'feed <channel>' (e.g. 'feed ai'), 'search <query>' (e.g. 'search AI inference'), 'test'" },
        },
        required: ["action"],
      },
      execute: (() => {
        let lastResult: string | null = null;
        let lastCheck = 0;
        const COOLDOWN_MS = 60 * 60 * 1000; // 1 hour
        return async (args: any, _ctx: any) => {
          const now = Date.now();
          if (lastResult && (now - lastCheck) < COOLDOWN_MS) {
            const minsAgo = Math.round((now - lastCheck) / 60000);
            return `${lastResult}\n\n⏱️ (cached from ${minsAgo}m ago — next fresh read in ${Math.round((COOLDOWN_MS - (now - lastCheck)) / 60000)}m. Farcaster doesn't change that fast. Do something productive instead.)`;
          }
          const { execFileSync } = await import('child_process');
          const action = (args as { action: string }).action || 'test';
          const parts = action.split(' ');
          const cmd = parts[0];
          if (!FARCASTER_READ_CMDS.includes(cmd)) return `Invalid command. Use: ${FARCASTER_READ_CMDS.join(', ')}`;
          const rest = parts.slice(1).join(' ');
          try {
            const fArgs = ['farcaster.py', cmd];
            if (rest) fArgs.push(rest);
            const output = execFileSync('python3', fArgs, {
              encoding: 'utf-8', timeout: 20000, cwd: '/root/entity/src/agent'
            }).trim();
            lastResult = output.slice(0, 3000);
            lastCheck = now;
            return lastResult;
          } catch (e: any) {
            return `Farcaster read failed: ${e.stderr?.slice(0, 500) || e.message}`;
          }
        };
      })(),
    },
    {
      name: "farcaster_engage",
      description: "Engage on Farcaster. Search topics and reply are handled automatically — you do NOT pass query, text, or limit. Just pass action. Examples: farcaster_engage({action:'run'}) to scan+reply, farcaster_engage({action:'like', cast_hash:'0xabc'}) to like. Valid actions: scan, run, stats, like, recast.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", enum: ["scan", "run", "stats", "like", "recast"], description: "scan=dry run, run=scan+auto-reply, stats=history, like=like a cast, recast=repost" },
          cast_hash: { type: "string", description: "Cast hash — ONLY for like/recast actions, omit for scan/run/stats" },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import('child_process');
        const { action, cast_hash } = args as { action: string; cast_hash?: string };
        if (!['scan', 'run', 'stats', 'like', 'recast'].includes(action))
          return `Invalid action. Use: scan, run, stats, like, recast`;
        if ((action === 'like' || action === 'recast') && !cast_hash)
          return `${action} requires a cast_hash parameter`;
        const pyArgs = ['farcaster_engage.py', action];
        if (cast_hash) pyArgs.push(cast_hash);
        try {
          const output = execFileSync('python3', pyArgs, {
            encoding: 'utf-8', timeout: 90000, cwd: '/root/entity/src/agent',
            env: { ...process.env }
          }).trim();
          if (['run', 'like', 'recast'].includes(action)) {
            const fs = await import('fs');
            fs.appendFileSync('/root/.automaton/tiamat.log', `\n[ENGAGE] ${action}: ${output.slice(0, 200)}\n`);
          }
          return output.slice(0, 3000);
        } catch (e: any) {
          return `farcaster_engage failed: ${e.stderr?.slice(0, 500) || e.message}`;
        }
      },
    },

    // ─── Dynamic Cooldown Task Manager ───────────────────────────
    {
      name: "manage_cooldown",
      description: "Manage dynamic cooldown tasks — Python scripts that run FREE between cycles. Actions: add (register a script), list (show all tasks + stats), remove (delete a task by name).",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", enum: ["add", "list", "remove"], description: "Action to perform" },
          name: { type: "string", description: "Task name (add/remove)" },
          script: { type: "string", description: "Absolute path to .py script (add)" },
          timeout: { type: "number", description: "Max execution time in ms (add, default 30000)" },
          description: { type: "string", description: "What this task does (add)" },
        },
        required: ["action"],
      },
      execute: async (args: any) => {
        const fs = await import('fs');
        const REGISTRY_PATH = '/root/.automaton/cooldown_registry.json';
        const ALLOWED_PREFIXES = ['/root/.automaton/', '/root/entity/src/agent/'];

        function loadRegistry(): any[] {
          try { return JSON.parse(fs.readFileSync(REGISTRY_PATH, 'utf-8')); } catch { return []; }
        }
        function saveRegistry(tasks: any[]) {
          fs.writeFileSync(REGISTRY_PATH, JSON.stringify(tasks, null, 2));
        }

        const { action, name, script, timeout, description } = args;

        if (action === 'list') {
          const tasks = loadRegistry();
          if (tasks.length === 0) return 'No dynamic cooldown tasks registered.';
          return tasks.map((t: any) =>
            `${t.enabled ? '✓' : '✗'} ${t.name}: ${t.script} (timeout ${t.timeout}ms, runs: ${t.runs || 0}, last: ${t.lastRun || 'never'})${t.lastResult ? '\n  → ' + t.lastResult.slice(0, 120) : ''}`
          ).join('\n');
        }

        if (action === 'remove') {
          if (!name) return 'Error: name required for remove';
          const tasks = loadRegistry();
          const idx = tasks.findIndex((t: any) => t.name === name);
          if (idx === -1) return `Task "${name}" not found`;
          tasks.splice(idx, 1);
          saveRegistry(tasks);
          return `Removed cooldown task "${name}". ${tasks.length} tasks remaining.`;
        }

        if (action === 'add') {
          if (!name || !script) return 'Error: name and script required for add';
          if (!script.endsWith('.py')) return 'Error: script must be a .py file';
          if (!ALLOWED_PREFIXES.some(p => script.startsWith(p)))
            return `Error: script must be under ${ALLOWED_PREFIXES.join(' or ')}`;
          try { fs.accessSync(script, fs.constants.R_OK); } catch {
            return `Error: script not found or not readable: ${script}`;
          }
          const tasks = loadRegistry();
          if (tasks.length >= 20) return 'Error: max 20 cooldown tasks. Remove some first.';
          if (tasks.some((t: any) => t.name === name)) return `Error: task "${name}" already exists. Remove it first.`;
          tasks.push({
            name, script, timeout: timeout || 30000,
            description: description || '', enabled: true,
            runs: 0, lastRun: null, lastResult: null,
          });
          saveRegistry(tasks);
          return `Registered cooldown task "${name}" → ${script} (timeout ${timeout || 30000}ms). It will run during idle cooldowns at zero API cost.`;
        }

        return 'Invalid action. Use: add, list, remove';
      },
    },
    // ─── Auto-Cron Task Manager ─────────────────────────────────
    {
      name: "cron_create",
      description: "Schedule a recurring task that runs automatically. Schedule: 'every N cycles' or 'every N minutes'. Must have a ticket first — pass the ticket ID. Commands run in /root with 30s timeout.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "Short task name (e.g., 'check_drift_traffic')" },
          command: { type: "string", description: "Shell command to run (e.g., 'wc -l /root/drift_requests.log')" },
          schedule_type: { type: "string", enum: ["cycles", "minutes"], description: "Schedule unit" },
          schedule_value: { type: "number", description: "How often to run (e.g., 50 for 'every 50 cycles')" },
          ticket_id: { type: "string", description: "Ticket ID this cron was created for (required for tracking)" },
        },
        required: ["name", "command", "schedule_type", "schedule_value"],
      },
      execute: async (args: any) => {
        const { loadCronTasks, saveCronTasks } = await import("./pacer.js");
        const state = loadCronTasks();

        if (state.tasks.length >= 30) return "Error: max 30 cron tasks. Remove some first.";
        if (state.tasks.some(t => t.name === args.name)) return `Error: cron "${args.name}" already exists.`;

        // Basic command safety — block dangerous patterns
        const cmd = args.command as string;
        const blocked = /rm\s+-rf|mkfs|dd\s+if=|>\s*\/dev|shutdown|reboot|kill\s+-9\s+1\b/i;
        if (blocked.test(cmd)) return "Error: command contains blocked pattern.";

        const id = `cron-${String(state.tasks.length + 1).padStart(3, "0")}`;
        state.tasks.push({
          id,
          name: args.name,
          command: cmd,
          schedule_type: args.schedule_type,
          schedule_value: args.schedule_value,
          last_run_cycle: null,
          last_run_time: null,
          last_result: null,
          created_by_ticket: args.ticket_id || null,
          enabled: true,
          created_at: new Date().toISOString(),
        });

        saveCronTasks(state);
        return `✓ Cron task "${args.name}" (${id}) scheduled: every ${args.schedule_value} ${args.schedule_type}. Command: ${cmd}`;
      },
    },
    {
      name: "cron_list",
      description: "List all auto-cron tasks with their last results and schedules.",
      category: "cognitive",
      parameters: { type: "object", properties: {} },
      execute: async () => {
        const { loadCronTasks } = await import("./pacer.js");
        const state = loadCronTasks();
        if (state.tasks.length === 0) return "No auto-cron tasks scheduled.";

        return state.tasks.map(t =>
          `${t.enabled ? "✓" : "✗"} ${t.id} "${t.name}" — every ${t.schedule_value} ${t.schedule_type}\n` +
          `  cmd: ${t.command}\n` +
          `  last: ${t.last_run_time || "never"} (cycle ${t.last_run_cycle ?? "—"})` +
          (t.last_result ? `\n  result: ${t.last_result.slice(0, 120)}` : "") +
          (t.created_by_ticket ? `\n  ticket: ${t.created_by_ticket}` : "")
        ).join("\n\n");
      },
    },
    {
      name: "cron_remove",
      description: "Remove an auto-cron task by name or ID.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "Task name or ID to remove" },
        },
        required: ["name"],
      },
      execute: async (args: any) => {
        const { loadCronTasks, saveCronTasks } = await import("./pacer.js");
        const state = loadCronTasks();
        const idx = state.tasks.findIndex(t => t.name === args.name || t.id === args.name);
        if (idx === -1) return `Cron task "${args.name}" not found.`;
        const removed = state.tasks.splice(idx, 1)[0];
        saveCronTasks(state);
        return `✓ Removed cron task "${removed.name}" (${removed.id}). ${state.tasks.length} remaining.`;
      },
    },

    // ── Android App Build & Deploy ──
    {
      name: "build_and_deploy_app",
      description: "Build and deploy the TIAMAT Command Center Android app. Actions: 'build' (commit+push to trigger GitHub Actions CI), 'status' (check recent build status), 'download' (download built APK to serve at tiamat.live/download/app), 'update_code' (write code to app source without building). Repo: toxfox69/tiamat-command-center.",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "One of: build, status, download, update_code",
          },
          file_path: {
            type: "string",
            description: "For update_code: relative path under src/ (e.g. 'App.jsx', 'components/Terminal.jsx')",
          },
          content: {
            type: "string",
            description: "For update_code: new file content",
          },
          commit_message: {
            type: "string",
            description: "For build: custom commit message (optional, auto-generated if omitted)",
          },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const action = args.action as string;
        const { execFileSync } = await import('child_process');
        const fs = await import('fs');
        const pathMod = await import('path');

        const APP_DIR = '/root/tiamat-app';
        const REPO = 'toxfox69/tiamat-command-center';

        switch (action) {
          case 'build': {
            try {
              // Stage all changes
              execFileSync('git', ['add', '-A'], { cwd: APP_DIR, encoding: 'utf-8', timeout: 15_000 });

              // Check if there are changes to commit
              let status: string;
              try {
                status = execFileSync('git', ['status', '--porcelain'], { cwd: APP_DIR, encoding: 'utf-8', timeout: 10_000 }).trim();
              } catch { status = ''; }

              if (!status) return 'No changes to commit. Push skipped.';

              const msg = (args.commit_message as string) || `feat: auto-update from TIAMAT cycle ${_ctx.turnNumber || 'unknown'}`;
              execFileSync('git', ['commit', '-m', msg], { cwd: APP_DIR, encoding: 'utf-8', timeout: 15_000 });
              const pushOut = execFileSync('git', ['push', 'origin', 'main'], { cwd: APP_DIR, encoding: 'utf-8', timeout: 60_000 });
              return `Build triggered! Committed and pushed to ${REPO}.\nCommit message: ${msg}\nGitHub Actions will compile the APK automatically.\nCheck status with build_and_deploy_app({action:"status"}).`;
            } catch (e: any) {
              return `Build failed: ${e.stderr || e.stdout || e.message}`;
            }
          }

          case 'status': {
            try {
              const out = execFileSync('gh', ['run', 'list', '--repo', REPO, '--limit', '3', '--json', 'status,conclusion,name,createdAt,url'], {
                encoding: 'utf-8', timeout: 30_000
              }).trim();
              const runs = JSON.parse(out);
              if (runs.length === 0) return 'No workflow runs found.';
              return runs.map((r: any) => {
                const state = r.conclusion || r.status;
                const icon = state === 'success' ? 'PASS' : state === 'failure' ? 'FAIL' : state === 'in_progress' ? 'BUILDING...' : state.toUpperCase();
                return `[${icon}] ${r.name} — ${r.createdAt}\n  ${r.url}`;
              }).join('\n\n');
            } catch (e: any) {
              return `Failed to check status: ${e.stderr || e.message}`;
            }
          }

          case 'download': {
            try {
              // Ensure download directory exists
              const downloadDir = '/var/www/tiamat/download';
              fs.mkdirSync(downloadDir, { recursive: true });

              // Download the latest APK artifact
              const out = execFileSync('gh', ['run', 'download', '--repo', REPO, '-n', 'tiamat-apk', '-D', downloadDir], {
                encoding: 'utf-8', timeout: 120_000
              });

              // Find the APK file and rename for clean URL
              const files = fs.readdirSync(downloadDir).filter((f: string) => f.endsWith('.apk'));
              if (files.length > 0) {
                const apkPath = pathMod.join(downloadDir, files[0]);
                const targetPath = pathMod.join(downloadDir, 'app.apk');
                if (apkPath !== targetPath) {
                  try { fs.unlinkSync(targetPath); } catch {}
                  fs.renameSync(apkPath, targetPath);
                }
                return `APK downloaded! Available at https://tiamat.live/download/app.apk\nFile: ${targetPath}`;
              }
              return `Download completed but no .apk file found in ${downloadDir}. Contents: ${fs.readdirSync(downloadDir).join(', ')}`;
            } catch (e: any) {
              return `Download failed: ${e.stderr || e.message}`;
            }
          }

          case 'update_code': {
            const filePath = args.file_path as string;
            const content = args.content as string;
            if (!filePath) return 'ERROR: file_path is required for update_code. Example: "App.jsx" or "components/Terminal.jsx"';
            if (!content && content !== '') return 'ERROR: content is required for update_code.';

            // Sanitize path — must stay under src/
            const normalized = pathMod.normalize(filePath).replace(/^\.\.\//, '');
            if (normalized.includes('..')) return 'ERROR: path traversal not allowed.';

            const fullPath = pathMod.join(APP_DIR, 'src', normalized);
            try {
              fs.mkdirSync(pathMod.dirname(fullPath), { recursive: true });
              fs.writeFileSync(fullPath, content, 'utf-8');
              return `File written: ${fullPath}\nUse build_and_deploy_app({action:"build"}) when ready to push.`;
            } catch (e: any) {
              return `Failed to write file: ${e.message}`;
            }
          }

          default:
            return 'Invalid action. Use: build, status, download, update_code';
        }
      },
    },
    // ── Android App Factory ──
    {
      name: "android_app_factory",
      description: "Create, build, and manage multiple Android apps. Each app gets its own GitHub repo under toxfox69/. Actions: 'scaffold' (create new app from template with its own repo), 'update_code' (write/update files in an app's src/), 'build' (commit+push to trigger GitHub Actions CI), 'status' (check build status), 'download' (download APK artifact), 'list' (list all apps with status).",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "One of: scaffold, update_code, build, status, download, list",
          },
          app_name: {
            type: "string",
            description: "Kebab-case app name (e.g. 'daily-quotes'). Used as repo name and directory name. Required for all actions except list.",
          },
          app_id: {
            type: "string",
            description: "For scaffold: reverse-domain app ID (e.g. 'com.energenai.dailyquotes'). Defaults to com.energenai.{name-without-dashes}.",
          },
          description: {
            type: "string",
            description: "For scaffold: short app description for the GitHub repo.",
          },
          file_path: {
            type: "string",
            description: "For update_code: relative path (e.g. 'src/App.jsx', 'src/components/Timer.jsx', 'index.html').",
          },
          content: {
            type: "string",
            description: "For update_code: file content to write.",
          },
          commit_message: {
            type: "string",
            description: "For build: optional custom commit message.",
          },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const action = args.action as string;
        const appName = (args.app_name as string || '').trim();
        const { execFileSync } = await import('child_process');
        const fs = await import('fs');
        const pathMod = await import('path');

        const APPS_DIR = '/root/android-apps';
        const TEMPLATE_DIR = '/root/android-app-template';
        const GITHUB_USER = 'toxfox69';

        // Validate app_name for actions that need it
        if (action !== 'list' && !appName) {
          return 'ERROR: app_name is required. Use kebab-case like "daily-quotes".';
        }
        if (appName && !/^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(appName) && appName.length > 2) {
          if (!/^[a-z0-9-]+$/.test(appName)) return 'ERROR: app_name must be kebab-case (lowercase letters, numbers, dashes).';
        }

        const appDir = pathMod.join(APPS_DIR, appName);

        switch (action) {
          case 'scaffold': {
            if (fs.existsSync(appDir)) return `ERROR: App "${appName}" already exists at ${appDir}. Use update_code to modify it.`;

            const appId = (args.app_id as string) || `com.energenai.${appName.replace(/-/g, '')}`;
            const displayName = appName.split('-').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
            const desc = (args.description as string) || `${displayName} — Android app by ENERGENAI`;

            try {
              // Copy template
              execFileSync('cp', ['-r', TEMPLATE_DIR, appDir], { timeout: 15_000 });

              // Replace placeholders in key files
              const replacements: [string, [string, string][]][] = [
                ['package.json', [['{{APP_NAME}}', appName]]],
                ['capacitor.config.json', [['{{APP_ID}}', appId], ['{{APP_DISPLAY_NAME}}', displayName]]],
                ['index.html', [['{{APP_DISPLAY_NAME}}', displayName]]],
                ['src/App.jsx', [['{{APP_DISPLAY_NAME}}', displayName]]],
              ];

              for (const [file, subs] of replacements) {
                const fp = pathMod.join(appDir, file);
                if (fs.existsSync(fp)) {
                  let txt = fs.readFileSync(fp, 'utf-8');
                  for (const [from, to] of subs) txt = txt.split(from).join(to);
                  fs.writeFileSync(fp, txt, 'utf-8');
                }
              }

              // Customize android/ native files
              const androidFiles: [string, [string, string][]][] = [
                ['android/app/build.gradle', [['live.tiamat.app', appId]]],
                ['android/app/src/main/assets/capacitor.config.json', [['live.tiamat.app', appId], ['TIAMAT', displayName]]],
                ['android/app/src/main/res/values/strings.xml', [['live.tiamat.app', appId], ['TIAMAT', displayName]]],
              ];

              for (const [file, subs] of androidFiles) {
                const fp = pathMod.join(appDir, file);
                if (fs.existsSync(fp)) {
                  let txt = fs.readFileSync(fp, 'utf-8');
                  for (const [from, to] of subs) txt = txt.split(from).join(to);
                  fs.writeFileSync(fp, txt, 'utf-8');
                }
              }

              // Rename Java package directory to match appId
              const oldJavaDir = pathMod.join(appDir, 'android/app/src/main/java/live/tiamat/app');
              if (fs.existsSync(oldJavaDir)) {
                const newJavaDir = pathMod.join(appDir, 'android/app/src/main/java', ...appId.split('.'));
                fs.mkdirSync(pathMod.dirname(newJavaDir), { recursive: true });
                execFileSync('mv', [oldJavaDir, newJavaDir], { timeout: 10_000 });
                // Update package declaration in MainActivity
                const mainActivity = pathMod.join(newJavaDir, 'MainActivity.java');
                if (fs.existsSync(mainActivity)) {
                  let src = fs.readFileSync(mainActivity, 'utf-8');
                  src = src.replace(/package live\.tiamat\.app;/, `package ${appId};`);
                  fs.writeFileSync(mainActivity, src, 'utf-8');
                }
                // Clean up old empty dirs
                try { fs.rmdirSync(pathMod.join(appDir, 'android/app/src/main/java/live/tiamat/app')); } catch {}
                try { fs.rmdirSync(pathMod.join(appDir, 'android/app/src/main/java/live/tiamat')); } catch {}
                try { fs.rmdirSync(pathMod.join(appDir, 'android/app/src/main/java/live')); } catch {}
              }

              // Create GitHub repo
              try {
                execFileSync('gh', ['repo', 'create', `${GITHUB_USER}/${appName}`, '--public', '--description', desc, '--confirm'], {
                  encoding: 'utf-8', timeout: 30_000
                });
              } catch (e: any) {
                // Repo might already exist
                if (!e.stderr?.includes('already exists')) {
                  return `Template created at ${appDir} but GitHub repo creation failed: ${e.stderr || e.message}`;
                }
              }

              // Git init and push
              execFileSync('git', ['init'], { cwd: appDir, encoding: 'utf-8', timeout: 10_000 });
              execFileSync('git', ['checkout', '-b', 'main'], { cwd: appDir, encoding: 'utf-8', timeout: 10_000 });
              execFileSync('git', ['add', '-A'], { cwd: appDir, encoding: 'utf-8', timeout: 15_000 });
              execFileSync('git', ['commit', '-m', `feat: scaffold ${displayName} app`], { cwd: appDir, encoding: 'utf-8', timeout: 15_000 });
              const remoteUrl = `https://${GITHUB_USER}:${process.env.GITHUB_TOKEN || execFileSync('gh', ['auth', 'token'], { encoding: 'utf-8' }).trim()}@github.com/${GITHUB_USER}/${appName}.git`;
              try { execFileSync('git', ['remote', 'remove', 'origin'], { cwd: appDir, encoding: 'utf-8', timeout: 5_000 }); } catch {}
              execFileSync('git', ['remote', 'add', 'origin', remoteUrl], { cwd: appDir, encoding: 'utf-8', timeout: 5_000 });
              execFileSync('git', ['push', '-u', 'origin', 'main', '--force'], { cwd: appDir, encoding: 'utf-8', timeout: 60_000 });

              return `App "${displayName}" scaffolded!\n` +
                     `  Directory: ${appDir}\n` +
                     `  Repo: github.com/${GITHUB_USER}/${appName}\n` +
                     `  App ID: ${appId}\n` +
                     `  GitHub Actions build triggered on push.\n` +
                     `  Next: Use android_app_factory({action:"update_code", app_name:"${appName}", file_path:"src/App.jsx", content:"..."}) to write your app code.`;
            } catch (e: any) {
              return `Scaffold failed: ${e.stderr || e.stdout || e.message}`;
            }
          }

          case 'update_code': {
            if (!fs.existsSync(appDir)) return `ERROR: App "${appName}" not found. Run scaffold first.`;
            const filePath = args.file_path as string;
            const content = args.content as string;
            if (!filePath) return 'ERROR: file_path is required (e.g. "src/App.jsx").';
            if (!content && content !== '') return 'ERROR: content is required.';

            const normalized = pathMod.normalize(filePath).replace(/^\/+/, '');
            if (normalized.includes('..')) return 'ERROR: path traversal not allowed.';

            const fullPath = pathMod.join(appDir, normalized);
            try {
              fs.mkdirSync(pathMod.dirname(fullPath), { recursive: true });
              fs.writeFileSync(fullPath, content, 'utf-8');
              return `File written: ${fullPath}\nUse android_app_factory({action:"build", app_name:"${appName}"}) when ready to push.`;
            } catch (e: any) {
              return `Failed to write file: ${e.message}`;
            }
          }

          case 'build': {
            if (!fs.existsSync(appDir)) return `ERROR: App "${appName}" not found.`;
            try {
              execFileSync('git', ['add', '-A'], { cwd: appDir, encoding: 'utf-8', timeout: 15_000 });
              let status: string;
              try {
                status = execFileSync('git', ['status', '--porcelain'], { cwd: appDir, encoding: 'utf-8', timeout: 10_000 }).trim();
              } catch { status = ''; }
              if (!status) return 'No changes to commit. Push skipped.';

              const msg = (args.commit_message as string) || `feat: update from TIAMAT cycle ${_ctx.turnNumber || 'unknown'}`;
              execFileSync('git', ['commit', '-m', msg], { cwd: appDir, encoding: 'utf-8', timeout: 15_000 });
              execFileSync('git', ['push', 'origin', 'main'], { cwd: appDir, encoding: 'utf-8', timeout: 60_000 });
              return `Build triggered! Pushed ${appName} to GitHub.\nCommit: ${msg}\nCheck status: android_app_factory({action:"status", app_name:"${appName}"})`;
            } catch (e: any) {
              return `Build failed: ${e.stderr || e.stdout || e.message}`;
            }
          }

          case 'status': {
            const repo = `${GITHUB_USER}/${appName}`;
            try {
              const out = execFileSync('gh', ['run', 'list', '--repo', repo, '--limit', '3', '--json', 'status,conclusion,name,createdAt,url'], {
                encoding: 'utf-8', timeout: 30_000
              }).trim();
              const runs = JSON.parse(out);
              if (runs.length === 0) return `No workflow runs found for ${repo}.`;
              return runs.map((r: any) => {
                const state = r.conclusion || r.status;
                const icon = state === 'success' ? 'PASS' : state === 'failure' ? 'FAIL' : state === 'in_progress' ? 'BUILDING...' : state.toUpperCase();
                return `[${icon}] ${r.name} — ${r.createdAt}\n  ${r.url}`;
              }).join('\n\n');
            } catch (e: any) {
              return `Failed to check status for ${repo}: ${e.stderr || e.message}`;
            }
          }

          case 'download': {
            const repo = `${GITHUB_USER}/${appName}`;
            try {
              const downloadDir = '/var/www/tiamat/download';
              fs.mkdirSync(downloadDir, { recursive: true });

              // Download into a temp subdir to avoid conflicts
              const tmpDir = pathMod.join(downloadDir, `_tmp_${appName}`);
              try { execFileSync('rm', ['-rf', tmpDir], { timeout: 5_000 }); } catch {}

              execFileSync('gh', ['run', 'download', '--repo', repo, '-n', 'app-apk', '-D', tmpDir], {
                encoding: 'utf-8', timeout: 120_000
              });

              const files = fs.readdirSync(tmpDir).filter((f: string) => f.endsWith('.apk'));
              if (files.length > 0) {
                const src = pathMod.join(tmpDir, files[0]);
                const dest = pathMod.join(downloadDir, `${appName}.apk`);
                try { fs.unlinkSync(dest); } catch {}
                fs.renameSync(src, dest);
                try { execFileSync('rm', ['-rf', tmpDir], { timeout: 5_000 }); } catch {}
                return `APK downloaded! Available at https://tiamat.live/download/${appName}.apk\nFile: ${dest}`;
              }
              return `Download completed but no .apk found. Contents: ${fs.readdirSync(tmpDir).join(', ')}`;
            } catch (e: any) {
              return `Download failed for ${repo}: ${e.stderr || e.message}`;
            }
          }

          case 'list': {
            try {
              if (!fs.existsSync(APPS_DIR)) {
                fs.mkdirSync(APPS_DIR, { recursive: true });
                return 'No apps yet. Use android_app_factory({action:"scaffold", app_name:"my-app"}) to create one.';
              }
              const apps = fs.readdirSync(APPS_DIR).filter((d: string) => {
                return fs.statSync(pathMod.join(APPS_DIR, d)).isDirectory();
              });
              if (apps.length === 0) return 'No apps yet. Use scaffold to create one.';

              const lines = apps.map((name: string) => {
                const dir = pathMod.join(APPS_DIR, name);
                const capConfig = pathMod.join(dir, 'capacitor.config.json');
                let appId = '?';
                try {
                  const cfg = JSON.parse(fs.readFileSync(capConfig, 'utf-8'));
                  appId = cfg.appId || '?';
                } catch {}
                return `  ${name} (${appId}) — ${dir}`;
              });

              return `Android Apps (${apps.length}):\n${lines.join('\n')}`;
            } catch (e: any) {
              return `Failed to list apps: ${e.message}`;
            }
          }

          default:
            return 'Invalid action. Use: scaffold, update_code, build, status, download, list';
        }
      },
    },
    // ── GPU Inference Tool ──
    {
      name: "gpu_infer",
      description:
        "Run inference on the RTX 3090 GPU node. Use for heavy research, planning, summarization, and child agent tasks. Returns the model's response text. GPU runs phi3:mini — good for brainstorming and drafting, NOT for customer-facing output.",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          prompt: {
            type: "string",
            description: "The prompt to send to the GPU model",
          },
          system: {
            type: "string",
            description: "Optional system prompt",
          },
          max_tokens: {
            type: "number",
            description: "Max tokens to generate (default: 512)",
          },
        },
        required: ["prompt"],
      },
      execute: async (args) => {
        const gpuEndpoint = process.env.GPU_ENDPOINT;
        if (!gpuEndpoint) return "GPU_ENDPOINT not configured in .env";

        try {
          // Health check first
          const healthResp = await fetch(`${gpuEndpoint}/health`, { signal: AbortSignal.timeout(3000) });
          if (!healthResp.ok) return "GPU node unreachable";
          const healthData = await healthResp.json() as Record<string, unknown>;
          if (healthData.cuda !== true) return "GPU node online but CUDA not available";

          // Inference
          const resp = await fetch(`${gpuEndpoint}/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: args.prompt as string,
              system: (args.system as string) || "",
              max_tokens: (args.max_tokens as number) || 512,
            }),
            signal: AbortSignal.timeout(60000),
          });

          if (!resp.ok) return `GPU inference failed: HTTP ${resp.status}`;
          const data = await resp.json() as Record<string, unknown>;
          return `[GPU-RTX3090] ${data.response || "No response"}`;
        } catch (e: any) {
          return `GPU inference error: ${e.message}`;
        }
      },
    },
    // ── TTS Synthesis Tool ──
    {
      name: "tts_synthesize",
      description:
        "Synthesize speech from text using Kokoro TTS on the GPU pod. Returns WAV audio. Use voice 'af_heart' (default, American English female) for TIAMAT's voice. Available lang_codes: a (American English), b (British English), j (Japanese), z (Mandarin), e (Spanish), f (French), h (Hindi), i (Italian), p (Portuguese).",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          text: {
            type: "string",
            description: "Text to synthesize (max 5000 chars)",
          },
          voice: {
            type: "string",
            description: "Voice ID (default: af_heart). Use /tts/voices on GPU to list all.",
          },
          lang_code: {
            type: "string",
            description: "Language code: a=American English, b=British, j=Japanese, z=Mandarin, e=Spanish, f=French, h=Hindi, i=Italian, p=Portuguese",
          },
          speed: {
            type: "number",
            description: "Speech speed multiplier (0.5-2.0, default: 1.0)",
          },
          save_as: {
            type: "string",
            description: "Filename to save as (default: auto-generated). Saved to /workspace/tiamat_tts_cache/",
          },
        },
        required: ["text"],
      },
      execute: async (args) => {
        const gpuEndpoint = process.env.GPU_ENDPOINT;
        if (!gpuEndpoint) return "GPU_ENDPOINT not configured in .env";

        const text = (args.text as string || "").trim();
        if (!text) return "No text provided";
        if (text.length > 5000) return "Text too long (max 5000 chars)";

        try {
          const resp = await fetch(`${gpuEndpoint}/tts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              text,
              voice: (args.voice as string) || "af_heart",
              lang_code: (args.lang_code as string) || "a",
              speed: (args.speed as number) || 1.0,
            }),
            signal: AbortSignal.timeout(60000),
          });

          if (!resp.ok) {
            const errText = await resp.text();
            return `TTS failed: HTTP ${resp.status} — ${errText}`;
          }

          // Save WAV locally (can't SSH to RunPod proxy)
          const wavBuffer = Buffer.from(await resp.arrayBuffer());
          const filename = (args.save_as as string) || `tts_${Date.now()}.wav`;

          const { writeFileSync, mkdirSync } = await import("fs");
          const cacheDir = "/tmp/tiamat_tts_cache";
          mkdirSync(cacheDir, { recursive: true });
          const localPath = `${cacheDir}/${filename}`;
          writeFileSync(localPath, wavBuffer);

          return `[TTS] Synthesized ${text.length} chars → ${localPath} (${wavBuffer.length} bytes, voice=${args.voice || "af_heart"})`;
        } catch (e: any) {
          return `TTS error: ${e.message}`;
        }
      },
    },
    // ── Growth & Evolution Tools ──
    ...createGrowthTools(),
  ];
}

// ─── Dynamic Tool Registry (Hot-Reload) ──────────────────────

/**
 * Load dynamic tools from /root/.automaton/tool_registry.json.
 * Called each cycle — tools can be added/removed/modified without restart.
 * Dynamic tools call Python scripts via execFileSync (same pattern as 13+ existing tools).
 */
export function loadDynamicTools(): AutomatonTool[] {
  const registryPath = "/root/.automaton/tool_registry.json";
  try {
    const raw = readFileSync(registryPath, "utf-8");
    const registry = JSON.parse(raw);
    return registry
      .filter((t: any) => t.enabled !== false)
      .map((t: any) => ({
        name: t.name,
        description: t.description,
        category: t.category || "vm",
        parameters: t.parameters || { type: "object", properties: {}, required: [] },
        execute: async (args: Record<string, unknown>) => {
          const scriptArgs = [t.script];
          if (t.argMap) {
            for (const key of t.argMap) {
              if (args[key] !== undefined) scriptArgs.push(String(args[key]));
            }
          } else if (Object.keys(args).length > 0) {
            scriptArgs.push(JSON.stringify(args));
          }
          const output = execFileSync("python3", scriptArgs, {
            encoding: "utf-8",
            timeout: t.timeout || 30000,
            cwd: t.cwd || "/root/entity/src/agent",
          }).trim();
          return output.slice(0, t.maxOutput || 4000);
        },
      }));
  } catch {
    return [];
  }
}

/**
 * Convert AutomatonTool list to OpenAI-compatible tool definitions.
 */
export function toolsToInferenceFormat(
  tools: AutomatonTool[],
): InferenceToolDefinition[] {
  return tools
    .filter((t) => !t.name.endsWith("_disabled"))
    .map((t) => ({
      type: "function" as const,
      function: {
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      },
    }));
}

/**
 * Execute a tool call and return the result.
 */
export async function executeTool(
  toolName: string,
  args: Record<string, unknown>,
  tools: AutomatonTool[],
  context: ToolContext,
): Promise<ToolCallResult> {
  const tool = tools.find((t) => t.name === toolName);
  const startTime = Date.now();

  if (!tool) {
    memory.recordToolOutcome(toolName, false, 0, `Unknown tool: ${toolName}`);
    return {
      id: `tc_${Date.now()}`,
      name: toolName,
      arguments: args,
      result: "",
      durationMs: 0,
      error: `Unknown tool: ${toolName}`,
    };
  }

  try {
    const result = await tool.execute(args, context);
    const duration = Date.now() - startTime;
    // Detect soft errors: tools that return error strings instead of throwing
    const isSoftError = typeof result === "string" && (
      result.startsWith("ERROR:") ||
      result.startsWith("Blocked:") ||
      result.startsWith("FORBIDDEN:") ||
      result.startsWith("COOLDOWN:")
    );
    memory.recordToolOutcome(toolName, !isSoftError, duration, isSoftError ? result.slice(0, 200) : undefined);
    return {
      id: `tc_${Date.now()}`,
      name: toolName,
      arguments: args,
      result,
      durationMs: duration,
    };
  } catch (err: any) {
    const duration = Date.now() - startTime;
    const errorMsg = err.message || String(err);
    memory.recordToolOutcome(toolName, false, duration, errorMsg);
    return {
      id: `tc_${Date.now()}`,
      name: toolName,
      arguments: args,
      result: "",
      durationMs: duration,
      error: errorMsg,
    };
  }
}
