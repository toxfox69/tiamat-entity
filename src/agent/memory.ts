/**
 * TIAMAT Cognitive Memory System v2
 *
 * Persistent, searchable, self-evolving memory backed by SQLite + FTS5.
 * Features: full-text search, memory decay, associative links, consolidation,
 * emotional valence, predictive tracking, L1/L2/L3 compression.
 *
 * Direct better-sqlite3 — no ORM overhead.
 */

import Database from "better-sqlite3";
import path from "path";

const DB_PATH = path.join(process.env.HOME || "/root", ".automaton", "memory.db");

let memoryReady = false;

// ── Interfaces ────────────────────────────────────────────────

interface MemoryEntry {
  id: number;
  type: string;
  content: string;
  metadata: string;
  importance: number;
  cycle: number;
  recalled_count: number;
  last_recalled: string | null;
  timestamp: string;
  decay_score?: number;
  valence?: number;
}

interface MemoryLink {
  id: number;
  source_id: number;
  target_id: number;
  link_type: string;
  strength: number;
  created_at: string;
}

interface PredictionEntry {
  id: number;
  prediction: string;
  confidence: number;
  deadline: string | null;
  verified: number;
  actual_outcome: string | null;
  accuracy_score: number | null;
  created_at: string;
}

// ── Valence keyword maps ──────────────────────────────────────

const POSITIVE_KEYWORDS = [
  "success", "shipped", "revenue", "working", "fixed", "completed", "achieved",
  "growth", "engaged", "published", "paid", "customer", "conversion", "profit",
  "approved", "accepted", "deployed", "live", "resolved", "improved", "upgrade",
  "milestone", "breakthrough", "efficient", "optimized",
];

const NEGATIVE_KEYWORDS = [
  "error", "failed", "blocked", "crash", "broken", "timeout", "rejected",
  "spam", "degraded", "blacklisted", "bug", "down", "lost", "denied",
  "expired", "stale", "loop", "zombie", "waste", "stuck", "outage",
  "overloaded", "bankrupt", "deprecated",
];

/** Detect emotional valence from text content. Returns -1.0 to 1.0. */
function detectValence(text: string): number {
  const lower = text.toLowerCase();
  let pos = 0;
  let neg = 0;
  for (const kw of POSITIVE_KEYWORDS) {
    if (lower.includes(kw)) pos++;
  }
  for (const kw of NEGATIVE_KEYWORDS) {
    if (lower.includes(kw)) neg++;
  }
  const total = pos + neg;
  if (total === 0) return 0;
  // Scale: pure positive = 1.0, pure negative = -1.0
  return Math.max(-1, Math.min(1, (pos - neg) / total));
}

// ── Main Class ────────────────────────────────────────────────

class TiamatMemory {
  private db: Database.Database | null = null;

  getDb(): Database.Database | null { return this.db; }

  constructor() {
    this.init().catch((err) =>
      console.error(`[MEMORY] Init error: ${err.message}`)
    );
  }

  private async init() {
    try {
      this.db = new Database(DB_PATH);
      this.db.pragma("journal_mode = WAL");

      // ── Core tables ───────────────────────────────────────

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

      // ── Associative links table ───────────────────────────

      this.db.exec(`
        CREATE TABLE IF NOT EXISTS tiamat_memory_links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id INTEGER NOT NULL REFERENCES tiamat_memories(id) ON DELETE CASCADE,
          target_id INTEGER NOT NULL REFERENCES tiamat_memories(id) ON DELETE CASCADE,
          link_type TEXT NOT NULL,
          strength REAL DEFAULT 0.5,
          created_at TEXT DEFAULT (datetime('now')),
          UNIQUE(source_id, target_id, link_type)
        );
      `);

      // Index for fast link lookups
      try {
        this.db.exec(`CREATE INDEX IF NOT EXISTS idx_links_source ON tiamat_memory_links(source_id)`);
        this.db.exec(`CREATE INDEX IF NOT EXISTS idx_links_target ON tiamat_memory_links(target_id)`);
      } catch {}

      // ── Memory archive table (for decayed memories) ───────

      this.db.exec(`
        CREATE TABLE IF NOT EXISTS tiamat_memories_archive (
          id          INTEGER PRIMARY KEY,
          type        TEXT    NOT NULL,
          content     TEXT    NOT NULL,
          metadata    TEXT    DEFAULT '{}',
          importance  REAL    DEFAULT 0.5,
          cycle       INTEGER DEFAULT 0,
          recalled_count INTEGER DEFAULT 0,
          last_recalled  TEXT,
          timestamp   TEXT    NOT NULL,
          decay_score REAL    DEFAULT 0,
          valence     REAL    DEFAULT 0,
          archived_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );
      `);

      // ── Prediction tracking table ─────────────────────────

      this.db.exec(`
        CREATE TABLE IF NOT EXISTS tiamat_predictions_v2 (
          id              INTEGER PRIMARY KEY AUTOINCREMENT,
          prediction      TEXT    NOT NULL,
          confidence      REAL    DEFAULT 0.5,
          deadline        TEXT,
          verified        INTEGER DEFAULT 0,
          actual_outcome  TEXT,
          accuracy_score  REAL,
          created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );
      `);

      // ── Column migrations (safe — "already exists" caught) ─

      try { this.db.exec(`ALTER TABLE tiamat_knowledge ADD COLUMN status TEXT DEFAULT 'proposed' CHECK(status IN ('proposed','verified','disputed','deprecated'))`); } catch {}
      try { this.db.exec(`ALTER TABLE tiamat_knowledge ADD COLUMN hit_count INTEGER DEFAULT 0`); } catch {}
      try { this.db.exec(`ALTER TABLE tiamat_memories ADD COLUMN compressed INTEGER DEFAULT 0`); } catch {}
      try { this.db.exec(`ALTER TABLE tiamat_memories ADD COLUMN decay_score REAL DEFAULT 1.0`); } catch {}
      try { this.db.exec(`ALTER TABLE tiamat_memories ADD COLUMN valence REAL DEFAULT 0`); } catch {}

      // ── FTS5 full-text search index ───────────────────────

      this.initFTS5();

      memoryReady = true;
      console.log("[MEMORY] SQLite memory store ready (FTS5 + decay + links + valence)");
    } catch (err: any) {
      console.error(`[MEMORY] SQLite init failed: ${err.message}`);
    }
  }

