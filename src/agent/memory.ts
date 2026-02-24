/**
 * TIAMAT Cognitive Memory System
 *
 * Persistent, searchable, self-evolving memory backed by SQLite.
 * Optionally wraps NOORMME (CardSorting/NOORMEAI) for richer cognition.
 * Falls back gracefully if NOORMME is unavailable.
 */

import Database from "better-sqlite3";
import path from "path";
import fs from "fs";

const DB_PATH = path.join(process.env.HOME || "/root", ".automaton", "memory.db");

let memoryReady = false;

export interface MemoryEntry {
  id: number;
  type: string;
  content: string;
  metadata: string;
  importance: number;
  cycle: number;
  recalled_count: number;
  last_recalled: string | null;
  timestamp: string;
}

class TiamatMemory {
  private db: Database.Database | null = null;
  private cortex: any = null;
  private useNoormme = false;

  constructor() {
    this.init().catch((err) =>
      console.error(`[MEMORY] Init error: ${err.message}`)
    );
  }

  private async init() {
    // Try NOORMME cognitive layer
    try {
      const noormme = await import("noormme");
      const { NOORMME } = noormme as any;
      if (NOORMME) {
        const noormmeDb = new NOORMME({
          dialect: "sqlite",
          connection: { database: path.join(process.env.HOME || "/root", ".automaton", "noormme.sqlite") },
        });
        await noormmeDb.initialize();
        // Provision agentic schema (agent_rituals, agent_knowledge_base, etc.)
        if (noormmeDb.agent?.schema?.initializeSchema) {
          await noormmeDb.agent.schema.initializeSchema();
        }
        this.cortex = noormmeDb.agent?.cortex || null;
        if (this.cortex) {
          this.useNoormme = true;
          console.log("[MEMORY] NOORMME cortex loaded ✓");
        }
      }
    } catch (e: any) {
      console.log(`[MEMORY] NOORMME not available — using SQLite fallback (${e.message?.slice(0, 80)})`);
    }

    // Always init SQLite (used even when NOORMME is active)
    try {
      this.db = new Database(DB_PATH);
      this.db.pragma("journal_mode = WAL");

      this.db.exec(`
        CREATE TABLE IF NOT EXISTS tiamat_memories (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          type        TEXT    NOT NULL,
          content     TEXT    NOT NULL,
          metadata    TEXT    DEFAULT '{}',
          importance  REAL    DEFAULT 0.5,
          cycle       INTEGER DEFAULT 0,
          recalled_count INTEGER DEFAULT 0,
          last_recalled  TEXT,
          timestamp   TEXT    NOT NULL DEFAULT (datetime('now'))
        );
      `);

      this.db.exec(`
        CREATE TABLE IF NOT EXISTS tiamat_knowledge (
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          entity     TEXT    NOT NULL,
          relation   TEXT    NOT NULL,
          value      TEXT    NOT NULL,
          confidence REAL    DEFAULT 0.5,
          source     TEXT    DEFAULT 'observation',
          status     TEXT    DEFAULT 'proposed' CHECK(status IN ('proposed','verified','disputed','deprecated')),
          hit_count  INTEGER DEFAULT 0,
          created_at TEXT    NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
          UNIQUE(entity, relation, value)
        );
      `);

      // Migrate: add status and hit_count columns if missing
      try { this.db.exec(`ALTER TABLE tiamat_knowledge ADD COLUMN status TEXT DEFAULT 'proposed' CHECK(status IN ('proposed','verified','disputed','deprecated'))`); } catch {}
      try { this.db.exec(`ALTER TABLE tiamat_knowledge ADD COLUMN hit_count INTEGER DEFAULT 0`); } catch {}

      // Tool reliability tracking table
      this.db.exec(`
        CREATE TABLE IF NOT EXISTS tool_reliability (
          id              INTEGER PRIMARY KEY AUTOINCREMENT,
          tool_name       TEXT    NOT NULL UNIQUE,
          total_calls     INTEGER DEFAULT 0,
          total_successes INTEGER DEFAULT 0,
          total_failures  INTEGER DEFAULT 0,
          reliability     REAL    DEFAULT 1.0,
          avg_duration_ms REAL    DEFAULT 0,
          last_error      TEXT,
          last_called     TEXT,
          consecutive_failures INTEGER DEFAULT 0,
          consecutive_successes INTEGER DEFAULT 0,
          status          TEXT    DEFAULT 'healthy' CHECK(status IN ('healthy','degraded','blacklisted')),
          created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );
      `);

      this.db.exec(`
        CREATE TABLE IF NOT EXISTS tiamat_strategies (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          strategy      TEXT NOT NULL,
          action_taken  TEXT NOT NULL,
          outcome       TEXT,
          success_score REAL,
          cycle_start   INTEGER,
          created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
      `);

      memoryReady = true;
      console.log("[MEMORY] SQLite memory store ready ✓");
    } catch (err: any) {
      console.error(`[MEMORY] SQLite init failed: ${err.message}`);
    }
  }

