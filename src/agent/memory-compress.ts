/**
 * TIAMAT 3-Tier Memory Compression
 *
 * L1: Raw memories (tiamat_memories) — every observation, stored per-cycle
 * L2: Compressed memories (compressed_memories) — clustered summaries
 * L3: Core knowledge (core_knowledge) — distilled facts with confidence
 *
 * L1 → L2: Every strategic cycle (every ~45 turns). Cluster old L1 memories
 *           by keyword similarity, compress each cluster via Groq.
 * L2 → L3: Every 100th strategic cycle. Extract repeated patterns from L2,
 *           store as high-confidence facts.
 *
 * smartRecall: L3 first (cheap, high signal) → L2 → L1 only if budget remains.
 */

import Database from "better-sqlite3";
import path from "path";

const DB_PATH = path.join(process.env.HOME || "/root", ".automaton", "memory.db");
// Provider cascade for compression — Groq first, then Cerebras, then Gemini
// Avoids blocking the strategic burst when cooldown scripts exhaust Groq's rate limit
const PROVIDERS = [
  {
    name: "groq",
    url: "https://api.groq.com/openai/v1/chat/completions",
    model: "llama-3.3-70b-versatile",
    keyEnv: "GROQ_API_KEY",
  },
  {
    name: "cerebras",
    url: "https://api.cerebras.ai/v1/chat/completions",
    model: "llama3.1-8b",
    keyEnv: "CEREBRAS_API_KEY",
  },
  {
    name: "gemini",
    url: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    model: "gemini-2.0-flash",
    keyEnv: "GEMINI_API_KEY",
  },
];

// ── Schema Setup ──────────────────────────────────────────────