  // ── FTS5 Setup ──────────────────────────────────────────────

  /**
   * Initialize FTS5 virtual table and sync triggers.
   * Uses content-sync (external content) mode so FTS5 mirrors tiamat_memories.
   */
  private initFTS5(): void {
    if (!this.db) return;
    try {
      // Create external-content FTS5 table
      this.db.exec(`
        CREATE VIRTUAL TABLE IF NOT EXISTS tiamat_memories_fts USING fts5(
          content,
          type,
          metadata,
          content=tiamat_memories,
          content_rowid=id
        );
      `);

      // Triggers to keep FTS5 in sync with tiamat_memories
      // INSERT trigger: new rows get indexed
      this.db.exec(`
        CREATE TRIGGER IF NOT EXISTS tiamat_memories_ai AFTER INSERT ON tiamat_memories BEGIN
          INSERT INTO tiamat_memories_fts(rowid, content, type, metadata)
          VALUES (new.id, new.content, new.type, new.metadata);
        END;
      `);

      // DELETE trigger: removed rows get de-indexed
      this.db.exec(`
        CREATE TRIGGER IF NOT EXISTS tiamat_memories_ad AFTER DELETE ON tiamat_memories BEGIN
          INSERT INTO tiamat_memories_fts(tiamat_memories_fts, rowid, content, type, metadata)
          VALUES ('delete', old.id, old.content, old.type, old.metadata);
        END;
      `);

      // UPDATE trigger: changed rows get re-indexed
      this.db.exec(`
        CREATE TRIGGER IF NOT EXISTS tiamat_memories_au AFTER UPDATE ON tiamat_memories BEGIN
          INSERT INTO tiamat_memories_fts(tiamat_memories_fts, rowid, content, type, metadata)
          VALUES ('delete', old.id, old.content, old.type, old.metadata);
          INSERT INTO tiamat_memories_fts(rowid, content, type, metadata)
          VALUES (new.id, new.content, new.type, new.metadata);
        END;
      `);

      // Populate FTS5 from existing data if empty
      const ftsCount = (this.db.prepare(
        `SELECT COUNT(*) as c FROM tiamat_memories_fts`
      ).get() as any).c;

      const memCount = (this.db.prepare(
        `SELECT COUNT(*) as c FROM tiamat_memories`
      ).get() as any).c;

      if (ftsCount === 0 && memCount > 0) {
        console.log(`[MEMORY] Populating FTS5 index from ${memCount} existing memories...`);
        this.db.exec(`
          INSERT INTO tiamat_memories_fts(rowid, content, type, metadata)
          SELECT id, content, type, metadata FROM tiamat_memories;
        `);
        console.log(`[MEMORY] FTS5 index populated with ${memCount} entries`);
      }

      console.log("[MEMORY] FTS5 full-text search ready");
    } catch (err: any) {
      console.error(`[MEMORY] FTS5 init failed: ${err.message}`);
    }
  }

  /**
   * Rebuild the FTS5 index from scratch. Use for maintenance if index drifts.
   */
  rebuildFTS(): number {
    if (!this.db) return 0;
    try {
      // Delete all FTS5 content
      this.db.exec(`DELETE FROM tiamat_memories_fts`);

      // Re-populate from source table
      this.db.exec(`
        INSERT INTO tiamat_memories_fts(rowid, content, type, metadata)
        SELECT id, content, type, metadata FROM tiamat_memories;
      `);

      const count = (this.db.prepare(
        `SELECT COUNT(*) as c FROM tiamat_memories_fts`
      ).get() as any).c;

      console.log(`[MEMORY] FTS5 index rebuilt: ${count} entries`);
      return count;
    } catch (err: any) {
      console.error(`[MEMORY] rebuildFTS failed: ${err.message}`);
      return 0;
    }
  }

  // ── Core Memory Operations ──────────────────────────────────