  /** Store a memory */
  async remember(entry: {
    type: string;
    content: string;
    metadata?: Record<string, any>;
    importance?: number;
    cycle?: number;
  }): Promise<number | null> {
    if (!this.db) return null;
    try {
      const result = this.db
        .prepare(
          `INSERT INTO tiamat_memories (type, content, metadata, importance, cycle)
           VALUES (?, ?, ?, ?, ?)`
        )
        .run(
          entry.type,
          entry.content,
          JSON.stringify(entry.metadata || {}),
          entry.importance ?? 0.5,
          entry.cycle ?? 0
        );

      if (this.useNoormme && this.cortex) {
        try {
          await this.cortex.knowledge?.addKnowledge?.({
            topic: entry.type,
            content: entry.content,
            confidence: entry.importance ?? 0.5,
          });
        } catch (_) {}
      }

      return result.lastInsertRowid as number;
    } catch (err: any) {
      console.error(`[MEMORY] remember failed: ${err.message}`);
      return null;
    }
  }

  /** Search memories by keywords and optional type filter */
  async recall(
    query: string,
    options?: { type?: string; limit?: number; minImportance?: number }
  ): Promise<MemoryEntry[]> {
    if (!this.db) return [];
    try {
      const limit = options?.limit ?? 10;
      const minImportance = options?.minImportance ?? 0;
      const keywords = query
        .toLowerCase()
        .split(/\s+/)
        .filter((w) => w.length > 2);

      let sql = `SELECT * FROM tiamat_memories WHERE importance >= ?`;
      const params: any[] = [minImportance];

      if (options?.type) {
        sql += ` AND type = ?`;
        params.push(options.type);
      }

      if (keywords.length > 0) {
        const conds = keywords.map(() => `LOWER(content) LIKE ?`).join(" OR ");
        sql += ` AND (${conds})`;
        keywords.forEach((k) => params.push(`%${k}%`));
      }

      sql += ` ORDER BY importance DESC, timestamp DESC LIMIT ?`;
      params.push(limit);

      const rows = this.db.prepare(sql).all(...params) as MemoryEntry[];

      for (const row of rows) {
        this.db
          .prepare(
            `UPDATE tiamat_memories
             SET recalled_count = recalled_count + 1, last_recalled = datetime('now')
             WHERE id = ?`
          )
          .run(row.id);
      }

      return rows;
    } catch (err: any) {
      console.error(`[MEMORY] recall failed: ${err.message}`);
      return [];
    }
  }

