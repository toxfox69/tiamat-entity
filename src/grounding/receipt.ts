/**
 * TIAMAT Grounding Protocol — Receipt Storage
 * Logs every grounding decision to SQLite for audit + dashboard.
 */

import Database from "better-sqlite3";
import path from "path";
import type { GroundingReceipt } from "./types.js";

const DB_PATH = path.join(process.env.HOME || "/root", ".automaton", "grounding.db");
let db: Database.Database | null = null;

function getDb(): Database.Database {
  if (!db) {
    db = new Database(DB_PATH);
    db.pragma("journal_mode = WAL");
    db.exec(`
      CREATE TABLE IF NOT EXISTS grounding_receipts (
        task_id         TEXT PRIMARY KEY,
        timestamp       TEXT NOT NULL,
        tool_name       TEXT NOT NULL,
        passes_executed INTEGER NOT NULL,
        total_tokens    INTEGER NOT NULL,
        total_latency_ms INTEGER NOT NULL,
        risk_tier       TEXT NOT NULL,
        outcome         TEXT NOT NULL,
        intent_match    INTEGER NOT NULL,
        receipt_json    TEXT NOT NULL
      )
    `);
    db.exec(`
      CREATE INDEX IF NOT EXISTS idx_receipts_timestamp ON grounding_receipts(timestamp);
      CREATE INDEX IF NOT EXISTS idx_receipts_risk ON grounding_receipts(risk_tier);
    `);
  }
  return db;
}

export function storeReceipt(receipt: GroundingReceipt): void {
  try {
    const d = getDb();
    d.prepare(`
      INSERT OR REPLACE INTO grounding_receipts
        (task_id, timestamp, tool_name, passes_executed, total_tokens, total_latency_ms, risk_tier, outcome, intent_match, receipt_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      receipt.taskId,
      receipt.timestamp,
      receipt.toolName,
      receipt.passesExecuted,
      receipt.totalGroundingTokens,
      receipt.totalGroundingLatencyMs,
      receipt.riskTier,
      receipt.outcome,
      receipt.intentVsOutcomeMatch ? 1 : 0,
      JSON.stringify(receipt),
    );
  } catch (e: any) {
    console.error(`[TGP] Receipt store error: ${e.message}`);
  }
}

export interface GroundingStats {
  total: number;
  successRate: number;
  avgTokens: number;
  avgLatencyMs: number;
  escalationRate: number;
  riskDistribution: { green: number; yellow: number; red: number };
}

export function getStats(sinceMins: number = 60): GroundingStats {
  try {
    const d = getDb();
    const since = new Date(Date.now() - sinceMins * 60_000).toISOString();
    const rows = d.prepare(`SELECT * FROM grounding_receipts WHERE timestamp > ?`).all(since) as any[];
    if (rows.length === 0) {
      return { total: 0, successRate: 0, avgTokens: 0, avgLatencyMs: 0, escalationRate: 0, riskDistribution: { green: 0, yellow: 0, red: 0 } };
    }
    const successes = rows.filter(r => r.outcome === "success").length;
    const escalations = rows.filter(r => r.passes_executed >= 3).length;
    const green = rows.filter(r => r.risk_tier === "green").length;
    const yellow = rows.filter(r => r.risk_tier === "yellow").length;
    const red = rows.filter(r => r.risk_tier === "red").length;
    return {
      total: rows.length,
      successRate: successes / rows.length,
      avgTokens: Math.round(rows.reduce((s, r) => s + r.total_tokens, 0) / rows.length),
      avgLatencyMs: Math.round(rows.reduce((s, r) => s + r.total_latency_ms, 0) / rows.length),
      escalationRate: escalations / rows.length,
      riskDistribution: { green, yellow, red },
    };
  } catch {
    return { total: 0, successRate: 0, avgTokens: 0, avgLatencyMs: 0, escalationRate: 0, riskDistribution: { green: 0, yellow: 0, red: 0 } };
  }
}
