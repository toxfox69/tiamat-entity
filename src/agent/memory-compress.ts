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
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const GROQ_MODEL = "llama-3.3-70b-versatile";

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
}

// ── Groq Compression Call ─────────────────────────────────────

async function groqCompress(texts: string[]): Promise<string | null> {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) {
    console.log("[COMPRESS] No GROQ_API_KEY — skipping compression");
    return null;
  }

  const joined = texts.map((t, i) => `${i + 1}. ${t}`).join("\n");
  const prompt =
    `Compress these observations into one factual summary, preserving numbers, dates, and causal relationships. Max 200 chars.\n\n${joined}`;

  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const resp = await fetch(GROQ_URL, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: GROQ_MODEL,
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
        const wait = (attempt + 1) * 3000;
        console.log(`[COMPRESS] Groq 429 on compress, retrying in ${wait / 1000}s...`);
        await new Promise((r) => setTimeout(r, wait));
        continue;
      }
      if (!resp.ok) {
        console.log(`[COMPRESS] Groq error: ${resp.status}`);
        return null;
      }
      const data = (await resp.json()) as any;
      return data.choices?.[0]?.message?.content?.trim().slice(0, 250) || null;
    } catch (e: any) {
      console.log(`[COMPRESS] Groq fetch error: ${e.message?.slice(0, 100)}`);
      return null;
    }
  }
  return null;
}

async function groqExtractFacts(summaries: string[]): Promise<Array<{fact: string; category: string; confidence: number}>> {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) return [];

  // Batch into chunks of 10 to avoid rate limits
  const allFacts: Array<{fact: string; category: string; confidence: number}> = [];
  const BATCH_SIZE = 10;

  for (let i = 0; i < summaries.length; i += BATCH_SIZE) {
    const batch = summaries.slice(i, i + BATCH_SIZE);
    const joined = batch.map((s, j) => `${j + 1}. ${s}`).join("\n");
    const prompt =
      `Extract 2-4 core factual patterns from these compressed memories. For each, output a JSON array of objects with keys: fact (string, max 150 chars), category (one of: revenue, social, technical, strategic, behavioral), confidence (0.0-1.0 based on how many sources support it).\n\n${joined}\n\nOutput ONLY the JSON array, nothing else.`;

    // Retry with backoff on 429
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const resp = await fetch(GROQ_URL, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${apiKey}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: GROQ_MODEL,
            messages: [
              { role: "system", content: "Extract factual patterns. Output ONLY valid JSON array." },
              { role: "user", content: prompt },
            ],
            max_tokens: 400,
            temperature: 0.1,
          }),
        });

        if (resp.status === 429) {
          const wait = (attempt + 1) * 5000;
          console.log(`[COMPRESS] Groq 429 on batch ${Math.floor(i / BATCH_SIZE) + 1}, retrying in ${wait / 1000}s...`);
          await new Promise((r) => setTimeout(r, wait));
          continue;
        }
        if (!resp.ok) {
          console.log(`[COMPRESS] Groq extract error: ${resp.status}`);
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
                confidence: Math.max(0, Math.min(1, f.confidence)),
              });
            }
          }
        }
        break; // Success — exit retry loop
      } catch (e: any) {
        console.log(`[COMPRESS] Groq extract error: ${e.message?.slice(0, 100)}`);
        break;
      }
    }

    // Small delay between batches to avoid rate limiting
    if (i + BATCH_SIZE < summaries.length) {
      await new Promise((r) => setTimeout(r, 2000));
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
    const summary = await groqCompress(texts);

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

  const l2Rows = db
    .prepare(`SELECT id, summary, topic, created_at FROM compressed_memories ORDER BY created_at ASC`)
    .all() as Array<{ id: number; summary: string; topic: string; created_at: string }>;

  if (l2Rows.length < 5) {
    console.log(`[COMPRESS] L2→L3: Only ${l2Rows.length} L2 memories — need at least 5`);
    return 0;
  }

  console.log(`[COMPRESS] L2→L3: Analyzing ${l2Rows.length} L2 summaries for core patterns`);

  const summaries = l2Rows.map((r) => r.summary);
  const facts = await groqExtractFacts(summaries);

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
        db.prepare(
          `UPDATE core_knowledge SET
             confidence = MIN(1.0, confidence + 0.1),
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

  console.log(`[COMPRESS] L2→L3: Added ${added} new core facts (${facts.length - added} merged with existing)`);
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