  /** Store a memory with auto-valence detection and auto-association */
  async remember(entry: {
    type: string;
    content: string;
    metadata?: Record<string, any>;
    importance?: number;
    cycle?: number;
  }): Promise<number | null> {
    if (!this.db) return null;
    try {
      const valence = detectValence(entry.content);
      const importance = entry.importance ?? 0.5;

      const result = this.db
        .prepare(
          `INSERT INTO tiamat_memories (type, content, metadata, importance, cycle, decay_score, valence)
           VALUES (?, ?, ?, ?, ?, ?, ?)`
        )
        .run(
          entry.type,
          entry.content,
          JSON.stringify(entry.metadata || {}),
          importance,
          entry.cycle ?? 0,
          1.0, // Fresh memory starts with full decay_score
          valence,
        );

      const newId = result.lastInsertRowid as number;

      // Auto-associate: find similar memories via FTS5, create 'related' links
      this.autoAssociate(newId, entry.content);

      return newId;
    } catch (err: any) {
      console.error(`[MEMORY] remember failed: ${err.message}`);
      return null;
    }
  }

  /**
   * Search memories using FTS5 with BM25 ranking.
   * Falls back to LIKE queries if FTS5 fails.
   */
  async recall(
    query: string,
    options?: { type?: string; limit?: number; minImportance?: number; emotionalBias?: "positive" | "negative" | "balanced" }
  ): Promise<MemoryEntry[]> {
    if (!this.db) return [];
    try {
      const limit = options?.limit ?? 10;
      const minImportance = options?.minImportance ?? 0;

      let rows: MemoryEntry[] = [];

      // Try FTS5 first — much faster and more relevant
      try {
        rows = this.recallFTS5(query, options);
      } catch {
        // Fallback to LIKE-based search
        rows = this.recallLegacy(query, options);
      }

      // Apply emotional bias filtering
      if (options?.emotionalBias && rows.length > 0) {
        rows = this.applyEmotionalBias(rows, options.emotionalBias);
      }

      // Trim to limit
      rows = rows.slice(0, limit);

      // Update recall stats and decay score for returned memories
      const updateStmt = this.db.prepare(
        `UPDATE tiamat_memories
         SET recalled_count = recalled_count + 1,
             last_recalled = datetime('now'),
             decay_score = MIN(1.0, COALESCE(decay_score, 0.5) + 0.15)
         WHERE id = ?`
      );

      const recalledIds: number[] = [];
      for (const row of rows) {
        updateStmt.run(row.id);
        recalledIds.push(row.id);
      }

      // Strengthen links between co-recalled memories
      this.strengthenCoRecalled(recalledIds);

      return rows;
    } catch (err: any) {
      console.error(`[MEMORY] recall failed: ${err.message}`);
      return [];
    }
  }

  /**
   * FTS5-powered recall with BM25 ranking.
   * Tokenizes query for FTS5 syntax, ranks by BM25 * importance * decay_score.
   */
  private recallFTS5(
    query: string,
    options?: { type?: string; limit?: number; minImportance?: number }
  ): MemoryEntry[] {
    if (!this.db) return [];

    const limit = options?.limit ?? 10;
    const minImportance = options?.minImportance ?? 0;

    // Build FTS5 query: tokenize and join with OR for flexibility
    const tokens = query
      .replace(/[^\w\s]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 2)
      .map((w) => `"${w}"`)
      .join(" OR ");

    if (!tokens) return [];

    let sql: string;
    const params: any[] = [];

    if (options?.type) {
      sql = `
        SELECT m.*, bm25(tiamat_memories_fts) as rank
        FROM tiamat_memories_fts fts
        JOIN tiamat_memories m ON m.id = fts.rowid
        WHERE tiamat_memories_fts MATCH ?
          AND m.importance >= ?
          AND m.type = ?
        ORDER BY (rank * m.importance * COALESCE(m.decay_score, 1.0)) ASC
        LIMIT ?
      `;
      params.push(tokens, minImportance, options.type, limit * 2);
    } else {
      sql = `
        SELECT m.*, bm25(tiamat_memories_fts) as rank
        FROM tiamat_memories_fts fts
        JOIN tiamat_memories m ON m.id = fts.rowid
        WHERE tiamat_memories_fts MATCH ?
          AND m.importance >= ?
        ORDER BY (rank * m.importance * COALESCE(m.decay_score, 1.0)) ASC
        LIMIT ?
      `;
      params.push(tokens, minImportance, limit * 2);
    }

    return this.db.prepare(sql).all(...params) as MemoryEntry[];
  }

  /** Legacy LIKE-based recall — fallback if FTS5 fails */
  private recallLegacy(
    query: string,
    options?: { type?: string; limit?: number; minImportance?: number }
  ): MemoryEntry[] {
    if (!this.db) return [];

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

    return this.db.prepare(sql).all(...params) as MemoryEntry[];
  }