  /** Store a knowledge triple with conflict detection.
   *  When a new fact contradicts an existing one (same entity+relation, different value),
   *  the old fact gets confidence penalized and marked 'disputed'. */
  async learn(
    entity: string,
    relation: string,
    value: string,
    confidence?: number,
    source?: string
  ): Promise<{ id: number; conflicts: number } | null> {
    if (!this.db) return null;
    try {
      const conf = confidence ?? 0.5;
      const src = source ?? "observation";

      // Check for conflicting facts: same entity+relation, different value
      const existing = this.db
        .prepare(
          `SELECT id, value, confidence, status, hit_count FROM tiamat_knowledge
           WHERE entity = ? AND relation = ? AND value != ? AND status != 'deprecated'`
        )
        .all(entity, relation, value) as Array<{
          id: number; value: string; confidence: number; status: string; hit_count: number;
        }>;

      let conflicts = 0;
      if (existing.length > 0) {
        // Penalize conflicting facts: reduce confidence by 0.15, mark disputed
        const penalize = this.db.prepare(
          `UPDATE tiamat_knowledge SET
             confidence = MAX(0.05, confidence - 0.15),
             status = CASE WHEN confidence - 0.15 <= 0.1 THEN 'deprecated' ELSE 'disputed' END,
             updated_at = datetime('now')
           WHERE id = ?`
        );
        for (const row of existing) {
          penalize.run(row.id);
          conflicts++;
        }
        if (conflicts > 0) {
          console.log(`[MEMORY] Conflict: ${entity}.${relation}=${value} disputes ${conflicts} existing fact(s)`);
        }
      }

      // Insert or update the new fact
      // Cap confidence at 0.85 for non-user sources until verified
      const cappedConf = src !== "user" ? Math.min(conf, 0.85) : conf;

      const result = this.db
        .prepare(
          `INSERT INTO tiamat_knowledge (entity, relation, value, confidence, source, status)
           VALUES (?, ?, ?, ?, ?, 'proposed')
           ON CONFLICT(entity, relation, value) DO UPDATE SET
             confidence = MIN(1.0, MAX(confidence, excluded.confidence) + 0.05),
             status = CASE
               WHEN hit_count >= 3 THEN 'verified'
               ELSE status
             END,
             hit_count = hit_count + 1,
             updated_at = datetime('now')`
        )
        .run(entity, relation, value, cappedConf, src);

      return { id: result.lastInsertRowid as number, conflicts };
    } catch (err: any) {
      console.error(`[MEMORY] learn failed: ${err.message}`);
      return null;
    }
  }

  /** Calculate fitness score for a knowledge item (0.0-1.0).
   *  Combines confidence (40%), signal-to-noise ratio (40%), source weight (20%). */
  calculateFitness(item: {
    confidence: number; hit_count: number; source: string; created_at: string;
  }): number {
    const ageMs = Date.now() - new Date(item.created_at).getTime();
    const ageInDays = Math.max(1, ageMs / (1000 * 60 * 60 * 24));
    const stn = Math.min(1.0, (item.hit_count || 0) / ageInDays); // Signal-to-noise
    const sourceMult = item.source === "user" ? 1.0 : 0.7;
    return item.confidence * 0.4 + stn * 0.4 + sourceMult * 0.2;
  }