export function ensureSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS compressed_memories (
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      summary           TEXT    NOT NULL,
      source_memory_ids TEXT    NOT NULL DEFAULT '[]',
      created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
      cycle_range       TEXT    DEFAULT '',
      topic             TEXT    DEFAULT ''
    );
  `);

  db.exec(`
    CREATE TABLE IF NOT EXISTS core_knowledge (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      fact            TEXT    NOT NULL,
      confidence      REAL    NOT NULL DEFAULT 0.5,
      evidence_count  INTEGER NOT NULL DEFAULT 1,
      first_seen      TEXT    NOT NULL DEFAULT (datetime('now')),
      last_confirmed  TEXT    NOT NULL DEFAULT (datetime('now')),
      category        TEXT    NOT NULL DEFAULT 'observation'
        CHECK(category IN ('revenue','social','technical','strategic','behavioral'))
    );
  `);

  // Add compressed column to existing memories table if missing
  try {
    db.exec(`ALTER TABLE tiamat_memories ADD COLUMN compressed INTEGER DEFAULT 0`);
  } catch {
    // Column already exists — ignore
  }

  // Add l3_processed column to compressed_memories if missing
  try {
    db.exec(`ALTER TABLE compressed_memories ADD COLUMN l3_processed INTEGER DEFAULT 0`);
  } catch {
    // Column already exists — ignore
  }
}

// ── Compression Call (cascading providers) ────────────────────

async function llmCompress(texts: string[]): Promise<string | null> {
  const joined = texts.map((t, i) => `${i + 1}. ${t}`).join("\n");
  const prompt =
    `Compress these observations into one factual summary, preserving numbers, dates, and causal relationships. Max 200 chars.\n\n${joined}`;

  for (const provider of PROVIDERS) {
    const apiKey = process.env[provider.keyEnv];
    if (!apiKey) continue;

    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const resp = await fetch(provider.url, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${apiKey}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: provider.model,
            messages: [
              {
                role: "system",
                content:
                  "You compress multiple observations into one dense factual summary. Preserve specifics: numbers, dates, names, causation. Output ONLY the summary, nothing else. Max 200 characters.",
              },
              { role: "user", content: prompt },
            ],
            max_tokens: 100,
            temperature: 0.1,
          }),
        });
        if (resp.status === 429) {
          if (attempt === 0) {
            await new Promise((r) => setTimeout(r, 2000));
            continue;
          }
          break; // Move to next provider
        }
        if (!resp.ok) {
          // silenced: provider cascade fallthrough
          break;
        }
        const data = (await resp.json()) as any;
        return data.choices?.[0]?.message?.content?.trim().slice(0, 250) || null;
      } catch (e: any) {
        // silenced: provider cascade fallthrough
        break;
      }
    }
  }
  return null;
}

async function llmExtractFacts(summaries: string[]): Promise<Array<{fact: string; category: string; confidence: number}>> {
  const allFacts: Array<{fact: string; category: string; confidence: number}> = [];
  const BATCH_SIZE = 10;
  let consecutiveFailures = 0;

  for (let i = 0; i < summaries.length; i += BATCH_SIZE) {
    // If 2+ consecutive batches failed (all providers 429), bail out
    if (consecutiveFailures >= 2) {
      console.log(`[COMPRESS] All providers exhausted after ${consecutiveFailures} failed batches — aborting remaining`);
      break;
    }

    const batch = summaries.slice(i, i + BATCH_SIZE);
    const joined = batch.map((s, j) => `${j + 1}. ${s}`).join("\n");
    const prompt =
      `Extract 1-3 core factual patterns from these compressed memories. Skip trivial observations (X is running, X exists, tool was used). Only extract facts with diagnostic, causal, or strategic value.\n\nFor each, output a JSON array of objects with keys: fact (string, max 150 chars), category (one of: revenue, social, technical, strategic, behavioral), confidence (0.0-1.0).\n\nScore facts as follows:\n- Observable system states (X is running, Y exists): 0.3-0.4\n- Tool capabilities (TIAMAT can do X): 0.2-0.3\n- Behavioral patterns with specific evidence: 0.7-0.8\n- Failure root causes with diagnostic detail: 0.8-0.9\n- Quantified performance insights (cost, rate, count): 0.85-0.95\nNever score a fact above 0.95. If uncertain, score lower.\n\n${joined}\n\nOutput ONLY the JSON array, nothing else.`;

    let batchDone = false;
    for (const provider of PROVIDERS) {
      if (batchDone) break;
      const apiKey = process.env[provider.keyEnv];
      if (!apiKey) continue;

      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const resp = await fetch(provider.url, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${apiKey}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              model: provider.model,
              messages: [
                { role: "system", content: "Extract only high-value factual patterns — failures, root causes, quantified insights, strategic decisions. Skip trivial status observations and tool usage descriptions. Output ONLY valid JSON array." },
                { role: "user", content: prompt },
              ],
              max_tokens: 400,
              temperature: 0.1,
            }),
          });

          if (resp.status === 429) {
            if (attempt === 0) {
              await new Promise((r) => setTimeout(r, 2000));
              continue;
            }
            break;
          }
          if (!resp.ok) {
            break;
          }

          const data = (await resp.json()) as any;
          let text = data.choices?.[0]?.message?.content?.trim() || "[]";
          text = text.replace(/```json?\s*/g, "").replace(/```\s*$/g, "");
          const parsed = JSON.parse(text);
          if (Array.isArray(parsed)) {
            for (const f of parsed) {
              if (f.fact && f.category && typeof f.confidence === "number") {
                allFacts.push({
                  fact: String(f.fact).slice(0, 150),
                  category: ["revenue", "social", "technical", "strategic", "behavioral"].includes(f.category)
                    ? f.category
                    : "behavioral",
                  confidence: Math.max(0, Math.min(0.95, f.confidence)),
                });
              }
            }
          }
          batchDone = true;
          break;
        } catch (e: any) {
          break;
        }
      }
    }

    if (batchDone) {
      consecutiveFailures = 0;
    } else {
      consecutiveFailures++;
    }

    // Small delay between batches
    if (i + BATCH_SIZE < summaries.length) {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  return allFacts;
}

// ── Keyword-Based Clustering ──────────────────────────────────
// No embeddings available — cluster by keyword overlap (Jaccard on tokens)

export function tokenize(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 2)
  );
}

export function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 0;
  let intersection = 0;
  for (const w of a) {
    if (b.has(w)) intersection++;
  }
  return intersection / (a.size + b.size - intersection);
}

interface MemRow {
  id: number;
  type: string;
  content: string;
  importance: number;
  cycle: number;
  timestamp: string;
}

function clusterMemories(memories: MemRow[], threshold = 0.25): MemRow[][] {
  const clusters: MemRow[][] = [];
  const assigned = new Set<number>();
  const tokenSets = memories.map((m) => tokenize(m.content));

  for (let i = 0; i < memories.length; i++) {
    if (assigned.has(i)) continue;
    const cluster = [memories[i]];
    assigned.add(i);

    for (let j = i + 1; j < memories.length; j++) {
      if (assigned.has(j)) continue;
      const sim = jaccardSimilarity(tokenSets[i], tokenSets[j]);
      if (sim >= threshold) {
        cluster.push(memories[j]);
        assigned.add(j);
      }
    }
    clusters.push(cluster);
  }

  return clusters;
}

// ── L1 → L2 Compression ──────────────────────────────────────

export async function compressL1toL2(db: Database.Database, currentCycle: number): Promise<number> {
  ensureSchema(db);

  const cutoffCycle = currentCycle - 50;
  const rows = db
    .prepare(
      `SELECT id, type, content, importance, cycle, timestamp
       FROM tiamat_memories
       WHERE compressed = 0 AND cycle > 0 AND cycle < ?
       ORDER BY cycle ASC`
    )
    .all(cutoffCycle) as MemRow[];

  if (rows.length < 3) {
    console.log(`[COMPRESS] L1→L2: Only ${rows.length} uncompressed memories older than 50 cycles — skipping`);
    return 0;
  }

  console.log(`[COMPRESS] L1→L2: Processing ${rows.length} memories (cycle < ${cutoffCycle})`);

  const clusters = clusterMemories(rows);
  let compressed = 0;

  const markCompressed = db.prepare(
    `UPDATE tiamat_memories SET compressed = 1 WHERE id = ?`
  );
  const insertL2 = db.prepare(
    `INSERT INTO compressed_memories (summary, source_memory_ids, cycle_range, topic)
     VALUES (?, ?, ?, ?)`
  );

  for (const cluster of clusters) {
    if (cluster.length === 1) {
      // Single memory — compress as-is (just truncate to summary)
      const m = cluster[0];
      const summary = m.content.slice(0, 200);
      const topic = m.type;
      insertL2.run(summary, JSON.stringify([m.id]), `${m.cycle}`, topic);
      markCompressed.run(m.id);
      compressed++;
      continue;
    }

    // Multi-memory cluster — compress via Groq
    const texts = cluster.map((m) => m.content.slice(0, 300));
    const summary = await llmCompress(texts);

    if (!summary) {
      // Fallback: concatenate first 80 chars of each
      const fallback = cluster.map((m) => m.content.slice(0, 80)).join("; ").slice(0, 200);
      const ids = cluster.map((m) => m.id);
      const cycles = cluster.map((m) => m.cycle);
      const topic = cluster[0].type;
      insertL2.run(fallback, JSON.stringify(ids), `${Math.min(...cycles)}-${Math.max(...cycles)}`, topic);
      for (const m of cluster) markCompressed.run(m.id);
      compressed++;
      continue;
    }

    const ids = cluster.map((m) => m.id);
    const cycles = cluster.map((m) => m.cycle);
    const topic = cluster[0].type;
    insertL2.run(summary, JSON.stringify(ids), `${Math.min(...cycles)}-${Math.max(...cycles)}`, topic);
    for (const m of cluster) markCompressed.run(m.id);
    compressed++;
  }

  console.log(
    `[COMPRESS] L1→L2: Created ${compressed} L2 summaries from ${rows.length} L1 memories (${clusters.length} clusters)`
  );
  return compressed;
}

// ── L2 → L3 Compression ──────────────────────────────────────

export async function compressL2toL3(db: Database.Database): Promise<number> {
  ensureSchema(db);

  const MAX_L2_PER_SLEEP = 50;

  const l2Rows = db
    .prepare(`SELECT id, summary, topic, created_at FROM compressed_memories WHERE l3_processed = 0 ORDER BY created_at ASC LIMIT ?`)
    .all(MAX_L2_PER_SLEEP) as Array<{ id: number; summary: string; topic: string; created_at: string }>;

  if (l2Rows.length < 5) {
    console.log(`[COMPRESS] L2→L3: Only ${l2Rows.length} unprocessed L2 memories — need at least 5`);
    return 0;
  }

  console.log(`[COMPRESS] L2→L3: Analyzing ${l2Rows.length} new L2 summaries (capped at ${MAX_L2_PER_SLEEP})`);

  const summaries = l2Rows.map((r) => r.summary);
  const facts = await llmExtractFacts(summaries);

  if (facts.length === 0) {
    console.log("[COMPRESS] L2→L3: No facts extracted");
    return 0;
  }

  const upsert = db.prepare(
    `INSERT INTO core_knowledge (fact, confidence, evidence_count, category)
     VALUES (?, ?, ?, ?)
     ON CONFLICT DO NOTHING`
  );

  // Check for existing similar facts (simple substring match)
  const existing = db
    .prepare(`SELECT fact FROM core_knowledge`)
    .all() as Array<{ fact: string }>;
  const existingFacts = new Set(existing.map((e) => e.fact.toLowerCase()));

  let added = 0;
  for (const f of facts) {
    // Skip if very similar to existing
    const lower = f.fact.toLowerCase();
    const isDuplicate = [...existingFacts].some(
      (e) => jaccardSimilarity(tokenize(e), tokenize(lower)) > 0.6
    );
    if (isDuplicate) {
      // Update confidence of existing similar fact
      const match = existing.find(
        (e) => jaccardSimilarity(tokenize(e.fact.toLowerCase()), tokenize(lower)) > 0.6
      );
      if (match) {
        // Diminishing confidence boost — cap at 0.95, smaller increments as confidence grows
        db.prepare(
          `UPDATE core_knowledge SET
             confidence = MIN(0.95, confidence + (0.95 - confidence) * 0.2),
             evidence_count = evidence_count + 1,
             last_confirmed = datetime('now')
           WHERE fact = ?`
        ).run(match.fact);
      }
      continue;
    }

    upsert.run(f.fact, f.confidence, 1, f.category);
    existingFacts.add(lower);
    added++;
  }

  // Mark all processed L2 rows so they aren't re-scanned next sleep
  const markProcessed = db.prepare(`UPDATE compressed_memories SET l3_processed = 1 WHERE id = ?`);
  for (const row of l2Rows) {
    markProcessed.run(row.id);
  }

  console.log(`[COMPRESS] L2→L3: Added ${added} new core facts (${facts.length - added} merged with existing), marked ${l2Rows.length} L2 as processed`);
  return added;
}

// ── Smart Recall ──────────────────────────────────────────────
// Tiered search: L3 → L2 → L1. Stays within token budget.

export interface SmartRecallResult {
  tier: "L3" | "L2" | "L1";
  content: string;
  id: number;
  score?: number;
}

export function smartRecall(
  db: Database.Database,
  query: string,
  tokenBudget: number = 2000
): SmartRecallResult[] {
  ensureSchema(db);

  const results: SmartRecallResult[] = [];
  let tokensUsed = 0;
  const keywords = query
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w.length > 2);

  if (keywords.length === 0) return results;

  const estimateTokens = (text: string) => Math.ceil(text.length / 4);

  // ── Tier 1: Core Knowledge (L3) — cheapest, highest signal ──
  try {
    const likeClauses = keywords.map(() => `LOWER(fact) LIKE ?`).join(" OR ");
    const params = keywords.map((k) => `%${k}%`);
    const l3Rows = db
      .prepare(
        `SELECT id, fact, confidence, category FROM core_knowledge
         WHERE ${likeClauses}
         ORDER BY confidence DESC LIMIT 10`
      )
      .all(...params) as Array<{ id: number; fact: string; confidence: number; category: string }>;

    for (const row of l3Rows) {
      const text = `[L3:${row.category}|${row.confidence.toFixed(1)}] ${row.fact}`;
      const cost = estimateTokens(text);
      if (tokensUsed + cost > tokenBudget) break;
      results.push({ tier: "L3", content: text, id: row.id, score: row.confidence });
      tokensUsed += cost;
    }
  } catch {}

  // ── Tier 2: Compressed Memories (L2) — medium cost ──
  if (tokensUsed < tokenBudget * 0.7) {
    try {
      const likeClauses = keywords.map(() => `LOWER(summary) LIKE ?`).join(" OR ");
      const params = keywords.map((k) => `%${k}%`);
      const l2Rows = db
        .prepare(
          `SELECT id, summary, topic, cycle_range FROM compressed_memories
           WHERE ${likeClauses}
           ORDER BY created_at DESC LIMIT 10`
        )
        .all(...params) as Array<{ id: number; summary: string; topic: string; cycle_range: string }>;

      for (const row of l2Rows) {
        const text = `[L2:${row.topic}|c${row.cycle_range}] ${row.summary}`;
        const cost = estimateTokens(text);
        if (tokensUsed + cost > tokenBudget) break;
        results.push({ tier: "L2", content: text, id: row.id });
        tokensUsed += cost;
      }
    } catch {}
  }

  // ── Tier 3: Raw Memories (L1) — only if budget remains ──
  if (tokensUsed < tokenBudget * 0.5) {
    try {
      const likeClauses = keywords.map(() => `LOWER(content) LIKE ?`).join(" OR ");
      const params = keywords.map((k) => `%${k}%`);
      const l1Rows = db
        .prepare(
          `SELECT id, type, content, importance FROM tiamat_memories
           WHERE compressed = 0 AND (${likeClauses})
           ORDER BY importance DESC, timestamp DESC LIMIT 8`
        )
        .all(...params) as Array<{ id: number; type: string; content: string; importance: number }>;

      for (const row of l1Rows) {
        const text = `[L1:${row.type}|${row.importance}] ${row.content}`;
        const cost = estimateTokens(text);
        if (tokensUsed + cost > tokenBudget) break;
        results.push({ tier: "L1", content: text, id: row.id, score: row.importance });
        tokensUsed += cost;
      }
    } catch {}
  }

  return results;
}

// ── CLI for testing ───────────────────────────────────────────

async function main() {
  const cmd = process.argv[2];
  const db = new Database(DB_PATH);
  db.pragma("journal_mode = WAL");
  ensureSchema(db);

  if (cmd === "l1tol2") {
    const cycle = parseInt(process.argv[3] || "3000", 10);
    const count = await compressL1toL2(db, cycle);
    console.log(`\nCompressed ${count} clusters.`);

    // Show L2 results
    const l2 = db.prepare(`SELECT * FROM compressed_memories ORDER BY id`).all() as any[];
    console.log(`\n── L2 Summaries (${l2.length}) ──`);
    for (const row of l2) {
      console.log(`  [${row.id}] topic=${row.topic} cycles=${row.cycle_range}`);
      console.log(`      ${row.summary}`);
      console.log(`      sources: ${row.source_memory_ids}`);
    }
  } else if (cmd === "l2tol3") {
    const count = await compressL2toL3(db);
    console.log(`\nExtracted ${count} core facts.`);

    const l3 = db.prepare(`SELECT * FROM core_knowledge ORDER BY confidence DESC`).all() as any[];
    console.log(`\n── Core Knowledge (${l3.length}) ──`);
    for (const row of l3) {
      console.log(`  [${row.category}|${row.confidence}] ${row.fact}`);
    }
  } else if (cmd === "recall") {
    const query = process.argv.slice(3).join(" ") || "revenue strategy";
    const results = smartRecall(db, query);
    console.log(`\n── Smart Recall for "${query}" (${results.length} results) ──`);
    for (const r of results) {
      console.log(`  ${r.content}`);
    }
  } else if (cmd === "stats") {
    const l1Total = (db.prepare(`SELECT COUNT(*) as c FROM tiamat_memories`).get() as any).c;
    const l1Compressed = (db.prepare(`SELECT COUNT(*) as c FROM tiamat_memories WHERE compressed = 1`).get() as any).c;
    const l2Total = (db.prepare(`SELECT COUNT(*) as c FROM compressed_memories`).get() as any).c;
    const l3Total = (db.prepare(`SELECT COUNT(*) as c FROM core_knowledge`).get() as any).c;
    console.log(`Memory Tiers:`);
    console.log(`  L1 (raw):        ${l1Total} total, ${l1Compressed} compressed, ${l1Total - l1Compressed} active`);
    console.log(`  L2 (compressed): ${l2Total}`);
    console.log(`  L3 (core facts): ${l3Total}`);
  } else {
    console.log("Usage: memory-compress.ts <l1tol2|l2tol3|recall|stats> [args]");
    console.log("  l1tol2 [cycle]  — Compress L1→L2 (memories older than cycle-50)");
    console.log("  l2tol3          — Extract L2→L3 core knowledge");
    console.log("  recall [query]  — Test smartRecall");
    console.log("  stats           — Show tier counts");
  }

  db.close();
}

// Run if invoked directly
const isMain = process.argv[1]?.endsWith("memory-compress.js") ||
               process.argv[1]?.endsWith("memory-compress.ts");
if (isMain) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