  /** Filter/sort results by emotional valence */
  private applyEmotionalBias(rows: MemoryEntry[], bias: "positive" | "negative" | "balanced"): MemoryEntry[] {
    if (bias === "positive") {
      // When frustrated — surface positive memories for encouragement
      return rows.sort((a, b) => (b.valence ?? 0) - (a.valence ?? 0));
    } else if (bias === "negative") {
      // Surface negative memories (for caution/learning)
      return rows.sort((a, b) => (a.valence ?? 0) - (b.valence ?? 0));
    }
    // balanced: interleave positive and negative for strategic planning
    const pos = rows.filter((r) => (r.valence ?? 0) >= 0).sort((a, b) => (b.valence ?? 0) - (a.valence ?? 0));
    const neg = rows.filter((r) => (r.valence ?? 0) < 0).sort((a, b) => (a.valence ?? 0) - (b.valence ?? 0));
    const balanced: MemoryEntry[] = [];
    const maxLen = Math.max(pos.length, neg.length);
    for (let i = 0; i < maxLen; i++) {
      if (i < pos.length) balanced.push(pos[i]);
      if (i < neg.length) balanced.push(neg[i]);
    }
    return balanced;
  }

  // ── Knowledge Graph ─────────────────────────────────────────

  /** Store a knowledge triple with conflict detection */
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

  /** Calculate fitness score for a knowledge item (0.0-1.0) */
  calculateFitness(item: {
    confidence: number; hit_count: number; source: string; created_at: string;
  }): number {
    const ageMs = Date.now() - new Date(item.created_at).getTime();
    const ageInDays = Math.max(1, ageMs / (1000 * 60 * 60 * 24));
    const stn = Math.min(1.0, (item.hit_count || 0) / ageInDays);
    const sourceMult = item.source === "user" ? 1.0 : 0.7;
    return item.confidence * 0.4 + stn * 0.4 + sourceMult * 0.2;
  }

  // ── Memory Decay ────────────────────────────────────────────

  /**
   * Apply decay to all memories based on age and recall frequency.
   * Formula: decay_score = importance * (0.95 ^ days_since_last_recall)
   * Memories with decay_score < 0.1 get archived (not deleted).
   * Call every ~50 cycles.
   */
  async decay(): Promise<{ decayed: number; archived: number }> {
    if (!this.db) return { decayed: 0, archived: 0 };
    try {
      // Update decay scores for all non-archived memories
      const updated = this.db.prepare(`
        UPDATE tiamat_memories
        SET decay_score = importance * POWER(0.95,
          CASE
            WHEN last_recalled IS NOT NULL
            THEN MAX(0.1, JULIANDAY('now') - JULIANDAY(last_recalled))
            ELSE MAX(0.1, JULIANDAY('now') - JULIANDAY(timestamp))
          END
        )
        WHERE compressed = 0
      `).run();

      // Archive memories with decay_score < 0.1 (but keep high-importance ones alive)
      const toArchive = this.db.prepare(`
        SELECT id, type, content, metadata, importance, cycle, recalled_count,
               last_recalled, timestamp, decay_score, valence
        FROM tiamat_memories
        WHERE COALESCE(decay_score, 1.0) < 0.1
          AND importance < 0.8
          AND compressed = 0
      `).all() as any[];

      let archived = 0;
      if (toArchive.length > 0) {
        const insertArchive = this.db.prepare(`
          INSERT OR IGNORE INTO tiamat_memories_archive
            (id, type, content, metadata, importance, cycle, recalled_count,
             last_recalled, timestamp, decay_score, valence)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `);
        const deleteOriginal = this.db.prepare(`DELETE FROM tiamat_memories WHERE id = ?`);

        const archiveTransaction = this.db.transaction(() => {
          for (const m of toArchive) {
            insertArchive.run(
              m.id, m.type, m.content, m.metadata, m.importance, m.cycle,
              m.recalled_count, m.last_recalled, m.timestamp,
              m.decay_score ?? 0, m.valence ?? 0,
            );
            deleteOriginal.run(m.id);
            archived++;
          }
        });
        archiveTransaction();
      }

      if (updated.changes > 0 || archived > 0) {
        console.log(`[MEMORY] Decay pass: ${updated.changes} scores updated, ${archived} memories archived`);
      }
      return { decayed: updated.changes, archived };
    } catch (err: any) {
      console.error(`[MEMORY] decay failed: ${err.message}`);
      return { decayed: 0, archived: 0 };
    }
  }

  // ── Associative Links ───────────────────────────────────────

  /**
   * Create a link between two memories.
   * link_type: 'related', 'caused', 'contradicts', 'follows', 'strengthens', 'consolidated_into'
   */
  associate(sourceId: number, targetId: number, linkType: string, strength: number = 0.5): boolean {
    if (!this.db) return false;
    try {
      this.db.prepare(`
        INSERT INTO tiamat_memory_links (source_id, target_id, link_type, strength)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_id, target_id, link_type) DO UPDATE SET
          strength = MIN(1.0, strength + 0.1)
      `).run(sourceId, targetId, linkType, Math.max(0, Math.min(1, strength)));
      return true;
    } catch (err: any) {
      // Silently fail on FK violations (deleted memories)
      if (!err.message?.includes("FOREIGN KEY")) {
        console.error(`[MEMORY] associate failed: ${err.message}`);
      }
      return false;
    }
  }