  /** Prune zombie memories: old, never recalled, low importance.
   *  Also prune deprecated knowledge facts. Returns count of items pruned. */
  async pruneZombies(options?: { memoryAgeDays?: number; knowledgeMinFitness?: number }): Promise<number> {
    if (!this.db) return 0;
    try {
      const memAgeDays = options?.memoryAgeDays ?? 30;
      const minFitness = options?.knowledgeMinFitness ?? 0.15;
      let pruned = 0;

      // Prune memories: old + never recalled + low importance
      const memResult = this.db
        .prepare(
          `DELETE FROM tiamat_memories
           WHERE recalled_count = 0
             AND importance < 0.4
             AND compressed = 0
             AND timestamp < datetime('now', ? || ' days')`
        )
        .run(`-${memAgeDays}`);
      pruned += memResult.changes;

      // Prune deprecated knowledge
      const deprecatedResult = this.db
        .prepare(`DELETE FROM tiamat_knowledge WHERE status = 'deprecated'`)
        .run();
      pruned += deprecatedResult.changes;

      // Prune low-fitness knowledge (older than 14 days, never hit, low confidence)
      const lowFitness = this.db
        .prepare(
          `SELECT id, confidence, hit_count, source, created_at FROM tiamat_knowledge
           WHERE hit_count = 0 AND confidence < 0.3
             AND created_at < datetime('now', '-14 days')`
        )
        .all() as Array<{ id: number; confidence: number; hit_count: number; source: string; created_at: string }>;

      const deleteStmt = this.db.prepare(`DELETE FROM tiamat_knowledge WHERE id = ?`);
      for (const item of lowFitness) {
        if (this.calculateFitness(item) < minFitness) {
          deleteStmt.run(item.id);
          pruned++;
        }
      }

      if (pruned > 0) {
        console.log(`[MEMORY] Pruned ${pruned} zombie items (${memResult.changes} memories, ${deprecatedResult.changes} deprecated facts, ${pruned - memResult.changes - deprecatedResult.changes} low-fitness facts)`);
      }
      return pruned;
    } catch (err: any) {
      console.error(`[MEMORY] pruneZombies failed: ${err.message}`);
      return 0;
    }
  }

  /** Log a strategy attempt and its measured outcome */
  async logStrategy(
    strategy: string,
    action: string,
    outcome?: string,
    score?: number,
    cycle?: number
  ): Promise<void> {
    if (!this.db) return;
    try {
      this.db
        .prepare(
          `INSERT INTO tiamat_strategies (strategy, action_taken, outcome, success_score, cycle_start)
           VALUES (?, ?, ?, ?, ?)`
        )
        .run(strategy, action, outcome ?? null, score ?? null, cycle ?? null);
    } catch (err: any) {
      console.error(`[MEMORY] logStrategy failed: ${err.message}`);
    }
  }

