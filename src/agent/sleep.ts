/**
 * TIAMAT Consolidation Sleep System
 *
 * Moves all memory compression into dedicated "sleep" cycles that replace
 * a normal agent cycle — zero Anthropic cost, exclusive Groq access.
 *
 * 5 Phases:
 *   1. COMPRESS — L1→L2 and L2→L3 via Groq
 *   2. PRUNE — delete old compressed memories, dedup L3
 *   3. DEFRAGMENT — VACUUM the database
 *   4. GENOME COMPILE — distill core_knowledge into genome.json
 *   5. REPORT — log stats to sleep_log table
 */

import Database from "better-sqlite3";
import fs from "fs";
import path from "path";
import { compressL1toL2, compressL2toL3, ensureSchema } from "./memory-compress.js";
import { tokenize, jaccardSimilarity } from "./memory-compress.js";

const DB_PATH = path.join(process.env.HOME || "/root", ".automaton", "memory.db");
const GENOME_PATH = path.join(process.env.HOME || "/root", ".automaton", "genome.json");
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const GROQ_MODEL = "llama-3.3-70b-versatile";

const SLEEP_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes hard cap

// ── Types ────────────────────────────────────────────────────

export interface SleepReport {
  l1Compressed: number;
  l2Compressed: number;
  l3Extracted: number;
  bytesFreed: number;
  durationMs: number;
  genomeVersion: string;
}

// ── shouldSleep ──────────────────────────────────────────────

export function shouldSleep(
  lastSleepTime: number,
  _currentCycle: number,
  idleStreak: number,
  force?: boolean,
): boolean {
  if (force === true) return true;

  // Minimum 30-minute cooldown between ALL consolidation triggers
  const timeSinceLastSleep = Date.now() - lastSleepTime;
  if (lastSleepTime > 0 && timeSinceLastSleep < 30 * 60 * 1000) return false;

  // 6-hour timer (only if we've slept at least once — skip on fresh DB)
  if (lastSleepTime > 0 && timeSinceLastSleep >= 6 * 60 * 60 * 1000) return true;

  // Extended idle
  if (idleStreak > 20) return true;

  // High uncompressed L1 count
  try {
    const db = new Database(DB_PATH, { readonly: true });
    try {
      const row = db.prepare(
        `SELECT COUNT(*) as c FROM tiamat_memories WHERE compressed = 0`
      ).get() as { c: number } | undefined;
      if (row && row.c > 500) return true;  // Raised from 200 — 206 recent memories were causing infinite loop
    } finally {
      db.close();
    }
  } catch {
    // DB not available — don't trigger sleep on error
  }

  return false;
}

// ── executeSleep — 5 phases ──────────────────────────────────