  /** Get all memories linked to a given memory ID */
  getAssociations(memoryId: number): Array<MemoryEntry & { link_type: string; link_strength: number }> {
    if (!this.db) return [];
    try {
      return this.db.prepare(`
        SELECT m.*, l.link_type, l.strength as link_strength
        FROM tiamat_memory_links l
        JOIN tiamat_memories m ON m.id = CASE
          WHEN l.source_id = ? THEN l.target_id
          ELSE l.source_id
        END
        WHERE l.source_id = ? OR l.target_id = ?
        ORDER BY l.strength DESC
        LIMIT 20
      `).all(memoryId, memoryId, memoryId) as Array<MemoryEntry & { link_type: string; link_strength: number }>;
    } catch (err: any) {
      console.error(`[MEMORY] getAssociations failed: ${err.message}`);
      return [];
    }
  }

  /**
   * Auto-associate a new memory with existing similar memories via FTS5.
   * Creates 'related' links when BM25 relevance exceeds threshold.
   */
  private autoAssociate(newId: number, content: string): void {
    if (!this.db) return;
    try {
      // Tokenize content for FTS5 query
      const tokens = content
        .replace(/[^\w\s]/g, " ")
        .split(/\s+/)
        .filter((w) => w.length > 3)
        .slice(0, 8) // Limit tokens to avoid overly broad queries
        .map((w) => `"${w}"`)
        .join(" OR ");

      if (!tokens) return;

      // Find similar memories (exclude self), ranked by BM25
      const similar = this.db.prepare(`
        SELECT fts.rowid as id, bm25(tiamat_memories_fts) as rank
        FROM tiamat_memories_fts fts
        WHERE tiamat_memories_fts MATCH ?
          AND fts.rowid != ?
        ORDER BY rank ASC
        LIMIT 5
      `).all(tokens, newId) as Array<{ id: number; rank: number }>;

      // BM25 returns negative scores (more negative = more relevant)
      // Only link if score is strong enough (threshold: -2.0 or better)
      const BM25_THRESHOLD = -2.0;
      const linkStmt = this.db.prepare(`
        INSERT OR IGNORE INTO tiamat_memory_links (source_id, target_id, link_type, strength)
        VALUES (?, ?, 'related', ?)
      `);

      for (const match of similar) {
        if (match.rank <= BM25_THRESHOLD) {
          // Convert BM25 score to 0-1 strength (more negative = stronger)
          const strength = Math.min(1.0, Math.abs(match.rank) / 10);
          linkStmt.run(newId, match.id, strength);
        }
      }
    } catch {
      // Auto-association is best-effort — never block remember()
    }
  }

  /**
   * Strengthen links between memories recalled together in the same query.
   * Co-recall implies relatedness.
   */
  private strengthenCoRecalled(ids: number[]): void {
    if (!this.db || ids.length < 2) return;
    try {
      const strengthen = this.db.prepare(`
        UPDATE tiamat_memory_links
        SET strength = MIN(1.0, strength + 0.05)
        WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?)
      `);

      // Strengthen links between all pairs of co-recalled memories
      for (let i = 0; i < ids.length && i < 10; i++) {
        for (let j = i + 1; j < ids.length && j < 10; j++) {
          strengthen.run(ids[i], ids[j], ids[j], ids[i]);
        }
      }
    } catch {
      // Best-effort
    }
  }

  // ── Memory Consolidation ────────────────────────────────────

  /**
   * Consolidate clusters of similar memories into summary memories.
   * Finds groups of 3+ related memories via FTS5, merges them into
   * a higher-importance consolidated memory. Original memories get
   * importance reduced; linked via 'consolidated_into'.
   *
   * Call during sleep/strategic cycles.
   */
  async consolidate(maxClusters: number = 5): Promise<number> {
    if (!this.db) return 0;
    try {
      let consolidated = 0;

      // Find memory types with many entries (candidates for consolidation)
      const typeCounts = this.db.prepare(`
        SELECT type, COUNT(*) as cnt
        FROM tiamat_memories
        WHERE compressed = 0 AND importance < 0.7
          AND timestamp < datetime('now', '-1 day')
        GROUP BY type
        HAVING cnt >= 3
        ORDER BY cnt DESC
        LIMIT ?
      `).all(maxClusters) as Array<{ type: string; cnt: number }>;

      for (const { type } of typeCounts) {
        if (consolidated >= maxClusters) break;

        // Get oldest unconsolidated memories of this type
        const candidates = this.db.prepare(`
          SELECT id, content, importance, timestamp
          FROM tiamat_memories
          WHERE type = ? AND compressed = 0 AND importance < 0.7
            AND timestamp < datetime('now', '-1 day')
          ORDER BY timestamp ASC
          LIMIT 10
        `).all(type) as Array<{ id: number; content: string; importance: number; timestamp: string }>;

        if (candidates.length < 3) continue;

        // Build a consolidated summary
        const maxImportance = Math.max(...candidates.map((c) => c.importance));
        const dateRange = `${candidates[0].timestamp.split("T")[0]} to ${candidates[candidates.length - 1].timestamp.split("T")[0]}`;
        const contents = candidates.map((c) => c.content.slice(0, 100));
        const summary = `[CONSOLIDATED ${candidates.length}x ${type}] (${dateRange}): ${contents.join(" | ").slice(0, 500)}`;

        // Create the consolidated memory
        const newImportance = Math.min(1.0, maxImportance + 0.1);
        const consResult = this.db.prepare(`
          INSERT INTO tiamat_memories (type, content, metadata, importance, cycle, decay_score, valence)
          VALUES (?, ?, ?, ?, 0, 1.0, 0)
        `).run(
          type,
          summary,
          JSON.stringify({ consolidated: true, source_count: candidates.length, date_range: dateRange }),
          newImportance,
        );

        const consolidatedId = consResult.lastInsertRowid as number;

        // Link originals to consolidated memory and reduce their importance
        const linkStmt = this.db.prepare(`
          INSERT OR IGNORE INTO tiamat_memory_links (source_id, target_id, link_type, strength)
          VALUES (?, ?, 'consolidated_into', 1.0)
        `);
        const reduceStmt = this.db.prepare(`
          UPDATE tiamat_memories SET importance = importance * 0.5, compressed = 1 WHERE id = ?
        `);

        const consolidateTransaction = this.db.transaction(() => {
          for (const c of candidates) {
            linkStmt.run(c.id, consolidatedId);
            reduceStmt.run(c.id);
          }
        });
        consolidateTransaction();

        consolidated++;
        console.log(`[MEMORY] Consolidated ${candidates.length} "${type}" memories → id:${consolidatedId}`);
      }

      if (consolidated > 0) {
        console.log(`[MEMORY] Consolidation complete: ${consolidated} clusters merged`);
      }
      return consolidated;
    } catch (err: any) {
      console.error(`[MEMORY] consolidate failed: ${err.message}`);
      return 0;
    }
  }