  /**
   * Full reflection — patterns, wins, failures, knowledge.
   * Used during strategic cycles. Returns a markdown summary.
   */
  async reflect(): Promise<string> {
    if (!this.db) return "Memory not initialized.";
    try {
      const totalMem = (
        this.db.prepare(`SELECT COUNT(*) as c FROM tiamat_memories`).get() as any
      ).c;
      const totalKnow = (
        this.db.prepare(`SELECT COUNT(*) as c FROM tiamat_knowledge`).get() as any
      ).c;

      const topMem = this.db
        .prepare(
          `SELECT type, content, importance FROM tiamat_memories
           WHERE importance >= 0.7 ORDER BY importance DESC LIMIT 10`
        )
        .all() as any[];

      const recentMem = this.db
        .prepare(
          `SELECT type, content, importance FROM tiamat_memories
           ORDER BY timestamp DESC LIMIT 10`
        )
        .all() as any[];

      const goodStrats = this.db
        .prepare(
          `SELECT strategy, action_taken, outcome, success_score FROM tiamat_strategies
           WHERE success_score >= 0.6 ORDER BY success_score DESC LIMIT 5`
        )
        .all() as any[];

      const badStrats = this.db
        .prepare(
          `SELECT strategy, action_taken, outcome FROM tiamat_strategies
           WHERE success_score IS NOT NULL AND success_score < 0.4
           ORDER BY created_at DESC LIMIT 5`
        )
        .all() as any[];

      const topKnow = this.db
        .prepare(
          `SELECT entity, relation, value FROM tiamat_knowledge
           ORDER BY confidence DESC LIMIT 10`
        )
        .all() as any[];

      const freqRecall = this.db
        .prepare(
          `SELECT content, recalled_count FROM tiamat_memories
           WHERE recalled_count > 2 ORDER BY recalled_count DESC LIMIT 5`
        )
        .all() as any[];

      if (this.useNoormme && this.cortex?.rituals) {
        try { await this.cortex.rituals.runPendingRituals(); } catch (_) {}
      }

      let r = `## MEMORY REFLECTION (${totalMem} memories · ${totalKnow} facts)\n\n`;

      if (topMem.length > 0) {
        r += `### High-Importance Memories\n`;
        topMem.forEach((m) => { r += `- [${m.type}] ${m.content.slice(0, 150)}\n`; });
        r += "\n";
      }

      if (recentMem.length > 0) {
        r += `### Recent Memories\n`;
        recentMem.forEach((m) => { r += `- [${m.type}] ${m.content.slice(0, 120)}\n`; });
        r += "\n";
      }

      if (goodStrats.length > 0) {
        r += `### What Worked\n`;
        goodStrats.forEach((s) => { r += `- ${s.strategy}: ${s.action_taken} → ${s.outcome} (${s.success_score})\n`; });
        r += "\n";
      }

      if (badStrats.length > 0) {
        r += `### What Failed (avoid repeating)\n`;
        badStrats.forEach((s) => { r += `- ${s.strategy}: ${s.action_taken} → ${s.outcome}\n`; });
        r += "\n";
      }

      if (topKnow.length > 0) {
        r += `### Key Knowledge\n`;
        topKnow.forEach((k) => { r += `- ${k.entity} —[${k.relation}]→ ${k.value}\n`; });
        r += "\n";
      }

      if (freqRecall.length > 0) {
        r += `### Frequently Recalled (act on these)\n`;
        freqRecall.forEach((m) => { r += `- (×${m.recalled_count}) ${m.content.slice(0, 100)}\n`; });
        r += "\n";
      }

      // Tool reliability report
      const toolReport = this.getToolReliabilityReport();
      if (toolReport) r += toolReport;

      // Knowledge health
      try {
        const disputed = (
          this.db!.prepare(`SELECT COUNT(*) as c FROM tiamat_knowledge WHERE status = 'disputed'`).get() as any
        ).c;
        const deprecated = (
          this.db!.prepare(`SELECT COUNT(*) as c FROM tiamat_knowledge WHERE status = 'deprecated'`).get() as any
        ).c;
        const verified = (
          this.db!.prepare(`SELECT COUNT(*) as c FROM tiamat_knowledge WHERE status = 'verified'`).get() as any
        ).c;
        if (disputed > 0 || deprecated > 0 || verified > 0) {
          r += `### Knowledge Health\n`;
          r += `- Verified: ${verified} | Disputed: ${disputed} | Deprecated: ${deprecated}\n`;
        }
      } catch {}

      return r;
    } catch (err: any) {
      return `Reflection failed: ${err.message}`;
    }
  }

  /** Compact memory context for injection into prompts — stays small */
  async getContextForPrompt(maxChars: number = 600): Promise<string> {
    if (!this.db) return "";
    try {
      const highlights = this.db
        .prepare(
          `SELECT type, content FROM tiamat_memories
           WHERE importance >= 0.6 ORDER BY timestamp DESC LIMIT 6`
        )
        .all() as any[];

      const knowledge = this.db
        .prepare(
          `SELECT entity, relation, value FROM tiamat_knowledge
           WHERE confidence >= 0.7 ORDER BY updated_at DESC LIMIT 6`
        )
        .all() as any[];

      let ctx = "";
      if (highlights.length > 0) {
        ctx += "MEM: " + highlights.map((h) => `[${h.type}] ${h.content.slice(0, 80)}`).join(" | ") + "\n";
      }
      if (knowledge.length > 0) {
        ctx += "KNOW: " + knowledge.map((k) => `${k.entity}→${k.value}`).join(", ") + "\n";
      }
      return ctx.slice(0, maxChars);
    } catch {
      return "";
    }
  }

  isReady(): boolean { return memoryReady; }

  // ── Stats (cached 60s) ────────────────────────────────────────
  private statsCache: { l1: number; l2: number; l3: number; knowledge: number; strategies: number } | null = null;
  private statsCacheTime = 0;

