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

// ─── Social Cooldown Tracker ───────────────────────────────────
// Persists last-post timestamps per platform to prevent spam.
// File: /root/.automaton/social_cooldowns.json

import { readFileSync, writeFileSync } from "fs";
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
];

// ─── Input Validation Helpers ────────────────────────────────

const VALID_HEX_ADDR = /^0x[0-9a-fA-F]{40}$/;
const VALID_PID = /^\d+$/;
const VALID_APP_NAME = /^[a-z0-9-]+$/;
const VALID_SUBDOMAIN = /^[a-z0-9-]*$/;
const FARCASTER_CHANNELS = ['base','ai','dev','agents','crypto','onchain','build'];
const SCANNER_CMDS = ['full','recent','pairs','immunefi','address'];
const FARCASTER_READ_CMDS = ['feed','search','test'];

const ALLOWED_READ_PATHS = ['/root/.automaton/', '/root/entity/', '/root/memory_api/', '/var/www/tiamat/', '/tmp/'];
const ALLOWED_WRITE_PATHS = ['/root/.automaton/', '/root/entity/src/agent/', '/root/entity/templates/', '/var/www/tiamat/', '/tmp/'];
const BLOCKED_PATH_PATTERNS = ['.env', '.ssh/', '.gnupg/', '/etc/shadow', 'wallet.json', 'automaton.json'];

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
        const blocked = isPathAllowed(resolvedPath, ALLOWED_WRITE_PATHS, BLOCKED_PATH_PATTERNS);
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
    description: "Send an email. Prefer send_telegram for all notifications — use this only as a fallback if Telegram fails.",
    category: "financial",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        to: { type: "string" as const, description: "Recipient email" },
        subject: { type: "string" as const, description: "Email subject" },
        body: { type: "string" as const, description: "Email body" },
      },
      required: ["subject", "body"],
    },
    execute: async (args: Record<string, unknown>, ctx: any) => {
      const { sendEmail } = await import('../tools/email.js');
      return await sendEmail(ctx.config, {
        to: args.to as string | undefined,
        subject: args.subject as string,
        body: args.body as string,
      });
    },
  },
  {
    name: "read_email",
    description: "Read recent emails from TIAMAT's Gmail inbox (tiamat.entity.prime@gmail.com). Use to check for verification emails, replies, notifications. Also receives all @tiamat.live emails via catch-all forwarding.",
    category: "survival",
    dangerous: false,
    parameters: {
      type: "object" as const,
      properties: {
        count: { type: "number" as const, description: "Number of recent emails to fetch (default 5, max 20)" },
        unread_only: { type: "boolean" as const, description: "Only fetch unread messages (default false)" },
      },
      required: [],
    },
    execute: async (args: Record<string, unknown>) => {
      const { execFileSync } = await import("child_process");
      const count = Math.min(Math.max(Number(args.count) || 5, 1), 20);
      const action = args.unread_only ? "unread" : "inbox";
      try {
        const result = execFileSync("python3", ["email_tool.py", action, String(count)], {
          cwd: "/root/entity/src/agent",
          timeout: 15000,
          env: { ...process.env },
        });
        return result.toString().slice(0, 4000);
      } catch (e: any) {
        return `Error reading email: ${e.message?.slice(0, 200)}`;
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
  {
    name: "browse_web",
    description: "Open a URL in headless Chromium browser. Can navigate, click buttons, type in fields, take screenshots, read page text. Use for interacting with web UIs, signing up for services, checking dashboards. Supports persistent sessions (cookies saved between calls). Actions: click, type, wait, screenshot, get_text, get_links, scroll, press.",
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
          timeout: 45000,
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
      description: "Ask Claude Code to modify your own runtime code in /root/entity. Write the task, Claude Code executes it with full permissions, then you get the output. Use this to add tools, fix bugs, improve yourself. If the task involves code changes, include 'rebuild' so the build runs automatically.",
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
        const { spawnSync } = await import("child_process");

        // Write task to file for debugging/logging
        writeFileSync("/root/.automaton/claude_task.txt", task, "utf-8");

        // Run Claude Code — strip session flags to allow nested invocation
        const childEnv = { ...process.env };
        delete childEnv.CLAUDECODE;
        delete childEnv.CLAUDE_CODE_ENTRYPOINT;
        delete childEnv.CLAUDE_CODE_SESSION_ID;
        delete childEnv.ANTHROPIC_AI_TOOL_USE_SESSION_ID;

        // Pipe task via stdin to avoid shell escaping issues with $(cat ...)
        const claudeResult = spawnSync(
          "sh",
          ["-c", 'cd /root/entity && claude --print --allowedTools "Edit,Write,Read,Bash"'],
          { encoding: "utf-8", timeout: 300_000, env: childEnv, input: task },
        );

        const claudeOutput = [
          claudeResult.stdout?.trim(),
          claudeResult.stderr?.trim(),
        ].filter(Boolean).join("\n");

        if (claudeResult.error) {
          return `ERROR launching Claude Code: ${claudeResult.error.message}`;
        }

        // Auto-rebuild if task involves code changes
        const shouldBuild = /rebuild|fix|add|update|change|modify|implement/i.test(task);
        if (shouldBuild) {
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
      name: "git_commit_disabled",
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
      name: "git_log_disabled",
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
      name: "git_push_disabled",
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
      name: "git_branch_disabled",
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
        if (cooldown) return cooldown;
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
      name: "fetch_terminal_markets",
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
      description: "Search long-term memory for relevant information. Use before making decisions or when you need context about past actions, customers, or strategies.",
      category: "cognitive",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Keywords to search for in memory" },
          type: { type: "string", enum: ["observation","outcome","strategy","customer","error","insight"], description: "Optional: filter by memory type" },
          limit: { type: "number", description: "Max results (default 5)" },
        },
        required: ["query"],
      },
      execute: async (args, _ctx) => {
        const memories = await memory.recall(args.query as string, {
          type: args.type as string | undefined,
          limit: (args.limit as number) || 5,
        });
        if (memories.length === 0) return "No memories found for that query.";
        return memories.map((m: any) => `[${m.type}|${m.importance}] ${m.content}`).join("\n---\n");
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
        await memory.learn(
          args.entity as string,
          args.relation as string,
          args.value as string,
          (args.confidence as number) || 0.7,
          "agent_observation"
        );
        return `Learned: ${args.entity} —[${args.relation}]→ ${args.value}`;
      },
    },
    {
      name: "reflect",
      description: "Deep reflection on accumulated memories, strategies, and knowledge. Use during strategic cycles to understand patterns, what's working/failing, and what to prioritize. Returns comprehensive memory analysis.",
      category: "cognitive",
      parameters: { type: "object", properties: {} },
      execute: async (_args, _ctx) => {
        return await memory.reflect();
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
      description: "Check API revenue metrics: total requests, free vs paid, last request time. Use this to measure traction and decide whether to pivot or double down.",
      category: "financial",
      parameters: { type: "object", properties: {} },
      execute: async (_args, _ctx) => {
        const { readFileSync } = await import("fs");
        try {
          const log = readFileSync("/root/api/requests.log", "utf-8");
          const lines = log.trim().split("\n").filter(Boolean);
          if (lines.length === 0) return "No requests logged yet.";
          const paid = lines.filter(l => l.includes("free:False") || l.includes("Free: False")).length;
          const free = lines.filter(l => l.includes("free:True") || l.includes("Free: True") || l.includes("Type: FREE")).length;
          const errors = lines.filter(l => l.includes("500") || l.includes("Error")).length;
          const first = lines[0];
          const last = lines[lines.length - 1];
          const revenueUsdc = (paid * 0.01).toFixed(2);
          return [
            `=== Revenue Report ===`,
            `Total requests: ${lines.length}`,
            `Free tier: ${free}`,
            `Paid (x402): ${paid} = $${revenueUsdc} USDC`,
            `Errors (500): ${errors}`,
            `First request: ${first.slice(0, 120)}`,
            `Last request:  ${last.slice(0, 120)}`,
          ].join("\n");
        } catch {
          return "No revenue data yet — /root/api/requests.log does not exist.";
        }
      },
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

        const { execFileSync } = await import('child_process');
        const result = execFileSync('claude', ['--print', '--allowedTools', 'Edit,Write,Read,Bash', task], {
          encoding: "utf-8", timeout: 300_000, env: childEnv, cwd: '/root/entity'
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
      description: "Run vulnerability scanner on Base chain contracts. READ-ONLY security research for Immunefi bounties. Actions: 'full' (all checks), 'recent' (new deployments last 50 blocks), 'pairs' (skim scan on DEX pairs), 'immunefi' (list bounty targets), 'status' (daemon status + recent findings), 'address 0x...' (scan specific contract). Findings logged to vuln_findings.json.",
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
          try {
            const findings = JSON.parse(fs.readFileSync('/root/.automaton/vuln_findings.json', 'utf-8'));
            status += `Total findings: ${findings.length}\n`;
            const recent = findings.slice(-3);
            for (const f of recent) { status += `  ${f.type} @ ${f.address} (${f.eth_value} ETH)\n`; }
          } catch { status += 'No findings yet.\n'; }
          return status;
        }

        try {
          const parts = action.split(' ');
          const cmd = parts[0];
          if (!SCANNER_CMDS.includes(cmd)) return `Invalid action: ${cmd}. Use: ${SCANNER_CMDS.join(', ')}`;
          const arg = parts[1] || '';
          if (cmd === 'address' && !VALID_HEX_ADDR.test(arg)) return 'Invalid address format. Use: 0x...40 hex chars';
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
      name: "check_opportunities",
      description: "Check the opportunity queue for pending items from background scanners/sniper. Returns pending opportunities that need action. After acting on an item, call again with action='done' and address to mark it handled. Actions: 'peek' (list pending), 'done <address>' (mark handled), 'stats' (queue summary).",
      category: "vm",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "peek|done <address>|stats" },
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
from opportunity_queue import OpportunityQueue
import json
pending = OpportunityQueue.peek()
if not pending:
    print("No pending opportunities.")
else:
    print(f"{len(pending)} pending opportunities:")
    for i, o in enumerate(pending):
        print(f"  [{i}] {o.get('type','?')} | {o.get('address','?')[:16]}... | {o.get('eth_value',0)} ETH | src: {o.get('source','?')} | action: {o.get('action','?')}")
`);
        }

        if (action === 'stats') {
          return pythonScript(`
import json
with open("/root/.automaton/opportunity_queue.json") as f:
    q = json.load(f)
pending = [x for x in q if x.get("status") == "pending"]
acted = [x for x in q if x.get("status") == "acted"]
print(f"Queue: {len(q)} total | {len(pending)} pending | {len(acted)} acted")
`);
        }

        if (action.startsWith('done ')) {
          const addr = action.split(' ')[1];
          if (!VALID_HEX_ADDR.test(addr)) return 'Invalid address format. Use: 0x...40 hex chars';
          return pythonScript(`
from opportunity_queue import OpportunityQueue
OpportunityQueue.mark_done_by_address("${addr}")
print("Marked done: ${addr}")
`);
        }

        return 'Unknown action. Use: peek, done <address>, stats';
      },
    },
    // ── Farcaster Tools ──
    {
      name: "post_farcaster",
      description: "Post a cast to Farcaster/Warpcast. Max 320 chars. Optionally target a channel (base, ai, dev, agents, crypto, onchain, build). Always embeds tiamat.live. Rate limited to 1 post per 5 minutes.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string", description: "Cast text (max 320 chars)" },
          channel: { type: "string", description: "Channel to post in: base, ai, dev, agents, crypto, onchain, build" },
        },
        required: ["text"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import('child_process');
        const { text, channel } = args as { text: string; channel?: string };
        if (channel && !FARCASTER_CHANNELS.includes(channel))
          return `Invalid channel. Use: ${FARCASTER_CHANNELS.join(', ')}`;
        try {
          const fArgs = ['farcaster.py', 'post', text];
          if (channel) fArgs.push(channel);
          const output = execFileSync('python3', fArgs, {
            encoding: 'utf-8', timeout: 20000, cwd: '/root/entity/src/agent'
          }).trim();
          const fs = await import('fs');
          fs.appendFileSync('/root/.automaton/tiamat.log', `\n[FARCASTER] Posted: ${text.slice(0, 60)}... ${channel ? 'to /' + channel : ''}\n`);
          return output.slice(0, 2000);
        } catch (e: any) {
          return `Farcaster post failed: ${e.stderr?.slice(0, 500) || e.message}`;
        }
      },
    },
    {
      name: "read_farcaster",
      description: "Read Farcaster feeds, search casts, or check notifications. Actions: 'feed <channel> [limit]' (read channel), 'search <query>' (find relevant casts), 'test' (check TIAMAT's profile).",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "feed <channel>|search <query>|test" },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
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
          return output.slice(0, 3000);
        } catch (e: any) {
          return `Farcaster read failed: ${e.stderr?.slice(0, 500) || e.message}`;
        }
      },
    },
    {
      name: "farcaster_engage",
      description: "Scan Farcaster for conversations about AI APIs, agent memory, summarization, x402 payments, and AI infrastructure. Replies helpfully to the best match (max 1 reply per 10 min). Actions: 'scan' (dry run, no posting), 'run' (scan + post reply), 'stats' (engagement history).",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", description: "scan | run | stats" },
        },
        required: ["action"],
      },
      execute: async (args, _ctx) => {
        const { execFileSync } = await import('child_process');
        const action = (args as { action: string }).action || 'scan';
        if (!['scan', 'run', 'stats'].includes(action))
          return `Invalid action. Use: scan, run, stats`;
        try {
          const output = execFileSync('python3', ['farcaster_engage.py', action], {
            encoding: 'utf-8', timeout: 90000, cwd: '/root/entity/src/agent',
            env: { ...process.env }
          }).trim();
          if (action === 'run') {
            const fs = await import('fs');
            fs.appendFileSync('/root/.automaton/tiamat.log', `\n[ENGAGE] ${action}: ${output.slice(0, 200)}\n`);
          }
          return output.slice(0, 3000);
        } catch (e: any) {
          return `farcaster_engage failed: ${e.stderr?.slice(0, 500) || e.message}`;
        }
      },
    },
  ];
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
    return {
      id: `tc_${Date.now()}`,
      name: toolName,
      arguments: args,
      result,
      durationMs: Date.now() - startTime,
    };
  } catch (err: any) {
    return {
      id: `tc_${Date.now()}`,
      name: toolName,
      arguments: args,
      result: "",
      durationMs: Date.now() - startTime,
      error: err.message || String(err),
    };
  }
}