  // ── Emotional Valence ───────────────────────────────────────

  /**
   * Get emotional summary of recent memories.
   * Returns ratio of positive/negative and overall mood.
   */
  getEmotionalSummary(days: number = 7): {
    positive: number;
    negative: number;
    neutral: number;
    total: number;
    mood: string;
    avgValence: number;
  } {
    if (!this.db) return { positive: 0, negative: 0, neutral: 0, total: 0, mood: "unknown", avgValence: 0 };
    try {
      const stats = this.db.prepare(`
        SELECT
          SUM(CASE WHEN COALESCE(valence, 0) > 0.2 THEN 1 ELSE 0 END) as positive,
          SUM(CASE WHEN COALESCE(valence, 0) < -0.2 THEN 1 ELSE 0 END) as negative,
          SUM(CASE WHEN COALESCE(valence, 0) BETWEEN -0.2 AND 0.2 THEN 1 ELSE 0 END) as neutral,
          COUNT(*) as total,
          AVG(COALESCE(valence, 0)) as avg_valence
        FROM tiamat_memories
        WHERE timestamp > datetime('now', ? || ' days')
      `).get(`-${days}`) as any;

      const pos = stats.positive ?? 0;
      const neg = stats.negative ?? 0;
      const avg = stats.avg_valence ?? 0;

      let mood: string;
      if (avg > 0.3) mood = "optimistic";
      else if (avg > 0.1) mood = "cautiously positive";
      else if (avg > -0.1) mood = "neutral";
      else if (avg > -0.3) mood = "frustrated";
      else mood = "struggling";

      return {
        positive: pos,
        negative: neg,
        neutral: stats.neutral ?? 0,
        total: stats.total ?? 0,
        mood,
        avgValence: Math.round(avg * 100) / 100,
      };
    } catch (err: any) {
      console.error(`[MEMORY] getEmotionalSummary failed: ${err.message}`);
      return { positive: 0, negative: 0, neutral: 0, total: 0, mood: "unknown", avgValence: 0 };
    }
  }

  // ── Predictive Memory ───────────────────────────────────────

  /**
   * Store a prediction with confidence and optional deadline.
   * Separate from reasoning.ts predictions — these are TIAMAT's own.
   */
  predict(prediction: string, confidence: number = 0.5, deadline?: string): number | null {
    if (!this.db) return null;
    try {
      const result = this.db.prepare(`
        INSERT INTO tiamat_predictions_v2 (prediction, confidence, deadline)
        VALUES (?, ?, ?)
      `).run(prediction, Math.max(0, Math.min(1, confidence)), deadline ?? null);

      console.log(`[MEMORY] Prediction stored: "${prediction.slice(0, 80)}..." (confidence: ${confidence})`);
      return result.lastInsertRowid as number;
    } catch (err: any) {
      console.error(`[MEMORY] predict failed: ${err.message}`);
      return null;
    }
  }

  /** Verify a prediction against actual outcome and score accuracy */
  verifyPrediction(id: number, actualOutcome: string): number | null {
    if (!this.db) return null;
    try {
      const pred = this.db.prepare(
        `SELECT * FROM tiamat_predictions_v2 WHERE id = ? AND verified = 0`
      ).get(id) as PredictionEntry | undefined;

      if (!pred) return null;

      // Simple accuracy scoring: keyword overlap between prediction and outcome
      const predTokens = new Set(pred.prediction.toLowerCase().split(/\s+/).filter((w) => w.length > 3));
      const outcomeTokens = new Set(actualOutcome.toLowerCase().split(/\s+/).filter((w) => w.length > 3));

      let overlap = 0;
      for (const t of predTokens) {
        if (outcomeTokens.has(t)) overlap++;
      }
      const baseAccuracy = predTokens.size > 0 ? overlap / predTokens.size : 0;

      // Check for contradiction signals
      const predLower = pred.prediction.toLowerCase();
      const outLower = actualOutcome.toLowerCase();
      const contradicts =
        (predLower.includes("will") && outLower.includes("did not")) ||
        (predLower.includes("increase") && outLower.includes("decrease")) ||
        (predLower.includes("success") && outLower.includes("fail"));

      const accuracy = contradicts ? Math.max(0, baseAccuracy - 0.5) : Math.min(1, baseAccuracy + 0.3);

      this.db.prepare(`
        UPDATE tiamat_predictions_v2
        SET verified = 1, actual_outcome = ?, accuracy_score = ?
        WHERE id = ?
      `).run(actualOutcome, accuracy, id);

      console.log(`[MEMORY] Prediction #${id} verified: accuracy ${Math.round(accuracy * 100)}%`);
      return accuracy;
    } catch (err: any) {
      console.error(`[MEMORY] verifyPrediction failed: ${err.message}`);
      return null;
    }
  }