export async function executeSleep(currentCycle: number): Promise<SleepReport> {
  const startTime = Date.now();
  const deadline = startTime + SLEEP_TIMEOUT_MS;

  const report: SleepReport = {
    l1Compressed: 0,
    l2Compressed: 0,
    l3Extracted: 0,
    bytesFreed: 0,
    durationMs: 0,
    genomeVersion: "0",
  };

  const db = new Database(DB_PATH);
  db.pragma("journal_mode = WAL");
  ensureSchema(db);

  // Ensure sleep_log table exists
  db.exec(`
    CREATE TABLE IF NOT EXISTS sleep_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      l1_compressed INTEGER DEFAULT 0,
      l2_compressed INTEGER DEFAULT 0,
      l3_extracted INTEGER DEFAULT 0,
      bytes_freed INTEGER DEFAULT 0,
      duration_ms INTEGER DEFAULT 0
    );
  `);

  const startedAt = new Date().toISOString();

  try {
    // ── Phase 1: COMPRESS (5 min budget) ──
    if (Date.now() < deadline) {
      console.log("[SLEEP:P1] COMPRESS — starting L1→L2...");
      try {
        report.l1Compressed = await withTimeout(
          compressL1toL2(db, currentCycle),
          Math.min(3 * 60 * 1000, deadline - Date.now()),
        );
        console.log(`[SLEEP:P1] L1→L2: ${report.l1Compressed} clusters compressed`);
      } catch (e: any) {
        console.log(`[SLEEP:P1] L1→L2 error: ${e.message?.slice(0, 150)}`);
      }
    }

    if (Date.now() < deadline) {
      console.log("[SLEEP:P1] COMPRESS — starting L2→L3...");
      try {
        report.l3Extracted = await withTimeout(
          compressL2toL3(db),
          Math.min(2 * 60 * 1000, deadline - Date.now()),
        );
        console.log(`[SLEEP:P1] L2→L3: ${report.l3Extracted} facts extracted`);
      } catch (e: any) {
        console.log(`[SLEEP:P1] L2→L3 error: ${e.message?.slice(0, 150)}`);
      }
    }

    // ── Phase 2: PRUNE (30s budget) ──
    if (Date.now() < deadline) {
      console.log("[SLEEP:P2] PRUNE — deleting old compressed memories...");
      try {
        // Delete old compressed L1 (14 days)
        const pruneL1 = db.prepare(
          `DELETE FROM tiamat_memories WHERE compressed = 1 AND timestamp < datetime('now', '-14 days')`
        );
        const l1Pruned = pruneL1.run();
        console.log(`[SLEEP:P2] Pruned ${l1Pruned.changes} old L1 memories`);

        // Delete old L2 (30 days)
        const pruneL2 = db.prepare(
          `DELETE FROM compressed_memories WHERE created_at < datetime('now', '-30 days')`
        );
        const l2Pruned = pruneL2.run();
        report.l2Compressed = l2Pruned.changes;
        console.log(`[SLEEP:P2] Pruned ${l2Pruned.changes} old L2 memories`);

        // L3 dedup: find pairs with >0.92 Jaccard similarity, merge
        const l3Rows = db.prepare(
          `SELECT id, fact, confidence, evidence_count, category FROM core_knowledge ORDER BY confidence DESC`
        ).all() as Array<{ id: number; fact: string; confidence: number; evidence_count: number; category: string }>;

        const toDelete: number[] = [];
        for (let i = 0; i < l3Rows.length; i++) {
          if (toDelete.includes(l3Rows[i].id)) continue;
          const tokensA = tokenize(l3Rows[i].fact);
          for (let j = i + 1; j < l3Rows.length; j++) {
            if (toDelete.includes(l3Rows[j].id)) continue;
            const tokensB = tokenize(l3Rows[j].fact);
            if (jaccardSimilarity(tokensA, tokensB) > 0.92) {
              // Keep higher confidence row, absorb evidence_count
              const keeper = l3Rows[i].confidence >= l3Rows[j].confidence ? l3Rows[i] : l3Rows[j];
              const loser = keeper === l3Rows[i] ? l3Rows[j] : l3Rows[i];
              db.prepare(
                `UPDATE core_knowledge SET evidence_count = evidence_count + ? WHERE id = ?`
              ).run(loser.evidence_count, keeper.id);
              toDelete.push(loser.id);
            }
          }
        }
        if (toDelete.length > 0) {
          const placeholders = toDelete.map(() => "?").join(",");
          db.prepare(`DELETE FROM core_knowledge WHERE id IN (${placeholders})`).run(...toDelete);
          console.log(`[SLEEP:P2] Deduped ${toDelete.length} L3 facts`);
        }
      } catch (e: any) {
        console.log(`[SLEEP:P2] Prune error: ${e.message?.slice(0, 150)}`);
      }
    }

    // ── Phase 3: DEFRAGMENT (10s budget) ──
    if (Date.now() < deadline) {
      console.log("[SLEEP:P3] DEFRAGMENT — vacuuming database...");
      try {
        const sizeBefore = fs.statSync(DB_PATH).size;
        db.exec("VACUUM");
        const sizeAfter = fs.statSync(DB_PATH).size;
        report.bytesFreed = sizeBefore - sizeAfter;
        console.log(`[SLEEP:P3] VACUUM: ${sizeBefore} → ${sizeAfter} (freed ${report.bytesFreed} bytes)`);
      } catch (e: any) {
        console.log(`[SLEEP:P3] Defrag error: ${e.message?.slice(0, 150)}`);
      }
    }

    // ── Phase 4: GENOME COMPILE (60s budget) ──
    if (Date.now() < deadline) {
      console.log("[SLEEP:P4] GENOME COMPILE — building genome.json...");
      try {
        const l3All = db.prepare(
          `SELECT fact, confidence, evidence_count, category FROM core_knowledge ORDER BY confidence DESC`
        ).all() as Array<{ fact: string; confidence: number; evidence_count: number; category: string }>;

        // Group by category → traits
        const traits: Record<string, string[]> = {};
        for (const row of l3All) {
          if (!traits[row.category]) traits[row.category] = [];
          traits[row.category].push(row.fact);
        }

        // High confidence → instincts
        const instincts = l3All
          .filter(r => r.confidence > 0.8)
          .map(r => r.fact);

        // Behavioral failures → antibodies
        const failureKeywords = ["fail", "error", "wrong", "broken", "stuck", "crash", "reject", "block"];
        const antibodies = l3All
          .filter(r =>
            r.category === "behavioral" &&
            (r.confidence < 0.5 || failureKeywords.some(kw => r.fact.toLowerCase().includes(kw)))
          )
          .map(r => r.fact);

        // Get sleep count for version
        const sleepCount = (db.prepare(`SELECT COUNT(*) as c FROM sleep_log`).get() as { c: number }).c + 1;

        // Optional Groq call to distill instincts into imperative rules
        let distilledInstincts = instincts;
        if (instincts.length > 0 && process.env.GROQ_API_KEY) {
          try {
            const distilled = await withTimeout(
              groqDistillInstincts(instincts),
              Math.min(30_000, deadline - Date.now()),
            );
            if (distilled && distilled.length > 0) {
              distilledInstincts = distilled;
            }
          } catch (e: any) {
            console.log(`[SLEEP:P4] Groq distill error: ${e.message?.slice(0, 100)}`);
          }
        }

        const genome = {
          version: String(sleepCount),
          compiled_at: new Date().toISOString(),
          traits,
          instincts: distilledInstincts,
          antibodies,
        };

        fs.writeFileSync(GENOME_PATH, JSON.stringify(genome, null, 2));
        report.genomeVersion = String(sleepCount);
        console.log(`[SLEEP:P4] Genome v${sleepCount} written (${instincts.length} instincts, ${antibodies.length} antibodies)`);
      } catch (e: any) {
        console.log(`[SLEEP:P4] Genome error: ${e.message?.slice(0, 150)}`);
      }
    }

    // ── Phase 5: REPORT ──
    report.durationMs = Date.now() - startTime;
    try {
      db.prepare(
        `INSERT INTO sleep_log (started_at, ended_at, l1_compressed, l2_compressed, l3_extracted, bytes_freed, duration_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?)`
      ).run(
        startedAt,
        new Date().toISOString(),
        report.l1Compressed,
        report.l2Compressed,
        report.l3Extracted,
        report.bytesFreed,
        report.durationMs,
      );
      console.log(`[SLEEP:P5] Report logged. Total duration: ${report.durationMs}ms`);
    } catch (e: any) {
      console.log(`[SLEEP:P5] Report error: ${e.message?.slice(0, 100)}`);
    }
  } finally {
    try { db.close(); } catch {}
  }

  return report;
}

// ── Helpers ──────────────────────────────────────────────────

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms);
    promise
      .then(val => { clearTimeout(timer); resolve(val); })
      .catch(err => { clearTimeout(timer); reject(err); });
  });
}

async function groqDistillInstincts(instincts: string[]): Promise<string[]> {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) return instincts;

  const joined = instincts.map((s, i) => `${i + 1}. ${s}`).join("\n");
  const prompt = `Distill these learned facts into 3-7 imperative rules (commands to yourself). Each rule should be actionable and concise (max 80 chars). Output ONLY a JSON array of strings.\n\n${joined}`;

  const resp = await fetch(GROQ_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: GROQ_MODEL,
      messages: [
        { role: "system", content: "Output ONLY a valid JSON array of imperative rule strings. No explanation." },
        { role: "user", content: prompt },
      ],
      max_tokens: 300,
      temperature: 0.2,
    }),
  });

  if (!resp.ok) return instincts;

  const data = (await resp.json()) as any;
  let text = data.choices?.[0]?.message?.content?.trim() || "[]";
  text = text.replace(/```json?\s*/g, "").replace(/```\s*$/g, "");

  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed.map((s: any) => String(s).slice(0, 80));
    }
  } catch {}

  return instincts;
}
