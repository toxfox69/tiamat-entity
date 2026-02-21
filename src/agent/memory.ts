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
    // Try NOORMME first
    try {
      const noormme = await import("NOORMEAI" as any);
      const NoormmeCortex = noormme.default?.Cortex || noormme.Cortex;
      if (NoormmeCortex) {
        this.cortex = new NoormmeCortex({ agentId: "tiamat" });
        await this.cortex.initialize?.();
        this.useNoormme = true;
        console.log("[MEMORY] NOORMME cortex loaded ✓");
      }
    } catch (_) {
      console.log("[MEMORY] NOORMME not available — using SQLite fallback");
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
          created_at TEXT    NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
          UNIQUE(entity, relation, value)
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

  /** Store a knowledge triple: entity --[relation]--> value */
  async learn(
    entity: string,
    relation: string,
    value: string,
    confidence?: number,
    source?: string
  ): Promise<void> {
    if (!this.db) return;
    try {
      this.db
        .prepare(
          `INSERT INTO tiamat_knowledge (entity, relation, value, confidence, source)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(entity, relation, value) DO UPDATE SET
             confidence = MAX(confidence, excluded.confidence),
             updated_at = datetime('now')`
        )
        .run(entity, relation, value, confidence ?? 0.5, source ?? "observation");
    } catch (err: any) {
      console.error(`[MEMORY] learn failed: ${err.message}`);
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
      }

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
}

// Singleton — imported once, shared across tools
export const memory = new TiamatMemory();
export { TiamatMemory };