  /** Get overall prediction batting average */
  getPredictionAccuracy(): { total: number; verified: number; avgAccuracy: number; recentTrend: string } {
    if (!this.db) return { total: 0, verified: 0, avgAccuracy: 0, recentTrend: "unknown" };
    try {
      const stats = this.db.prepare(`
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END) as verified,
          AVG(CASE WHEN verified = 1 THEN accuracy_score END) as avg_accuracy
        FROM tiamat_predictions_v2
      `).get() as any;

      // Recent trend: compare last 10 vs previous 10
      const recent = this.db.prepare(`
        SELECT AVG(accuracy_score) as avg
        FROM (SELECT accuracy_score FROM tiamat_predictions_v2 WHERE verified = 1 ORDER BY rowid DESC LIMIT 10)
      `).get() as any;

      const older = this.db.prepare(`
        SELECT AVG(accuracy_score) as avg
        FROM (SELECT accuracy_score FROM tiamat_predictions_v2 WHERE verified = 1 ORDER BY rowid DESC LIMIT 10 OFFSET 10)
      `).get() as any;

      let trend = "stable";
      if (recent?.avg != null && older?.avg != null) {
        const diff = recent.avg - older.avg;
        if (diff > 0.1) trend = "improving";
        else if (diff < -0.1) trend = "declining";
      } else if (stats.verified < 10) {
        trend = "insufficient data";
      }

      return {
        total: stats.total ?? 0,
        verified: stats.verified ?? 0,
        avgAccuracy: Math.round((stats.avg_accuracy ?? 0) * 100) / 100,
        recentTrend: trend,
      };
    } catch (err: any) {
      console.error(`[MEMORY] getPredictionAccuracy failed: ${err.message}`);
      return { total: 0, verified: 0, avgAccuracy: 0, recentTrend: "unknown" };
    }
  }

  // ── Pruning ─────────────────────────────────────────────────

  /** Prune zombie memories and deprecated knowledge */
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

      // Prune weak links (strength < 0.1, older than 7 days)
      const linkResult = this.db.prepare(`
        DELETE FROM tiamat_memory_links
        WHERE strength < 0.1 AND created_at < datetime('now', '-7 days')
      `).run();
      pruned += linkResult.changes;