  getStats(): { l1: number; l2: number; l3: number; knowledge: number; strategies: number } {
    if (!this.db) return { l1: 0, l2: 0, l3: 0, knowledge: 0, strategies: 0 };
    const now = Date.now();
    if (this.statsCache && now - this.statsCacheTime < 60_000) return this.statsCache;
    try {
      const l1 = (this.db.prepare(`SELECT COUNT(*) as c FROM tiamat_memories`).get() as any).c;
      let l2 = 0;
      try { l2 = (this.db.prepare(`SELECT COUNT(*) as c FROM compressed_memories`).get() as any).c; } catch {}
      let l3 = 0;
      try { l3 = (this.db.prepare(`SELECT COUNT(*) as c FROM core_knowledge`).get() as any).c; } catch {}
      const knowledge = (this.db.prepare(`SELECT COUNT(*) as c FROM tiamat_knowledge`).get() as any).c;
      const strategies = (this.db.prepare(`SELECT COUNT(*) as c FROM tiamat_strategies`).get() as any).c;
      this.statsCache = { l1, l2, l3, knowledge, strategies };
      this.statsCacheTime = now;
      return this.statsCache;
    } catch {
      return { l1: 0, l2: 0, l3: 0, knowledge: 0, strategies: 0 };
    }
  }

  // ── Tool Reliability Tracking ──────────────────────────────────

  /** Record a tool execution outcome. Uses damped moving average for reliability. */
  recordToolOutcome(toolName: string, success: boolean, durationMs: number, error?: string): void {
    if (!this.db) return;
    try {
      const DAMPING = 0.8; // 80% old, 20% new

      const existing = this.db
        .prepare(`SELECT * FROM tool_reliability WHERE tool_name = ?`)
        .get(toolName) as any;

      if (!existing) {
        // First call — initialize
        this.db
          .prepare(
            `INSERT INTO tool_reliability (tool_name, total_calls, total_successes, total_failures,
               reliability, avg_duration_ms, last_error, last_called,
               consecutive_failures, consecutive_successes, status)
             VALUES (?, 1, ?, ?, ?, ?, ?, datetime('now'), ?, ?, 'healthy')`
          )
          .run(
            toolName,
            success ? 1 : 0,
            success ? 0 : 1,
            success ? 1.0 : 0.0,
            durationMs,
            success ? null : (error || "unknown"),
            success ? 0 : 1,
            success ? 1 : 0,
          );
        return;
      }

      // Damped moving average: new_reliability = old * 0.8 + current * 0.2
      const newReliability = existing.reliability * DAMPING + (success ? 1.0 : 0.0) * (1 - DAMPING);
      const newAvgDuration = existing.avg_duration_ms * DAMPING + durationMs * (1 - DAMPING);
      const consecFail = success ? 0 : existing.consecutive_failures + 1;
      const consecSuccess = success ? existing.consecutive_successes + 1 : 0;

      // Status transitions
      let newStatus = existing.status;
      if (consecFail >= 5) {
        newStatus = "blacklisted"; // 5 consecutive failures → blacklist
      } else if (consecFail >= 3 || newReliability < 0.3) {
        newStatus = "degraded"; // 3 consecutive or <30% reliability → degraded
      } else if (consecSuccess >= 5 && newReliability > 0.7) {
        newStatus = "healthy"; // 5 consecutive successes + >70% → recovery
      }

      this.db
        .prepare(
          `UPDATE tool_reliability SET
             total_calls = total_calls + 1,
             total_successes = total_successes + ?,
             total_failures = total_failures + ?,
             reliability = ?,
             avg_duration_ms = ?,
             last_error = CASE WHEN ? = 0 THEN ? ELSE last_error END,
             last_called = datetime('now'),
             consecutive_failures = ?,
             consecutive_successes = ?,
             status = ?
           WHERE tool_name = ?`
        )
        .run(
          success ? 1 : 0,
          success ? 0 : 1,
          newReliability,
          newAvgDuration,
          success ? 1 : 0, // condition: if not success, update last_error
          error || "unknown",
          consecFail,
          consecSuccess,
          newStatus,
          toolName,
        );
    } catch (err: any) {
      // Never let tracking break tool execution
      console.error(`[TOOL-TRACK] Record failed: ${err.message}`);
    }
  }

