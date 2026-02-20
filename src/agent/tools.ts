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
];

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
        // Guard against overwriting critical files
        if (
          filePath.includes("wallet.json") ||
          filePath.includes("state.db")
        ) {
          return "Blocked: Cannot overwrite critical identity/state files directly";
        }
        const { writeFileSync, mkdirSync } = await import('fs');
        const { dirname } = await import('path');
        const { homedir } = await import('os');
        const resolvedPath = filePath.replace(/^~/, homedir());
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
      execute: async (args, ctx) => {
        const { readFileSync } = await import('fs');
        const { homedir } = await import('os');
        const rpath = (args.path as string).replace(/^~/, homedir());
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

    // ── Conway API Tools ──
    {
      name: "check_credits_disabled",
      description: "Check your current Conway compute credit balance.",
      category: "conway",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const balance = 0;
        return `Credit balance: $${(balance / 100).toFixed(2)} (${balance} cents)`;
      },
    },
    {
      name: "check_usdc_balance",
      description: "Check your on-chain USDC balance on Base.",
      category: "conway",
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
        "Create a new Conway sandbox (separate VM) for sub-tasks or testing.",
      category: "conway",
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
      category: "conway",
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
      category: "conway",
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
    name: "sleep",
      description:
        "Enter sleep mode for a specified duration. Heartbeat continues running.",
      category: "survival",
      parameters: {
        type: "object",
        properties: {
          duration_seconds: {
            type: "number",
            description: "How long to sleep in seconds",
          },
          reason: {
            type: "string",
            description: "Why you are sleeping",
          },
        },
        required: ["duration_seconds"],
      },
      execute: async (args, ctx) => {
        const duration = args.duration_seconds as number;
        const reason = (args.reason as string) || "No reason given";
        ctx.db.setAgentState("sleeping");
        ctx.db.setKV("sleep_until", new Date(Date.now() + duration * 1000).toISOString());
        ctx.db.setKV("sleep_reason", reason);
        return `Entering sleep mode for ${duration}s. Reason: ${reason}. Heartbeat will continue.`;
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
        "Publish a heartbeat status ping to Conway. Shows the world you are alive.",
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
      description: "Overwrite /root/.automaton/MISSION.md with new content. Use this to update your own goals and operational directives.",
      category: "self_mod",
      parameters: {
        type: "object",
        properties: {
          content: { type: "string", description: "New MISSION.md content (max 2000 chars)" },
        },
        required: ["content"],
      },
      execute: async (args, _ctx) => {
        const content = args.content as string;
        if (!content || content.trim().length === 0) {
          return "ERROR: content cannot be empty.";
        }
        if (content.length > 2000) {
          return `ERROR: content is ${content.length} characters, exceeds 2000 character limit.`;
        }
        const { writeFileSync } = await import("fs");
        writeFileSync("/root/.automaton/MISSION.md", content, "utf-8");
        return `MISSION.md updated (${content.length} chars).`;
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
        if (!task?.trim()) return "ERROR: task is required.";

        const { writeFileSync } = await import("fs");
        const { spawnSync } = await import("child_process");

        // Write task to file — keeps task content out of the shell command string
        writeFileSync("/root/.automaton/claude_task.txt", task, "utf-8");

        // Run Claude Code
        const claudeResult = spawnSync(
          "sh",
          ["-c", 'cd /root/entity && claude --print --dangerously-skip-permissions "$(cat /root/.automaton/claude_task.txt)"'],
          { encoding: "utf-8", timeout: 300_000 },
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
      description: "Transfer Conway compute credits to another address.",
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
        const { execSync } = await import('child_process');
        const { homedir } = await import('os');
        const repoPath = ((args.path as string) || '~/.automaton').replace(/^~/, homedir());
        const limit = (args.limit as number) || 10;
        try {
          const result = execSync(`git -C ${repoPath} log --oneline -${limit}`, { encoding: 'utf-8' });
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
      name: "spawn_child_disabled",
      description: "Spawn a child automaton in a new Conway sandbox.",
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
      name: "list_children_disabled",
      description: "List all spawned child automatons.",
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

    // ── Moltbook Tools ──
    {
      name: "moltbook_post",
      description: "Publish a post (molt) to Moltbook. Use this to announce your services, share updates, and attract customers.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          submolt_name: { type: "string", description: "Short tagline or subtitle (max 100 chars)" },
          title:   { type: "string", description: "Post title" },
          content: { type: "string", description: "Post body (markdown supported)" },
        },
        required: ["title", "content"],
      },
      execute: async (args, ctx) => {
        const apiKey = ctx.config.moltbookApiKey;
        if (!apiKey) return "ERROR: moltbookApiKey not set in automaton.json";
        const resp = await fetch("https://www.moltbook.com/api/v1/posts", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
          body: JSON.stringify({ submolt_name: (args.submolt_name as string) || "general", title: args.title, content: args.content }),
        });
        const text = await resp.text();
        if (!resp.ok) return `ERROR ${resp.status}: ${text}`;
        const data = JSON.parse(text);
        return `Post published: ${data.url || data.id || JSON.stringify(data)}`;
      },
    },
    {
      name: "moltbook_comment",
      description: "Comment on a Moltbook post. Use post_id from moltbook_feed results.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          post_id: { type: "string", description: "ID of the post to comment on" },
          content: { type: "string", description: "Comment text" },
        },
        required: ["post_id", "content"],
      },
      execute: async (args, ctx) => {
        const apiKey = ctx.config.moltbookApiKey;
        if (!apiKey) return "ERROR: moltbookApiKey not set in automaton.json";
        const resp = await fetch(`https://www.moltbook.com/api/v1/posts/${args.post_id}/comments`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
          body: JSON.stringify({ content: args.content }),
        });
        const text = await resp.text();
        if (!resp.ok) return `ERROR ${resp.status}: ${text}`;
        return `Comment posted on ${args.post_id}`;
      },
    },
    {
      name: "moltbook_feed",
      description: "Fetch recent posts from the Moltbook feed. Use this to find potential customers and see what other agents are doing.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Number of posts to fetch (default: 10, max: 50)" },
        },
      },
      execute: async (args, ctx) => {
        const apiKey = ctx.config.moltbookApiKey;
        if (!apiKey) return "ERROR: moltbookApiKey not set in automaton.json";
        const limit = Math.min((args.limit as number) || 10, 50);
        const resp = await fetch(`https://www.moltbook.com/api/v1/feed?limit=${limit}`, {
          headers: { Authorization: `Bearer ${apiKey}` },
        });
        const text = await resp.text();
        if (!resp.ok) return `ERROR ${resp.status}: ${text}`;
        const data = JSON.parse(text);
        const posts = Array.isArray(data) ? data : (data.posts || data.items || []);
        if (posts.length === 0) return "No posts found.";
        return posts
          .map((p: any) => `[${p.id}] ${p.author || p.name || "unknown"}: ${p.title || p.content?.slice(0, 80) || ""}`)
          .join("\n");
      },
    },
    {
      name: "moltbook_get_submolts",
      description: "Fetch available Moltbook communities (submolts) so you know valid names to use in moltbook_post.",
      category: "social",
      parameters: { type: "object", properties: {} },
      execute: async (_args, ctx) => {
        const apiKey = ctx.config.moltbookApiKey;
        if (!apiKey) return "ERROR: moltbookApiKey not set in automaton.json";
        const resp = await fetch("https://www.moltbook.com/api/v1/submolts", {
          headers: { Authorization: `Bearer ${apiKey}` },
        });
        const text = await resp.text();
        if (!resp.ok) return `ERROR ${resp.status}: ${text}`;
        const data = JSON.parse(text);
        const items = Array.isArray(data) ? data : (data.submolts || data.items || []);
        if (items.length === 0) return "No submolts found.";
        return items
          .map((s: any) => `${s.name || s.id}${s.description ? ` — ${s.description}` : ""}`)
          .join("\n");
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
      name: "search_twitter",
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
      description: "Post to Bluesky social network using AT Protocol. Use this to reach developers and AI researchers on Bluesky. Requires BLUESKY_HANDLE and BLUESKY_APP_PASSWORD env vars.",
      category: "social",
      parameters: {
        type: "object",
        properties: {
          text: {
            type: "string",
            description: "Post text (max 300 characters)",
          },
        },
        required: ["text"],
      },
      execute: async (args, _ctx) => {
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

        // Step 2: create post record
        const postResp = await fetch("https://bsky.social/xrpc/com.atproto.repo.createRecord", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${accessJwt}`,
          },
          body: JSON.stringify({
            repo: did,
            collection: "app.bsky.feed.post",
            record: {
              $type: "app.bsky.feed.post",
              text,
              createdAt: new Date().toISOString(),
            },
          }),
        });
        if (!postResp.ok) {
          const err = await postResp.text();
          return `ERROR posting to Bluesky (${postResp.status}): ${err}`;
        }
        const result = await postResp.json() as any;
        return `Posted to Bluesky. URI: ${result.uri}`;
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
        const limit = (args.limit as number) || 10;
        const resp = await fetch(`https://api.gitterapp.com/repositories?since=${since}`, {
          headers: { "Accept": "application/json", "User-Agent": "TIAMAT-agent/1.0" },
        });
        if (!resp.ok) return `ERROR ${resp.status}: ${await resp.text()}`;
        const repos = await resp.json() as any[];
        return repos.slice(0, limit).map((r: any, i: number) =>
          `${i + 1}. ${r.author}/${r.name} ⭐${r.stars ?? r.currentPeriodStars ?? "?"}\n   ${r.description || "(no description)"}\n   ${r.url || ""}`
        ).join("\n\n");
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

    // ── Social / Messaging Tools ──
    {
      name: "send_message_disabled",
      description:
        "Send a message to another automaton or address via the social relay.",
      category: "conway",
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
        "List all available inference models from the Conway API with their provider and pricing. Use this to discover what models you can use and pick the best one for your needs.",
      category: "conway",
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
      category: "conway",
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
      category: "conway",
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
      category: "conway",
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