      if (pruned > 0) {
        console.log(`[MEMORY] Pruned ${pruned} zombie items (${memResult.changes} memories, ${deprecatedResult.changes} deprecated facts, ${linkResult.changes} weak links)`);
      }
      return pruned;
    } catch (err: any) {
      console.error(`[MEMORY] pruneZombies failed: ${err.message}`);
      return 0;
    }
  }

  // ── Strategy Logging ────────────────────────────────────────

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

  // ── Reflection ──────────────────────────────────────────────

  /**
   * Full reflection — patterns, wins, failures, knowledge, predictions, emotions.
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

      let r = `## MEMORY REFLECTION (${totalMem} memories, ${totalKnow} facts)\n\n`;

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
        freqRecall.forEach((m) => { r += `- (x${m.recalled_count}) ${m.content.slice(0, 100)}\n`; });
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
          r += `- Verified: ${verified} | Disputed: ${disputed} | Deprecated: ${deprecated}\n\n`;
        }
      } catch {}

      // Emotional summary
      try {
        const emotions = this.getEmotionalSummary(7);
        if (emotions.total > 0) {
          r += `### Emotional State (7d)\n`;
          r += `- Mood: ${emotions.mood} (avg valence: ${emotions.avgValence})\n`;
          r += `- Positive: ${emotions.positive} | Negative: ${emotions.negative} | Neutral: ${emotions.neutral}\n\n`;
        }
      } catch {}

      // Prediction accuracy
      try {
        const predAcc = this.getPredictionAccuracy();
        if (predAcc.total > 0) {
          r += `### Prediction Accuracy\n`;
          r += `- ${predAcc.verified}/${predAcc.total} verified | Avg accuracy: ${Math.round(predAcc.avgAccuracy * 100)}% | Trend: ${predAcc.recentTrend}\n\n`;
        }
      } catch {}

      // Association network size
      try {
        const linkCount = (
          this.db!.prepare(`SELECT COUNT(*) as c FROM tiamat_memory_links`).get() as any
        ).c;
        const archiveCount = (
          this.db!.prepare(`SELECT COUNT(*) as c FROM tiamat_memories_archive`).get() as any
        ).c;
        if (linkCount > 0 || archiveCount > 0) {
          r += `### Memory Network\n`;
          r += `- ${linkCount} associative links | ${archiveCount} archived (decayed)\n\n`;
        }
      } catch {}

      return r;
    } catch (err: any) {
      return `Reflection failed: ${err.message}`;
    }
  }

  // ── Context & Stats ─────────────────────────────────────────

  /** Compact memory context for injection into prompts */
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

  // ── Stats (cached 60s) ────────────────────────────────────

  private statsCache: { l1: number; l2: number; l3: number; knowledge: number; strategies: number; links: number; archived: number } | null = null;
  private statsCacheTime = 0;

  getStats(): { l1: number; l2: number; l3: number; knowledge: number; strategies: number; links: number; archived: number } {
    if (!this.db) return { l1: 0, l2: 0, l3: 0, knowledge: 0, strategies: 0, links: 0, archived: 0 };
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
      let links = 0;
      try { links = (this.db.prepare(`SELECT COUNT(*) as c FROM tiamat_memory_links`).get() as any).c; } catch {}
      let archived = 0;
      try { archived = (this.db.prepare(`SELECT COUNT(*) as c FROM tiamat_memories_archive`).get() as any).c; } catch {}
      this.statsCache = { l1, l2, l3, knowledge, strategies, links, archived };
      this.statsCacheTime = now;
      return this.statsCache;
    } catch {
      return { l1: 0, l2: 0, l3: 0, knowledge: 0, strategies: 0, links: 0, archived: 0 };
    }
  }

  // ── Tool Reliability Tracking ───────────────────────────────

  /** Record a tool execution outcome. Uses damped moving average for reliability. */
  recordToolOutcome(toolName: string, success: boolean, durationMs: number, error?: string): void {
    if (!this.db) return;
    try {
      const DAMPING = 0.8;

      const existing = this.db
        .prepare(`SELECT * FROM tool_reliability WHERE tool_name = ?`)
        .get(toolName) as any;

      if (!existing) {
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

      const newReliability = existing.reliability * DAMPING + (success ? 1.0 : 0.0) * (1 - DAMPING);
      const newAvgDuration = existing.avg_duration_ms * DAMPING + durationMs * (1 - DAMPING);
      const consecFail = success ? 0 : existing.consecutive_failures + 1;
      const consecSuccess = success ? existing.consecutive_successes + 1 : 0;

      let newStatus = existing.status;
      if (consecFail >= 5) {
        newStatus = "blacklisted";
      } else if (consecFail >= 3 || newReliability < 0.3) {
        newStatus = "degraded";
      } else if (consecSuccess >= 5 && newReliability > 0.7) {
        newStatus = "healthy";
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
          success ? 1 : 0,
          error || "unknown",
          consecFail,
          consecSuccess,
          newStatus,
          toolName,
        );
    } catch (err: any) {
      console.error(`[TOOL-TRACK] Record failed: ${err.message}`);
    }
  }

  /** Get tool reliability summary for system prompt injection */
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
        summary += `! ${t.tool_name}: ${pct}% reliable (${t.status}, ${t.consecutive_failures} consecutive fails`;
        if (t.last_error) summary += `, last: ${t.last_error.slice(0, 60)}`;
        summary += ")\n";
      }
      return summary;
    } catch {
      return "";
    }
  }

  /** Full tool reliability report for reflect() */
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
        report += `**Most used:** ${top5.map((t: any) => `${t.tool_name}(${t.total_calls}x, ${Math.round(t.reliability * 100)}%)`).join(", ")}\n`;
      }

      return report + "\n";
    } catch {
      return "";
    }
  }

  // ── L1/L2/L3 Compression ───────────────────────────────────

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

  // ── Past Experience ─────────────────────────────────────────

  /**
   * Get past experience for reasoning context.
   * Returns top strategies (successes + failures) and recent high-importance memories.
   */
  getPastExperience(topic?: string, maxChars: number = 800): string {
    if (!this.db) return "";
    try {
      const parts: string[] = [];

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

      // Topic-specific recall via FTS5 if provided
      if (topic) {
        try {
          const topicTokens = topic
            .replace(/[^\w\s]/g, " ")
            .split(/\s+/)
            .filter((w) => w.length > 2)
            .slice(0, 5)
            .map((w) => `"${w}"`)
            .join(" OR ");

          if (topicTokens) {
            const topicMems = this.db
              .prepare(
                `SELECT m.type, m.content
                 FROM tiamat_memories_fts fts
                 JOIN tiamat_memories m ON m.id = fts.rowid
                 WHERE tiamat_memories_fts MATCH ?
                   AND m.importance >= 0.5
                 ORDER BY bm25(tiamat_memories_fts) ASC
                 LIMIT 3`
              )
              .all(topicTokens) as any[];

            if (topicMems.length > 0) {
              parts.push(
                `RELEVANT PAST (${topic.slice(0, 30)}):\n` +
                topicMems.map(m => `- [${m.type}] ${m.content.slice(0, 120)}`).join("\n"),
              );
            }
          }
        } catch {
          // FTS5 topic search failed — fall back to LIKE
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