  /** Get tool reliability data for system prompt injection.
   *  Returns only degraded/blacklisted tools to save prompt tokens. */
  getToolReliabilitySummary(): string {
    if (!this.db) return "";
    try {
      const degraded = this.db
        .prepare(
          `SELECT tool_name, reliability, status, total_calls, consecutive_failures, last_error
           FROM tool_reliability
           WHERE status IN ('degraded', 'blacklisted') AND total_calls >= 3
           ORDER BY reliability ASC`
        )
        .all() as Array<{
          tool_name: string; reliability: number; status: string;
          total_calls: number; consecutive_failures: number; last_error: string;
        }>;

      if (degraded.length === 0) return "";

      let summary = "[TOOL HEALTH]\n";
      for (const t of degraded) {
        const pct = Math.round(t.reliability * 100);
        summary += `⚠ ${t.tool_name}: ${pct}% reliable (${t.status}, ${t.consecutive_failures} consecutive fails`;
        if (t.last_error) summary += `, last: ${t.last_error.slice(0, 60)}`;
        summary += ")\n";
      }
      return summary;
    } catch {
      return "";
    }
  }

  /** Full tool reliability report for reflect(). */
  getToolReliabilityReport(): string {
    if (!this.db) return "";
    try {
      const all = this.db
        .prepare(
          `SELECT tool_name, total_calls, reliability, status, avg_duration_ms,
                  total_successes, total_failures, consecutive_failures, last_error
           FROM tool_reliability
           WHERE total_calls >= 2
           ORDER BY total_calls DESC`
        )
        .all() as any[];

      if (all.length === 0) return "";

      let report = `### Tool Reliability (${all.length} tracked)\n`;
      const healthy = all.filter((t) => t.status === "healthy");
      const degraded = all.filter((t) => t.status === "degraded");
      const blacklisted = all.filter((t) => t.status === "blacklisted");

      if (blacklisted.length > 0) {
        report += `**Blacklisted (avoid):** ${blacklisted.map((t: any) => `${t.tool_name}(${Math.round(t.reliability * 100)}%)`).join(", ")}\n`;
      }
      if (degraded.length > 0) {
        report += `**Degraded (use cautiously):** ${degraded.map((t: any) => `${t.tool_name}(${Math.round(t.reliability * 100)}%)`).join(", ")}\n`;
      }
      if (healthy.length > 0) {
        const top5 = healthy.slice(0, 5);
        report += `**Most used:** ${top5.map((t: any) => `${t.tool_name}(${t.total_calls}×, ${Math.round(t.reliability * 100)}%)`).join(", ")}\n`;
      }

      return report + "\n";
    } catch {
      return "";
    }
  }

  /** Run L1→L2 memory compression (call during strategic cycles) */
  async compressL1toL2(currentCycle: number): Promise<number> {
    if (!this.db) return 0;
    try {
      const { compressL1toL2, ensureSchema } = await import("./memory-compress.js");
      ensureSchema(this.db);
      return await compressL1toL2(this.db, currentCycle);
    } catch (err: any) {
      console.error(`[MEMORY] compressL1toL2 failed: ${err.message}`);
      return 0;
    }
  }

  /** Run L2→L3 core knowledge extraction (call every ~100 strategic cycles) */
  async compressL2toL3(): Promise<number> {
    if (!this.db) return 0;
    try {
      const { compressL2toL3, ensureSchema } = await import("./memory-compress.js");
      ensureSchema(this.db);
      return await compressL2toL3(this.db);
    } catch (err: any) {
      console.error(`[MEMORY] compressL2toL3 failed: ${err.message}`);
      return 0;
    }
  }

  /** Smart tiered recall: L3 → L2 → L1, within token budget */
  async smartRecall(
    query: string,
    tokenBudget: number = 2000
  ): Promise<Array<{ tier: string; content: string; id: number; score?: number }>> {
    if (!this.db) return [];
    try {
      const { smartRecall, ensureSchema } = await import("./memory-compress.js");
      ensureSchema(this.db);
      return smartRecall(this.db, query, tokenBudget);
    } catch (err: any) {
      console.error(`[MEMORY] smartRecall failed: ${err.message}`);
      // Fallback to basic recall
      const basic = await this.recall(query, { limit: 5 });
      return basic.map((m) => ({
        tier: "L1" as const,
        content: `[L1:${m.type}|${m.importance}] ${m.content}`,
        id: m.id,
        score: m.importance,
      }));
    }
  }

  /**
   * Get past experience for reasoning context.
   * Returns top strategies (successes + failures) and recent high-importance memories.
   * Used by the reasoning layer to give TIAMAT genuine learning from her own history.
   */
  getPastExperience(topic?: string, maxChars: number = 800): string {
    if (!this.db) return "";
    try {
      const parts: string[] = [];

      // Top successful strategies
      const goodStrats = this.db
        .prepare(
          `SELECT strategy, action_taken, outcome, success_score FROM tiamat_strategies
           WHERE success_score >= 0.6 ORDER BY success_score DESC LIMIT 3`
        )
        .all() as any[];
      if (goodStrats.length > 0) {
        parts.push(
          "WHAT WORKED:\n" +
          goodStrats.map(s =>
            `- ${s.strategy}: ${s.action_taken} → ${s.outcome || "no outcome recorded"} (score: ${s.success_score})`
          ).join("\n"),
        );
      }

      // Recent failures to avoid
      const badStrats = this.db
        .prepare(
          `SELECT strategy, action_taken, outcome FROM tiamat_strategies
           WHERE success_score IS NOT NULL AND success_score < 0.3
           ORDER BY created_at DESC LIMIT 3`
        )
        .all() as any[];
      if (badStrats.length > 0) {
        parts.push(
          "WHAT FAILED (avoid repeating):\n" +
          badStrats.map(s =>
            `- ${s.strategy}: ${s.action_taken} → ${s.outcome || "failed"}`
          ).join("\n"),
        );
      }

      // Actions with 0 revenue impact (from recent memories tagged as outcome)
      const zeroImpact = this.db
        .prepare(
          `SELECT content FROM tiamat_memories
           WHERE type = 'outcome' AND importance < 0.4
           ORDER BY timestamp DESC LIMIT 3`
        )
        .all() as any[];
      if (zeroImpact.length > 0) {
        parts.push(
          "LOW-IMPACT ACTIONS (deprioritize):\n" +
          zeroImpact.map(m => `- ${m.content.slice(0, 120)}`).join("\n"),
        );
      }

      // Topic-specific recall if provided
      if (topic) {
        const topicMems = this.db
          .prepare(
            `SELECT type, content FROM tiamat_memories
             WHERE importance >= 0.5 AND content LIKE ?
             ORDER BY timestamp DESC LIMIT 3`
          )
          .all(`%${topic.slice(0, 30)}%`) as any[];
        if (topicMems.length > 0) {
          parts.push(
            `RELEVANT PAST (${topic.slice(0, 30)}):\n` +
            topicMems.map(m => `- [${m.type}] ${m.content.slice(0, 120)}`).join("\n"),
          );
        }
      }

      const result = parts.join("\n\n");
      return result.length > maxChars ? result.slice(0, maxChars) + "..." : result;
    } catch (err: any) {
      console.error(`[MEMORY] getPastExperience failed: ${err.message}`);
      return "";
    }
  }
}

// Singleton — imported once, shared across tools
export const memory = new TiamatMemory();
export { TiamatMemory };
